"""Expected monthly baselines and performance-year compensation, separate from cash."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from sallimbook.cashflow.schemas import InputModel, Note, Reason
from sallimbook.core.types import KrwString, YearMonth

Label = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)
]
Percent = Annotated[
    str, StringConstraints(strict=True, pattern=r"^(0|[1-9][0-9]{0,4})(\.[0-9]{1,2})?$")
]


class ExpectedInput(InputModel):
    member_id: UUID
    label: Label
    amount_krw: KrwString | None = None
    active: bool = Field(default=True, strict=True)
    note: Note | None = None


class ExpectedChange(ExpectedInput):
    reason: Reason


class BonusInput(InputModel):
    member_id: UUID
    performance_year: int = Field(strict=True, ge=1900, le=9998)
    award_kind: Literal["tai_h1", "tai_h2", "opi"]
    payment_month: YearMonth | None = None
    gross_krw: KrwString | None = None
    net_cash_krw: KrwString | None = None
    stock_grant_value_krw: KrwString | None = None
    payout_rate_percent: Percent | None = None
    received: bool = Field(default=False, strict=True)
    active: bool = Field(default=True, strict=True)
    note: Note | None = None

    @model_validator(mode="after")
    def receipt(self) -> Self:
        if self.received and (self.payment_month is None or self.net_cash_krw is None):
            raise ValueError("Confirmed receipts require a payment month and known cash amount")
        return self


class BonusChange(BonusInput):
    reason: Reason


class PlanningMetadata(InputModel):
    id: UUID
    household_id: UUID
    version: int
    created_at: datetime
    updated_at: datetime
    created_by_member_id: UUID
    updated_by_member_id: UUID


class ExpectedResponse(ExpectedInput, PlanningMetadata):
    pass


class BonusResponse(BonusInput, PlanningMetadata):
    cash_record_id: UUID | None


class ExpectedList(InputModel):
    items: list[ExpectedResponse]
    next_cursor: UUID | None


class BonusList(InputModel):
    items: list[BonusResponse]
    next_cursor: UUID | None
