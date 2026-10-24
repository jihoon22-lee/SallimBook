"""Read-only bounded replacement projections and pooled physical stock quantities."""

from datetime import date

from sallimbook.homecare.calculations import next_check_on

MAX_AGGREGATE_QUANTITY = 9_007_199_254_740_991


def projected_replacements(next_on, as_of, through, interval_unit, interval_count):
    if (
        any(type(value) is not date for value in (as_of, through))
        or not 0 <= (through - as_of).days <= 365
    ):
        raise ValueError("Choose today through at most 365 days ahead")
    if interval_unit not in {"manual", "days", "months"}:
        raise ValueError("Unknown interval")
    if interval_unit == "manual":
        if interval_count is not None:
            raise ValueError("Manual intervals have no recurring count")
    elif type(interval_count) is not int or not 1 <= interval_count <= (
        3650 if interval_unit == "days" else 120
    ):
        raise ValueError("Invalid replacement interval")
    if next_on is None:
        return None
    if type(next_on) is not date:
        raise ValueError("A next check must be a date")
    # An overdue schedule means one outstanding check, never inferred past consumption.
    current = max(next_on, as_of)
    count = 0
    while current <= through:
        count += 1
        if interval_unit == "manual":
            break
        try:
            current = next_check_on(
                current, interval_unit=interval_unit, interval_count=interval_count
            )
        except ValueError, OverflowError:
            break  # The next cycle is beyond the supported calendar.
    return count


def purchase_quantities(demands, stock, planned, ordered):
    demands = tuple(demands)
    amounts = [*demands, stock, planned, ordered]
    if any(type(value) is not int or not 0 <= value <= MAX_AGGREGATE_QUANTITY for value in amounts):
        raise ValueError("Invalid aggregate quantity")
    demand = sum(demands)
    if demand > MAX_AGGREGATE_QUANTITY:
        raise ValueError("Too many projected replacements")
    shortage = max(0, demand - stock)
    return {
        "demand_quantity": demand,
        "shortage_quantity": shortage,
        "additional_quantity": max(0, shortage - planned - ordered),
    }
