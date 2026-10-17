"""Read-only, historical asset comparison and trend projections."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from sallimbook.assets.month_schemas import (
    MonthReference,
    MonthState,
    MonthTotals,
    MonthValueResponse,
)
from sallimbook.assets.schemas import AssetCategory, AssetKind, DateOnly, OwnershipKind
from sallimbook.core.types import SignedKrwString, YearMonth


class ComparisonFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    asset_id: UUID | None = None
    kind: AssetKind | None = None
    category: AssetCategory | None = None
    ownership_kind: OwnershipKind | None = None
    owner_member_id: UUID | None = None


class ObservationDates(BaseModel):
    non_month_end_asset_ids: list[UUID]
    missing_date_asset_ids: list[UUID]
    mixed_dates: bool


class ComparisonPeriod(BaseModel):
    month: YearMonth
    state: MonthState | Literal["missing"]
    revision: MonthReference | None
    confirmed_at: datetime | None
    totals: MonthTotals | None
    dates: ObservationDates


type ComparisonState = Literal["available", "no_previous_month", "current_missing", "unconfirmed"]
type PercentUnavailable = Literal[
    "no_previous_month",
    "current_missing",
    "unconfirmed",
    "zero_previous_total",
    "negative_previous_total",
]
type ScopeReason = Literal[
    "previously_held_added",
    "started_after_previous_period",
    "ended_before_current_period",
    "not_in_previous_scope",
    "not_in_current_scope",
    "inclusion_changed",
    "filter_membership_changed",
    "household_share_changed",
    "excluded_from_total",
]
ChangePercent = Annotated[
    str, StringConstraints(pattern=r"^-?(0|[1-9][0-9]*)\.[0-9]{2}$", max_length=27)
]


class ComparisonItem(BaseModel):
    asset_id: UUID
    before: MonthValueResponse | None
    after: MonthValueResponse | None
    before_in_scope: bool
    after_in_scope: bool
    membership: Literal["common", "added", "removed", "excluded", "unavailable"]
    share_changed: bool
    same_scope: bool
    scope_reason: ScopeReason | None
    # Value movement is distinct from the effect on household net assets.
    # Added/removed scope has no invented zero value on its absent side.
    amount_delta_krw: SignedKrwString | None
    net_assets_effect_krw: SignedKrwString | None


class AssetComparisonResponse(BaseModel):
    from_month: YearMonth | None
    to_month: YearMonth
    filters: ComparisonFilters
    state: ComparisonState
    previous: ComparisonPeriod | None
    current: ComparisonPeriod
    total_delta_krw: SignedKrwString | None
    common_scope_delta_krw: SignedKrwString | None
    change_percent: ChangePercent | None
    change_percent_unavailable_reason: PercentUnavailable | None
    scope_changed: bool | None
    added_asset_ids: list[UUID]
    removed_asset_ids: list[UUID]
    changed_share_asset_ids: list[UUID]
    item_count: int = Field(ge=0)
    items: list[ComparisonItem]
    next_cursor: UUID | None


type TrendValueState = Literal[
    "missing_month", "missing_item", "outside_filter", "missing_value", "unconfirmed", "verified"
]


class AssetTrendPoint(BaseModel):
    month: YearMonth
    state: MonthState | Literal["missing"]
    revision: MonthReference | None
    totals: MonthTotals | None
    value_state: TrendValueState
    # Household series uses net assets; an asset_id series uses that source's owned amount.
    observed_amount_krw: SignedKrwString | None
    confirmed_amount_krw: SignedKrwString | None
    included_in_total: bool | None
    as_of_date: DateOnly | None
    dates: ObservationDates


class AssetTrendResponse(BaseModel):
    from_month: YearMonth
    to_month: YearMonth
    filters: ComparisonFilters
    series_kind: Literal["household_net_assets", "asset_owned_amount"]
    points: list[AssetTrendPoint]
