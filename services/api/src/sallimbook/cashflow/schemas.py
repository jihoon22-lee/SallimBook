from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.json_schema import SkipJsonSchema

from sallimbook.assets.schemas import DateOnly
from sallimbook.core.types import KrwString, SignedKrwString, YearMonth

type IncomeKind = Literal["salary", "bonus", "other_income"]
type ProjectedIncomeKind = Literal[
    "salary", "bonus", "other_income", "income_return", "insurance_receipt", "insurance_return"
]
type CashKind = Literal[
    "salary",
    "bonus",
    "other_income",
    "income_return",
    "insurance_receipt",
    "insurance_return",
    "medical_payment",
    "medical_refund",
    "fixed_payment",
]
type Precision = Literal["day", "month"]
Reason = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500)
]
Note = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=2000)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CashInput(InputModel):
    """Internal domain service input. No generic cash-record creation route exists."""

    amount_krw: KrwString = Field(repr=False)
    period_month: YearMonth
    date_precision: Precision
    occurred_on: DateOnly | None = None
    member_id: UUID | None = None
    account_id: UUID | None = None
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def validate_fact(self) -> Self:
        if self.amount_krw == "0":
            raise ValueError("A cash event must be positive")
        if (self.date_precision == "day") != (self.occurred_on is not None):
            raise ValueError("Only day precision supplies an actual date")
        return self


class IncomeInput(CashInput):
    kind: IncomeKind
    member_id: UUID


class IncomeCreate(IncomeInput):
    duplicate_acknowledged: bool = Field(default=False, strict=True)


class IncomePatch(InputModel):
    reason: Reason = Field(repr=False)
    kind: IncomeKind | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    amount_krw: KrwString | SkipJsonSchema[None] = Field(default_factory=lambda: None, repr=False)
    period_month: YearMonth | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    date_precision: Precision | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    occurred_on: DateOnly | None = None
    member_id: UUID | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    account_id: UUID | None = None
    note: Note | None = Field(default=None, repr=False)
    duplicate_acknowledged: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        supplied = self.model_fields_set - {"reason", "duplicate_acknowledged"}
        if not supplied or any(
            getattr(self, field) is None
            for field in supplied - {"occurred_on", "account_id", "note"}
        ):
            raise ValueError("Supply at least one valid correction")
        return self


class IncomeVoid(InputModel):
    reason: Reason = Field(repr=False)


class IncomeReturn(CashInput):
    reason: Reason = Field(repr=False)
    # The member is inherited from the original income; callers cannot choose another one.
    member_id: None = None


class ConversionSource(InputModel):
    id: UUID
    version: int = Field(strict=True, ge=1, le=2**63 - 1)


class IncomeConvert(InputModel):
    sources: list[ConversionSource] = Field(min_length=1, max_length=100)
    replacements: list[IncomeInput] = Field(min_length=1, max_length=100)
    reason: Reason = Field(repr=False)

    @model_validator(mode="after")
    def distinct_sources(self) -> Self:
        if len({source.id for source in self.sources}) != len(self.sources):
            raise ValueError("Each source may appear only once")
        return self


class CashResponse(BaseModel):
    id: UUID
    household_id: UUID
    kind: CashKind
    flow: Literal["in", "out"]
    amount_krw: KrwString = Field(repr=False)
    period_month: YearMonth
    occurred_on: DateOnly | None
    date_precision: Precision
    member_id: UUID | None
    account_id: UUID | None
    reverses_id: UUID | None
    state: Literal["active", "void"]
    note: str | None = Field(repr=False)
    created_by_member_id: UUID
    updated_by_member_id: UUID
    created_at: datetime
    updated_at: datetime
    version: int
    action: Literal["create", "correct", "void", "convert_source", "convert_result"]
    reason: str | None = Field(repr=False)
    conversion_id: UUID | None
    editable: bool
    voidable: bool


class IncomeListResponse(BaseModel):
    items: list[CashResponse]
    next_cursor: UUID | None


class IncomeHistoryResponse(BaseModel):
    items: list[CashResponse]
    next_cursor: int | None


class DuplicateResponse(BaseModel):
    suspected: bool
    items: list[CashResponse]
    truncated: bool


class ConversionResponse(BaseModel):
    id: UUID
    version: Literal[1]
    reason: str = Field(repr=False)
    created_at: datetime
    sources: list[CashResponse]
    replacements: list[CashResponse]


class IncomeTotalsResponse(BaseModel):
    salary_krw: KrwString
    bonus_krw: KrwString
    other_income_krw: KrwString
    income_returns_krw: KrwString
    insurance_receipts_krw: KrwString
    insurance_returns_krw: KrwString
    earned_net_krw: SignedKrwString
    insurance_net_krw: SignedKrwString
    net_inflow_krw: SignedKrwString
    record_count: int


class MemberIncomeSummary(BaseModel):
    member_id: UUID | None
    totals: IncomeTotalsResponse


class IncomeSummaryResponse(BaseModel):
    period_month: YearMonth
    totals: IncomeTotalsResponse
    members: list[MemberIncomeSummary]
