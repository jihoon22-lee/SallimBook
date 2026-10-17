"""Income projections count each limited cash source once and never mutate snapshots."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from sallimbook.cashflow.models import PROJECTED_INCOME_KINDS
from sallimbook.core.types import krw_string


@dataclass(frozen=True)
class IncomeValue:
    source_id: str
    kind: str
    amount_krw: int | Decimal
    state: str = "active"

    def __post_init__(self):
        if not self.source_id or self.kind not in PROJECTED_INCOME_KINDS:
            raise ValueError("An income source and supported kind are required")
        if self.state not in {"active", "void"} or int(krw_string(self.amount_krw)) <= 0:
            raise ValueError("A cash fact requires positive exact KRW and a known state")


def income_totals(values: Iterable[IncomeValue]) -> dict[str, str | int]:
    sources = {}
    for value in values:
        if value.source_id in sources and sources[value.source_id] != value:
            raise ValueError("Conflicting projections of the same cash source")
        sources[value.source_id] = value
    sums = dict.fromkeys(PROJECTED_INCOME_KINDS, 0)
    count = 0
    for value in sources.values():
        if value.state == "active":
            sums[value.kind] += int(krw_string(value.amount_krw))
            count += 1
    earned = sums["salary"] + sums["bonus"] + sums["other_income"] - sums["income_return"]
    insurance = sums["insurance_receipt"] - sums["insurance_return"]
    return {
        "salary_krw": krw_string(sums["salary"]),
        "bonus_krw": krw_string(sums["bonus"]),
        "other_income_krw": krw_string(sums["other_income"]),
        "income_returns_krw": krw_string(sums["income_return"]),
        "insurance_receipts_krw": krw_string(sums["insurance_receipt"]),
        "insurance_returns_krw": krw_string(sums["insurance_return"]),
        "earned_net_krw": krw_string(earned),
        "insurance_net_krw": krw_string(insurance),
        "net_inflow_krw": krw_string(earned + insurance),
        "record_count": count,
    }
