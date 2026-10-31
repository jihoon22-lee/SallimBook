from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.json_schema import SkipJsonSchema

from sallimbook.assets.schemas import DateOnly
from sallimbook.cashflow.payment_link_schemas import CLOSURE_FIELDS, ClosureFields
from sallimbook.core.types import KrwString

type CardType = Literal["credit", "debit"]
Name = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)
]
Alias = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=80)]
Note = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=500)]
LastFour = Annotated[
    str, StringConstraints(strict=True, pattern=r"^[0-9]{4}$", min_length=4, max_length=4)
]
SettlementDay = Annotated[int, Field(strict=True, ge=1, le=31)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CardCreate(InputModel):
    owner_member_id: UUID
    issuer_name: Name
    product_name: Name
    alias: Alias | None = None
    card_type: CardType
    annual_fee_krw: KrwString | None = None
    is_family_card: bool | None = Field(default=None, strict=True)
    last_four: LastFour | None = None
    settlement_day: SettlementDay | None = None
    settlement_account_id: UUID | None = None
    started_on: DateOnly | None = None
    ended_on: DateOnly | None = None
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def dates(self) -> Self:
        if (
            self.started_on is not None
            and self.ended_on is not None
            and self.started_on > self.ended_on
        ):
            raise ValueError("Card use cannot end before it starts")
        return self


class CardPatch(InputModel, ClosureFields):
    owner_member_id: UUID | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    issuer_name: Name | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    product_name: Name | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    alias: Alias | None = None
    card_type: CardType | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    annual_fee_krw: KrwString | None = None
    is_family_card: bool | None = Field(default=None, strict=True)
    last_four: LastFour | None = None
    settlement_day: SettlementDay | None = None
    settlement_account_id: UUID | None = None
    started_on: DateOnly | None = None
    ended_on: DateOnly | None = None
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def supplied(self) -> Self:
        if not self.model_fields_set - CLOSURE_FIELDS:
            raise ValueError("Supply at least one card field")
        if any(
            getattr(self, field) is None
            for field in self.model_fields_set
            & {"owner_member_id", "issuer_name", "product_name", "card_type"}
        ):
            raise ValueError("Required card metadata cannot be cleared")
        return self


class CardArchive(InputModel, ClosureFields):
    ended_on: DateOnly


class CardResponse(BaseModel):
    id: UUID
    household_id: UUID
    owner_member_id: UUID
    issuer_name: str
    product_name: str
    alias: str | None
    card_type: CardType
    annual_fee_krw: KrwString | None
    is_family_card: bool | None
    last_four: str | None
    masked_number: str | None
    has_secret: bool
    settlement_day: int | None
    settlement_account_id: UUID | None
    settlement_account_status: Literal["active", "closed"] | None
    started_on: date | None
    ended_on: date | None
    status: Literal["active", "closed"]
    note: str | None = Field(repr=False)
    created_by_member_id: UUID
    updated_by_member_id: UUID
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class CardListResponse(BaseModel):
    items: list[CardResponse]
    next_cursor: UUID | None
