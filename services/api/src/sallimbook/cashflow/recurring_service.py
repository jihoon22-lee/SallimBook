"""Household-serialized recurrence and actual settlements; no balance/snapshot writes."""

import calendar
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from sallimbook.accounts.models import FinancialAccount
from sallimbook.assets.models import Asset
from sallimbook.cashflow import service as cash
from sallimbook.cashflow.models import CashRecord
from sallimbook.cashflow.recurring_models import (
    FixedSettlement,
    ObligationGeneration,
    ObligationGenerationItem,
    ObligationRevision,
    RecurringRule,
    RecurringRuleVersion,
    ScheduledObligation,
)
from sallimbook.cashflow.recurring_schemas import (
    FixedSummaryResponse,
    GenerateObligations,
    GenerationResponse,
    MutationReference,
    ObligationHistoryItem,
    ObligationHistoryResponse,
    ObligationListResponse,
    ObligationResponse,
    RuleListResponse,
    RuleResponse,
    RuleVersionResponse,
    ScheduleTerms,
    SettlementListResponse,
    SettlementResponse,
)
from sallimbook.cashflow.scheduling import occurrence_dates, payment_breakdown, settlement_totals
from sallimbook.cashflow.schemas import CashInput
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.idempotency import IdempotentResult, run_idempotent
from sallimbook.core.types import SEOUL, decimal_krw, krw_string, month_start
from sallimbook.identity.service import utcnow

_SNAPSHOT = tuple(
    name
    for name in ScheduleTerms.model_fields
    if name not in {"anchor_date", "frequency", "interval_count"}
)
_OBLIGATION_VALUES = (
    *_SNAPSHOT,
    "household_id",
    "rule_id",
    "rule_version_id",
    "nominal_date",
    "scheduled_date",
    "schedule_state",
    "manual_override",
    "skipped",
    "manually_completed",
    "created_at",
    "updated_at",
)


def today():
    return utcnow().astimezone(SEOUL).date()


def _money(value):
    return None if value is None else krw_string(value)


def _audit(session, principal, row, entity, action, fields, before=None):
    record_event(
        session,
        principal,
        entity_type=entity,
        entity_id=row.id,
        action=action,
        before_version=before,
        after_version=getattr(row, "version", 1),
        changed_fields=fields,
    )


def _validate_method(session, principal, account_id, card_id):
    if account_id is not None:
        account = scoped_entity(session, FinancialAccount, account_id, principal)
        asset = scoped_entity(session, Asset, account.asset_id, principal, for_update=True)
        scoped_entity(session, FinancialAccount, account_id, principal, for_update=True)
        if asset.ended_on is not None:
            raise DomainError("ACCOUNT_UNAVAILABLE", "사용 중인 납부 계좌를 선택해 주세요.", 422)
    if card_id is not None:
        from sallimbook.cards.models import Card

        card = scoped_entity(session, Card, card_id, principal, for_update=True)
        if card.ended_on is not None:
            raise DomainError("CARD_UNAVAILABLE", "사용 중인 납부 카드를 선택해 주세요.", 422)


def _term_values(payload):
    result = payload.model_dump(include=set(ScheduleTerms.model_fields))
    result["expected_amount_krw"] = (
        None if payload.expected_amount_krw is None else decimal_krw(payload.expected_amount_krw)
    )
    return result


def _versions(session, principal, rule_id):
    return list(
        session.scalars(
            select(RecurringRuleVersion)
            .where(
                RecurringRuleVersion.household_id == principal.household_id,
                RecurringRuleVersion.rule_id == rule_id,
            )
            .order_by(RecurringRuleVersion.effective_from)
        )
    )


def _rule_response(session, principal, row):
    return RuleResponse(
        id=row.id,
        household_id=row.household_id,
        version=row.version,
        ended_on=row.ended_on,
        end_reason=row.end_reason,
        versions=[
            RuleVersionResponse(
                **(
                    {name: getattr(version, name) for name in ScheduleTerms.model_fields}
                    | {"expected_amount_krw": _money(version.expected_amount_krw)}
                ),
                id=version.id,
                effective_from=version.effective_from,
                effective_until=version.effective_until,
                reason=version.reason,
                created_at=version.created_at,
            )
            for version in _versions(session, principal, row.id)
        ],
    )


def _reference_finish(session, result):
    response = MutationReference(id=result.resource_id, version=result.resource_version)
    session.commit()
    return response


def create_rule(session, principal, payload, key):
    cash.lock_cash_household(session, principal)

    def execute():
        _validate_method(session, principal, payload.account_id, payload.card_id)
        row = RecurringRule(
            household_id=principal.household_id, created_by_member_id=principal.member_id
        )
        session.add(row)
        session.flush()
        session.add(
            RecurringRuleVersion(
                **_term_values(payload),
                household_id=principal.household_id,
                rule_id=row.id,
                effective_from=payload.effective_from,
            )
        )
        _audit(session, principal, row, "recurring_rule", "create", payload.model_fields_set)
        session.flush()
        return IdempotentResult(row.id, "recurring_rule", row.version)

    return _reference_finish(
        session,
        run_idempotent(
            session,
            principal,
            "recurring.create",
            key,
            payload.model_dump(mode="json"),
            execute,
        ),
    )


def _change_window(session, principal, rule, start):
    end = session.scalar(
        select(func.max(ScheduledObligation.nominal_date)).where(
            ScheduledObligation.household_id == principal.household_id,
            ScheduledObligation.rule_id == rule.id,
        )
    )
    if end is None or end < start:
        return
    # Bound work without losing already-generated future coverage across multiple annual windows.
    cursor = start
    while cursor <= end:
        window_end = min(end, cursor + timedelta(days=365))
        _generate_rows(session, principal, cursor, window_end, [rule])
        cursor = window_end + timedelta(days=1)


def change_rule(session, principal, rule_id, payload, if_match, key):
    cash.lock_cash_household(session, principal)

    def execute():
        row = scoped_entity(session, RecurringRule, rule_id, principal, for_update=True)
        require_version(row, if_match)
        versions = _versions(session, principal, row.id)
        last = versions[-1]
        if row.ended_on is not None or payload.effective_from <= last.effective_from:
            raise DomainError(
                "RULE_PERIOD_OVERLAP", "기존 마지막 규칙 이후 적용일을 선택해 주세요.", 409
            )
        if payload.effective_from < today():
            raise DomainError("PAST_RULE_CHANGE", "지난 규칙은 변경할 수 없습니다.", 409)
        _validate_method(session, principal, payload.account_id, payload.card_id)
        last.effective_until = payload.effective_from
        session.flush()  # Close the old range before the exclusion constraint sees its successor.
        session.add(
            RecurringRuleVersion(
                **_term_values(payload),
                household_id=principal.household_id,
                rule_id=row.id,
                effective_from=payload.effective_from,
                reason=payload.reason,
            )
        )
        before = row.version
        row.version += 1
        row.updated_at = datetime.now(UTC)
        _audit(
            session, principal, row, "recurring_rule", "update", payload.model_fields_set, before
        )
        session.flush()
        _change_window(session, principal, row, payload.effective_from)
        return IdempotentResult(row.id, "recurring_rule", row.version, 200)

    return _reference_finish(
        session,
        run_idempotent(
            session,
            principal,
            "recurring.change",
            key,
            {"id": str(rule_id), "if_match": if_match, "body": payload.model_dump(mode="json")},
            execute,
        ),
    )


def end_rule(session, principal, rule_id, payload, if_match, key):
    cash.lock_cash_household(session, principal)

    def execute():
        row = scoped_entity(session, RecurringRule, rule_id, principal, for_update=True)
        require_version(row, if_match)
        last = _versions(session, principal, row.id)[-1]
        if row.ended_on is not None or payload.effective_on <= last.effective_from:
            raise DomainError(
                "RULE_PERIOD_OVERLAP", "마지막 규칙 이후 종료일을 선택해 주세요.", 409
            )
        if payload.effective_on < today():
            raise DomainError("PAST_RULE_CHANGE", "지난 규칙은 변경할 수 없습니다.", 409)
        last.effective_until = payload.effective_on
        row.ended_on = payload.effective_on
        row.end_reason = payload.reason
        before = row.version
        row.version += 1
        row.updated_at = datetime.now(UTC)
        _audit(session, principal, row, "recurring_rule", "archive", ("ended_on",), before)
        session.flush()
        _change_window(session, principal, row, payload.effective_on)
        return IdempotentResult(row.id, "recurring_rule", row.version, 200)

    return _reference_finish(
        session,
        run_idempotent(
            session,
            principal,
            "recurring.end",
            key,
            {"id": str(rule_id), "if_match": if_match, "body": payload.model_dump(mode="json")},
            execute,
        ),
    )


def get_rule(session, principal, rule_id):
    response = _rule_response(
        session, principal, scoped_entity(session, RecurringRule, rule_id, principal)
    )
    session.commit()
    return response


def list_rules(session, principal, *, cursor=None, limit=50):
    query = select(RecurringRule).where(RecurringRule.household_id == principal.household_id)
    if cursor:
        query = query.where(RecurringRule.id < cursor)
    rows = list(session.scalars(query.order_by(RecurringRule.id.desc()).limit(limit + 1)))
    response = RuleListResponse(
        items=[_rule_response(session, principal, row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )
    session.commit()
    return response


def _remember(session, principal, row, action, *, reason=None, before=None):
    session.flush()
    session.add(
        ObligationRevision(
            **{name: getattr(row, name) for name in _OBLIGATION_VALUES},
            obligation_id=row.id,
            version=row.version,
            action=action,
            reason=reason,
        )
    )
    _audit(
        session,
        principal,
        row,
        "obligation",
        action,
        (
            "rule_version_id",
            "scheduled_date",
            "schedule_state",
            "manual_override",
            "skipped",
            "manually_completed",
        ),
        before,
    )
    session.flush()


def _touch(session, principal, row, action, reason=None):
    before = row.version
    row.version += 1
    row.updated_at = datetime.now(UTC)
    _remember(session, principal, row, action, reason=reason, before=before)


def _active_settlements(session, principal, obligation_id):
    return list(
        session.execute(
            select(FixedSettlement, CashRecord)
            .join(
                CashRecord,
                (
                    (CashRecord.id == FixedSettlement.cash_record_id)
                    & (CashRecord.household_id == FixedSettlement.household_id)
                ),
            )
            .where(
                FixedSettlement.household_id == principal.household_id,
                FixedSettlement.obligation_id == obligation_id,
                CashRecord.state == "active",
            )
            .order_by(FixedSettlement.id)
        )
    )


def _generate_rows(session, principal, start, end, rules):
    results = []
    for rule in rules:
        desired = {}
        for version in _versions(session, principal, rule.id):
            lower = max(start, version.effective_from)
            upper = (
                min(end, version.effective_until - timedelta(days=1))
                if version.effective_until
                else end
            )
            if lower > upper:
                continue
            for occurrence in occurrence_dates(
                version.anchor_date,
                lower,
                upper,
                frequency=version.frequency,
                interval_count=version.interval_count,
            ):
                desired[occurrence] = version
        existing = {
            row.nominal_date: row
            for row in session.scalars(
                select(ScheduledObligation)
                .where(
                    ScheduledObligation.household_id == principal.household_id,
                    ScheduledObligation.rule_id == rule.id,
                    ScheduledObligation.nominal_date.between(start, end),
                )
                .order_by(ScheduledObligation.id)
                .with_for_update()
            )
        }
        for nominal in sorted(set(desired) | set(existing)):
            version, row = desired.get(nominal), existing.get(nominal)
            if row is None:
                row = ScheduledObligation(
                    **{name: getattr(version, name) for name in _SNAPSHOT},
                    household_id=principal.household_id,
                    rule_id=rule.id,
                    rule_version_id=version.id,
                    nominal_date=nominal,
                    scheduled_date=nominal,
                )
                session.add(row)
                _remember(session, principal, row, "create")
            elif (
                nominal >= today()
                and not row.manual_override
                and not _active_settlements(session, principal, row.id)
            ):
                changed = False
                if version is None and row.schedule_state != "superseded":
                    row.schedule_state = "superseded"
                    changed = True
                elif version is not None and (
                    row.rule_version_id != version.id or row.schedule_state != "active"
                ):
                    for name in _SNAPSHOT:
                        setattr(row, name, getattr(version, name))
                    row.rule_version_id = version.id
                    row.schedule_state = "active"
                    changed = True
                if changed:
                    _touch(session, principal, row, "regenerate")
            results.append(row)
            if len(results) > 2000:
                raise DomainError("GENERATION_TOO_LARGE", "규칙 또는 생성 기간을 줄여 주세요.", 422)
    return results


def generate(session, principal, payload: GenerateObligations, key):
    cash.lock_cash_household(session, principal)

    def execute():
        if payload.rule_id:
            rules = [
                scoped_entity(session, RecurringRule, payload.rule_id, principal, for_update=True)
            ]
        else:
            rules = list(
                session.scalars(
                    select(RecurringRule)
                    .where(
                        RecurringRule.household_id == principal.household_id,
                    )
                    .order_by(RecurringRule.id)
                    .limit(101)
                    .with_for_update()
                )
            )
            if len(rules) > 100:
                raise DomainError("GENERATION_TOO_LARGE", "규칙을 지정해서 생성해 주세요.", 422)
        rows = _generate_rows(session, principal, payload.start_date, payload.end_date, rules)
        batch = ObligationGeneration(
            household_id=principal.household_id,
            created_by_member_id=principal.member_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
        session.add(batch)
        session.flush()
        session.add_all(
            [
                ObligationGenerationItem(
                    generation_id=batch.id,
                    household_id=principal.household_id,
                    obligation_id=row.id,
                    obligation_version=row.version,
                )
                for row in rows
            ]
        )
        session.flush()
        return IdempotentResult(batch.id, "obligation_generation", 1)

    result = run_idempotent(
        session, principal, "obligations.generate", key, payload.model_dump(mode="json"), execute
    )
    items = list(
        session.scalars(
            select(ObligationGenerationItem)
            .where(
                ObligationGenerationItem.household_id == principal.household_id,
                ObligationGenerationItem.generation_id == result.resource_id,
            )
            .order_by(ObligationGenerationItem.obligation_id)
        )
    )
    response = GenerationResponse(
        id=result.resource_id,
        items=[
            MutationReference(
                id=item.obligation_id,
                version=item.obligation_version,
            )
            for item in items
        ],
    )
    session.commit()
    return response


def _obligation_response(session, principal, row):
    actuals = _active_settlements(session, principal, row.id)
    try:
        totals = settlement_totals(
            row.expected_amount_krw, [fact.amount_krw for _, fact in actuals]
        )
        breakdown = {
            field: krw_string(sum(int(getattr(payment, field)) for payment, _ in actuals))
            for field in ("consumption_krw", "principal_krw", "asset_transfer_krw")
        }
    except ValueError:
        raise DomainError(
            "AMOUNT_OUT_OF_RANGE", "집계 금액이 지원 범위를 초과합니다.", 422
        ) from None
    status = "unpaid"
    if row.schedule_state == "superseded":
        status = "superseded"
    elif row.skipped:
        status = "skipped"
    elif row.manually_completed or (
        totals.actual_krw > 0
        and totals.expected_krw is not None
        and totals.actual_krw >= totals.expected_krw
    ):
        status = "paid"
    elif totals.actual_krw > 0:
        status = "partial"
    values = {name: getattr(row, name) for name in _OBLIGATION_VALUES}
    values["expected_amount_krw"] = _money(row.expected_amount_krw)
    return ObligationResponse(
        **values,
        **breakdown,
        id=row.id,
        version=row.version,
        status=status,
        actual_amount_krw=str(totals.actual_krw),
        difference_krw=_money(totals.difference_krw),
    )


def get_obligation(session, principal, obligation_id):
    row = scoped_entity(session, ScheduledObligation, obligation_id, principal)
    response = _obligation_response(session, principal, row)
    session.commit()
    return response


def _month_bounds(month):
    start = month_start(month)
    return start, date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])


def list_obligations(session, principal, month, *, cursor=None, limit=50):
    start, end = _month_bounds(month)
    query = select(ScheduledObligation).where(
        ScheduledObligation.household_id == principal.household_id,
        ScheduledObligation.scheduled_date.between(start, end),
    )
    if cursor:
        query = query.where(ScheduledObligation.id < cursor)
    rows = list(session.scalars(query.order_by(ScheduledObligation.id.desc()).limit(limit + 1)))
    response = ObligationListResponse(
        items=[_obligation_response(session, principal, row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )
    session.commit()
    return response


def obligation_action(session, principal, obligation_id, payload, if_match, key, *, action):
    cash.lock_cash_household(session, principal)

    def execute():
        row = scoped_entity(session, ScheduledObligation, obligation_id, principal, for_update=True)
        require_version(row, if_match)
        if row.schedule_state != "active":
            raise DomainError("OBLIGATION_SUPERSEDED", "현재 적용되는 회차를 선택해 주세요.", 409)
        actuals = _active_settlements(session, principal, row.id)
        if action == "reschedule":
            if actuals or row.manually_completed or row.skipped:
                raise DomainError(
                    "OBLIGATION_HAS_PAYMENT",
                    "납부·처리 이력이 있는 회차는 이동할 수 없습니다.",
                    409,
                )
            row.scheduled_date = payload.scheduled_date
        elif action == "skip":
            if actuals or row.manually_completed or row.skipped:
                raise DomainError(
                    "OBLIGATION_HAS_PAYMENT", "납부를 먼저 취소한 뒤 건너뛰어 주세요.", 409
                )
            row.skipped = True
        elif action == "unskip":
            if not row.skipped:
                raise DomainError(
                    "INVALID_OBLIGATION_STATE", "건너뛴 회차만 되돌릴 수 있습니다.", 409
                )
            row.skipped = False
        elif action == "complete":
            if row.skipped or row.manually_completed or not actuals:
                raise DomainError(
                    "ACTUAL_PAYMENT_REQUIRED", "실제 납부를 기록한 뒤 완료해 주세요.", 409
                )
            row.manually_completed = True
        elif action == "reopen":
            if not row.manually_completed:
                raise DomainError(
                    "INVALID_OBLIGATION_STATE", "수동 완료한 회차만 재개할 수 있습니다.", 409
                )
            row.manually_completed = False
        else:
            raise ValueError("Unknown obligation action")
        row.manual_override = True
        _touch(session, principal, row, action, payload.reason)
        return IdempotentResult(row.id, "obligation", row.version, 200)

    return _reference_finish(
        session,
        run_idempotent(
            session,
            principal,
            f"obligations.{action}",
            key,
            {
                "id": str(obligation_id),
                "if_match": if_match,
                "body": payload.model_dump(mode="json"),
            },
            execute,
        ),
    )


def obligation_history(session, principal, obligation_id, *, cursor=None, limit=50):
    scoped_entity(session, ScheduledObligation, obligation_id, principal)
    query = select(ObligationRevision).where(
        ObligationRevision.household_id == principal.household_id,
        ObligationRevision.obligation_id == obligation_id,
    )
    if cursor:
        query = query.where(ObligationRevision.version < cursor)
    rows = list(session.scalars(query.order_by(ObligationRevision.version.desc()).limit(limit + 1)))
    items = []
    for row in rows[:limit]:
        values = {
            name: getattr(row, name)
            for name in ObligationHistoryItem.model_fields
            if name not in {"id", "expected_amount_krw"}
        }
        items.append(
            ObligationHistoryItem(
                **values, id=row.obligation_id, expected_amount_krw=_money(row.expected_amount_krw)
            )
        )
    response = ObligationHistoryResponse(
        items=items, next_cursor=rows[limit - 1].version if len(rows) > limit else None
    )
    session.commit()
    return response


def _settlement_response(session, principal, row, version=None):
    fact = scoped_entity(session, CashRecord, row.cash_record_id, principal)
    revision = cash._revision(session, principal, fact.id, version or fact.version)
    return SettlementResponse(
        id=row.id,
        obligation_id=row.obligation_id,
        economic_type=row.economic_type,
        principal_krw=krw_string(row.principal_krw),
        consumption_krw=krw_string(row.consumption_krw),
        asset_transfer_krw=krw_string(row.asset_transfer_krw),
        cash=cash._response(revision),
    )


def settle(session, principal, obligation_id, payload, if_match, key):
    cash.lock_cash_household(session, principal)

    def execute():
        row = scoped_entity(session, ScheduledObligation, obligation_id, principal, for_update=True)
        require_version(row, if_match)
        if row.schedule_state != "active" or row.skipped or row.manually_completed:
            raise DomainError("OBLIGATION_CLOSED", "납부 가능한 회차를 선택해 주세요.", 409)
        try:
            breakdown = payment_breakdown(
                decimal_krw(payload.amount_krw),
                economic_type=row.economic_type,
                principal_krw=decimal_krw(payload.principal_krw),
                interest_krw=None
                if payload.interest_krw is None
                else decimal_krw(payload.interest_krw),
            )
        except ValueError:
            raise DomainError(
                "INVALID_PAYMENT_SPLIT", "원금·이자 합계와 실제 납부액을 확인해 주세요.", 422
            ) from None
        _validate_method(session, principal, payload.account_id, payload.card_id)
        cash_values = dict(
            amount_krw=payload.amount_krw,
            occurred_on=payload.occurred_on,
            period_month=payload.occurred_on.strftime("%Y-%m"),
            date_precision="day",
            account_id=payload.account_id,
            note=payload.note,
        )
        if payload.card_id is not None:
            cash_values["card_id"] = payload.card_id
        fact = cash.prepare_cash_record(
            session, principal, CashInput(**cash_values), kind="fixed_payment"
        )
        settlement = FixedSettlement(
            household_id=principal.household_id,
            obligation_id=row.id,
            cash_record_id=fact.id,
            economic_type=row.economic_type,
            principal_krw=breakdown.principal_krw,
            consumption_krw=breakdown.consumption_krw,
            asset_transfer_krw=breakdown.asset_transfer_krw,
        )
        session.add(settlement)
        session.flush()
        _touch(session, principal, row, "settle")
        _audit(session, principal, settlement, "fixed_settlement", "create", ("cash_record_id",))
        # Detect aggregate overflow before committing a cash fact that the UI cannot represent.
        _obligation_response(session, principal, row)
        return IdempotentResult(settlement.id, "fixed_settlement", fact.version)

    result = run_idempotent(
        session,
        principal,
        "obligations.settle",
        key,
        {"id": str(obligation_id), "if_match": if_match, "body": payload.model_dump(mode="json")},
        execute,
    )
    row = scoped_entity(session, FixedSettlement, result.resource_id, principal)
    response = _settlement_response(session, principal, row, result.resource_version)
    session.commit()
    return response


def void_settlement(session, principal, settlement_id, payload, if_match, key):
    cash.lock_cash_household(session, principal)

    def execute():
        payment = scoped_entity(session, FixedSettlement, settlement_id, principal)
        row = scoped_entity(
            session, ScheduledObligation, payment.obligation_id, principal, for_update=True
        )
        fact = cash.prepare_void_cash_record(
            session,
            principal,
            payment.cash_record_id,
            kind="fixed_payment",
            reason=payload.reason,
            if_match=if_match,
        )
        row.manually_completed = False
        _touch(session, principal, row, "void_settlement", payload.reason)
        _audit(session, principal, payment, "fixed_settlement", "void", ("cash_record_id",))
        return IdempotentResult(payment.id, "fixed_settlement", fact.version, 200)

    result = run_idempotent(
        session,
        principal,
        "settlements.void",
        key,
        {"id": str(settlement_id), "if_match": if_match, "body": payload.model_dump(mode="json")},
        execute,
    )
    response = _settlement_response(
        session,
        principal,
        scoped_entity(session, FixedSettlement, result.resource_id, principal),
        result.resource_version,
    )
    session.commit()
    return response


def list_settlements(session, principal, obligation_id, *, cursor=None, limit=50):
    scoped_entity(session, ScheduledObligation, obligation_id, principal)
    query = select(FixedSettlement).where(
        FixedSettlement.household_id == principal.household_id,
        FixedSettlement.obligation_id == obligation_id,
    )
    if cursor:
        query = query.where(FixedSettlement.id < cursor)
    rows = list(session.scalars(query.order_by(FixedSettlement.id.desc()).limit(limit + 1)))
    response = SettlementListResponse(
        items=[_settlement_response(session, principal, row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )
    session.commit()
    return response


def summary(session, principal, month):
    start, end = _month_bounds(month)
    expected = list(
        session.scalars(
            select(ScheduledObligation).where(
                ScheduledObligation.household_id == principal.household_id,
                ScheduledObligation.scheduled_date.between(start, end),
                ScheduledObligation.schedule_state == "active",
                ScheduledObligation.skipped.is_(False),
            )
        )
    )
    actuals = list(
        session.execute(
            select(FixedSettlement, CashRecord)
            .join(
                CashRecord,
                (
                    (CashRecord.id == FixedSettlement.cash_record_id)
                    & (CashRecord.household_id == FixedSettlement.household_id)
                ),
            )
            .where(
                FixedSettlement.household_id == principal.household_id,
                CashRecord.state == "active",
                CashRecord.occurred_on.between(start, end),
            )
        )
    )
    try:
        response = FixedSummaryResponse(
            expected_known_krw=krw_string(
                sum(
                    int(row.expected_amount_krw)
                    for row in expected
                    if row.expected_amount_krw is not None
                )
            ),
            unknown_expected_count=sum(row.expected_amount_krw is None for row in expected),
            actual_amount_krw=krw_string(sum(int(fact.amount_krw) for _, fact in actuals)),
            **{
                field: krw_string(sum(int(getattr(payment, field)) for payment, _ in actuals))
                for field in ("consumption_krw", "principal_krw", "asset_transfer_krw")
            },
            obligation_count=len(expected),
        )
    except ValueError:
        raise DomainError(
            "AMOUNT_OUT_OF_RANGE", "집계 금액이 지원 범위를 초과합니다.", 422
        ) from None
    session.commit()
    return response
