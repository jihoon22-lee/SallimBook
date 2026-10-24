"""Preserve every non-payment term; each selected rule is its own atomic command."""

from operator import attrgetter

from sqlalchemy import or_, select

from sallimbook.accounts.models import FinancialAccount
from sallimbook.assets.models import Asset
from sallimbook.cards.models import Card
from sallimbook.cashflow import recurring_service as recurring
from sallimbook.cashflow import service as cash
from sallimbook.cashflow.payment_switch_schemas import (
    PaymentSwitchInput,
    PaymentSwitchPreview,
    PaymentSwitchRow,
)
from sallimbook.cashflow.recurring_models import (
    RecurringRule,
    RecurringRuleVersion,
    ScheduledObligation,
)
from sallimbook.cashflow.recurring_schemas import ScheduleTerms
from sallimbook.core.authorization import require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.idempotency import IdempotentResult, payload_hash, run_idempotent
from sallimbook.core.pagination import page_after
from sallimbook.identity.service import utcnow


def _method(session, principal, kind, identifier):
    if kind == "card":
        row = scoped_entity(session, Card, identifier, principal)
        return row.version
    row = scoped_entity(session, FinancialAccount, identifier, principal)
    return scoped_entity(session, Asset, row.asset_id, principal).version


def _scope(session, principal, payload):
    return [
        _method(session, principal, payload.source_kind, payload.source_id),
        _method(session, principal, payload.target_kind, payload.target_id),
    ]


def _validate(session, principal, payload):
    if payload.effective_on < recurring.today():
        raise DomainError("PAST_RULE_CHANGE", "지난 날짜부터는 변경할 수 없습니다.", 409)
    recurring._validate_method(
        session,
        principal,
        payload.target_id if payload.target_kind == "account" else None,
        payload.target_id if payload.target_kind == "card" else None,
    )


def _matches(row, payload):
    return getattr(row, f"{payload.source_kind}_id") == payload.source_id


def _affected(version, payload):
    return _matches(version, payload) and (
        version.effective_until is None or version.effective_until > payload.effective_on
    )


def _row(session, principal, rule, payload, method_versions):
    versions = recurring._versions(session, principal, rule.id)
    matched = [version for version in versions if _affected(version, payload)]
    if not matched:
        raise DomainError(
            "PAYMENT_LINKS_CHANGED", "연결이 변경되었습니다. 다시 확인해 주세요.", 409
        )
    obligations = list(
        session.scalars(
            select(ScheduledObligation)
            .where(
                ScheduledObligation.household_id == principal.household_id,
                ScheduledObligation.rule_id == rule.id,
            )
            .order_by(ScheduledObligation.id)
        )
    )
    paid = recurring._active_settlements_by_obligation(
        session, principal, [row.id for row in obligations]
    )
    counts = dict(
        update_occurrence_count=0,
        preserved_past_count=0,
        preserved_paid_count=0,
        preserved_manual_count=0,
    )
    affected_ids = {version.id for version in matched}
    for row in obligations:
        if not _matches(row, payload):
            continue
        if row.nominal_date < payload.effective_on:
            counts["preserved_past_count"] += 1
        elif paid[row.id]:
            counts["preserved_paid_count"] += 1
        elif row.manual_override:
            counts["preserved_manual_count"] += 1
        elif row.rule_version_id in affected_ids and row.schedule_state == "active":
            counts["update_occurrence_count"] += 1
    # Full term/state fingerprints detect same-version occurrence/payment edits as well.
    response = recurring._rule_response(session, principal, rule, versions=versions)
    digest = payload_hash(
        dict(
            request=PaymentSwitchInput.model_validate(
                payload.model_dump(include=set(PaymentSwitchInput.model_fields))
            ).model_dump(mode="json"),
            method_versions=method_versions,
            rule=response.model_dump(mode="json"),
            obligations=[
                dict(
                    id=str(row.id),
                    version=row.version,
                    paid=[[str(item.id), fact.version] for item, fact in paid[row.id]],
                )
                for row in obligations
            ],
        )
    )
    return PaymentSwitchRow(
        id=rule.id,
        version=rule.version,
        title=matched[0].title,
        periods=[version for version in response.versions if version.id in affected_ids],
        unchanged_period_count=len(versions) - len(matched),
        blocked_reason=(
            "INITIAL_PERIOD_START"
            if versions[0] in matched and payload.effective_on <= versions[0].effective_from
            else None
        ),
        preview_digest=digest,
        **counts,
    ), matched


def preview(session, principal, payload, *, cursor=None, limit=50):
    cash.lock_cash_household(session, principal)
    method_versions = _scope(session, principal, payload)
    _validate(session, principal, payload)
    rules = list(
        session.scalars(
            select(RecurringRule)
            .where(
                RecurringRule.household_id == principal.household_id,
                RecurringRule.id.in_(
                    select(RecurringRuleVersion.rule_id).where(
                        RecurringRuleVersion.household_id == principal.household_id,
                        RecurringRuleVersion.revoked_at.is_(None),
                        getattr(RecurringRuleVersion, f"{payload.source_kind}_id")
                        == payload.source_id,
                        or_(
                            RecurringRuleVersion.effective_until.is_(None),
                            RecurringRuleVersion.effective_until > payload.effective_on,
                        ),
                    )
                ),
            )
            .order_by(RecurringRule.id)
        )
    )
    selected, next_cursor = page_after(rules, cursor=cursor, limit=limit, key=attrgetter("id"))
    result = PaymentSwitchPreview(
        items=[_row(session, principal, row, payload, method_versions)[0] for row in selected],
        next_cursor=next_cursor,
    )
    session.commit()
    return result


def apply(session, principal, rule_id, payload, if_match, key):
    cash.lock_cash_household(session, principal)
    # Authorization precedes idempotent replay; current linkage is only required on first write.
    method_versions = _scope(session, principal, payload)
    rule = scoped_entity(session, RecurringRule, rule_id, principal, for_update=True)

    def execute():
        require_version(rule, if_match)
        _validate(session, principal, payload)
        view, matched = _row(session, principal, rule, payload, method_versions)
        if view.preview_digest != payload.preview_digest:
            raise DomainError(
                "PAYMENT_LINKS_CHANGED", "미리보기 후 기록이 바뀌었습니다. 다시 확인해 주세요.", 409
            )
        if view.blocked_reason:
            raise DomainError(
                "RULE_PERIOD_OVERLAP", "첫 규칙 시작일 다음 날부터 적용해 주세요.", 409
            )
        replacements = []
        for old in matched:
            start = max(payload.effective_on, old.effective_from)
            values = {name: getattr(old, name) for name in ScheduleTerms.model_fields}
            values.update(account_id=None, card_id=None)
            values[f"{payload.target_kind}_id"] = payload.target_id
            replacements.append(
                RecurringRuleVersion(
                    **values,
                    household_id=principal.household_id,
                    rule_id=rule.id,
                    effective_from=start,
                    effective_until=old.effective_until,
                    reason=payload.reason,
                )
            )
            if old.effective_from < start:
                old.effective_until = start
            else:
                # This method-only replacement preserves paid/manual occurrence snapshots.
                # No period, amount or cadence is removed as in a general rule rewrite.
                old.revoked_at = utcnow()
        session.flush()
        session.add_all(replacements)
        before = rule.version
        rule.version += 1
        rule.updated_at = utcnow()
        recurring._audit(
            session,
            principal,
            rule,
            "recurring_rule",
            "update",
            {"account_id", "card_id", "effective_from", "reason"},
            before,
        )
        session.flush()
        recurring._change_window(session, principal, rule, payload.effective_on)
        return IdempotentResult(rule.id, "recurring_rule", rule.version, 200)

    return recurring._reference_finish(
        session,
        run_idempotent(
            session,
            principal,
            "payment-switch.apply",
            key,
            dict(id=str(rule_id), if_match=if_match, body=payload.model_dump(mode="json")),
            execute,
        ),
    )
