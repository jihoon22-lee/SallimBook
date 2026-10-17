from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from sallimbook.assets.schemas import DateOnly
from sallimbook.cashflow.schemas import CashResponse, InputModel, Note, Reason
from sallimbook.core.types import KrwString, SignedKrwString

Title = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)
]
Category = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=40)
]
Currency = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z]{3}$")]
ForeignAmount = Annotated[
    str, StringConstraints(strict=True, max_length=40, pattern=r"^(0|[1-9][0-9]*)(\.[0-9]{1,8})?$")
]
type EconomicType = Literal["expense", "loan", "asset_transfer"]


class ScheduleTerms(InputModel):
    title: Title
    category: Category
    amount_mode: Literal["fixed", "variable"]
    expected_amount_krw: KrwString | None = Field(default=None, repr=False)
    economic_type: EconomicType
    loan_asset_id: UUID | None = None
    account_id: UUID | None = None
    card_id: UUID | None = None
    currency_reference: Currency | None = None
    foreign_amount_reference: ForeignAmount | None = Field(default=None, repr=False)
    note: Note | None = Field(default=None, repr=False)
    anchor_date: DateOnly
    frequency: Literal["monthly", "annual", "days"]
    interval_count: int = Field(default=1, strict=True, ge=1, le=3650)

    @model_validator(mode="after")
    def valid_terms(self) -> Self:
        if self.loan_asset_id is not None and self.economic_type != "loan":
            raise ValueError("Only a loan schedule may link a liability asset")
        if self.account_id and self.card_id:
            raise ValueError("Choose an account or a card, not both")
        if self.amount_mode == "fixed" and self.expected_amount_krw is None:
            raise ValueError("A fixed schedule needs an expected amount")
        if (self.currency_reference is None) != (self.foreign_amount_reference is None):
            raise ValueError("Foreign currency references must be a pair")
        return self


class RuleCreate(ScheduleTerms):
    effective_from: DateOnly


class RuleChange(RuleCreate):
    reason: Reason = Field(repr=False)


class RuleEnd(InputModel):
    effective_on: DateOnly
    reason: Reason = Field(repr=False)


class MutationReference(BaseModel):
    id: UUID
    version: int


class RuleVersionResponse(ScheduleTerms):
    id: UUID
    effective_from: DateOnly
    effective_until: DateOnly | None
    reason: str | None = Field(repr=False)
    created_at: datetime


class RuleResponse(BaseModel):
    id: UUID
    household_id: UUID
    version: int
    ended_on: DateOnly | None
    end_reason: str | None = Field(repr=False)
    versions: list[RuleVersionResponse]


class RuleListResponse(BaseModel):
    items: list[RuleResponse]
    next_cursor: UUID | None


class GenerateObligations(InputModel):
    start_date: DateOnly
    end_date: DateOnly
    rule_id: UUID | None = None

    @model_validator(mode="after")
    def bounded_window(self) -> Self:
        if not 0 <= (self.end_date - self.start_date).days <= 365:
            raise ValueError("Generate an inclusive window of at most 366 days")
        return self


class GenerationResponse(BaseModel):
    id: UUID
    version: Literal[1] = 1
    items: list[MutationReference]


class ObligationReschedule(InputModel):
    scheduled_date: DateOnly
    reason: Reason = Field(repr=False)


class ObligationAction(InputModel):
    reason: Reason = Field(repr=False)


class SettlementCreate(InputModel):
    amount_krw: KrwString = Field(repr=False)
    occurred_on: DateOnly
    account_id: UUID | None = None
    card_id: UUID | None = None
    principal_krw: KrwString = Field(default="0", repr=False)
    interest_krw: KrwString | None = Field(default=None, repr=False)
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def valid_payment(self) -> Self:
        if self.amount_krw == "0":
            raise ValueError("An actual payment must be positive")
        if self.account_id and self.card_id:
            raise ValueError("Choose only one actual payment method")
        return self


class SettlementResponse(BaseModel):
    id: UUID
    obligation_id: UUID
    economic_type: EconomicType
    principal_krw: KrwString
    consumption_krw: KrwString
    asset_transfer_krw: KrwString
    cash: CashResponse


class SettlementListResponse(BaseModel):
    items: list[SettlementResponse]
    next_cursor: UUID | None


class ObligationResponse(BaseModel):
    id: UUID
    household_id: UUID
    rule_id: UUID
    rule_version_id: UUID
    version: int
    title: str
    category: str
    amount_mode: Literal["fixed", "variable"]
    expected_amount_krw: KrwString | None
    economic_type: EconomicType
    loan_asset_id: UUID | None = None
    account_id: UUID | None
    card_id: UUID | None
    currency_reference: str | None
    foreign_amount_reference: str | None = Field(repr=False)
    note: str | None = Field(repr=False)
    nominal_date: DateOnly
    scheduled_date: DateOnly
    schedule_state: Literal["active", "superseded"]
    manual_override: bool
    skipped: bool
    manually_completed: bool
    status: Literal["unpaid", "partial", "paid", "skipped", "superseded"]
    actual_amount_krw: KrwString
    difference_krw: SignedKrwString | None
    consumption_krw: KrwString
    principal_krw: KrwString
    asset_transfer_krw: KrwString
    created_at: datetime
    updated_at: datetime


class ObligationListResponse(BaseModel):
    items: list[ObligationResponse]
    next_cursor: UUID | None


class ObligationHistoryItem(BaseModel):
    id: UUID
    version: int
    rule_version_id: UUID
    expected_amount_krw: KrwString | None
    nominal_date: DateOnly
    scheduled_date: DateOnly
    schedule_state: Literal["active", "superseded"]
    manual_override: bool
    skipped: bool
    manually_completed: bool
    action: str
    reason: str | None = Field(repr=False)
    updated_at: datetime


class ObligationHistoryResponse(BaseModel):
    items: list[ObligationHistoryItem]
    next_cursor: int | None


class FixedSummaryResponse(BaseModel):
    expected_known_krw: KrwString
    unknown_expected_count: int
    actual_amount_krw: KrwString
    consumption_krw: KrwString
    principal_krw: KrwString
    asset_transfer_krw: KrwString
    obligation_count: int
