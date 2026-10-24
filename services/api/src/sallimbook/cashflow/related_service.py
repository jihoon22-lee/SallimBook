"""Household-scoped reverse references, including ended and void source records."""

from sqlalchemy import select

from sallimbook.cashflow.recurring_models import RecurringRule
from sallimbook.cashflow.related_schemas import (
    IncomeAllocationLink,
    IncomeInsuranceSource,
    RuleInsuranceLink,
    RulePolicyLink,
)
from sallimbook.cashflow.service import _income_record, lock_cash_household
from sallimbook.core.authorization import scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.types import krw_string
from sallimbook.insurance.event_models import InsurancePayout, InsuranceReturn, PayoutAllocation
from sallimbook.insurance.models import InsuranceCase, InsurancePolicy, PolicyPremiumLink


def income_source(session, principal, record_id):
    lock_cash_household(session, principal)
    cash = _income_record(session, principal, record_id)
    payout_id = return_id = allocation_id = None
    allocations = []
    if cash.kind in ("insurance_receipt", "insurance_return"):
        model = InsurancePayout if cash.kind == "insurance_receipt" else InsuranceReturn
        source = session.scalar(
            select(model).where(
                model.household_id == principal.household_id,
                model.cash_record_id == cash.id,
            )
        )
        if source is None:
            raise DomainError("NOT_FOUND", "보험 원본 기록을 찾을 수 없습니다.", 404)
        payout_id = source.id if cash.kind == "insurance_receipt" else source.payout_id
        if cash.kind == "insurance_return":
            return_id, allocation_id = source.id, source.original_allocation_id
        rows = session.execute(
            select(PayoutAllocation, InsuranceCase.title)
            .join(
                InsuranceCase,
                (InsuranceCase.id == PayoutAllocation.case_id)
                & (InsuranceCase.household_id == PayoutAllocation.household_id),
            )
            .where(
                PayoutAllocation.household_id == principal.household_id,
                PayoutAllocation.payout_id == payout_id,
            )
            .order_by(PayoutAllocation.id)
        )
        allocations = [
            IncomeAllocationLink(
                id=row.id,
                case_id=row.case_id,
                case_title=title,
                amount_krw=krw_string(row.amount_krw),
            )
            for row, title in rows
        ]
    result = IncomeInsuranceSource(
        record_id=cash.id,
        payout_id=payout_id,
        return_id=return_id,
        original_allocation_id=allocation_id,
        allocations=allocations,
    )
    session.commit()
    return result


def rule_insurance(session, principal, rule_id):
    lock_cash_household(session, principal)
    scoped_entity(session, RecurringRule, rule_id, principal)
    row = session.execute(
        select(PolicyPremiumLink, InsurancePolicy)
        .join(
            InsurancePolicy,
            (InsurancePolicy.id == PolicyPremiumLink.policy_id)
            & (InsurancePolicy.household_id == PolicyPremiumLink.household_id),
        )
        .where(
            PolicyPremiumLink.household_id == principal.household_id,
            PolicyPremiumLink.rule_id == rule_id,
        )
    ).one_or_none()
    link = None
    if row:
        reference, policy = row
        link = RulePolicyLink(
            id=reference.id,
            policy_id=policy.id,
            product_name=policy.product_name,
            insurer=policy.insurer,
            policy_status=policy.status,
            active=reference.active,
            ended_at=reference.ended_at,
        )
    result = RuleInsuranceLink(rule_id=rule_id, link=link)
    session.commit()
    return result
