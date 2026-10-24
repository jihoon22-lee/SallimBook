"""Actual cash-year summaries; no claim join, balance changes, or tax estimates."""

from datetime import date

from sqlalchemy import and_, exists, func, or_, select

from sallimbook.core.database import Base

METRICS = ("medical_paid", "medical_refunded", "insurance_received", "insurance_returned")


def totals(values):
    result = {key: int(values.get(key, 0)) for key in METRICS}
    result["net_medical"] = result["medical_paid"] - result["medical_refunded"]
    result["net_insurance"] = result["insurance_received"] - result["insurance_returned"]
    result["net_burden"] = result["net_medical"] - result["net_insurance"]
    return result


def annual_summary(session, household_id, year, budget):
    """Called inside the export's read-only repeatable-read transaction."""
    tables = Base.metadata.tables
    cash = tables["cash_records"].alias("cash")
    case = tables["insurance_cases"]
    expense = tables["medical_expenses"]
    refund = tables["medical_refunds"]
    payout = tables["insurance_payouts"]
    allocation = tables["payout_allocations"]
    returned = tables["insurance_returns"]
    obligation = tables["scheduled_obligations"]
    settlement = tables["fixed_settlements"]
    premium = tables["policy_premium_links"]
    start, end = date(year, 1, 1), date(year, 12, 31)
    # Month-precision records belong to their actual recorded month, never an invented day.
    actual_date = func.coalesce(cash.c.occurred_on, cash.c.period_month)
    condition = (
        cash.c.household_id == household_id,
        cash.c.state == "active",
        actual_date >= start,
        actual_date <= end,
    )

    def same(left, right, left_key, right_key="id"):
        return and_(
            left.c.household_id == right.c.household_id, left.c[left_key] == right.c[right_key]
        )

    people = {}
    cash_count = 0
    month_only_count = 0

    def consume(query, metric):
        nonlocal cash_count, month_only_count
        for person, amount, precision in session.execute(
            query.where(*condition).execution_options(yield_per=500)
        ):
            budget.add("rows", 1)
            cash_count += 1
            month_only_count += int(precision == "month")
            row = people.setdefault(person, dict.fromkeys(METRICS, 0))
            row[metric] += int(amount)

    consume(
        select(case.c.patient_member_id, cash.c.amount_krw, cash.c.date_precision).select_from(
            cash.join(expense, same(cash, expense, "id", "cash_record_id")).join(
                case, same(expense, case, "case_id")
            )
        ),
        "medical_paid",
    )
    consume(
        select(case.c.patient_member_id, cash.c.amount_krw, cash.c.date_precision).select_from(
            cash.join(refund, same(cash, refund, "id", "cash_record_id"))
            .join(expense, same(refund, expense, "expense_id"))
            .join(case, same(expense, case, "case_id"))
        ),
        "medical_refunded",
    )
    consume(
        select(
            case.c.patient_member_id, allocation.c.amount_krw, cash.c.date_precision
        ).select_from(
            cash.join(payout, same(cash, payout, "id", "cash_record_id"))
            .join(allocation, same(payout, allocation, "id", "payout_id"))
            .join(case, same(allocation, case, "case_id"))
        ),
        "insurance_received",
    )
    allocated = (
        select(func.coalesce(func.sum(allocation.c.amount_krw), 0))
        .where(allocation.c.household_id == household_id, allocation.c.payout_id == payout.c.id)
        .correlate(payout)
        .scalar_subquery()
    )
    # Receipts entered without allocations remain visible and unassigned.
    query = (
        select(cash.c.amount_krw - allocated, cash.c.date_precision)
        .select_from(cash.outerjoin(payout, same(cash, payout, "id", "cash_record_id")))
        .where(*condition, cash.c.kind == "insurance_receipt", cash.c.amount_krw > allocated)
    )
    for amount, precision in session.execute(query.execution_options(yield_per=500)):
        budget.add("rows", 1)
        cash_count += 1
        month_only_count += int(precision == "month")
        people.setdefault(None, dict.fromkeys(METRICS, 0))["insurance_received"] += int(amount)
    consume(
        select(case.c.patient_member_id, cash.c.amount_krw, cash.c.date_precision)
        .select_from(
            cash.outerjoin(returned, same(cash, returned, "id", "cash_record_id"))
            .outerjoin(allocation, same(returned, allocation, "original_allocation_id"))
            .outerjoin(case, same(allocation, case, "case_id"))
        )
        .where(cash.c.kind == "insurance_return"),
        "insurance_returned",
    )
    fixed = dict.fromkeys(
        ("premium", "pension", "other_consumption", "other_transfer", "principal"), 0
    )
    linked = exists(
        select(premium.c.id).where(
            premium.c.household_id == household_id,
            premium.c.rule_id == obligation.c.rule_id,
        )
    )
    query = (
        select(
            settlement.c.consumption_krw,
            settlement.c.asset_transfer_krw,
            settlement.c.principal_krw,
            settlement.c.economic_type,
            obligation.c.category,
            or_(obligation.c.category == "보험료", linked).label("is_premium"),
            cash.c.date_precision,
        )
        .select_from(
            cash.join(settlement, same(cash, settlement, "id", "cash_record_id")).join(
                obligation, same(settlement, obligation, "obligation_id")
            )
        )
        .where(*condition)
    )
    for (
        consumption,
        transfer,
        principal,
        economic,
        category,
        is_premium,
        precision,
    ) in session.execute(query.execution_options(yield_per=500)):
        budget.add("rows", 1)
        cash_count += 1
        month_only_count += int(precision == "month")
        fixed["premium" if economic == "expense" and is_premium else "other_consumption"] += int(
            consumption
        )
        fixed[
            "pension" if economic == "asset_transfer" and category == "연금" else "other_transfer"
        ] += int(transfer)
        fixed["principal"] += int(principal)
    return {
        "year": year,
        "people": {person: totals(values) for person, values in people.items()},
        "total": totals({key: sum(row[key] for row in people.values()) for key in METRICS}),
        "fixed": fixed,
        "fact_count": cash_count,
        "month_only_count": month_only_count,
    }
