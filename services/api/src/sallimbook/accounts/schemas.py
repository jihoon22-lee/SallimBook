import re
from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from sallimbook.assets.schemas import AssetCreate, AssetResponse, DateOnly

type AccountType = Literal[
    "checking",
    "savings",
    "term_deposit",
    "brokerage",
    "pension_savings",
    "irp",
    "dc_pension",
    "isa",
    "cma",
    "other",
]
type AccountStatus = Literal["active", "closed"]
InstitutionName = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)
]
Purpose = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=500)]


def _validate_number(value: SecretStr) -> SecretStr:
    number = value.get_secret_value()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]{3,62}[A-Za-z0-9]", number):
        raise ValueError("Use a bounded account identifier with optional spaces or hyphens")
    canonical = number.replace(" ", "").replace("-", "")
    if not 5 <= len(canonical) <= 40:
        raise ValueError("Account identifier length is invalid")
    return value


AccountNumber = Annotated[
    SecretStr, Field(min_length=5, max_length=64), AfterValidator(_validate_number)
]


class AccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountCreate(AccountInput):
    asset_id: UUID | None = None
    asset: AssetCreate | None = None
    institution_name: InstitutionName
    account_type: AccountType
    account_number: AccountNumber | None = Field(default=None, repr=False)
    purpose: Purpose | None = None
    opened_on: DateOnly | None = None

    @model_validator(mode="after")
    def validate_asset(self) -> Self:
        if (self.asset_id is None) == (self.asset is None):
            raise ValueError("Choose an existing asset or supply a new asset")
        if self.asset is not None:
            if self.asset.kind != "asset" or self.asset.category != "financial":
                raise ValueError("An account requires a financial asset")
            if (
                self.opened_on is not None
                and self.asset.ended_on is not None
                and self.opened_on > self.asset.ended_on
            ):
                raise ValueError("Opening cannot follow closure")
        return self


class AccountPatch(AccountInput):
    institution_name: InstitutionName | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    account_type: AccountType | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    account_number: AccountNumber | None = Field(default=None, repr=False)
    purpose: Purpose | None = None
    opened_on: DateOnly | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Supply at least one account field")
        for name in self.model_fields_set & {"institution_name", "account_type"}:
            if getattr(self, name) is None:
                raise ValueError("Required account metadata cannot be cleared")
        return self


class AccountResponse(BaseModel):
    id: UUID
    household_id: UUID
    asset_id: UUID
    asset: AssetResponse
    institution_name: str
    account_type: AccountType
    masked_number: str | None
    has_number: bool
    purpose: str | None
    opened_on: date | None
    closed_on: date | None
    status: AccountStatus
    created_by_member_id: UUID
    updated_by_member_id: UUID
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class AccountListResponse(BaseModel):
    items: list[AccountResponse]
    next_cursor: UUID | None


class AccountRevealResponse(BaseModel):
    id: UUID
    account_number: str = Field(repr=False)
    display_for_seconds: Literal[30] = 30
