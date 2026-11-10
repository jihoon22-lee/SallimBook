"""Premiums paid against benefits received, per policy; estimates from what is registered.

Premiums are not a ledger here. The household may enter what it had already paid up to a date;
later months are estimated from the linked monthly-plan items in effect in each month. Benefits
are the actual payouts allocated to a policy minus their returns.
"""

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sallimbook.cashflow import recurring_service
from sallimbook.cashflow.expense_plan_service import monthly_equivalent
from sallimbook.cashflow.models import CashRecord
from sallimbook.cashflow.recurring_models import RecurringRuleVersion
from sallimbook.core.authorization import Principal
from sallimbook.core.errors import DomainError
from sallimbook.core.types import SEOUL, krw_string, month_end, month_start
from sallimbook.insurance.event_models import InsurancePayout, InsuranceReturn, PayoutAllocation
from sallimbook.insurance.models import InsurancePolicy, PolicyPremiumLink
from sallimbook.insurance.schemas import InsuranceSummaryResponse, PolicyMoney
from sallimbook.overview.service import percent


def _index(day) -> int:
    return day.year * 12 + day.month - 1


def _label(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _received(session: Session, principal: Principal) -> dict:
    """Net benefits per policy id (None: not tied to a policy) from active cash records."""
    totals: dict = defaultdict(int)
    for policy_id, amount in session.execute(
        select(PayoutAllocation.policy_id, func.sum(PayoutAllocation.amount_krw))
        .join(
            InsurancePayout,
            (InsurancePayout.household_id == PayoutAllocation.household_id)
            & (InsurancePayout.id == PayoutAllocation.payout_id),
        )
        .join(
            CashRecord,
            (CashRecord.household_id == InsurancePayout.household_id)
            & (CashRecord.id == InsurancePayout.cash_record_id),
        )
        .where(
            PayoutAllocation.household_id == principal.household_id,
            CashRecord.state == "active",
        )
        .group_by(PayoutAllocation.policy_id)
    ):
        totals[policy_id] += int(amount)
    for policy_id, amount in session.execute(
        select(PayoutAllocation.policy_id, func.sum(CashRecord.amount_krw))
        .select_from(InsuranceReturn)
        .join(
            CashRecord,
            (CashRecord.household_id == InsuranceReturn.household_id)
            & (CashRecord.id == InsuranceReturn.cash_record_id),
        )
        .join(
            PayoutAllocation,
            (PayoutAllocation.household_id == InsuranceReturn.household_id)
            & (PayoutAllocation.id == InsuranceReturn.original_allocation_id),
        )
        .where(
            InsuranceReturn.household_id == principal.household_id,
            CashRecord.state == "active",
        )
        .group_by(PayoutAllocation.policy_id)
    ):
        totals[policy_id] -= int(amount)
    return totals


def _in_effect(versions, day):
    for version in versions:
        if version.effective_from <= day and (
            version.effective_until is None or version.effective_until > day
        ):
            return version
    return None


def _in_month(versions, index: int):
    """The version covering any day of the month; a change mid-month counts the newer one once."""
    first = month_start(_label(index))
    last = month_end(_label(index))
    found = None
    for version in versions:  # oldest first
        if version.effective_from <= last and (
            version.effective_until is None or version.effective_until > first
        ):
            found = version
    return found


def _estimate(policy, links, versions_of, today):
    """(estimated total, first counted month index, counted months, months without an amount)."""
    current = _index(today)
    floor = None if policy.premium_paid_through is None else _index(policy.premium_paid_through)
    total = counted = unknown = 0
    first = None
    for link in links:
        versions = versions_of.get(link.rule_id, [])
        if not versions:
            continue
        start = min(_index(version.effective_from) for version in versions)
        if policy.payment_start is not None:
            start = max(start, _index(policy.payment_start))
        if floor is not None:
            start = max(start, floor + 1)
        end = current
        if policy.payment_end is not None:
            end = min(end, _index(policy.payment_end))
        if link.ended_at is not None:
            end = min(end, _index(link.ended_at.astimezone(SEOUL).date()))
        if policy.status != "active":
            # An ended or lapsed policy stops accruing; its last change is the latest it ended.
            end = min(end, _index(policy.updated_at.astimezone(SEOUL).date()))
        for index in range(start, end + 1):
            version = _in_month(versions, index)
            if version is None:
                continue
            amount = monthly_equivalent(version)
            if amount is None:
                unknown += 1
                continue
            total += amount
            counted += 1
            first = index if first is None else min(first, index)
    return total, first, counted, unknown


def insurance_summary(session: Session, principal: Principal) -> InsuranceSummaryResponse:
    today = recurring_service.today()
    policies = list(
        session.scalars(
            select(InsurancePolicy)
            .where(InsurancePolicy.household_id == principal.household_id)
            .order_by(InsurancePolicy.insurer, InsurancePolicy.product_name, InsurancePolicy.id)
        )
    )
    links_of: dict = defaultdict(list)
    for link in session.scalars(
        select(PolicyPremiumLink)
        .where(PolicyPremiumLink.household_id == principal.household_id)
        .order_by(PolicyPremiumLink.id)
    ):
        links_of[link.policy_id].append(link)
    rule_ids = {link.rule_id for links in links_of.values() for link in links}
    versions_of: dict = defaultdict(list)
    if rule_ids:
        for version in session.scalars(
            select(RecurringRuleVersion)
            .where(
                RecurringRuleVersion.household_id == principal.household_id,
                RecurringRuleVersion.rule_id.in_(rule_ids),
                RecurringRuleVersion.revoked_at.is_(None),
            )
            .order_by(RecurringRuleVersion.effective_from, RecurringRuleVersion.id)
        ):
            versions_of[version.rule_id].append(version)
    received = _received(session, principal)
    rows: list[PolicyMoney] = []
    try:
        for policy in policies:
            links = links_of.get(policy.id, [])
            estimated, first, counted, unknown = _estimate(policy, links, versions_of, today)
            entered = policy.premium_paid_before_krw
            before = None if entered is None else int(entered)
            known = before is not None or counted > 0
            paid = (before or 0) + estimated
            monthly = 0
            for link in links:
                if not link.active:
                    continue
                version = _in_effect(versions_of.get(link.rule_id, []), today)
                amount = None if version is None else monthly_equivalent(version)
                monthly += amount or 0
            got = received.get(policy.id, 0)
            rows.append(
                PolicyMoney(
                    policy_id=policy.id,
                    insurer=policy.insurer,
                    product_name=policy.product_name,
                    status=policy.status,
                    monthly_premium_krw=krw_string(monthly if policy.status == "active" else 0),
                    paid_before_krw=None if before is None else krw_string(before),
                    paid_through=policy.premium_paid_through,
                    paid_estimated_krw=krw_string(estimated),
                    estimated_from_month=None if first is None else _label(first),
                    estimated_months=counted,
                    unknown_months=unknown,
                    paid_total_krw=krw_string(paid) if known else None,
                    received_krw=krw_string(got),
                    recovery_percent=percent(got, paid) if known else None,
                )
            )
        known_rows = [row for row in rows if row.paid_total_krw is not None]
        paid_total = sum(int(row.paid_total_krw) for row in known_rows)
        # The ratio compares like with like: benefits of the policies whose premiums are known.
        matched = sum(int(row.received_krw) for row in known_rows)
        unassigned = received.get(None, 0)
        got_total = sum(int(row.received_krw) for row in rows) + unassigned
        return InsuranceSummaryResponse(
            as_of=today,
            policy_count=len(rows),
            paid_unknown_count=sum(row.paid_total_krw is None for row in rows),
            monthly_premium_krw=krw_string(sum(int(row.monthly_premium_krw) for row in rows)),
            paid_total_krw=krw_string(paid_total),
            received_krw=krw_string(got_total),
            matched_received_krw=krw_string(matched),
            unassigned_received_krw=krw_string(unassigned),
            recovery_percent=percent(matched, paid_total),
            policies=rows,
        )
    except ValueError:
        raise DomainError(
            "TOTAL_OUT_OF_RANGE", "합산 가능한 금액 범위를 확인해 주세요.", 422
        ) from None
