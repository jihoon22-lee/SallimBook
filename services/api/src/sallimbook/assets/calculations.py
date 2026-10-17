"""Exact asset calculations, independent of database and authorization.

Inputs are the asset source rows, not account/owner display rows. Identical
source IDs may be projected twice; conflicting projections are rejected.
Confirmation locks, corrections, and household authorization remain service
responsibilities. No helper changes an account or liability snapshot.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Literal

from sallimbook.core.types import krw_string, month_start

type Money = int | Decimal
type Verification = Literal["verified", "missing", "carried_unconfirmed"]


def _amount(value: Money) -> int:
    amount = int(krw_string(value))
    if amount < 0:
        raise ValueError("Asset valuations and liability balances must be nonnegative")
    return amount


def owned_valuation(
    amount_krw: Money, *, household_share: Decimal, basis: Literal["whole", "owned"]
) -> int:
    """Apply the household share once, rounding half a won upwards."""
    amount = _amount(amount_krw)
    if not isinstance(household_share, Decimal) or not household_share.is_finite():
        raise ValueError("Household share requires a finite Decimal")
    if not 0 <= household_share <= 1:
        raise ValueError("Household share must be between zero and one")
    if basis == "owned":
        return amount
    if basis != "whole":
        raise ValueError("Unknown valuation basis")
    # Do not inherit a caller's low Decimal precision before HALF_UP rounding.
    with localcontext() as context:
        context.prec = max(40, len(str(amount)) + len(household_share.as_tuple().digits) + 2)
        owned = (Decimal(amount) * household_share).to_integral_value(rounding=ROUND_HALF_UP)
    return int(krw_string(owned))


@dataclass(frozen=True)
class AssetValue:
    asset_id: str
    amount_krw: Money | None
    kind: Literal["asset", "liability"] = "asset"
    verification_state: Verification = "verified"
    included: bool = True
    household_share: Decimal = Decimal(1)

    def __post_init__(self):
        if not isinstance(self.asset_id, str) or not self.asset_id:
            raise ValueError("Asset source ID is required")
        if self.kind not in {"asset", "liability"}:
            raise ValueError("Unknown asset kind")
        if self.verification_state not in {"verified", "missing", "carried_unconfirmed"}:
            raise ValueError("Unknown verification state")
        if not isinstance(self.included, bool):
            raise ValueError("Included must be boolean")
        if (
            not isinstance(self.household_share, Decimal)
            or not self.household_share.is_finite()
            or not 0 <= self.household_share <= 1
        ):
            raise ValueError("Household share requires a finite Decimal between zero and one")
        if self.amount_krw is not None:
            _amount(self.amount_krw)
        if self.verification_state == "verified" and self.amount_krw is None:
            raise ValueError("A verified asset requires an amount, including explicit zero")
        if self.verification_state == "missing" and self.amount_krw is not None:
            raise ValueError("A missing asset has no amount")


def _sources(values: Iterable[AssetValue]) -> dict[str, AssetValue]:
    sources: dict[str, AssetValue] = {}
    for value in values:
        if not isinstance(value, AssetValue):
            raise ValueError("AssetValue source rows are required")
        previous = sources.get(value.asset_id)
        if previous is not None and previous != value:
            raise ValueError("Conflicting values for the same asset source")
        sources[value.asset_id] = value
    return {key: value for key, value in sources.items() if value.included}


@dataclass(frozen=True)
class AssetTotals:
    assets_krw: int | None
    liabilities_krw: int | None
    net_assets_krw: int | None
    verified_count: int
    item_count: int
    provisional: bool


def asset_totals(values: Iterable[AssetValue]) -> AssetTotals:
    """Return unknown totals for missing rows, provisional totals for carried rows."""
    sources = _sources(values)

    def total(kind: str) -> int | None:
        amounts = [value.amount_krw for value in sources.values() if value.kind == kind]
        if any(amount is None for amount in amounts):
            return None
        return int(krw_string(sum(_amount(amount) for amount in amounts)))

    assets, liabilities = total("asset"), total("liability")
    verified = sum(v.verification_state == "verified" for v in sources.values())
    net = None if assets is None or liabilities is None else int(krw_string(assets - liabilities))
    return AssetTotals(assets, liabilities, net, verified, len(sources), verified != len(sources))


@dataclass(frozen=True)
class AssetMonth:
    month: str
    values: tuple[AssetValue, ...]
    state: Literal["draft", "confirmed", "reopened"] = "draft"

    def __post_init__(self):
        month_start(self.month)
        if self.state not in {"draft", "confirmed", "reopened"}:
            raise ValueError("Unknown month state")
        # Freeze caller-owned collections before later comparison.
        object.__setattr__(self, "values", tuple(self.values))
        _sources(self.values)


@dataclass(frozen=True)
class MonthComparison:
    state: Literal["available", "no_previous_month", "unconfirmed"]
    total_delta_krw: int | None
    common_scope_delta_krw: int | None
    scope_changed: bool | None
    added_asset_ids: tuple[str, ...] = ()
    removed_asset_ids: tuple[str, ...] = ()
    changed_share_asset_ids: tuple[str, ...] = ()


def compare_months(previous: AssetMonth | None, current: AssetMonth) -> MonthComparison:
    """Compare confirmed source sets; never infer savings, return, or a fake zero rate."""
    if previous is None:
        return MonthComparison("no_previous_month", None, None, None)
    if month_start(previous.month) >= month_start(current.month):
        raise ValueError("The comparison month must precede the current month")
    prior, now = _sources(previous.values), _sources(current.values)
    if (
        previous.state != "confirmed"
        or current.state != "confirmed"
        or asset_totals(prior.values()).provisional
        or asset_totals(now.values()).provisional
    ):
        return MonthComparison("unconfirmed", None, None, None)
    shared = prior.keys() & now.keys()
    if any(prior[key].kind != now[key].kind for key in shared):
        raise ValueError("An asset source cannot change between asset and liability")

    def signed(value: AssetValue) -> int:
        return _amount(value.amount_krw) * (-1 if value.kind == "liability" else 1)

    delta = sum(map(signed, now.values())) - sum(map(signed, prior.values()))
    changed_share = {
        key for key in shared if prior[key].household_share != now[key].household_share
    }
    common = sum(signed(now[key]) - signed(prior[key]) for key in shared - changed_share)
    return MonthComparison(
        "available",
        int(krw_string(delta)),
        int(krw_string(common)),
        prior.keys() != now.keys() or bool(changed_share),
        tuple(sorted(now.keys() - prior.keys())),
        tuple(sorted(prior.keys() - now.keys())),
        tuple(sorted(changed_share)),
    )
