"""Actual sources and explicit corrections, separate from estimates and receipt detail lines."""

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import delete, func, select

from sallimbook.cashflow import service as cash
from sallimbook.cashflow.models import CashRecord, CashRecordRevision
from sallimbook.cashflow.schemas import CashInput
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.idempotency import IdempotentResult, run_idempotent
from sallimbook.core.types import SEOUL, krw_string
from sallimbook.identity.service import utcnow
from sallimbook.insurance import calculations as calc
from sallimbook.insurance.event_models import (
    ClaimExpense,
    ClaimRevisionExpense,
    InsuranceClaim,
    InsuranceClaimRevision,
    InsurancePayout,
    InsuranceReturn,
    MedicalExpense,
    MedicalExpenseLine,
    MedicalRefund,
    PayoutAllocation,
    PayoutAllocationRevision,
)
from sallimbook.insurance.event_schemas import (
    AllocationHistoryResponse,
    AllocationInput,
    AllocationResponse,
    AllocationRevisionResponse,
    BenefitSummary,
    CaseSummaryResponse,
    ClaimFields,
    ClaimHistoryResponse,
    ClaimListItem,
    ClaimListResponse,
    ClaimResponse,
    ClaimRevisionResponse,
    EventCashHistoryResponse,
    EventReference,
    ExpenseLineResponse,
    ExpenseListItem,
    ExpenseListResponse,
    ExpenseResponse,
    NodeSummaryResponse,
    PayoutListItem,
    PayoutListResponse,
    PayoutResponse,
    RefundListResponse,
    RefundResponse,
    ReturnListResponse,
    ReturnResponse,
)
from sallimbook.insurance.models import InsuranceCase, InsurancePolicy, MedicalNode

_MONEY_FIELDS = {
    "gross_medical_krw",
    "public_coverage_krw",
    "requested_krw",
    "decided_krw",
    "amount_krw",
}


def _actors(principal):
    return dict(
        household_id=principal.household_id,
        created_by_member_id=principal.member_id,
        updated_by_member_id=principal.member_id,
    )


def _values(row, schema, exclude=()):
    result = {name: getattr(row, name) for name in schema.model_fields if name not in exclude}
    for name in result.keys() & _MONEY_FIELDS:
        if result[name] is not None:
            result[name] = krw_string(result[name])
    return result


def _money_values(values):
    return {
        name: Decimal(value) if name in _MONEY_FIELDS and value is not None else value
        for name, value in values.items()
    }


def _bump(session, row, principal):
    before = row.version
    row.version += 1
    row.updated_by_member_id = principal.member_id
    row.updated_at = datetime.now(UTC)
    session.flush()
    return before


def _audit(session, principal, row, kind, action, *, before=None, fields=()):
    record_event(
        session,
        principal,
        entity_type=kind,
        entity_id=row.id,
        action=action,
        before_version=before,
        after_version=row.version,
        changed_fields=fields,
    )


def _finish(session, result):
    session.commit()
    return result


def _mutate(
    session, principal, operation, key, payload, execute, *, resource_id=None, if_match=None
):
    cash.lock_cash_household(session, principal)
    body = {"body": payload.model_dump(mode="json")}
    if resource_id is not None:
        body.update(id=str(resource_id), if_match=if_match)
    result = run_idempotent(session, principal, operation, key, body, execute)
    return _finish(session, EventReference(id=result.resource_id, version=result.resource_version))


def _reference(row, kind, status=201):
    return IdempotentResult(row.id, kind, row.version, status)


def _actual(payload, *, member_id=None):
    return CashInput(
        amount_krw=payload.amount_krw,
        occurred_on=payload.occurred_on,
        period_month=payload.occurred_on.strftime("%Y-%m"),
        date_precision="day",
        account_id=payload.account_id,
        card_id=payload.card_id,
        member_id=member_id,
        note=payload.note,
    )


def _source(session, principal, row, kind, *, active=True, lock=False):
    source = scoped_entity(session, CashRecord, row.cash_record_id, principal, for_update=lock)
    if source.kind != kind:
        raise DomainError("SOURCE_DOMAIN_REQUIRED", "원본 기록의 종류를 확인해 주세요.", 409)
    if active and source.state != "active":
        raise DomainError("EVENT_ALREADY_VOID", "이미 무효 처리된 기록입니다.", 409)
    return source


def _loaded(session, principal, model, ids):
    if not ids:
        return {}
    rows = {
        row.id: row
        for row in session.scalars(
            select(model).where(
                model.household_id == principal.household_id,
                model.id.in_(ids),
            )
        )
    }
    if rows.keys() != set(ids):
        raise DomainError("NOT_FOUND", "요청한 항목을 찾을 수 없습니다.", 404)
    return rows


def _current_cash(session, principal, ids):
    if not ids:
        return {}
    rows = session.scalars(
        select(CashRecordRevision)
        .join(
            CashRecord,
            (CashRecord.id == CashRecordRevision.cash_record_id)
            & (CashRecord.household_id == CashRecordRevision.household_id)
            & (CashRecord.version == CashRecordRevision.version),
        )
        .where(CashRecord.household_id == principal.household_id, CashRecord.id.in_(ids))
    )
    return {row.cash_record_id: cash._response(row) for row in rows}


def _page(session, query, model, cursor, limit):
    if cursor is not None:
        query = query.where(model.id < cursor)
    rows = list(session.scalars(query.order_by(model.id.desc()).limit(limit + 1)))
    return rows[:limit], rows[limit - 1].id if len(rows) > limit else None


def _expense_responses(session, principal, rows, *, detail=False):
    if not rows:
        return []
    ids = [row.id for row in rows]
    sources = _current_cash(session, principal, [row.cash_record_id for row in rows])
    lines = defaultdict(list)
    if detail:
        for line in session.scalars(
            select(MedicalExpenseLine)
            .where(
                MedicalExpenseLine.household_id == principal.household_id,
                MedicalExpenseLine.expense_id.in_(ids),
            )
            .order_by(MedicalExpenseLine.id)
        ):
            lines[line.expense_id].append(ExpenseLineResponse(**_values(line, ExpenseLineResponse)))
        counts = {identifier: len(items) for identifier, items in lines.items()}
    else:
        counts = dict(
            session.execute(
                select(MedicalExpenseLine.expense_id, func.count())
                .where(
                    MedicalExpenseLine.household_id == principal.household_id,
                    MedicalExpenseLine.expense_id.in_(ids),
                )
                .group_by(MedicalExpenseLine.expense_id)
            ).all()
        )
    schema = ExpenseResponse if detail else ExpenseListItem
    return [
        schema(
            **_values(row, schema, {"cash", "line_count", "lines"}),
            cash=sources[row.cash_record_id],
            line_count=counts.get(row.id, 0),
            **({"lines": lines[row.id]} if detail else {}),
        )
        for row in rows
    ]


def _simple_cash_responses(session, principal, rows, schema):
    sources = _current_cash(session, principal, [row.cash_record_id for row in rows])
    return [
        schema(**_values(row, schema, {"cash"}), cash=sources[row.cash_record_id]) for row in rows
    ]


def _new_expense(session, principal, payload, *, correction_of=None, correction_reason=None):
    scoped_entity(session, InsuranceCase, payload.case_id, principal)
    node = scoped_entity(session, MedicalNode, payload.node_id, principal)
    if node.case_id != payload.case_id:
        raise DomainError("NOT_FOUND", "같은 사건의 진료 항목을 선택해 주세요.", 404)
    if node.kind == "prescription":
        raise DomainError(
            "PRESCRIPTION_HAS_NO_PAYMENT", "처방전에는 비용을 입력할 수 없습니다.", 422
        )
    source = cash.prepare_cash_record(
        session, principal, _actual(payload), kind="medical_payment", reason=correction_reason
    )
    fields = {
        "case_id",
        "node_id",
        "provider_name",
        "receipt_reference",
        "gross_medical_krw",
        "public_coverage_krw",
    }
    row = MedicalExpense(
        **_money_values(payload.model_dump(include=fields)),
        **_actors(principal),
        cash_record_id=source.id,
        correction_of_id=correction_of,
        correction_reason=correction_reason,
    )
    session.add(row)
    session.flush()
    session.add_all(
        [
            MedicalExpenseLine(
                household_id=principal.household_id,
                expense_id=row.id,
                **_money_values(line.model_dump()),
            )
            for line in payload.lines
        ]
    )
    _audit(
        session,
        principal,
        row,
        "medical_expense",
        "create",
        fields=payload.model_fields_set - {"reason"},
    )
    return row


def create_expense(session, principal, payload, key):
    return _mutate(
        session,
        principal,
        "medical_expense.create",
        key,
        payload,
        lambda: _reference(_new_expense(session, principal, payload), "medical_expense"),
    )


def get_expense(session, principal, expense_id):
    cash.lock_cash_household(session, principal)
    row = scoped_entity(session, MedicalExpense, expense_id, principal)
    return _finish(session, _expense_responses(session, principal, [row], detail=True)[0])


def list_expenses(
    session, principal, *, case_id=None, node_id=None, state=None, cursor=None, limit=50
):
    cash.lock_cash_household(session, principal)
    query = select(MedicalExpense).where(MedicalExpense.household_id == principal.household_id)
    if case_id is not None:
        scoped_entity(session, InsuranceCase, case_id, principal)
        query = query.where(MedicalExpense.case_id == case_id)
    if node_id is not None:
        node = scoped_entity(session, MedicalNode, node_id, principal)
        if case_id is not None and node.case_id != case_id:
            raise DomainError("NOT_FOUND", "같은 사건의 진료 항목을 선택해 주세요.", 404)
        query = query.where(MedicalExpense.node_id == node_id)
    if state is not None:
        query = query.join(CashRecord, CashRecord.id == MedicalExpense.cash_record_id).where(
            CashRecord.state == state
        )
    rows, next_cursor = _page(session, query, MedicalExpense, cursor, limit)
    return _finish(
        session,
        ExpenseListResponse(
            items=_expense_responses(session, principal, rows), next_cursor=next_cursor
        ),
    )


def _void_expense(session, principal, row, reason):
    source = _source(session, principal, row, "medical_payment", lock=True)
    if cash._active_returns(session, principal, source):
        raise DomainError("MEDICAL_EXPENSE_HAS_REFUNDS", "활성 환불을 먼저 확인해 주세요.", 409)
    if (
        session.scalar(
            select(ClaimExpense.claim_id)
            .where(
                ClaimExpense.household_id == principal.household_id,
                ClaimExpense.expense_id == row.id,
            )
            .limit(1)
        )
        is not None
    ):
        raise DomainError(
            "MEDICAL_EXPENSE_IN_CLAIM", "청구의 현재 비용 근거를 먼저 정정해 주세요.", 409
        )
    cash.prepare_void_cash_record(
        session, principal, source.id, kind="medical_payment", reason=reason
    )
    before = _bump(session, row, principal)
    _audit(session, principal, row, "medical_expense", "void", before=before, fields={"state"})


def void_expense(session, principal, expense_id, payload, if_match, key):
    def execute():
        row = scoped_entity(session, MedicalExpense, expense_id, principal, for_update=True)
        require_version(row, if_match)
        _void_expense(session, principal, row, payload.reason)
        return _reference(row, "medical_expense", 200)

    return _mutate(
        session,
        principal,
        "medical_expense.void",
        key,
        payload,
        execute,
        resource_id=expense_id,
        if_match=if_match,
    )


def correct_expense(session, principal, expense_id, payload, if_match, key):
    def execute():
        row = scoped_entity(session, MedicalExpense, expense_id, principal, for_update=True)
        require_version(row, if_match)
        _void_expense(session, principal, row, payload.reason)
        replacement = _new_expense(
            session, principal, payload, correction_of=row.id, correction_reason=payload.reason
        )
        return _reference(replacement, "medical_expense")

    return _mutate(
        session,
        principal,
        "medical_expense.correct",
        key,
        payload,
        execute,
        resource_id=expense_id,
        if_match=if_match,
    )


def _new_refund(session, principal, expense, payload, *, correction_of=None):
    original = _source(session, principal, expense, "medical_payment", lock=True)
    source = cash.prepare_cash_record(
        session,
        principal,
        _actual(payload, member_id=original.member_id),
        kind="medical_refund",
        reverses_id=original.id,
        reason=payload.reason,
    )
    row = MedicalRefund(
        expense_id=expense.id,
        cash_record_id=source.id,
        reason=payload.reason,
        correction_of_id=correction_of,
        **_actors(principal),
    )
    session.add(row)
    session.flush()
    _bump(session, expense, principal)
    _audit(session, principal, row, "medical_refund", "create", fields=payload.model_fields_set)
    return row


def create_refund(session, principal, expense_id, payload, if_match, key):
    def execute():
        expense = scoped_entity(session, MedicalExpense, expense_id, principal, for_update=True)
        require_version(expense, if_match)
        return _reference(_new_refund(session, principal, expense, payload), "medical_refund")

    return _mutate(
        session,
        principal,
        "medical_refund.create",
        key,
        payload,
        execute,
        resource_id=expense_id,
        if_match=if_match,
    )


def get_refund(session, principal, refund_id):
    cash.lock_cash_household(session, principal)
    row = scoped_entity(session, MedicalRefund, refund_id, principal)
    return _finish(session, _simple_cash_responses(session, principal, [row], RefundResponse)[0])


def list_refunds(session, principal, expense_id, *, cursor=None, limit=50):
    cash.lock_cash_household(session, principal)
    scoped_entity(session, MedicalExpense, expense_id, principal)
    rows, next_cursor = _page(
        session,
        select(MedicalRefund).where(
            MedicalRefund.household_id == principal.household_id,
            MedicalRefund.expense_id == expense_id,
        ),
        MedicalRefund,
        cursor,
        limit,
    )
    return _finish(
        session,
        RefundListResponse(
            items=_simple_cash_responses(session, principal, rows, RefundResponse),
            next_cursor=next_cursor,
        ),
    )


def _void_refund(session, principal, row, reason):
    expense = scoped_entity(session, MedicalExpense, row.expense_id, principal, for_update=True)
    cash.prepare_void_cash_record(
        session, principal, row.cash_record_id, kind="medical_refund", reason=reason
    )
    before = _bump(session, row, principal)
    _bump(session, expense, principal)
    _audit(session, principal, row, "medical_refund", "void", before=before, fields={"state"})
    return expense


def void_refund(session, principal, refund_id, payload, if_match, key):
    def execute():
        row = scoped_entity(session, MedicalRefund, refund_id, principal, for_update=True)
        require_version(row, if_match)
        _void_refund(session, principal, row, payload.reason)
        return _reference(row, "medical_refund", 200)

    return _mutate(
        session,
        principal,
        "medical_refund.void",
        key,
        payload,
        execute,
        resource_id=refund_id,
        if_match=if_match,
    )


def correct_refund(session, principal, refund_id, payload, if_match, key):
    def execute():
        row = scoped_entity(session, MedicalRefund, refund_id, principal, for_update=True)
        require_version(row, if_match)
        expense = _void_refund(session, principal, row, payload.reason)
        return _reference(
            _new_refund(session, principal, expense, payload, correction_of=row.id),
            "medical_refund",
        )

    return _mutate(
        session,
        principal,
        "medical_refund.correct",
        key,
        payload,
        execute,
        resource_id=refund_id,
        if_match=if_match,
    )


def _claim_expenses(session, principal, case_id, ids):
    rows = _loaded(session, principal, MedicalExpense, set(ids))
    sources = _loaded(session, principal, CashRecord, {row.cash_record_id for row in rows.values()})
    for row in rows.values():
        if row.case_id != case_id:
            raise DomainError("NOT_FOUND", "같은 사건의 비용만 청구 근거로 선택해 주세요.", 404)
        if sources[row.cash_record_id].state != "active":
            raise DomainError("MEDICAL_EXPENSE_UNAVAILABLE", "활성 의료비를 선택해 주세요.", 422)


def _remember_claim(session, principal, row, expense_ids, reason=None):
    revision = InsuranceClaimRevision(
        **_money_values(_values(row, ClaimFields)),
        case_id=row.case_id,
        policy_id=row.policy_id,
        claim_id=row.id,
        version=row.version,
        household_id=row.household_id,
        changed_by_member_id=principal.member_id,
        changed_at=row.updated_at,
        reason=reason,
    )
    session.add(revision)
    session.flush()
    session.add_all(
        [
            ClaimRevisionExpense(
                claim_id=row.id,
                claim_version=row.version,
                expense_id=identifier,
                household_id=row.household_id,
                case_id=row.case_id,
            )
            for identifier in expense_ids
        ]
    )


def _claim_responses(session, principal, rows, *, detail=False):
    ids = [row.id for row in rows]
    evidence = defaultdict(list)
    if ids:
        for link in session.scalars(
            select(ClaimExpense)
            .where(
                ClaimExpense.household_id == principal.household_id,
                ClaimExpense.claim_id.in_(ids),
            )
            .order_by(ClaimExpense.expense_id)
        ):
            evidence[link.claim_id].append(link.expense_id)
    schema = ClaimResponse if detail else ClaimListItem
    return [
        schema(
            **_values(row, schema, {"expense_ids", "expense_count"}),
            expense_count=len(evidence[row.id]),
            **({"expense_ids": evidence[row.id]} if detail else {}),
        )
        for row in rows
    ]


def _submitted_date(payload):
    if (
        payload.submitted_on is not None
        and payload.submitted_on > utcnow().astimezone(SEOUL).date()
    ):
        raise DomainError("INVALID_SUBMISSION_DATE", "실제 접수 날짜를 확인해 주세요.", 422)


def create_claim(session, principal, payload):
    cash.lock_cash_household(session, principal)
    scoped_entity(session, InsuranceCase, payload.case_id, principal)
    policy = scoped_entity(session, InsurancePolicy, payload.policy_id, principal)
    if policy.status != "active":
        raise DomainError(
            "POLICY_UNAVAILABLE", "새 청구에는 사용 중인 보험계약을 선택해 주세요.", 422
        )
    _submitted_date(payload)
    _claim_expenses(session, principal, payload.case_id, payload.expense_ids)
    row = InsuranceClaim(
        **_money_values(payload.model_dump(exclude={"expense_ids"})), **_actors(principal)
    )
    session.add(row)
    session.flush()
    session.add_all(
        [
            ClaimExpense(
                claim_id=row.id,
                expense_id=identifier,
                household_id=row.household_id,
                case_id=row.case_id,
            )
            for identifier in payload.expense_ids
        ]
    )
    _remember_claim(session, principal, row, payload.expense_ids)
    _audit(session, principal, row, "insurance_claim", "create", fields=payload.model_fields_set)
    return _finish(session, _claim_responses(session, principal, [row], detail=True)[0])


def get_claim(session, principal, claim_id):
    cash.lock_cash_household(session, principal)
    row = scoped_entity(session, InsuranceClaim, claim_id, principal)
    return _finish(session, _claim_responses(session, principal, [row], detail=True)[0])


def list_claims(
    session, principal, *, case_id=None, policy_id=None, claim_state=None, cursor=None, limit=50
):
    cash.lock_cash_household(session, principal)
    query = select(InsuranceClaim).where(InsuranceClaim.household_id == principal.household_id)
    for field, value, model in (
        ("case_id", case_id, InsuranceCase),
        ("policy_id", policy_id, InsurancePolicy),
    ):
        if value is not None:
            scoped_entity(session, model, value, principal)
            query = query.where(getattr(InsuranceClaim, field) == value)
    if claim_state is not None:
        query = query.where(InsuranceClaim.claim_state == claim_state)
    rows, next_cursor = _page(session, query, InsuranceClaim, cursor, limit)
    return _finish(
        session,
        ClaimListResponse(
            items=_claim_responses(session, principal, rows), next_cursor=next_cursor
        ),
    )


def update_claim(session, principal, claim_id, payload, if_match):
    cash.lock_cash_household(session, principal)
    row = scoped_entity(session, InsuranceClaim, claim_id, principal, for_update=True)
    require_version(row, if_match)
    candidate = ClaimFields.model_validate(
        _values(row, ClaimFields)
        | payload.model_dump(exclude_unset=True, exclude={"reason", "expense_ids"})
    )
    _submitted_date(candidate)
    evidence = list(
        session.scalars(
            select(ClaimExpense.expense_id).where(
                ClaimExpense.household_id == principal.household_id,
                ClaimExpense.claim_id == row.id,
            )
        )
    )
    if "expense_ids" in payload.model_fields_set:
        evidence = payload.expense_ids
        _claim_expenses(session, principal, row.case_id, evidence)
        session.execute(
            delete(ClaimExpense).where(
                ClaimExpense.household_id == principal.household_id, ClaimExpense.claim_id == row.id
            )
        )
        session.add_all(
            [
                ClaimExpense(
                    claim_id=row.id,
                    expense_id=identifier,
                    case_id=row.case_id,
                    household_id=row.household_id,
                )
                for identifier in evidence
            ]
        )
    for name, value in _money_values(candidate.model_dump()).items():
        setattr(row, name, value)
    before = _bump(session, row, principal)
    _remember_claim(session, principal, row, evidence, payload.reason)
    _audit(
        session,
        principal,
        row,
        "insurance_claim",
        "correct",
        before=before,
        fields=payload.model_fields_set - {"reason"},
    )
    return _finish(session, _claim_responses(session, principal, [row], detail=True)[0])


def claim_history(session, principal, claim_id, *, cursor=None, limit=50):
    scoped_entity(session, InsuranceClaim, claim_id, principal)
    query = select(InsuranceClaimRevision).where(
        InsuranceClaimRevision.household_id == principal.household_id,
        InsuranceClaimRevision.claim_id == claim_id,
    )
    if cursor is not None:
        query = query.where(InsuranceClaimRevision.version < cursor)
    rows = list(
        session.scalars(query.order_by(InsuranceClaimRevision.version.desc()).limit(limit + 1))
    )
    evidence = defaultdict(list)
    if rows:
        for link in session.scalars(
            select(ClaimRevisionExpense)
            .where(
                ClaimRevisionExpense.household_id == principal.household_id,
                ClaimRevisionExpense.claim_id == claim_id,
                ClaimRevisionExpense.claim_version.in_([r.version for r in rows[:limit]]),
            )
            .order_by(ClaimRevisionExpense.expense_id)
        ):
            evidence[link.claim_version].append(link.expense_id)
    return _finish(
        session,
        ClaimHistoryResponse(
            items=[
                ClaimRevisionResponse(
                    **_values(row, ClaimRevisionResponse, {"expense_ids"}),
                    expense_ids=evidence[row.version],
                )
                for row in rows[:limit]
            ],
            next_cursor=rows[limit - 1].version if len(rows) > limit else None,
        ),
    )


def _allocation_targets(session, principal, allocations, *, previous=()):
    _loaded(session, principal, InsuranceCase, {r.case_id for r in allocations})
    policies = _loaded(
        session,
        principal,
        InsurancePolicy,
        {r.policy_id for r in allocations if r.policy_id is not None},
    )
    claims = _loaded(
        session,
        principal,
        InsuranceClaim,
        {r.claim_id for r in allocations if r.claim_id is not None},
    )
    historical = {(r.case_id, r.policy_id) for r in previous}
    for row in allocations:
        if row.claim_id is not None:
            claim = claims[row.claim_id]
            if claim.case_id != row.case_id or claim.policy_id != row.policy_id:
                raise DomainError(
                    "CLAIM_ALLOCATION_MISMATCH", "청구와 같은 사건·보험계약을 선택해 주세요.", 422
                )
            # A late receipt may settle an existing claim after its policy ended.
        elif (
            row.policy_id is not None
            and policies[row.policy_id].status != "active"
            and (row.case_id, row.policy_id) not in historical
        ):
            raise DomainError(
                "POLICY_UNAVAILABLE",
                "새 직접 지급 연결에는 사용 중인 보험계약을 선택해 주세요.",
                422,
            )


def _remember_allocation(session, principal, row, reason=None):
    session.add(
        PayoutAllocationRevision(
            **{
                name: getattr(row, name)
                for name in (
                    "payout_id",
                    "case_id",
                    "policy_id",
                    "claim_id",
                    "benefit_type",
                    "amount_krw",
                )
            },
            allocation_id=row.id,
            version=row.version,
            household_id=row.household_id,
            changed_by_member_id=principal.member_id,
            changed_at=row.updated_at,
            reason=reason,
        )
    )


def _payout_responses(session, principal, rows, *, detail=False):
    if not rows:
        return []
    ids = [row.id for row in rows]
    sources = _current_cash(session, principal, [row.cash_record_id for row in rows])
    allocations = defaultdict(list)
    if detail:
        for allocation in session.scalars(
            select(PayoutAllocation)
            .where(
                PayoutAllocation.household_id == principal.household_id,
                PayoutAllocation.payout_id.in_(ids),
            )
            .order_by(PayoutAllocation.id)
        ):
            allocations[allocation.payout_id].append(
                AllocationResponse(**_values(allocation, AllocationResponse))
            )
        counts = {identifier: len(items) for identifier, items in allocations.items()}
    else:
        counts = dict(
            session.execute(
                select(PayoutAllocation.payout_id, func.count())
                .where(
                    PayoutAllocation.household_id == principal.household_id,
                    PayoutAllocation.payout_id.in_(ids),
                )
                .group_by(PayoutAllocation.payout_id)
            ).all()
        )
    schema = PayoutResponse if detail else PayoutListItem
    return [
        schema(
            **_values(row, schema, {"cash", "allocation_count", "allocations"}),
            cash=sources[row.cash_record_id],
            allocation_count=counts.get(row.id, 0),
            **({"allocations": allocations[row.id]} if detail else {}),
        )
        for row in rows
    ]


def _new_payout(
    session, principal, payload, *, correction_of=None, correction_reason=None, previous=()
):
    _allocation_targets(session, principal, payload.allocations, previous=previous)
    source = cash.prepare_cash_record(
        session, principal, _actual(payload), kind="insurance_receipt", reason=correction_reason
    )
    row = InsurancePayout(
        cash_record_id=source.id,
        insurer_note=payload.insurer_note,
        correction_of_id=correction_of,
        correction_reason=correction_reason,
        **_actors(principal),
    )
    session.add(row)
    session.flush()
    allocations = [
        PayoutAllocation(payout_id=row.id, **_money_values(item.model_dump()), **_actors(principal))
        for item in payload.allocations
    ]
    session.add_all(allocations)
    session.flush()
    for allocation in allocations:
        _remember_allocation(session, principal, allocation)
    _audit(
        session,
        principal,
        row,
        "insurance_payout",
        "create",
        fields=payload.model_fields_set - {"reason"},
    )
    return row


def create_payout(session, principal, payload, key):
    return _mutate(
        session,
        principal,
        "insurance_payout.create",
        key,
        payload,
        lambda: _reference(_new_payout(session, principal, payload), "insurance_payout"),
    )


def get_payout(session, principal, payout_id):
    cash.lock_cash_household(session, principal)
    row = scoped_entity(session, InsurancePayout, payout_id, principal)
    return _finish(session, _payout_responses(session, principal, [row], detail=True)[0])


def list_payouts(
    session,
    principal,
    *,
    case_id=None,
    policy_id=None,
    claim_id=None,
    state=None,
    cursor=None,
    limit=50,
):
    cash.lock_cash_household(session, principal)
    query = select(InsurancePayout).where(InsurancePayout.household_id == principal.household_id)
    matching = select(PayoutAllocation.payout_id).where(
        PayoutAllocation.household_id == principal.household_id
    )
    filtered = False
    for field, value, model in (
        ("case_id", case_id, InsuranceCase),
        ("policy_id", policy_id, InsurancePolicy),
        ("claim_id", claim_id, InsuranceClaim),
    ):
        if value is not None:
            scoped_entity(session, model, value, principal)
            matching = matching.where(getattr(PayoutAllocation, field) == value)
            filtered = True
    if filtered:
        query = query.where(InsurancePayout.id.in_(matching))
    if state is not None:
        query = query.join(CashRecord, CashRecord.id == InsurancePayout.cash_record_id).where(
            CashRecord.state == state
        )
    rows, next_cursor = _page(session, query, InsurancePayout, cursor, limit)
    return _finish(
        session,
        PayoutListResponse(
            items=_payout_responses(session, principal, rows), next_cursor=next_cursor
        ),
    )


def _void_payout(session, principal, row, reason):
    source = _source(session, principal, row, "insurance_receipt", lock=True)
    if cash._active_returns(session, principal, source):
        raise DomainError("INSURANCE_PAYOUT_HAS_RETURNS", "활성 반환을 먼저 확인해 주세요.", 409)
    cash.prepare_void_cash_record(
        session, principal, source.id, kind="insurance_receipt", reason=reason
    )
    before = _bump(session, row, principal)
    _audit(session, principal, row, "insurance_payout", "void", before=before, fields={"state"})


def void_payout(session, principal, payout_id, payload, if_match, key):
    def execute():
        row = scoped_entity(session, InsurancePayout, payout_id, principal, for_update=True)
        require_version(row, if_match)
        _void_payout(session, principal, row, payload.reason)
        return _reference(row, "insurance_payout", 200)

    return _mutate(
        session,
        principal,
        "insurance_payout.void",
        key,
        payload,
        execute,
        resource_id=payout_id,
        if_match=if_match,
    )


def correct_payout(session, principal, payout_id, payload, if_match, key):
    def execute():
        row = scoped_entity(session, InsurancePayout, payout_id, principal, for_update=True)
        require_version(row, if_match)
        previous = list(
            session.scalars(
                select(PayoutAllocation).where(
                    PayoutAllocation.household_id == principal.household_id,
                    PayoutAllocation.payout_id == row.id,
                )
            )
        )
        _void_payout(session, principal, row, payload.reason)
        replacement = _new_payout(
            session,
            principal,
            payload,
            correction_of=row.id,
            correction_reason=payload.reason,
            previous=previous,
        )
        return _reference(replacement, "insurance_payout")

    return _mutate(
        session,
        principal,
        "insurance_payout.correct",
        key,
        payload,
        execute,
        resource_id=payout_id,
        if_match=if_match,
    )


def get_allocation(session, principal, allocation_id):
    row = scoped_entity(session, PayoutAllocation, allocation_id, principal)
    return _finish(session, AllocationResponse(**_values(row, AllocationResponse)))


def update_allocation_links(session, principal, allocation_id, payload, if_match, key):
    def execute():
        row = scoped_entity(session, PayoutAllocation, allocation_id, principal, for_update=True)
        require_version(row, if_match)
        payout = scoped_entity(session, InsurancePayout, row.payout_id, principal, for_update=True)
        _source(session, principal, payout, "insurance_receipt", lock=True)
        try:
            candidate = AllocationInput.model_validate(
                _values(row, AllocationInput)
                | payload.model_dump(exclude_unset=True, exclude={"reason"})
            )
        except ValidationError:
            raise DomainError(
                "CLAIM_ALLOCATION_MISMATCH", "청구와 보험계약 연결을 확인해 주세요.", 422
            ) from None
        _allocation_targets(session, principal, [candidate], previous=[row])
        row.policy_id, row.claim_id = candidate.policy_id, candidate.claim_id
        before = _bump(session, row, principal)
        _remember_allocation(session, principal, row, payload.reason)
        _bump(session, payout, principal)
        _audit(
            session,
            principal,
            row,
            "payout_allocation",
            "correct",
            before=before,
            fields=payload.model_fields_set - {"reason"},
        )
        return _reference(row, "payout_allocation", 200)

    return _mutate(
        session,
        principal,
        "payout_allocation.link",
        key,
        payload,
        execute,
        resource_id=allocation_id,
        if_match=if_match,
    )


def allocation_history(session, principal, allocation_id, *, cursor=None, limit=50):
    scoped_entity(session, PayoutAllocation, allocation_id, principal)
    query = select(PayoutAllocationRevision).where(
        PayoutAllocationRevision.household_id == principal.household_id,
        PayoutAllocationRevision.allocation_id == allocation_id,
    )
    if cursor is not None:
        query = query.where(PayoutAllocationRevision.version < cursor)
    rows = list(
        session.scalars(query.order_by(PayoutAllocationRevision.version.desc()).limit(limit + 1))
    )
    return _finish(
        session,
        AllocationHistoryResponse(
            items=[
                AllocationRevisionResponse(**_values(row, AllocationRevisionResponse))
                for row in rows[:limit]
            ],
            next_cursor=rows[limit - 1].version if len(rows) > limit else None,
        ),
    )


def _new_return(session, principal, payout, payload, *, correction_of=None):
    source = _source(session, principal, payout, "insurance_receipt", lock=True)
    allocation = scoped_entity(
        session, PayoutAllocation, payload.original_allocation_id, principal, for_update=True
    )
    if allocation.payout_id != payout.id:
        raise DomainError("NOT_FOUND", "원래 지급의 배분을 선택해 주세요.", 404)
    returned = session.scalar(
        select(func.coalesce(func.sum(CashRecord.amount_krw), 0))
        .join(
            InsuranceReturn,
            (InsuranceReturn.cash_record_id == CashRecord.id)
            & (InsuranceReturn.household_id == CashRecord.household_id),
        )
        .where(
            InsuranceReturn.household_id == principal.household_id,
            InsuranceReturn.original_allocation_id == allocation.id,
            CashRecord.state == "active",
        )
    )
    if int(returned) + int(payload.amount_krw) > int(allocation.amount_krw):
        raise DomainError(
            "RETURN_EXCEEDS_ALLOCATION", "반환 합계가 원래 배분 금액을 초과합니다.", 409
        )
    actual = cash.prepare_cash_record(
        session,
        principal,
        _actual(payload, member_id=source.member_id),
        kind="insurance_return",
        reverses_id=source.id,
        reason=payload.reason,
    )
    row = InsuranceReturn(
        payout_id=payout.id,
        original_allocation_id=allocation.id,
        cash_record_id=actual.id,
        reason=payload.reason,
        correction_of_id=correction_of,
        **_actors(principal),
    )
    session.add(row)
    session.flush()
    _bump(session, payout, principal)
    _audit(session, principal, row, "insurance_return", "create", fields=payload.model_fields_set)
    return row


def create_return(session, principal, payout_id, payload, if_match, key):
    def execute():
        payout = scoped_entity(session, InsurancePayout, payout_id, principal, for_update=True)
        require_version(payout, if_match)
        return _reference(_new_return(session, principal, payout, payload), "insurance_return")

    return _mutate(
        session,
        principal,
        "insurance_return.create",
        key,
        payload,
        execute,
        resource_id=payout_id,
        if_match=if_match,
    )


def get_return(session, principal, return_id):
    cash.lock_cash_household(session, principal)
    row = scoped_entity(session, InsuranceReturn, return_id, principal)
    return _finish(session, _simple_cash_responses(session, principal, [row], ReturnResponse)[0])


def list_returns(session, principal, payout_id, *, cursor=None, limit=50):
    cash.lock_cash_household(session, principal)
    scoped_entity(session, InsurancePayout, payout_id, principal)
    rows, next_cursor = _page(
        session,
        select(InsuranceReturn).where(
            InsuranceReturn.household_id == principal.household_id,
            InsuranceReturn.payout_id == payout_id,
        ),
        InsuranceReturn,
        cursor,
        limit,
    )
    return _finish(
        session,
        ReturnListResponse(
            items=_simple_cash_responses(session, principal, rows, ReturnResponse),
            next_cursor=next_cursor,
        ),
    )


def _void_return(session, principal, row, reason):
    payout = scoped_entity(session, InsurancePayout, row.payout_id, principal, for_update=True)
    cash.prepare_void_cash_record(
        session, principal, row.cash_record_id, kind="insurance_return", reason=reason
    )
    before = _bump(session, row, principal)
    _bump(session, payout, principal)
    _audit(session, principal, row, "insurance_return", "void", before=before, fields={"state"})
    return payout


def void_return(session, principal, return_id, payload, if_match, key):
    def execute():
        row = scoped_entity(session, InsuranceReturn, return_id, principal, for_update=True)
        require_version(row, if_match)
        _void_return(session, principal, row, payload.reason)
        return _reference(row, "insurance_return", 200)

    return _mutate(
        session,
        principal,
        "insurance_return.void",
        key,
        payload,
        execute,
        resource_id=return_id,
        if_match=if_match,
    )


def correct_return(session, principal, return_id, payload, if_match, key):
    def execute():
        row = scoped_entity(session, InsuranceReturn, return_id, principal, for_update=True)
        require_version(row, if_match)
        payout = _void_return(session, principal, row, payload.reason)
        return _reference(
            _new_return(session, principal, payout, payload, correction_of=row.id),
            "insurance_return",
        )

    return _mutate(
        session,
        principal,
        "insurance_return.correct",
        key,
        payload,
        execute,
        resource_id=return_id,
        if_match=if_match,
    )


def event_cash_history(session, principal, kind, resource_id, *, cursor=None, limit=50):
    models = {
        "medical_expense": MedicalExpense,
        "medical_refund": MedicalRefund,
        "insurance_payout": InsurancePayout,
        "insurance_return": InsuranceReturn,
    }
    source = scoped_entity(session, models[kind], resource_id, principal)
    query = select(CashRecordRevision).where(
        CashRecordRevision.household_id == principal.household_id,
        CashRecordRevision.cash_record_id == source.cash_record_id,
    )
    if cursor is not None:
        query = query.where(CashRecordRevision.version < cursor)
    rows = list(session.scalars(query.order_by(CashRecordRevision.version.desc()).limit(limit + 1)))
    return _finish(
        session,
        EventCashHistoryResponse(
            items=[cash._response(row) for row in rows[:limit]],
            next_cursor=rows[limit - 1].version if len(rows) > limit else None,
        ),
    )


def _medical_sources(session, principal, case_id, *, node_ids=None):
    query = (
        select(MedicalExpense, CashRecord)
        .join(
            CashRecord,
            (CashRecord.id == MedicalExpense.cash_record_id)
            & (CashRecord.household_id == MedicalExpense.household_id),
        )
        .where(
            MedicalExpense.household_id == principal.household_id,
            MedicalExpense.case_id == case_id,
            CashRecord.state == "active",
        )
    )
    if node_ids is not None:
        query = query.where(MedicalExpense.node_id.in_(node_ids))
    rows = session.execute(query).all()
    payments = [
        calc.MedicalPayment(str(row.id), str(case_id), source.amount_krw) for row, source in rows
    ]
    ids = [row.id for row, _ in rows]
    refunds = []
    if ids:
        refund_rows = session.execute(
            select(MedicalRefund, CashRecord)
            .join(
                CashRecord,
                (CashRecord.id == MedicalRefund.cash_record_id)
                & (CashRecord.household_id == MedicalRefund.household_id),
            )
            .where(
                MedicalRefund.household_id == principal.household_id,
                MedicalRefund.expense_id.in_(ids),
                CashRecord.state == "active",
            )
        ).all()
        refunds = [
            calc.MedicalRefund(str(row.id), str(row.expense_id), source.amount_krw)
            for row, source in refund_rows
        ]
    return payments, refunds


def _payout_sources(session, principal, case_id):
    rows = session.execute(
        select(InsurancePayout, CashRecord)
        .join(
            CashRecord,
            (CashRecord.id == InsurancePayout.cash_record_id)
            & (CashRecord.household_id == InsurancePayout.household_id),
        )
        .where(
            InsurancePayout.household_id == principal.household_id,
            CashRecord.state == "active",
            InsurancePayout.id.in_(
                select(PayoutAllocation.payout_id).where(
                    PayoutAllocation.household_id == principal.household_id,
                    PayoutAllocation.case_id == case_id,
                )
            ),
        )
    ).all()
    ids = [row.id for row, _ in rows]
    if not ids:
        return [], []
    allocations = defaultdict(list)
    for allocation in session.scalars(
        select(PayoutAllocation).where(
            PayoutAllocation.household_id == principal.household_id,
            PayoutAllocation.payout_id.in_(ids),
        )
    ):
        allocations[allocation.payout_id].append(
            calc.Allocation(
                str(allocation.id),
                str(allocation.case_id),
                allocation.amount_krw,
                allocation.benefit_type,
                str(allocation.claim_id) if allocation.claim_id is not None else None,
            )
        )
    payouts = [
        calc.Payout(str(row.id), source.amount_krw, tuple(allocations[row.id]))
        for row, source in rows
    ]
    returns = [
        calc.InsuranceReturn(
            str(row.id), str(row.payout_id), str(row.original_allocation_id), source.amount_krw
        )
        for row, source in session.execute(
            select(InsuranceReturn, CashRecord)
            .join(
                CashRecord,
                (CashRecord.id == InsuranceReturn.cash_record_id)
                & (CashRecord.household_id == InsuranceReturn.household_id),
            )
            .where(
                InsuranceReturn.household_id == principal.household_id,
                InsuranceReturn.payout_id.in_(ids),
                CashRecord.state == "active",
            )
        ).all()
    ]
    return payouts, returns


def _balance(payments, payouts, refunds, returns, case_id):
    try:
        summary = calc.insurance_summary(payments, payouts, refunds=refunds, returns=returns)
        return summary.cases.get(str(case_id), calc.CaseBalance(*([0] * 10)))
    except ValueError:
        raise DomainError(
            "AMOUNT_OUT_OF_RANGE", "집계 금액과 원본 연결을 확인해 주세요.", 422
        ) from None


def case_summary(session, principal, case_id):
    cash.lock_cash_household(session, principal)
    scoped_entity(session, InsuranceCase, case_id, principal)
    payments, refunds = _medical_sources(session, principal, case_id)
    payouts, returns = _payout_sources(session, principal, case_id)
    balance = _balance(payments, payouts, refunds, returns, case_id)
    allocations = {row.id: row for payout in payouts for row in payout.allocations}
    received, returned = defaultdict(int), defaultdict(int)
    for row in allocations.values():
        if row.case_id == str(case_id):
            received[row.benefit_type] += int(row.amount_krw)
    for row in returns:
        original = allocations[row.allocation_id]
        if original.case_id == str(case_id):
            returned[original.benefit_type] += int(row.amount_krw)
    result = CaseSummaryResponse(
        case_id=case_id,
        **{
            name: krw_string(getattr(balance, name))
            for name in CaseSummaryResponse.model_fields
            if name not in {"case_id", "benefits"}
        },
        benefits=[
            BenefitSummary(
                benefit_type=kind,
                received_krw=krw_string(received[kind]),
                returned_krw=krw_string(returned[kind]),
                net_received_krw=krw_string(received[kind] - returned[kind]),
            )
            for kind in ("reimbursement", "fixed", "other")
        ],
    )
    return _finish(session, result)


def node_summary(session, principal, case_id, node_id):
    cash.lock_cash_household(session, principal)
    scoped_entity(session, InsuranceCase, case_id, principal)
    rows = session.execute(
        select(MedicalNode.id, MedicalNode.parent_id).where(
            MedicalNode.household_id == principal.household_id,
            MedicalNode.case_id == case_id,
        )
    ).all()
    children = defaultdict(list)
    for identifier, parent in rows:
        children[parent].append(identifier)
    if node_id not in {identifier for identifier, _ in rows}:
        raise DomainError("NOT_FOUND", "요청한 진료 항목을 찾을 수 없습니다.", 404)
    selected, pending = set(), [node_id]
    while pending:
        identifier = pending.pop()
        if identifier in selected:
            continue
        selected.add(identifier)
        pending.extend(children[identifier])
    payments, refunds = _medical_sources(session, principal, case_id, node_ids=selected)
    balance = _balance(payments, [], refunds, [], case_id)
    return _finish(
        session,
        NodeSummaryResponse(
            case_id=case_id,
            node_id=node_id,
            subtree_node_count=len(selected),
            medical_paid_krw=krw_string(balance.medical_paid_krw),
            medical_refunded_krw=krw_string(balance.medical_refunded_krw),
            net_medical_krw=krw_string(balance.net_medical_krw),
        ),
    )
