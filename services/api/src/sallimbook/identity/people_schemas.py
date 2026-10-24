from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator
from pydantic.json_schema import SkipJsonSchema

from sallimbook.cashflow.schemas import InputModel

PersonName = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)
]
type FamilyRelation = Literal["child", "parent", "other"]


class PersonCreate(InputModel):
    display_name: PersonName
    relation: FamilyRelation


class PersonPatch(InputModel):
    display_name: PersonName | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    relation: FamilyRelation | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    active: bool | SkipJsonSchema[None] = Field(default_factory=lambda: None)

    @model_validator(mode="after")
    def supplied(self) -> Self:
        if not self.model_fields_set or any(
            getattr(self, key) is None for key in self.model_fields_set
        ):
            raise ValueError("Supply non-null editable fields")
        return self


class PersonResponse(BaseModel):
    id: UUID
    household_id: UUID
    member_id: UUID | None
    display_name: str
    relation: Literal["member", "child", "parent", "other"]
    active: bool
    archived_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime
    created_by_member_id: UUID
    updated_by_member_id: UUID


class PersonListResponse(BaseModel):
    items: list[PersonResponse]
    next_cursor: UUID | None


class PersonCreatedReference(BaseModel):
    id: UUID
    version: int
