from datetime import date
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from sallimbook.cashflow.expense_plan_schemas import PlanCreate
from sallimbook.cashflow.schemas import InputModel

SourceKey = Annotated[
    str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")
]
Hash = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$")]


class ImportRow(InputModel):
    source_key: SourceKey
    plan: PlanCreate

    @model_validator(mode="after")
    def baseline_owned(self) -> Self:
        if self.plan.effective_from is not None or self.plan.tracking_mode != "plan_only":
            raise ValueError("Initial import owns the baseline and creates plans only")
        return self


class ImportRequest(InputModel):
    household_id: UUID
    actor_member_id: UUID
    source_id: SourceKey
    manifest_hash: Hash
    rows: list[ImportRow] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_keys(self) -> Self:
        if len({r.source_key for r in self.rows}) != len(self.rows):
            raise ValueError("Duplicate source keys")
        return self


class ImportResultRow(BaseModel):
    source_key: str
    created_rule_id: UUID
    rule_id: UUID | None
    state: Literal["linked", "user_deleted"]


class ImportResult(BaseModel):
    status: Literal["preview", "created", "replayed"]
    baseline_date: date
    created_count: int
    row_count: int
    rows: list[ImportResultRow]
