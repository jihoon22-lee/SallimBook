"""Idempotent planning facts, immutable receipts, and atomic bonus cash linkage."""

from datetime import UTC, datetime

from sqlalchemy import select

from sallimbook.cashflow import service as cash
from sallimbook.cashflow.planning_models import BonusAward, ExpectedIncome, IncomePlanningRevision
from sallimbook.cashflow.planning_schemas import BonusResponse, ExpectedResponse
from sallimbook.cashflow.schemas import CashInput
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.idempotency import IdempotentResult, run_idempotent
from sallimbook.core.types import SEOUL, decimal_krw, krw_string, month_start
from sallimbook.identity.auth_models import HouseholdMember


def response(row):
    schema = BonusResponse if isinstance(row, BonusAward) else ExpectedResponse
    values = {key: getattr(row, key) for key in schema.model_fields}
    for key, value in values.items():
        if key.endswith("_krw") and value is not None:
            values[key] = krw_string(value)
    if values.get("payment_month") is not None:
        values["payment_month"] = values["payment_month"].strftime("%Y-%m")
    return schema(**values)


def _cash_link(session, principal, payload, previous):
    old_id = previous.cash_record_id if previous else None
    wants_cash = payload.active and payload.received and int(payload.net_cash_krw or "0") > 0
    if (
        old_id
        and wants_cash
        and all(
            getattr(previous, key) == value
            for key, value in (
                ("member_id", payload.member_id),
                ("net_cash_krw", decimal_krw(payload.net_cash_krw)),
                ("payment_month", month_start(payload.payment_month)),
            )
        )
    ):
        return old_id
    if old_id:
        original = scoped_entity(session, cash.CashRecord, old_id, principal, for_update=True)
        cash._no_returns(session, principal, original)
        if original.state != "active":
            raise DomainError("SOURCE_DOMAIN_REQUIRED", "연결된 수입 상태를 확인해 주세요.", 409)
        cash._void(session, principal, original, payload.reason)
    if wants_cash:
        # Importing a detail must not create a second fact for an already recorded bonus.
        duplicate = session.scalar(
            select(cash.CashRecord.id)
            .where(
                cash.CashRecord.household_id == principal.household_id,
                cash.CashRecord.member_id == payload.member_id,
                cash.CashRecord.kind == "bonus",
                cash.CashRecord.state == "active",
                cash.CashRecord.period_month == month_start(payload.payment_month),
            )
            .limit(1)
        )
        if duplicate is not None:
            raise DomainError(
                "INCOME_DUPLICATE_SUSPECTED",
                "같은 지급월에 상여 수입이 있어요. 기존 기록을 확인해 주세요.",
                409,
            )
        row = cash.prepare_cash_record(
            session,
            principal,
            CashInput(
                member_id=payload.member_id,
                amount_krw=payload.net_cash_krw,
                period_month=payload.payment_month,
                date_precision="month",
                note=(
                    f"성과연도 {payload.performance_year} · {payload.award_kind}"
                    " · 상여 상세에 연결됨"
                ),
            ),
            kind="bonus",
        )
        return row.id
    return None


def _write(session, principal, payload, key, *, model, kind, record_id=None, if_match=None):
    cash.lock_cash_household(session, principal)
    body = payload.model_dump(mode="json")

    def execute():
        member = scoped_entity(session, HouseholdMember, payload.member_id, principal)
        if member.status != "active":
            raise DomainError("MEMBER_UNAVAILABLE", "현재 가계 구성원을 선택해 주세요.", 422)
        row = (
            scoped_entity(session, model, record_id, principal, for_update=True)
            if record_id
            else None
        )
        if row:
            require_version(row, if_match)
        if (
            kind == "bonus"
            and payload.received
            and month_start(payload.payment_month)
            > datetime.now(UTC).astimezone(SEOUL).date().replace(day=1)
        ):
            raise DomainError("INVALID_OCCURRED_DATE", "실제 수령한 지급월을 확인해 주세요.", 422)
        unique = (
            ("member_id", "label")
            if kind == "expected"
            else ("member_id", "performance_year", "award_kind")
        )
        query = select(model.id).where(
            model.household_id == principal.household_id,
            *(getattr(model, name) == getattr(payload, name) for name in unique),
        )
        if record_id:
            query = query.where(model.id != record_id)
        if session.scalar(query) is not None:
            raise DomainError(
                "INCOME_PLANNING_DUPLICATE",
                "같은 구성원의 수입 항목이 이미 있어요. 기존 항목을 수정해 주세요.",
                409,
            )
        values = payload.model_dump(exclude={"reason"})
        for name, value in values.items():
            if name.endswith("_krw") and value is not None:
                values[name] = decimal_krw(value)
        if kind == "bonus":
            values["payment_month"] = (
                month_start(payload.payment_month) if payload.payment_month else None
            )
            values["cash_record_id"] = _cash_link(session, principal, payload, row)
        before = row.version if row else None
        if row is None:
            row = model(
                **values,
                household_id=principal.household_id,
                created_by_member_id=principal.member_id,
                updated_by_member_id=principal.member_id,
            )
            session.add(row)
        else:
            for name, value in values.items():
                setattr(row, name, value)
            row.version += 1
            row.updated_at = datetime.now(UTC)
            row.updated_by_member_id = principal.member_id
        session.flush()
        snapshot = response(row)
        session.add(
            IncomePlanningRevision(
                household_id=principal.household_id,
                resource_id=row.id,
                version=row.version,
                kind=kind,
                actor_member_id=principal.member_id,
                reason=getattr(payload, "reason", None),
                snapshot=snapshot.model_dump(mode="json"),
                created_at=row.updated_at,
            )
        )
        record_event(
            session,
            principal,
            entity_type=f"{kind}_income" if kind == "expected" else "bonus_award",
            entity_id=row.id,
            action="create" if before is None else "correct",
            before_version=before,
            after_version=row.version,
            changed_fields=values.keys(),
        )
        session.flush()
        return IdempotentResult(
            row.id, "income_planning", row.version, 201 if before is None else 200
        )

    result = run_idempotent(
        session,
        principal,
        f"income.{kind}.{'change' if record_id else 'create'}",
        key,
        {"body": body, "id": str(record_id) if record_id else None, "if_match": if_match},
        execute,
    )
    revision = session.get(
        IncomePlanningRevision,
        (principal.household_id, result.resource_id, result.resource_version),
    )
    schema = BonusResponse if kind == "bonus" else ExpectedResponse
    receipt = schema.model_validate(revision.snapshot)
    session.commit()
    return receipt


def create_expected(session, principal, payload, key):
    return _write(session, principal, payload, key, model=ExpectedIncome, kind="expected")


def change_expected(session, principal, record_id, payload, if_match, key):
    return _write(
        session,
        principal,
        payload,
        key,
        model=ExpectedIncome,
        kind="expected",
        record_id=record_id,
        if_match=if_match,
    )


def create_bonus(session, principal, payload, key):
    return _write(session, principal, payload, key, model=BonusAward, kind="bonus")


def change_bonus(session, principal, record_id, payload, if_match, key):
    return _write(
        session,
        principal,
        payload,
        key,
        model=BonusAward,
        kind="bonus",
        record_id=record_id,
        if_match=if_match,
    )


def list_records(session, principal, model, cursor=None, limit=100):
    query = select(model).where(model.household_id == principal.household_id)
    if cursor:
        scoped_entity(session, model, cursor, principal)
        query = query.where(model.id > cursor)
    rows = list(session.scalars(query.order_by(model.id).limit(limit + 1)))
    return dict(
        items=[response(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


def guard_linked_cash(session, principal, record_id):
    if session.scalar(
        select(BonusAward.id).where(
            BonusAward.household_id == principal.household_id,
            BonusAward.cash_record_id == record_id,
        )
    ):
        raise DomainError(
            "SOURCE_DOMAIN_REQUIRED", "상여 상세에서 연결된 현금 수입을 정정해 주세요.", 409
        )
