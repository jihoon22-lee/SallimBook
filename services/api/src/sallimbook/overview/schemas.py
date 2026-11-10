"""Read-only household status: what is registered, with the latest amount each item has."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from sallimbook.accounts.schemas import AccountType
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


class InvestmentHolding(BaseModel):
    """An investment or pension account whose put-in money was entered by hand."""

    asset_id: UUID
    account_id: UUID
    name: str
    account_type: AccountType
    value_krw: KrwString
    basis_month: YearMonth
    contributed_krw: KrwString
    contributed_as_of: date | None
    gain_krw: SignedKrwString
    return_percent: str | None


class InvestmentsOverview(BaseModel):
    """Latest saved value against the money put in; a plain difference, not a rate over time."""

    count: int
    value_krw: KrwString
    contributed_krw: KrwString
    gain_krw: SignedKrwString
    return_percent: str | None
    missing_contribution_count: int
    items: list[InvestmentHolding]


class NetAssetsPoint(BaseModel):
    """One month of the household total from the latest amount saved up to that month."""

    month: YearMonth
    assets_krw: KrwString | None
    liabilities_krw: KrwString | None
    net_assets_krw: SignedKrwString | None
    item_count: int
    known_count: int
    entered_count: int
    confirmed: bool


class PlanPoint(BaseModel):
    """One month's plan-based estimate; never a balance or an amount saved."""

    month: YearMonth
    as_of: date
    income_known_krw: KrwString
    income_count: int
    income_unknown_count: int
    spending_known_krw: KrwString
    loan_known_krw: KrwString
    transfer_known_krw: KrwString
    planned_unknown_count: int
    margin_before_transfers_krw: SignedKrwString | None
    margin_after_transfers_krw: SignedKrwString | None
    actual_income_krw: SignedKrwString


class HouseholdTrendsResponse(BaseModel):
    to_month: YearMonth
    months: int
    net_assets: list[NetAssetsPoint]
    plan: list[PlanPoint]


class HouseholdOverviewResponse(BaseModel):
    month: YearMonth
    holdings: HoldingsOverview
    investments: InvestmentsOverview
    cards: RegisteredItems
    appliances: RegisteredItems
    insurance: InsuranceOverview
    plan: MonthlyPlanOverview
