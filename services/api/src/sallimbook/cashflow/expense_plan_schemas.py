"""Monthly planning contract; legacy scheduled-rule DTOs remain unchanged."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from sallimbook.assets.schemas import DateOnly
from sallimbook.cashflow.recurring_schemas import ScheduleTerms
from sallimbook.cashflow.schemas import Reason
from sallimbook.core.types import KrwString

PLAN_FIELDS = (
    "tracking_mode",
    "plan_kind",
    "budget_treatment",
    "subject_member_id",
    "annual_month",
)


class PlanTerms(ScheduleTerms):
    anchor_date: DateOnly | None = None
    tracking_mode: Literal["plan_only", "scheduled"] = "plan_only"
    plan_kind: Literal["recurring", "budget"] = "recurring"
    budget_treatment: Literal["included", "external_support", "payroll", "reference_only"] = (
        "included"
    )
    subject_member_id: UUID | None = None
    annual_month: int | None = Field(default=None, strict=True, ge=1, le=12)

    @model_validator(mode="after")
    def valid_plan(self) -> Self:
        if self.tracking_mode == "scheduled" and self.anchor_date is None:
            raise ValueError("Scheduled plans need a date")
        if self.annual_month is not None and self.frequency != "annual":
            raise ValueError("An annual month requires annual frequency")
        if (
            self.annual_month is not None
            and self.anchor_date is not None
            and self.annual_month != self.anchor_date.month
        ):
            raise ValueError("Annual month must match the anchor")
        if self.plan_kind == "budget" and (
            self.tracking_mode != "plan_only"
            or self.frequency != "monthly"
            or self.interval_count != 1
        ):
            raise ValueError("Budgets are monthly plans without generated payments")
        return self


class PlanCreate(PlanTerms):
    effective_from: DateOnly | None = None


class PlanChange(PlanTerms):
    effective_from: DateOnly | None = None
    reason: Reason = Field(default="월 계획 수정", repr=False)


class PlanVersionResponse(PlanTerms):
    id: UUID
    effective_from: DateOnly
    effective_until: DateOnly | None
    reason: str | None = Field(repr=False)
    created_at: datetime
    revoked_at: datetime | None
    monthly_equivalent_krw: KrwString | None


class PlanResponse(BaseModel):
    id: UUID
    household_id: UUID
    version: int
    ended_on: DateOnly | None
    end_reason: str | None = Field(repr=False)
    versions: list[PlanVersionResponse]
    history: list[PlanVersionResponse]


class PlanListResponse(BaseModel):
    items: list[PlanResponse]
    next_cursor: UUID | None


class PlanSubtotal(BaseModel):
    key: str
    known_krw: KrwString
    unknown_count: int
    unconverted_count: int
    count: int


class PlanSummaryResponse(BaseModel):
    as_of: DateOnly
    fixed_known_krw: KrwString
    budget_known_krw: KrwString
    combined_known_krw: KrwString
    excluded_known_krw: KrwString
    included_unknown_count: int
    excluded_unknown_count: int
    unconverted_count: int
    plan_count: int
    categories: list[PlanSubtotal]
    treatments: list[PlanSubtotal]
    economic_types: list[PlanSubtotal]
