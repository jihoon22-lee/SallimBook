"""Read-only household status: what is registered, with the latest amount each item has."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from sallimbook.assets.schemas import AssetCategory, AssetKind
from sallimbook.core.types import KrwString, SignedKrwString, YearMonth

type HoldingGroup = Literal["accounts", "financial", "real_estate", "deposit", "loan", "other"]


class OverviewHolding(BaseModel):
    """One asset held at the selected month's end and its latest saved household amount."""

    asset_id: UUID
    account_id: UUID | None
    name: str
    kind: AssetKind
    category: AssetCategory
    group: HoldingGroup
    included: bool
    owned_amount_krw: KrwString | None
    basis_month: YearMonth | None
    as_of_date: date | None
    stale: bool


class HoldingGroupTotal(BaseModel):
    group: HoldingGroup
    count: int
    known_count: int
    assets_krw: KrwString
    liabilities_krw: KrwString


class HoldingsOverview(BaseModel):
    """Totals use each included item's latest saved amount; unsaved items are counted apart."""

    assets_krw: KrwString
    liabilities_krw: KrwString
    net_assets_krw: SignedKrwString
    item_count: int
    known_count: int
    missing_count: int
    stale_count: int
    current_count: int
    oldest_basis_month: YearMonth | None
    groups: list[HoldingGroupTotal]
    items: list[OverviewHolding]


class NamedItem(BaseModel):
    id: UUID
    name: str


class RegisteredItems(BaseModel):
    count: int
    items: list[NamedItem]


class InsuranceOverview(BaseModel):
    active_policy_count: int
    open_case_count: int
    claims_in_progress_count: int
    documents_required_count: int
    policies: list[NamedItem]


class MonthlyPlanOverview(BaseModel):
    """A plan-based estimate from the expected income and the monthly plan, never a balance."""

    as_of: date
    expected_income_known_krw: KrwString
    expected_income_count: int
    expected_income_unknown_count: int
    spending_known_krw: KrwString
    loan_known_krw: KrwString
    transfer_known_krw: KrwString
    planned_unknown_count: int
    unconverted_count: int
    excluded_known_krw: KrwString
    margin_before_transfers_krw: SignedKrwString
    margin_after_transfers_krw: SignedKrwString


class HouseholdOverviewResponse(BaseModel):
    month: YearMonth
    holdings: HoldingsOverview
    cards: RegisteredItems
    appliances: RegisteredItems
    insurance: InsuranceOverview
    plan: MonthlyPlanOverview
