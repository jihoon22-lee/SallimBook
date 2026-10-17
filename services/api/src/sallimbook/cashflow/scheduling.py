"""Deterministic recurrence dates and payment arithmetic without persistence.

Dates are inclusive and use the original anchor, without business-day shifts.
Unique occurrences, rule-version overlap, and settlement transactions still
require database constraints and service tests.
"""

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from sallimbook.core.types import krw_string

type Money = int | Decimal


def _amount(value: Money) -> int:
    amount = int(krw_string(value))
    if amount < 0:
        raise ValueError("Payment amounts must be nonnegative")
    return amount


def occurrence_dates(
    anchor: date,
    start: date,
    end: date,
    *,
    frequency: Literal["monthly", "annual", "days"],
    interval_count: int = 1,
) -> tuple[date, ...]:
    """Generate monthly/yearly/custom-day dates with a positive interval.

    Monthly and annual intervals support every N months/years. A short month is
    clamped independently, so Jan 31 -> Feb 28 -> Mar 31 and Feb 29 returns in
    leap years. Dates before the rule anchor are excluded.
    """
    if any(type(value) is not date for value in (anchor, start, end)):
        raise ValueError("Date-only anchor and bounds are required")
    if type(interval_count) is not int or interval_count <= 0:
        raise ValueError("A positive integer interval is required")
    if end < start:
        raise ValueError("The end date must not precede the start date")
    if frequency not in {"monthly", "annual", "days"}:
        raise ValueError("Unknown recurrence frequency")
    if end < anchor:
        return ()
    if frequency == "days":
        first_index = max(0, -(-(start - anchor).days // interval_count))
        last_index = (end - anchor).days // interval_count
        return tuple(
            anchor + timedelta(days=i * interval_count) for i in range(first_index, last_index + 1)
        )
    step = interval_count * (12 if frequency == "annual" else 1)
    anchor_index = (anchor.year - 1) * 12 + anchor.month - 1
    start_index = (start.year - 1) * 12 + start.month - 1
    end_index = (end.year - 1) * 12 + end.month - 1
    first = max(0, -(-(start_index - anchor_index) // step))
    last = (end_index - anchor_index) // step
    dates = []
    for index in range(first, last + 1):
        year_offset, month_offset = divmod(anchor_index + index * step, 12)
        year, month = year_offset + 1, month_offset + 1
        day = min(anchor.day, calendar.monthrange(year, month)[1])
        occurrence = date(year, month, day)
        if start <= occurrence <= end:
            dates.append(occurrence)
    return tuple(dates)


@dataclass(frozen=True)
class PaymentBreakdown:
    cash_payment_krw: int
    consumption_krw: int
    principal_krw: int
    asset_transfer_krw: int


def payment_breakdown(
    amount_krw: Money,
    *,
    economic_type: Literal["expense", "loan", "asset_transfer"],
    principal_krw: Money = 0,
    interest_krw: Money | None = None,
) -> PaymentBreakdown:
    """Separate loan principal and pension transfers from consumption."""
    amount, principal = _amount(amount_krw), _amount(principal_krw)
    interest = None if interest_krw is None else _amount(interest_krw)
    if amount == 0:
        raise ValueError("An actual cash payment must be positive")
    if economic_type == "loan":
        if interest is None or principal + interest != amount:
            raise ValueError("Principal and interest must equal the actual payment")
        return PaymentBreakdown(amount, interest, principal, 0)
    if principal != 0 or interest is not None:
        raise ValueError("Only loan payments have a principal/interest split")
    if economic_type == "expense":
        return PaymentBreakdown(amount, amount, 0, 0)
    if economic_type == "asset_transfer":
        return PaymentBreakdown(amount, 0, 0, amount)
    raise ValueError("Unknown economic payment type")


@dataclass(frozen=True)
class SettlementTotals:
    expected_krw: int | None
    actual_krw: int
    difference_krw: int | None


def settlement_totals(
    expected_krw: Money | None, actual_payments_krw: Iterable[Money]
) -> SettlementTotals:
    """Sum actual installments independently of the scheduled estimate."""
    expected = None if expected_krw is None else _amount(expected_krw)
    payments = [_amount(value) for value in actual_payments_krw]
    if any(value == 0 for value in payments):
        raise ValueError("Actual payment records must be positive")
    actual = int(krw_string(sum(payments)))
    difference = None if expected is None else int(krw_string(actual - expected))
    return SettlementTotals(expected, actual, difference)
