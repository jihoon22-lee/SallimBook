"""One version store for plans and schedules; no cash or snapshot side effects."""

from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select

from sallimbook.cashflow import recurring_service as recurring
from sallimbook.cashflow import service as cash
from sallimbook.cashflow.expense_plan_schemas import (
    PlanListResponse,
    PlanResponse,
    PlanSubtotal,
    PlanSummaryResponse,
    PlanTerms,
    PlanVersionResponse,
)
from sallimbook.cashflow.recurring_models import (
    RecurringRule,
    RecurringRuleVersion,
    ScheduledObligation,
)
from sallimbook.core.authorization import require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.idempotency import IdempotentResult, run_idempotent
from sallimbook.core.name_search import search_names
from sallimbook.core.pagination import keyset_page
from sallimbook.identity.auth_models import HouseholdMember


def monthly_equivalent(version):
    if version.expected_amount_krw is None or version.frequency == "days":
        return None
    divisor = version.interval_count * (12 if version.frequency == "annual" else 1)
    return int(
        (Decimal(version.expected_amount_krw) / divisor).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
    )


def _validate(session, principal, payload):
    recurring._validate_method(
        session, principal, payload.account_id, payload.card_id, payload.loan_asset_id
    )
    if payload.subject_member_id is not None:
        scoped_entity(session, HouseholdMember, payload.subject_member_id, principal)


def _values(payload):
    return payload.model_dump(include=set(PlanTerms.model_fields)) | {
        "expected_amount_krw": None
        if payload.expected_amount_krw is None
        else Decimal(payload.expected_amount_krw)
    }


def create_plan_in_transaction(session, principal, payload, *, baseline=None):
    """Caller owns the household lock and commit, including all-or-nothing imports."""
    _validate(session, principal, payload)
    row = RecurringRule(
        household_id=principal.household_id, created_by_member_id=principal.member_id
    )
    session.add(row)
    session.flush()
    session.add(
        RecurringRuleVersion(
            **_values(payload),
            household_id=principal.household_id,
            rule_id=row.id,
            effective_from=payload.effective_from or baseline or recurring.today(),
        )
    )
    recurring._audit(session, principal, row, "recurring_rule", "create", payload.model_fields_set)
    session.flush()
    return row


def create_plan(session, principal, payload, key):
    cash.lock_cash_household(session, principal)

    def execute():
        row = create_plan_in_transaction(session, principal, payload)
        return IdempotentResult(row.id, "recurring_rule", row.version)

    return recurring._reference_finish(
        session,
        run_idempotent(
            session, principal, "expense_plan.create", key, payload.model_dump(mode="json"), execute
        ),
    )


def split_plan_at(session, principal, versions, cutoff):
    """Allow same-start plan corrections only when no occurrence has ever referenced them."""
    pending = [v for v in versions if v.effective_from >= cutoff]
    earlier = [v for v in versions if v.effective_from < cutoff]
    if pending and all(v.tracking_mode == "plan_only" for v in pending):
        used = session.scalar(
            select(ScheduledObligation.id)
            .where(
                ScheduledObligation.household_id == principal.household_id,
                ScheduledObligation.rule_version_id.in_([v.id for v in pending]),
            )
            .limit(1)
        )
        if used is None:
            return (earlier[-1] if earlier else None), pending
    return recurring._split_at(versions, cutoff)


def change_plan(session, principal, rule_id, payload, if_match, key):
    cash.lock_cash_household(session, principal)

    def execute():
        row = scoped_entity(session, RecurringRule, rule_id, principal, for_update=True)
        require_version(row, if_match)
        start = payload.effective_from or recurring.today()
        if start < recurring.today():
            raise DomainError("PAST_RULE_CHANGE", "지난 계획은 변경할 수 없습니다.", 409)
        if row.ended_on is not None and start >= row.ended_on:
            raise DomainError("RULE_PERIOD_OVERLAP", "종료일 전의 적용일을 선택해 주세요.", 409)
        versions = recurring._versions(session, principal, row.id)
        anchor, pending = split_plan_at(session, principal, versions, start)
        _validate(session, principal, payload)
        recurring._revoke(session, principal, pending)
        if anchor is not None and anchor.effective_until != start:
            anchor.effective_until = start
        session.flush()
        session.add(
            RecurringRuleVersion(
                **_values(payload),
                household_id=principal.household_id,
                rule_id=row.id,
                effective_from=start,
                effective_until=row.ended_on,
                reason=payload.reason,
            )
        )
        before = row.version
        row.version += 1
        row.updated_at = datetime.now(UTC)
        recurring._audit(
            session, principal, row, "recurring_rule", "update", payload.model_fields_set, before
        )
        session.flush()
        recurring._change_window(session, principal, row, start)
        return IdempotentResult(row.id, "recurring_rule", row.version, 200)

    return recurring._reference_finish(
        session,
        run_idempotent(
            session,
            principal,
            "expense_plan.change",
            key,
            {"id": str(rule_id), "if_match": if_match, "body": payload.model_dump(mode="json")},
            execute,
        ),
    )


def _response(session, principal, row):
    all_versions = list(
        session.scalars(
            select(RecurringRuleVersion)
            .where(
                RecurringRuleVersion.household_id == principal.household_id,
                RecurringRuleVersion.rule_id == row.id,
            )
            .order_by(
                RecurringRuleVersion.effective_from,
                RecurringRuleVersion.created_at,
                RecurringRuleVersion.id,
            )
        )
    )
    history = [
        PlanVersionResponse(
            **(
                {name: getattr(v, name) for name in PlanTerms.model_fields}
                | {"expected_amount_krw": recurring._money(v.expected_amount_krw)}
            ),
            id=v.id,
            effective_from=v.effective_from,
            effective_until=v.effective_until,
            reason=v.reason,
            created_at=v.created_at,
            revoked_at=v.revoked_at,
            monthly_equivalent_krw=None
            if monthly_equivalent(v) is None
            else str(monthly_equivalent(v)),
        )
        for v in all_versions
    ]
    return PlanResponse(
        id=row.id,
        household_id=row.household_id,
        version=row.version,
        ended_on=row.ended_on,
        end_reason=row.end_reason,
        versions=[v for v in history if v.revoked_at is None],
        history=history,
    )


def get_plan(session, principal, rule_id):
    cash.lock_cash_household(session, principal)
    result = _response(
        session, principal, scoped_entity(session, RecurringRule, rule_id, principal)
    )
    session.commit()
    return result


def list_plans(session, principal, *, q=None, cursor=None, limit=50, account_id=None, card_id=None):
    cash.lock_cash_household(session, principal)
    query = select(RecurringRule).where(RecurringRule.household_id == principal.household_id)
    if q is not None or account_id is not None or card_id is not None:
        matching = select(RecurringRuleVersion.rule_id).where(
            RecurringRuleVersion.household_id == principal.household_id,
            RecurringRuleVersion.revoked_at.is_(None),
        )
        if q is not None:
            matching = search_names(matching, q, RecurringRuleVersion.title)
        for field, value in (("account_id", account_id), ("card_id", card_id)):
            if value is not None:
                matching = matching.where(
                    getattr(RecurringRuleVersion, field) == value,
                    or_(
                        RecurringRuleVersion.effective_until.is_(None),
                        RecurringRuleVersion.effective_until > recurring.today(),
                    ),
                )
        query = query.where(RecurringRule.id.in_(matching))
    rows, next_cursor = keyset_page(
        session,
        query,
        model=RecurringRule,
        household_id=principal.household_id,
        keys=(RecurringRule.created_at,),
        cursor=cursor,
        limit=limit,
    )
    result = PlanListResponse(
        items=[_response(session, principal, row) for row in rows], next_cursor=next_cursor
    )
    session.commit()
    return result


def summary(session, principal, as_of=None):
    cash.lock_cash_household(session, principal)
    day = as_of or recurring.today()
    versions = list(
        session.scalars(
            select(RecurringRuleVersion).where(
                RecurringRuleVersion.household_id == principal.household_id,
                RecurringRuleVersion.revoked_at.is_(None),
                RecurringRuleVersion.effective_from <= day,
                or_(
                    RecurringRuleVersion.effective_until.is_(None),
                    RecurringRuleVersion.effective_until > day,
                ),
            )
        )
    )
    fixed = budget = excluded = included_unknown = excluded_unknown = unconverted = 0
    groups = {
        k: defaultdict(lambda: {"known": 0, "unknown": 0, "unconverted": 0, "count": 0})
        for k in ("categories", "treatments", "economic_types")
    }
    for v in versions:
        amount = monthly_equivalent(v)
        included = v.budget_treatment == "included"
        unknown = v.expected_amount_krw is None
        unsupported = v.expected_amount_krw is not None and amount is None
        unconverted += unsupported
        included_unknown += included and unknown
        excluded_unknown += not included and unknown
        if amount is not None:
            if not included:
                excluded += amount
            elif v.plan_kind == "budget":
                budget += amount
            else:
                fixed += amount
        for key, value in (
            ("categories", v.category),
            ("treatments", v.budget_treatment),
            ("economic_types", v.economic_type),
        ):
            if key != "treatments" and not included:
                continue
            group = groups[key][value]
            group["count"] += 1
            group["known"] += amount or 0
            group["unknown"] += unknown
            group["unconverted"] += unsupported
    result = PlanSummaryResponse(
        as_of=day,
        fixed_known_krw=str(fixed),
        budget_known_krw=str(budget),
        combined_known_krw=str(fixed + budget),
        excluded_known_krw=str(excluded),
        included_unknown_count=included_unknown,
        excluded_unknown_count=excluded_unknown,
        unconverted_count=unconverted,
        plan_count=len(versions),
        **{
            k: [
                PlanSubtotal(
                    key=name,
                    known_krw=str(v["known"]),
                    unknown_count=v["unknown"],
                    unconverted_count=v["unconverted"],
                    count=v["count"],
                )
                for name, v in sorted(data.items())
            ]
            for k, data in groups.items()
        },
    )
    session.commit()
    return result
