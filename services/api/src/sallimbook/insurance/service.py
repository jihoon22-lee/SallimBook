"""Insurance metadata, protected identifiers and independent medical-case trees."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from sallimbook.accounts.crypto import KeyRing, SealedNumber
from sallimbook.assets.locking import lock_asset_scope
from sallimbook.assets.models import Asset
from sallimbook.cashflow.recurring_models import RecurringRule, RecurringRuleVersion
from sallimbook.cashflow.recurring_service import _rule_response
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.types import SEOUL
from sallimbook.identity import service as identity
from sallimbook.identity.auth_models import HouseholdMember
from sallimbook.insurance.crypto import decrypt_number, encrypt_number
from sallimbook.insurance.event_models import MedicalExpense
from sallimbook.insurance.models import (
    InsuranceCase,
    InsuranceCaseRevision,
    InsuranceCoverage,
    InsurancePolicy,
    MedicalNode,
    PolicyPremiumLink,
)
from sallimbook.insurance.schemas import (
    CaseHistoryResponse,
    CaseInput,
    CaseListItem,
    CaseListResponse,
    CaseResponse,
    CaseRevisionResponse,
    CoverageInput,
    CoverageListResponse,
    CoverageResponse,
    MedicalNodeInput,
    MedicalNodeListResponse,
    MedicalNodeResponse,
    PolicyFields,
    PolicyListResponse,
    PolicyResponse,
    PolicyRevealResponse,
    PremiumLinkListResponse,
    PremiumLinkResponse,
)


def _values(row, schema):
    return {name: getattr(row, name) for name in schema.model_fields}


def _response(row, schema):
    values = _values(row, schema)
    if "insured_amount_krw" in values and values["insured_amount_krw"] is not None:
        values["insured_amount_krw"] = str(values["insured_amount_krw"])
    return schema(**values)


def policy_response(row):
    return PolicyResponse(
        **{
            name: getattr(row, name)
            for name in PolicyResponse.model_fields
            if name not in {"masked_number", "has_number"}
        },
        masked_number="**** " + row.last_four if row.last_four is not None else None,
        has_number=row.policy_number_ciphertext is not None,
    )


def _finish(session, response):
    session.commit()
    return response


def _actors(principal):
    return dict(
        household_id=principal.household_id,
        created_by_member_id=principal.member_id,
        updated_by_member_id=principal.member_id,
    )


def _touch(row, principal):
    before = row.version
    row.version += 1
    row.updated_by_member_id = principal.member_id
    row.updated_at = datetime.now(UTC)
    return before


def _audit(session, principal, row, entity_type, action, fields=(), before=None, request_id=None):
    record_event(
        session,
        principal,
        entity_type=entity_type,
        entity_id=row.id,
        action=action,
        before_version=before,
        after_version=None if action == "delete" else row.version,
        changed_fields=fields,
        request_id=request_id,
    )


def _member(session, principal, member_id, *, active=True):
    if member_id is None:
        return
    member = scoped_entity(session, HouseholdMember, member_id, principal, for_update=active)
    if active and member.status != "active":
        raise DomainError("MEMBER_UNAVAILABLE", "현재 가계 구성원을 선택해 주세요.", 422)


def _policy_links(session, principal, candidate, previous=None):
    reactivating = (
        previous is not None and previous.status != "active" and candidate.status == "active"
    )
    for field in ("policyholder_member_id", "insured_member_id"):
        member_id = getattr(candidate, field)
        _member(
            session,
            principal,
            member_id,
            active=previous is None or reactivating or getattr(previous, field) != member_id,
        )
    if candidate.valuation_asset_id is not None:
        asset = scoped_entity(session, Asset, candidate.valuation_asset_id, principal)
        if previous is None or reactivating or previous.valuation_asset_id != asset.id:
            if asset.kind != "asset" or asset.category != "financial" or asset.ended_on is not None:
                raise DomainError(
                    "VALUATION_ASSET_UNAVAILABLE", "사용 중인 금융 자산을 선택해 주세요.", 422
                )


def _candidate(row, schema, payload, *, exclude=frozenset()):
    values = _values(row, schema)
    if "insured_amount_krw" in values and values["insured_amount_krw"] is not None:
        values["insured_amount_krw"] = str(values["insured_amount_krw"])
    try:
        return schema.model_validate(
            values | payload.model_dump(exclude_unset=True, exclude=exclude)
        )
    except ValidationError:
        raise DomainError(
            "INVALID_INSURANCE_INPUT", "입력 항목과 기간을 확인해 주세요.", 422
        ) from None


def _assign(row, values):
    for name, value in values.items():
        if name == "insured_amount_krw" and value is not None:
            value = Decimal(value)
        setattr(row, name, value)


def _write_number(row, number, key_file):
    if number is None:
        row.policy_number_ciphertext = row.number_nonce = row.number_key_version = row.last_four = (
            None
        )
        return
    raw = number.get_secret_value()
    sealed = encrypt_number(KeyRing.load(key_file), row.household_id, row.id, raw)
    row.policy_number_ciphertext = sealed.ciphertext
    row.number_nonce = sealed.nonce
    row.number_key_version = sealed.key_version
    row.last_four = raw.replace(" ", "").replace("-", "")[-4:]


def _page_rows(session, query, model, cursor, limit):
    if cursor is not None:
        query = query.where(model.id < cursor)
    rows = list(session.scalars(query.order_by(model.id.desc()).limit(limit + 1)))
    return rows[:limit], rows[limit - 1].id if len(rows) > limit else None


def create_policy(session, principal, payload, key_file, *, request_id=None):
    lock_asset_scope(session, principal)
    _policy_links(session, principal, payload)
    row = InsurancePolicy(
        id=uuid4(), **payload.model_dump(exclude={"policy_number"}), **_actors(principal)
    )
    _write_number(row, payload.policy_number, key_file)
    session.add(row)
    session.flush()
    _audit(
        session,
        principal,
        row,
        "insurance_policy",
        "create",
        payload.model_fields_set,
        request_id=request_id,
    )
    return _finish(session, policy_response(row))


def get_policy(session, principal, policy_id):
    return _finish(
        session, policy_response(scoped_entity(session, InsurancePolicy, policy_id, principal))
    )


def list_policies(
    session,
    principal,
    *,
    status=None,
    insured_member_id=None,
    policyholder_member_id=None,
    cursor=None,
    limit=50,
):
    query = select(InsurancePolicy).where(InsurancePolicy.household_id == principal.household_id)
    for field, value in (
        ("insured_member_id", insured_member_id),
        ("policyholder_member_id", policyholder_member_id),
    ):
        if value is not None:
            _member(session, principal, value, active=False)
            query = query.where(getattr(InsurancePolicy, field) == value)
    if status is not None:
        query = query.where(InsurancePolicy.status == status)
    rows, next_cursor = _page_rows(session, query, InsurancePolicy, cursor, limit)
    return _finish(
        session,
        PolicyListResponse(items=[policy_response(r) for r in rows], next_cursor=next_cursor),
    )


def update_policy(session, principal, policy_id, payload, if_match, key_file, *, request_id=None):
    lock_asset_scope(session, principal)
    row = scoped_entity(session, InsurancePolicy, policy_id, principal, for_update=True)
    require_version(row, if_match)
    candidate = _candidate(row, PolicyFields, payload, exclude={"policy_number"})
    _policy_links(session, principal, candidate, row)
    before = _touch(row, principal)
    _assign(row, candidate.model_dump())
    if "policy_number" in payload.model_fields_set:
        _write_number(row, payload.policy_number, key_file)
    session.flush()
    _audit(
        session,
        principal,
        row,
        "insurance_policy",
        "update",
        payload.model_fields_set,
        before,
        request_id,
    )
    return _finish(session, policy_response(row))


def reveal_policy_number(session, principal, policy_id, key_file, *, request_id=None):
    # Identity barriers precede every domain lock, matching device/session revocation.
    auth, devices = identity.lock_session_devices(session, principal)
    lock_asset_scope(session, principal)
    row = scoped_entity(session, InsurancePolicy, policy_id, principal, for_update=True)

    def validate():
        identity.validate_locked_session(
            principal, auth, devices[principal.device_id], recent_login=True
        )

    validate()  # Domain lock waits cannot extend the five-minute recent-login window.
    if row.policy_number_ciphertext is None:
        raise DomainError("POLICY_NUMBER_NOT_SET", "등록된 증권번호가 없습니다.", 409)
    validate()
    number = decrypt_number(
        KeyRing.load(key_file),
        row.household_id,
        row.id,
        SealedNumber(row.number_key_version, row.number_nonce, row.policy_number_ciphertext),
    )
    validate()
    _audit(
        session,
        principal,
        row,
        "insurance_policy",
        "reveal",
        before=row.version,
        request_id=request_id,
    )
    session.flush()
    validate()
    session.commit()
    return PolicyRevealResponse(id=policy_id, policy_number=number)


def _child(session, principal, model, child_id, parent_field, parent_id, *, lock=False):
    row = scoped_entity(session, model, child_id, principal, for_update=lock)
    if getattr(row, parent_field) != parent_id:
        raise DomainError("NOT_FOUND", "요청한 항목을 찾을 수 없습니다.", 404)
    return row


def create_coverage(session, principal, policy_id, payload):
    lock_asset_scope(session, principal)
    scoped_entity(session, InsurancePolicy, policy_id, principal)
    row = InsuranceCoverage(policy_id=policy_id, **_actors(principal))
    _assign(row, payload.model_dump())
    session.add(row)
    session.flush()
    _audit(session, principal, row, "insurance_coverage", "create", payload.model_fields_set)
    return _finish(session, _response(row, CoverageResponse))


def list_coverages(session, principal, policy_id, *, active=None, cursor=None, limit=50):
    scoped_entity(session, InsurancePolicy, policy_id, principal)
    query = select(InsuranceCoverage).where(
        InsuranceCoverage.household_id == principal.household_id,
        InsuranceCoverage.policy_id == policy_id,
    )
    if active is not None:
        query = query.where(InsuranceCoverage.active == active)
    rows, next_cursor = _page_rows(session, query, InsuranceCoverage, cursor, limit)
    return _finish(
        session,
        CoverageListResponse(
            items=[_response(r, CoverageResponse) for r in rows], next_cursor=next_cursor
        ),
    )


def update_coverage(session, principal, policy_id, coverage_id, payload, if_match):
    lock_asset_scope(session, principal)
    scoped_entity(session, InsurancePolicy, policy_id, principal)
    row = _child(
        session, principal, InsuranceCoverage, coverage_id, "policy_id", policy_id, lock=True
    )
    require_version(row, if_match)
    candidate = _candidate(row, CoverageInput, payload)
    before = _touch(row, principal)
    _assign(row, candidate.model_dump())
    session.flush()
    _audit(
        session, principal, row, "insurance_coverage", "update", payload.model_fields_set, before
    )
    return _finish(session, _response(row, CoverageResponse))


def _premium_available(policy, rule):
    if policy.status != "active":
        raise DomainError("POLICY_UNAVAILABLE", "사용 중인 보험계약을 선택해 주세요.", 422)
    if rule.ended_on is not None and rule.ended_on <= identity.utcnow().astimezone(SEOUL).date():
        raise DomainError("RECURRING_RULE_UNAVAILABLE", "사용 중인 납부 규칙을 선택해 주세요.", 422)


def _premium_responses(session, principal, rows):
    if not rows:
        return []
    ids = {r.rule_id for r in rows}
    rules = {
        r.id: r
        for r in session.scalars(
            select(RecurringRule).where(
                RecurringRule.household_id == principal.household_id, RecurringRule.id.in_(ids)
            )
        )
    }
    versions = {identifier: [] for identifier in ids}
    for version in session.scalars(
        select(RecurringRuleVersion)
        .where(
            RecurringRuleVersion.household_id == principal.household_id,
            RecurringRuleVersion.rule_id.in_(ids),
        )
        .order_by(RecurringRuleVersion.rule_id, RecurringRuleVersion.effective_from)
    ):
        versions[version.rule_id].append(version)
    return [
        PremiumLinkResponse(
            **{
                name: getattr(row, name)
                for name in PremiumLinkResponse.model_fields
                if name != "rule"
            },
            rule=_rule_response(
                session, principal, rules[row.rule_id], versions=versions[row.rule_id]
            ),
        )
        for row in rows
    ]


def create_premium_link(session, principal, policy_id, payload):
    lock_asset_scope(session, principal)
    policy = scoped_entity(session, InsurancePolicy, policy_id, principal)
    rule = scoped_entity(session, RecurringRule, payload.rule_id, principal)
    _premium_available(policy, rule)
    if (
        session.scalar(
            select(PolicyPremiumLink.id).where(
                PolicyPremiumLink.household_id == principal.household_id,
                PolicyPremiumLink.rule_id == rule.id,
            )
        )
        is not None
    ):
        raise DomainError("PREMIUM_RULE_ALREADY_LINKED", "이미 계약에 연결된 납부 규칙입니다.", 409)
    row = PolicyPremiumLink(
        policy_id=policy_id, rule_id=rule.id, active=True, ended_at=None, **_actors(principal)
    )
    session.add(row)
    session.flush()
    _audit(session, principal, row, "policy_premium_link", "create", {"rule_id", "active"})
    return _finish(session, _premium_responses(session, principal, [row])[0])


def list_premium_links(session, principal, policy_id, *, active=None, cursor=None, limit=50):
    lock_asset_scope(session, principal)
    scoped_entity(session, InsurancePolicy, policy_id, principal)
    query = select(PolicyPremiumLink).where(
        PolicyPremiumLink.household_id == principal.household_id,
        PolicyPremiumLink.policy_id == policy_id,
    )
    if active is not None:
        query = query.where(PolicyPremiumLink.active == active)
    rows, next_cursor = _page_rows(session, query, PolicyPremiumLink, cursor, limit)
    return _finish(
        session,
        PremiumLinkListResponse(
            items=_premium_responses(session, principal, rows), next_cursor=next_cursor
        ),
    )


def update_premium_link(session, principal, policy_id, link_id, payload, if_match):
    lock_asset_scope(session, principal)
    policy = scoped_entity(session, InsurancePolicy, policy_id, principal)
    row = _child(session, principal, PolicyPremiumLink, link_id, "policy_id", policy_id, lock=True)
    require_version(row, if_match)
    if payload.active and not row.active:
        _premium_available(policy, scoped_entity(session, RecurringRule, row.rule_id, principal))
    before = _touch(row, principal)
    row.active = payload.active
    row.ended_at = None if payload.active else row.ended_at or datetime.now(UTC)
    session.flush()
    _audit(session, principal, row, "policy_premium_link", "update", {"active"}, before)
    return _finish(session, _premium_responses(session, principal, [row])[0])


def _actual_dates(*dates):
    today = identity.utcnow().astimezone(SEOUL).date()
    if any(value is not None and value > today for value in dates):
        raise DomainError("INVALID_MEDICAL_DATES", "실제 진료 날짜를 확인해 주세요.", 422)


def _case_revision(session, row, principal, reason=None):
    session.add(
        InsuranceCaseRevision(
            **_values(row, CaseInput),
            case_id=row.id,
            household_id=row.household_id,
            version=row.version,
            changed_by_member_id=principal.member_id,
            changed_at=row.updated_at,
            reason=reason,
        )
    )


def create_case(session, principal, payload):
    lock_asset_scope(session, principal)
    _member(session, principal, payload.patient_member_id)
    _actual_dates(payload.start_on, payload.end_on)
    row = InsuranceCase(**payload.model_dump(), **_actors(principal))
    session.add(row)
    session.flush()
    _case_revision(session, row, principal)
    _audit(session, principal, row, "insurance_case", "create", payload.model_fields_set)
    return _finish(session, _response(row, CaseResponse))


def get_case(session, principal, case_id):
    return _finish(
        session, _response(scoped_entity(session, InsuranceCase, case_id, principal), CaseResponse)
    )


def list_cases(
    session,
    principal,
    *,
    patient_member_id=None,
    treatment_state=None,
    financial_state=None,
    cursor=None,
    limit=50,
):
    query = select(InsuranceCase).where(InsuranceCase.household_id == principal.household_id)
    if patient_member_id is not None:
        _member(session, principal, patient_member_id, active=False)
    for field, value in (
        ("patient_member_id", patient_member_id),
        ("treatment_state", treatment_state),
        ("financial_state", financial_state),
    ):
        if value is not None:
            query = query.where(getattr(InsuranceCase, field) == value)
    rows, next_cursor = _page_rows(session, query, InsuranceCase, cursor, limit)
    return _finish(
        session,
        CaseListResponse(items=[_response(r, CaseListItem) for r in rows], next_cursor=next_cursor),
    )


def update_case(session, principal, case_id, payload, if_match):
    lock_asset_scope(session, principal)
    row = scoped_entity(session, InsuranceCase, case_id, principal, for_update=True)
    require_version(row, if_match)
    candidate = _candidate(row, CaseInput, payload, exclude={"reason"})
    _member(
        session,
        principal,
        candidate.patient_member_id,
        active=candidate.patient_member_id != row.patient_member_id,
    )
    _actual_dates(candidate.start_on, candidate.end_on)
    reopening = (row.treatment_state == "ended" and candidate.treatment_state == "ongoing") or (
        row.financial_state == "settled" and candidate.financial_state == "open"
    )
    before = _touch(row, principal)
    _assign(row, candidate.model_dump())
    session.flush()
    _case_revision(session, row, principal, payload.reason)
    _audit(
        session,
        principal,
        row,
        "insurance_case",
        "reopen" if reopening else "correct",
        payload.model_fields_set - {"reason"},
        before,
    )
    return _finish(session, _response(row, CaseResponse))


def case_history(session, principal, case_id, *, cursor=None, limit=50):
    scoped_entity(session, InsuranceCase, case_id, principal)
    query = select(InsuranceCaseRevision).where(
        InsuranceCaseRevision.household_id == principal.household_id,
        InsuranceCaseRevision.case_id == case_id,
    )
    if cursor is not None:
        query = query.where(InsuranceCaseRevision.version < cursor)
    rows = list(
        session.scalars(query.order_by(InsuranceCaseRevision.version.desc()).limit(limit + 1))
    )
    return _finish(
        session,
        CaseHistoryResponse(
            items=[_response(r, CaseRevisionResponse) for r in rows[:limit]],
            next_cursor=rows[limit - 1].version if len(rows) > limit else None,
        ),
    )


def _parent(session, principal, case_id, parent_id, node_id=None):
    if parent_id is None:
        return
    # One scoped topology read, independent of tree depth. Household writer lock
    # prevents two individually valid cross-moves from forming a cycle together.
    parents = dict(
        session.execute(
            select(MedicalNode.id, MedicalNode.parent_id).where(
                MedicalNode.household_id == principal.household_id,
                MedicalNode.case_id == case_id,
            )
        ).all()
    )
    if parent_id not in parents:
        raise DomainError("NOT_FOUND", "같은 사건의 진료 항목을 선택해 주세요.", 404)
    seen = {node_id} if node_id is not None else set()
    current = parent_id
    while current is not None:
        if current in seen:
            raise DomainError(
                "MEDICAL_NODE_CYCLE", "자신이나 하위 항목으로 이동할 수 없습니다.", 422
            )
        seen.add(current)
        current = parents[current]


def create_node(session, principal, case_id, payload):
    lock_asset_scope(session, principal)
    scoped_entity(session, InsuranceCase, case_id, principal)
    _actual_dates(payload.start_on, payload.end_on)
    _parent(session, principal, case_id, payload.parent_id)
    row = MedicalNode(case_id=case_id, **payload.model_dump(), **_actors(principal))
    session.add(row)
    session.flush()
    _audit(session, principal, row, "medical_node", "create", payload.model_fields_set)
    return _finish(session, _response(row, MedicalNodeResponse))


def get_node(session, principal, case_id, node_id):
    scoped_entity(session, InsuranceCase, case_id, principal)
    row = _child(session, principal, MedicalNode, node_id, "case_id", case_id)
    return _finish(session, _response(row, MedicalNodeResponse))


def list_nodes(session, principal, case_id, *, cursor=None, limit=50):
    lock_asset_scope(session, principal)
    scoped_entity(session, InsuranceCase, case_id, principal)
    if cursor is not None:
        _child(session, principal, MedicalNode, cursor, "case_id", case_id)
    # UUID remains the opaque cursor, but its current tree path determines page
    # membership. PostgreSQL orders parents before descendants and siblings by
    # (sort_order, start_on nulls last, created_at, id), without fetching every clinical
    # row into Python. Record comparison puts a NULL start_on after dated siblings, the
    # same way for ORDER BY and the cursor's ">".
    rows = list(
        session.scalars(
            select(MedicalNode).from_statement(
                text("""
                    WITH RECURSIVE tree(id, parent_id, sort_order, start_on, created_at) AS (
                        SELECT id, parent_id, sort_order, start_on, created_at
                        FROM medical_nodes
                        WHERE household_id = :household_id AND case_id = :case_id
                          AND parent_id IS NULL
                        UNION ALL
                        SELECT n.id, n.parent_id, n.sort_order, n.start_on, n.created_at
                        FROM medical_nodes n
                        JOIN tree t ON n.parent_id = t.id
                        WHERE n.household_id = :household_id AND n.case_id = :case_id
                    ) SEARCH DEPTH FIRST BY sort_order, start_on, created_at, id SET tree_path
                    SELECT n.* FROM tree t JOIN medical_nodes n ON n.id = t.id
                    WHERE CAST(:cursor AS uuid) IS NULL OR t.tree_path > (
                        SELECT tree_path FROM tree WHERE id = CAST(:cursor AS uuid)
                    )
                    ORDER BY t.tree_path LIMIT :page_size
                """)
            ),
            {
                "household_id": principal.household_id,
                "case_id": case_id,
                "cursor": cursor,
                "page_size": limit + 1,
            },
        )
    )
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return _finish(
        session,
        MedicalNodeListResponse(
            items=[_response(r, MedicalNodeResponse) for r in rows[:limit]],
            next_cursor=next_cursor,
        ),
    )


def update_node(session, principal, case_id, node_id, payload, if_match):
    lock_asset_scope(session, principal)
    scoped_entity(session, InsuranceCase, case_id, principal)
    row = _child(session, principal, MedicalNode, node_id, "case_id", case_id, lock=True)
    require_version(row, if_match)
    candidate = _candidate(row, MedicalNodeInput, payload)
    if (
        candidate.kind == "prescription"
        and session.scalar(
            select(MedicalExpense.id)
            .where(
                MedicalExpense.household_id == principal.household_id,
                MedicalExpense.node_id == row.id,
            )
            .limit(1)
        )
        is not None
    ):
        raise DomainError(
            "MEDICAL_NODE_IN_USE", "비용 이력이 있는 항목은 처방으로 바꿀 수 없습니다.", 409
        )
    _actual_dates(candidate.start_on, candidate.end_on)
    _parent(session, principal, case_id, candidate.parent_id, node_id)
    before = _touch(row, principal)
    _assign(row, candidate.model_dump())
    session.flush()
    _audit(session, principal, row, "medical_node", "update", payload.model_fields_set, before)
    return _finish(session, _response(row, MedicalNodeResponse))


def delete_node(session, principal, case_id, node_id, if_match):
    lock_asset_scope(session, principal)
    scoped_entity(session, InsuranceCase, case_id, principal)
    row = _child(session, principal, MedicalNode, node_id, "case_id", case_id, lock=True)
    require_version(row, if_match)
    if (
        session.scalar(
            select(MedicalNode.id)
            .where(
                MedicalNode.household_id == principal.household_id,
                MedicalNode.parent_id == row.id,
            )
            .limit(1)
        )
        is not None
    ):
        raise DomainError(
            "MEDICAL_NODE_IN_USE", "하위 항목이나 연결 기록이 있는 진료 항목입니다.", 409
        )
    _audit(session, principal, row, "medical_node", "delete", before=row.version)
    try:
        session.delete(row)
        session.flush()
        session.commit()
    except IntegrityError as error:
        session.rollback()
        if getattr(error.orig, "sqlstate", None) in {"23001", "23503"}:
            raise DomainError(
                "MEDICAL_NODE_IN_USE", "연결 기록이 있는 진료 항목입니다.", 409
            ) from None
        raise
