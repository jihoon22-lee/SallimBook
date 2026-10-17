"""Pure stock arithmetic and date policy, without transaction guarantees.

The database service must lock stock, persist movement/replacement atomically,
and enforce idempotency. These helpers alone cannot prevent concurrent spends.
"""

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

MAX_QUANTITY = 1_000_000


def _quantity(value: int, *, positive: bool = False) -> int:
    if type(value) is not int or not (1 if positive else 0) <= value <= MAX_QUANTITY:
        raise ValueError(
            "Quantity must be a positive integer"
            if positive
            else "Quantity must be a nonnegative integer"
        )
    return value


@dataclass(frozen=True)
class StockMovement:
    id: str
    kind: Literal["receipt", "replacement", "return_in", "return_out", "adjustment", "reversal"]
    quantity_delta: int
    reversal_of: str | None = None
    reason: str | None = None

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("Stock source ID is required")
        if (
            type(self.quantity_delta) is not int
            or self.quantity_delta == 0
            or abs(self.quantity_delta) > MAX_QUANTITY
        ):
            raise ValueError("A stock movement requires a nonzero integer delta")
        if self.kind in {"receipt", "return_in"}:
            if self.quantity_delta < 0:
                raise ValueError("An incoming movement must be positive")
        elif self.kind in {"replacement", "return_out"}:
            if self.quantity_delta > 0:
                raise ValueError("An outgoing movement must be negative")
        elif self.kind == "adjustment":
            if not isinstance(self.reason, str) or not self.reason.strip():
                raise ValueError("An adjustment requires a reason")
        elif self.kind == "reversal":
            if not isinstance(self.reversal_of, str) or not self.reversal_of:
                raise ValueError("A reversal must identify the original movement")
        else:
            raise ValueError("Unknown stock movement kind")
        if self.kind != "reversal" and self.reversal_of is not None:
            raise ValueError("Only a reversal can reference an original movement")


def stock_balance(movements: Iterable[StockMovement], *, opening_quantity: int = 0) -> int:
    """Sum unique movement sources and validate complete reversal references.

    Input order has no meaning for this balance calculation. Per-operation stock
    availability must be checked by the caller under a database row lock.
    """
    opening = _quantity(opening_quantity)
    sources: dict[str, StockMovement] = {}
    for movement in movements:
        if not isinstance(movement, StockMovement):
            raise ValueError("StockMovement source rows are required")
        previous = sources.get(movement.id)
        if previous is not None and previous != movement:
            raise ValueError("Conflicting data for a repeated movement source")
        sources[movement.id] = movement
    reversed_ids = set()
    for movement in sources.values():
        if movement.kind != "reversal":
            continue
        original = sources.get(movement.reversal_of)
        if original is None or original.kind == "reversal":
            raise ValueError("A reversal requires an original non-reversal movement")
        if original.id in reversed_ids or movement.quantity_delta != -original.quantity_delta:
            raise ValueError("A movement can be reversed once, for its full quantity")
        reversed_ids.add(original.id)
    return _quantity(opening + sum(m.quantity_delta for m in sources.values()))


def quantity_after_replacement(stock: int, quantity: int) -> int:
    """Check one replacement against the supplied stock; callers must lock it."""
    stock, quantity = _quantity(stock), _quantity(quantity, positive=True)
    if quantity > stock:
        raise ValueError("Insufficient stock")
    return stock - quantity


def next_check_on(
    last_replaced_on: date | None,
    *,
    interval_unit: Literal["days", "months"],
    interval_count: int,
    override: date | None = None,
) -> date | None:
    """A receipt never supplies this date; only replacement history or override does."""
    _quantity(interval_count, positive=True)
    if interval_unit not in {"days", "months"}:
        raise ValueError("Unknown replacement interval")
    for value in (last_replaced_on, override):
        if value is not None and type(value) is not date:
            raise ValueError("Replacement dates must be date-only")
    if override is not None:
        return override
    if last_replaced_on is None:
        return None
    if interval_unit == "days":
        return last_replaced_on + timedelta(days=interval_count)
    year_offset, month_offset = divmod(
        (last_replaced_on.year - 1) * 12 + last_replaced_on.month - 1 + interval_count, 12
    )
    year, month = year_offset + 1, month_offset + 1
    day = min(last_replaced_on.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


@dataclass(frozen=True)
class ConsumableStatus:
    as_of: date
    replacement_due: bool | None
    purchase_needed: bool


def consumable_status(
    *, today: date, stock: int, next_check: date | None, required_quantity: int = 1
) -> ConsumableStatus:
    """Use an explicit Seoul today, independent of the selected asset month."""
    _quantity(stock)
    if type(today) is not date or (next_check is not None and type(next_check) is not date):
        raise ValueError("Status dates must be date-only")
    _quantity(required_quantity, positive=True)
    return ConsumableStatus(
        today, None if next_check is None else next_check <= today, stock < required_quantity
    )
