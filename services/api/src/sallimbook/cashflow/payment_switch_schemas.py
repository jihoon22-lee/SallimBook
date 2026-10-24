"""Transient method-only preview; no stored bulk job or additional money contract."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, model_validator

from sallimbook.assets.schemas import DateOnly
from sallimbook.cashflow.payment_link_schemas import Digest
from sallimbook.cashflow.recurring_schemas import RuleVersionResponse
from sallimbook.cashflow.schemas import InputModel, Reason

type MethodKind = Literal["card", "account"]


class PaymentSwitchInput(InputModel):
    source_kind: MethodKind
    source_id: UUID
    target_kind: MethodKind
    target_id: UUID
    effective_on: DateOnly

    @model_validator(mode="after")
    def distinct_method(self) -> Self:
        if self.source_kind == self.target_kind and self.source_id == self.target_id:
            raise ValueError("Choose a different payment method")
        return self


class PaymentSwitchApply(PaymentSwitchInput):
    preview_digest: Digest
    reason: Reason


class PaymentSwitchRow(BaseModel):
    id: UUID
    version: int
    title: str
    periods: list[RuleVersionResponse]
    unchanged_period_count: int
    update_occurrence_count: int
    preserved_past_count: int
    preserved_paid_count: int
    preserved_manual_count: int
    blocked_reason: Literal["INITIAL_PERIOD_START"] | None
    preview_digest: Digest


class PaymentSwitchPreview(BaseModel):
    items: list[PaymentSwitchRow]
    next_cursor: UUID | None
