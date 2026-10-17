import re
from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from sallimbook.cashflow.payment_link_schemas import CLOSURE_FIELDS, ClosureFields

type AssetKind = Literal["asset", "liability"]
type AssetCategory = Literal["real_estate", "deposit", "financial", "loan", "other"]
type OwnershipKind = Literal["individual", "joint"]
type AmountBasis = Literal["whole", "owned"]
type InclusionStatus = Literal["included", "excluded"]
type AssetStatus = Literal["active", "archived"]

AssetName = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)
]
AssetNote = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=2000)]
HouseholdShare = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^(0(?:\.[0-9]{1,18})?|1(?:\.0{1,18})?)$",
        max_length=20,
    ),
]


def _date_only(value: object) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return date.fromisoformat(value)
    raise ValueError("Use an ISO date without a time or timestamp")


DateOnly = Annotated[date, BeforeValidator(_date_only)]


class AssetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssetCreate(AssetInput):
    name: AssetName
    kind: AssetKind
    category: AssetCategory
    ownership_kind: OwnershipKind
    owner_member_id: UUID | None = None
    household_share: HouseholdShare = "1"
    amount_basis: AmountBasis
    inclusion_status: InclusionStatus = "included"
    started_on: DateOnly
    ended_on: DateOnly | None = None
    note: AssetNote | None = None

    @model_validator(mode="after")
    def validate_relations(self) -> Self:
        if (self.ownership_kind == "individual") != (self.owner_member_id is not None):
            raise ValueError(
                "An individual asset needs one owner; a joint asset has no single owner"
            )
        if self.ended_on is not None and self.ended_on < self.started_on:
            raise ValueError("The end date cannot precede the start date")
        return self


def _omitted_patch_field():
    # None represents an omitted Python attribute only. The validator rejects an
    # explicit null; a factory avoids advertising null as a JSON Schema default.
    return Field(default_factory=lambda: None)


class AssetPatch(AssetInput, ClosureFields):
    name: AssetName | SkipJsonSchema[None] = _omitted_patch_field()
    kind: AssetKind | SkipJsonSchema[None] = _omitted_patch_field()
    category: AssetCategory | SkipJsonSchema[None] = _omitted_patch_field()
    ownership_kind: OwnershipKind | SkipJsonSchema[None] = _omitted_patch_field()
    owner_member_id: UUID | None = None
    household_share: HouseholdShare | SkipJsonSchema[None] = _omitted_patch_field()
    amount_basis: AmountBasis | SkipJsonSchema[None] = _omitted_patch_field()
    inclusion_status: InclusionStatus | SkipJsonSchema[None] = _omitted_patch_field()
    started_on: DateOnly | SkipJsonSchema[None] = _omitted_patch_field()
    ended_on: DateOnly | None = None
    note: AssetNote | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set - CLOSURE_FIELDS:
            raise ValueError("Supply at least one field to edit")
        nullable = {"owner_member_id", "ended_on", "note"}
        if any(
            getattr(self, field) is None
            for field in self.model_fields_set - nullable - CLOSURE_FIELDS
        ):
            raise ValueError("A required asset field cannot be cleared")
        return self


class AssetArchive(AssetInput, ClosureFields):
    ended_on: DateOnly


class AssetResponse(AssetCreate):
    id: UUID
    household_id: UUID
    status: AssetStatus
    archived_at: datetime | None
    created_by_member_id: UUID
    updated_by_member_id: UUID
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class AssetListResponse(BaseModel):
    items: list[AssetResponse]
    next_cursor: UUID | None
