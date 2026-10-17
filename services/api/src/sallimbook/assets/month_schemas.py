from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from sallimbook.assets.schemas import (
    AmountBasis,
    AssetCategory,
    AssetInput,
    AssetKind,
    DateOnly,
    HouseholdShare,
    InclusionStatus,
    OwnershipKind,
)
from sallimbook.core.types import KrwString, SignedKrwString, YearMonth

type MonthState = Literal["draft", "reopened", "confirmed"]
type VerificationState = Literal["missing", "carried_unconfirmed", "verified"]
Reason = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=1000)
]


class MonthDraft(AssetInput):
    copy_previous: bool = True


class MonthReopen(AssetInput):
    revision_id: UUID
    reason: Reason


class MonthConfirm(AssetInput):
    revision_id: UUID
    acknowledge_non_month_end_dates: bool = False
    acknowledge_scope_change: bool = False


class MonthValueUpdate(AssetInput):
    revision_id: UUID
    value_id: UUID
    input_amount_krw: KrwString | None = None
    as_of_date: DateOnly | None = None
    unchanged: bool = False
    change_reason: Reason | None = None

    @model_validator(mode="after")
    def require_explicit_action(self) -> Self:
        if self.unchanged:
            if "input_amount_krw" in self.model_fields_set or self.as_of_date is None:
                raise ValueError("Unchanged requires a new as-of date and no replacement amount")
        elif "input_amount_krw" not in self.model_fields_set:
            raise ValueError("Supply an amount, explicit null, or unchanged")
        if self.input_amount_krw is not None and self.as_of_date is None:
            raise ValueError("An observed amount requires an as-of date")
        return self


class MonthScopeSync(AssetInput):
    revision_id: UUID


class MonthReference(BaseModel):
    month: YearMonth
    revision_id: UUID
    revision_no: int = Field(ge=1)
    version: int = Field(ge=1)


class MonthTotals(BaseModel):
    assets_krw: KrwString | None
    liabilities_krw: KrwString | None
    net_assets_krw: SignedKrwString | None
    verified_count: int
    item_count: int
    missing_count: int
    carried_count: int
    provisional: bool


class MonthValueResponse(BaseModel):
    id: UUID
    asset_id: UUID
    name: str
    kind: AssetKind
    category: AssetCategory
    ownership_kind: OwnershipKind
    owner_member_id: UUID | None
    household_share: HouseholdShare
    amount_basis: AmountBasis
    inclusion_status: InclusionStatus
    started_on: DateOnly
    ended_on: DateOnly | None
    source_asset_version: int
    input_amount_krw: KrwString | None
    owned_amount_krw: KrwString | None
    as_of_date: DateOnly | None
    verification_state: VerificationState
    origin: Literal["manual", "carried"]
    origin_revision_id: UUID | None
    change_reason: str | None
    version: int


class MonthResponse(MonthReference):
    state: MonthState
    previous_revision_id: UUID | None
    reopened_reason: str | None
    confirmed_at: datetime | None
    confirmed_by_member_id: UUID | None
    created_at: datetime
    totals: MonthTotals
    # Original drafts must synchronize changed live metadata before confirmation.
    # Reopened revisions deliberately preserve historical scope unless explicitly synchronized.
    scope_stale: bool
    values: list[MonthValueResponse]
    next_cursor: UUID | None


class MonthValueResult(BaseModel):
    value: MonthValueResponse
    revision_version: int
    totals: MonthTotals


class MonthHistoryItem(MonthReference):
    state: MonthState
    previous_revision_id: UUID | None
    reopened_reason: str | None
    confirmed_at: datetime | None
    created_at: datetime


class MonthHistoryResponse(BaseModel):
    items: list[MonthHistoryItem]
    next_cursor: int | None
