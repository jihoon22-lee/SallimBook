"""Household-serialized recurrence and actual settlements; no balance/snapshot writes."""

import calendar
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, or_, select, text

from sallimbook.accounts.models import FinancialAccount
from sallimbook.assets.models import Asset
from sallimbook.assets.month_models import AssetMonthRecord, AssetMonthRevision
from sallimbook.cashflow import service as cash
from sallimbook.cashflow.models import CashRecord, CashRecordRevision
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
from sallimbook.core.pagination import keyset_page
from sallimbook.core.types import SEOUL, decimal_krw, krw_string, month_start
from sallimbook.identity.service import utcnow
from sallimbook.insurance.models import PolicyPremiumLink

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


def _audit(session, principal, row, entity, action, fields, before=None, after=None):
    record_event(
        session,
        principal,
        entity_type=entity,
        entity_id=row.id,
        action=action,
        before_version=before,
        after_version=after if after is not None else getattr(row, "version", 1),
        changed_fields=fields,
    )


def _validate_method(session, principal, account_id, card_id, loan_asset_id=None, *, on=None):
    # Plans (on=None) need a method still in use; an actual payment only needs it on that day.
    def closed(ended_on):
        return ended_on is not None and (on is None or ended_on < on)

    account = None
    asset_ids = set()
    if account_id is not None:
        account = scoped_entity(session, FinancialAccount, account_id, principal)
        asset_ids.add(account.asset_id)
    if loan_asset_id is not None:
        asset_ids.add(loan_asset_id)
    assets = {
        asset_id: scoped_entity(session, Asset, asset_id, principal, for_update=True)
        for asset_id in sorted(asset_ids)
    }
    if loan_asset_id is not None:
        loan = assets[loan_asset_id]
        if loan.kind != "liability" or loan.ended_on is not None:
            raise DomainError("LOAN_UNAVAILABLE", "사용 중인 부채를 선택해 주세요.", 422)
    if account is not None:
        scoped_entity(session, FinancialAccount, account_id, principal, for_update=True)
        if closed(assets[account.asset_id].ended_on):
            raise DomainError("ACCOUNT_UNAVAILABLE", "사용 중인 납부 계좌를 선택해 주세요.", 422)
    if card_id is not None:
        from sallimbook.cards.models import Card

        card = scoped_entity(session, Card, card_id, principal, for_update=True)
        if closed(card.ended_on):
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
                RecurringRuleVersion.revoked_at.is_(None),
            )
            .order_by(RecurringRuleVersion.effective_from)
        )
    )


def _rule_response(session, principal, row, *, versions=None):
    if versions is None:
        versions = _versions(session, principal, row.id)
    # Callers with their own queries (list_rules, insurance premiums) pass revoked rows too.
    versions = [version for version in versions if version.revoked_at is None]
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
            for version in versions
        ],
    )


def _reference_finish(session, result):
    response = MutationReference(id=result.resource_id, version=result.resource_version)
    session.commit()
    return response


def create_rule(session, principal, payload, key):
    cash.lock_cash_household(session, principal)

    def execute():
        _validate_method(
            session, principal, payload.account_id, payload.card_id, payload.loan_asset_id
        )
        row = RecurringRule(
            household_id=principal.household_id,
            created_by_member_id=principal.member_id,
            ended_on=payload.effective_until,
            end_reason=payload.end_reason,
        )
        session.add(row)
        session.flush()
        session.add(
            RecurringRuleVersion(
                **_term_values(payload),
                household_id=principal.household_id,
                rule_id=row.id,
                effective_from=payload.effective_from,
                effective_until=payload.effective_until,
                reason=payload.end_reason,
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
    # Preserve the requested horizon, not just the date of its last occurrence.
    # Otherwise moving a monthly anchor from the 15th to the 31st loses the final month.
    windows = list(
        session.execute(
            select(ObligationGeneration.start_date, ObligationGeneration.end_date)
            .where(
                ObligationGeneration.household_id == principal.household_id,
                or_(
                    ObligationGeneration.rule_id == rule.id, ObligationGeneration.rule_id.is_(None)
                ),
                ObligationGeneration.end_date >= start,
            )
            .order_by(ObligationGeneration.start_date)
        )
    )
    merged = []
    for lower, upper in windows:
        lower = max(start, lower)
        if merged and lower <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], upper))
        else:
            merged.append((lower, upper))
    for lower, upper in merged:
        cursor = lower
        while cursor <= upper:
            window_end = cursor + timedelta(days=min(365, (upper - cursor).days))
            _generate_rows(session, principal, cursor, window_end, [rule])
            if window_end == date.max:
                break
            cursor = window_end + timedelta(days=1)


def _split_at(versions, cutoff):
    """The version running into cutoff and the not-yet-started versions from cutoff on."""
    anchor = None
    for version in versions:
        if version.effective_from < cutoff:
            anchor = version
    pending = [version for version in versions if version.effective_from >= cutoff]
    if anchor is None or any(version.effective_from <= today() for version in pending):
        raise DomainError(
            "RULE_PERIOD_OVERLAP",
            "현재 적용 중인 규칙의 시작일 뒤이면서 기존 종료일 전인 날짜를 선택해 주세요.",
            409,
        )
    return anchor, pending


def _revoke(session, principal, versions):
    """Withdraw not-yet-started versions whose occurrences are still untouched."""
    if not versions:
        return
    ids = [version.id for version in versions]
    rows = list(
        session.scalars(
            select(ScheduledObligation)
            .where(
                ScheduledObligation.household_id == principal.household_id,
                ScheduledObligation.rule_version_id.in_(ids),
            )
            .order_by(ScheduledObligation.id)
            .with_for_update()
        )
    )
    settlements = _active_settlements_by_obligation(session, principal, [row.id for row in rows])
    if any(settlements[row.id] or _has_exception(row) for row in rows):
        raise DomainError(
            "OBLIGATION_HAS_PAYMENT",
            "시작 전 변경에 납부·수동 변경한 회차가 있어 철회할 수 없습니다.",
            409,
        )
    revoked_at = datetime.now(UTC)
    for version in versions:
        version.revoked_at = revoked_at
    session.flush()  # Free the start date and period before a replacement version is added.


def change_rule(session, principal, rule_id, payload, if_match, key):
    cash.lock_cash_household(session, principal)

    def execute():
        row = scoped_entity(session, RecurringRule, rule_id, principal, for_update=True)
        require_version(row, if_match)
        versions = _versions(session, principal, row.id)
        if row.ended_on is not None and payload.effective_from >= row.ended_on:
            raise DomainError(
                "RULE_PERIOD_OVERLAP",
                "마지막 규칙 이후이면서 기존 종료일 전인 적용일을 선택해 주세요.",
                409,
            )
        if payload.effective_from < today():
            raise DomainError("PAST_RULE_CHANGE", "지난 규칙은 변경할 수 없습니다.", 409)
        # A change dated at or before a not-yet-started version replaces it.
        anchor, pending = _split_at(versions, payload.effective_from)
        _validate_method(
            session, principal, payload.account_id, payload.card_id, payload.loan_asset_id
        )
        _revoke(session, principal, pending)
        # The trigger only lets a period end move earlier, so equal values are not reassigned.
        if anchor.effective_until != payload.effective_from:
            anchor.effective_until = payload.effective_from
        session.flush()  # Close the old range before the exclusion constraint sees its successor.
        session.add(
            RecurringRuleVersion(
                **_term_values(payload),
                household_id=principal.household_id,
                rule_id=row.id,
                effective_from=payload.effective_from,
                effective_until=row.ended_on,
                reason=payload.reason,
            )
        )
        before = row.version
        row.version += 1
        row.updated_at = datetime.now(UTC)
        changed = set(payload.model_fields_set) | ({"revoked_at"} if pending else set())
        _audit(session, principal, row, "recurring_rule", "update", changed, before)
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
        versions = _versions(session, principal, row.id)
        # A future cutoff can only move earlier. Together with today's lower bound,
        # this cannot reopen an elapsed rule or rewrite an earlier version's period.
        if row.ended_on is not None and payload.effective_on >= row.ended_on:
            raise DomainError(
                "RULE_PERIOD_OVERLAP",
                "마지막 적용일 이후이며 기존 종료일보다 이른 날짜를 선택해 주세요.",
                409,
            )
        if payload.effective_on < today():
            raise DomainError("PAST_RULE_CHANGE", "지난 규칙은 변경할 수 없습니다.", 409)
        # Ending before a not-yet-started version withdraws it.
        anchor, pending = _split_at(versions, payload.effective_on)
        _revoke(session, principal, pending)
        if anchor.effective_until != payload.effective_on:
            anchor.effective_until = payload.effective_on
        row.ended_on = payload.effective_on
        row.end_reason = payload.reason
        before = row.version
        row.version += 1
        row.updated_at = datetime.now(UTC)
        fields = ("ended_on", "revoked_at") if pending else ("ended_on",)
        _audit(session, principal, row, "recurring_rule", "archive", fields, before)
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


def _rule_in_use(session, principal, rule, obligations):
    """A payment, a confirmed month or a handled occurrence keeps the rule; it can only end."""
    ids = [row.id for row in obligations]
    months = {
        month_start(day.strftime("%Y-%m"))
        for row in obligations
        for day in (row.nominal_date, row.scheduled_date)
    }
    checks = [
        select(PolicyPremiumLink.id).where(
            PolicyPremiumLink.household_id == principal.household_id,
            PolicyPremiumLink.rule_id == rule.id,
        )
    ]
    if ids:
        checks += [
            # Active and voided payments alike: a voided one is still ledger history.
            select(FixedSettlement.id).where(
                FixedSettlement.household_id == principal.household_id,
                FixedSettlement.obligation_id.in_(ids),
            ),
            select(ObligationRevision.obligation_id).where(
                ObligationRevision.household_id == principal.household_id,
                ObligationRevision.obligation_id.in_(ids),
                ObligationRevision.action.not_in(("create", "regenerate")),
            ),
            select(AssetMonthRecord.id)
            .join(
                AssetMonthRevision,
                (AssetMonthRevision.month_id == AssetMonthRecord.id)
                & (AssetMonthRevision.household_id == AssetMonthRecord.household_id),
            )
            .where(
                AssetMonthRecord.household_id == principal.household_id,
                AssetMonthRecord.period_month.in_(months),
                AssetMonthRevision.state == "confirmed",
            ),
        ]
    return any(session.scalar(check.limit(1)) is not None for check in checks)


def delete_rule(session, principal, rule_id, if_match, key):
    cash.lock_cash_household(session, principal)

    def execute():
        row = scoped_entity(session, RecurringRule, rule_id, principal, for_update=True)
        require_version(row, if_match)
        obligations = list(
            session.scalars(
                select(ScheduledObligation)
                .where(
                    ScheduledObligation.household_id == principal.household_id,
                    ScheduledObligation.rule_id == row.id,
                )
                .order_by(ScheduledObligation.id)
                .with_for_update()
            )
        )
        if _rule_in_use(session, principal, row, obligations):
            raise DomainError(
                "RULE_IN_USE",
                "보험료로 연결됐거나 납부 기록·확정된 월이 있는 규칙은 종료만 할 수 있어요.",
                409,
            )
        record_event(
            session,
            principal,
            entity_type="recurring_rule",
            entity_id=row.id,
            action="delete",
            before_version=row.version,
            after_version=None,
        )
        ids = [item.id for item in obligations]
        household = principal.household_id
        # The history triggers let this transaction delete this rule's generated rows only.
        session.execute(
            text("SELECT set_config('sallimbook.deleting_rule', :rule, true)"),
            {"rule": str(row.id)},
        )
        for statement in (
            delete(ObligationGenerationItem).where(
                ObligationGenerationItem.household_id == household,
                ObligationGenerationItem.obligation_id.in_(ids),
            ),
            delete(ObligationRevision).where(
                ObligationRevision.household_id == household,
                ObligationRevision.obligation_id.in_(ids),
            ),
            delete(ScheduledObligation).where(
                ScheduledObligation.household_id == household, ScheduledObligation.id.in_(ids)
            ),
            delete(ObligationGeneration).where(
                ObligationGeneration.household_id == household,
                ObligationGeneration.rule_id == row.id,
            ),
            delete(RecurringRuleVersion).where(
                RecurringRuleVersion.household_id == household,
                RecurringRuleVersion.rule_id == row.id,
            ),
        ):
            session.execute(statement.execution_options(synchronize_session=False))
        version = row.version
        session.delete(row)
        session.flush()
        session.execute(text("SELECT set_config('sallimbook.deleting_rule', '', true)"))
        return IdempotentResult(rule_id, "recurring_rule", version, 204)

    run_idempotent(
        session,
        principal,
        "recurring.delete",
        key,
        {"id": str(rule_id), "if_match": if_match},
        execute,
    )
    session.commit()


def get_rule(session, principal, rule_id):
    cash.lock_cash_household(session, principal)
    response = _rule_response(
        session, principal, scoped_entity(session, RecurringRule, rule_id, principal)
    )
    session.commit()
    return response


def list_rules(session, principal, *, cursor=None, limit=50):
    cash.lock_cash_household(session, principal)
    query = select(RecurringRule).where(RecurringRule.household_id == principal.household_id)
    rows, next_cursor = keyset_page(
        session,
        query,
        model=RecurringRule,
        household_id=principal.household_id,
        keys=(RecurringRule.created_at,),
        cursor=cursor,
        limit=limit,
    )
    versions = {row.id: [] for row in rows}
    if versions:
        for version in session.scalars(
            select(RecurringRuleVersion)
            .where(
                RecurringRuleVersion.household_id == principal.household_id,
                RecurringRuleVersion.rule_id.in_(versions),
            )
            .order_by(RecurringRuleVersion.rule_id, RecurringRuleVersion.effective_from)
        ):
            versions[version.rule_id].append(version)
    response = RuleListResponse(
        items=[_rule_response(session, principal, row, versions=versions[row.id]) for row in rows],
        next_cursor=next_cursor,
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


def _has_exception(row: ScheduledObligation) -> bool:
    """The occurrence differs from what its rule would generate; keep it on regeneration."""
    return row.skipped or row.manually_completed or row.scheduled_date != row.nominal_date


def _touch(session, principal, row, action, reason=None):
    row.manual_override = _has_exception(row)
    before = row.version
    row.version += 1
    row.updated_at = datetime.now(UTC)
    _remember(session, principal, row, action, reason=reason, before=before)


def _follow_rule(session, principal, row):
    """Once its last exception is cleared, an occurrence takes what its rule now generates.

    Generation leaves exceptions alone, so a rule ended or changed meanwhile only reaches the
    occurrence here. The same refresh applies: paid and past occurrences stay as they are.
    """
    if row.manual_override:
        return
    rule = scoped_entity(session, RecurringRule, row.rule_id, principal, for_update=True)
    _generate_rows(session, principal, row.nominal_date, row.nominal_date, [rule])


def _active_settlements_by_obligation(session, principal, obligation_ids):
    grouped = {obligation_id: [] for obligation_id in obligation_ids}
    if not grouped:
        return grouped
    rows = session.execute(
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
            FixedSettlement.obligation_id.in_(grouped),
            CashRecord.state == "active",
        )
        .order_by(FixedSettlement.id)
    )
    for payment, fact in rows:
        grouped[payment.obligation_id].append((payment, fact))
    return grouped


def _active_settlements(session, principal, obligation_id):
    return _active_settlements_by_obligation(session, principal, [obligation_id])[obligation_id]


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
            rule_id=payload.rule_id,
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


def _obligation_response(session, principal, row, *, actuals=None):
    if actuals is None:
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
        and (totals.expected_krw is None or totals.actual_krw >= totals.expected_krw)
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
    cash.lock_cash_household(session, principal)
    row = scoped_entity(session, ScheduledObligation, obligation_id, principal)
    response = _obligation_response(session, principal, row)
    session.commit()
    return response


def _month_bounds(month):
    start = month_start(month)
    return start, date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])


def list_obligations(session, principal, month, *, cursor=None, limit=50):
    cash.lock_cash_household(session, principal)
    start, end = _month_bounds(month)
    query = select(ScheduledObligation).where(
        ScheduledObligation.household_id == principal.household_id,
        ScheduledObligation.scheduled_date.between(start, end),
    )
    rows, next_cursor = keyset_page(
        session,
        query,
        model=ScheduledObligation,
        household_id=principal.household_id,
        keys=(ScheduledObligation.scheduled_date, ScheduledObligation.created_at),
        cursor=cursor,
        limit=limit,
        descending=False,
    )
    actuals = _active_settlements_by_obligation(session, principal, [row.id for row in rows])
    response = ObligationListResponse(
        items=[
            _obligation_response(session, principal, row, actuals=actuals[row.id]) for row in rows
        ],
        next_cursor=next_cursor,
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
        _touch(session, principal, row, action, payload.reason)
        if action in ("unskip", "reschedule", "reopen"):
            _follow_rule(session, principal, row)
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


def _settlement_response(session, principal, row, version=None, *, revision=None):
    if revision is None:
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
        _validate_method(
            session, principal, payload.account_id, payload.card_id, on=payload.occurred_on
        )
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
        # A completion stands on a recorded payment: it stays while another payment remains.
        if not _active_settlements(session, principal, row.id):
            row.manually_completed = False
        _touch(session, principal, row, "void_settlement", payload.reason)
        _follow_rule(session, principal, row)
        _audit(
            session,
            principal,
            payment,
            "fixed_settlement",
            "void",
            ("cash_record_id",),
            before=fact.version - 1,
            after=fact.version,
        )
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
    cash.lock_cash_household(session, principal)
    scoped_entity(session, ScheduledObligation, obligation_id, principal)
    query = (
        select(FixedSettlement, CashRecordRevision)
        .join(
            CashRecord,
            (
                (CashRecord.id == FixedSettlement.cash_record_id)
                & (CashRecord.household_id == FixedSettlement.household_id)
            ),
        )
        .join(
            CashRecordRevision,
            (
                (CashRecordRevision.cash_record_id == CashRecord.id)
                & (CashRecordRevision.household_id == CashRecord.household_id)
                & (CashRecordRevision.version == CashRecord.version)
            ),
        )
        .where(
            FixedSettlement.household_id == principal.household_id,
            FixedSettlement.obligation_id == obligation_id,
        )
    )
    rows, next_cursor = keyset_page(
        session,
        query,
        model=FixedSettlement,
        household_id=principal.household_id,
        keys=(cash.cash_date(FixedSettlement), FixedSettlement.created_at),
        cursor=cursor,
        limit=limit,
        scalars=False,
        cursor_of=lambda row: row[0].id,
    )
    response = SettlementListResponse(
        items=[
            _settlement_response(session, principal, payment, revision=revision)
            for payment, revision in rows
        ],
        next_cursor=next_cursor,
    )
    session.commit()
    return response


def summary(session, principal, month):
    # Share the mutation barrier so planned and actual queries agree.
    cash.lock_cash_household(session, principal)
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
