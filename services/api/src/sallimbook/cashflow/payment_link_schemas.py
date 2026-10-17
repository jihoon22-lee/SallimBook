"""Public payment usage and transient closure confirmation commands."""

from datetime import date
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from sallimbook.core.types import KrwString

CLOSURE_FIELDS = {"closure_ack", "usage_digest"}
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
type PaymentBasis = Literal["account_payment_plan", "card_approval_plan"]


class ClosureFields(BaseModel):
    closure_ack: bool = Field(default=False, strict=True)
    usage_digest: Digest | None = None

    @model_validator(mode="after")
    def confirmation_pair(self) -> Self:
        if self.closure_ack:
            if self.usage_digest is None or getattr(self, "ended_on", None) is None:
                raise ValueError("Closure confirmation requires a digest and explicit end date")
        elif self.usage_digest is not None:
            raise ValueError("A usage digest requires closure confirmation")
        return self


class LinkedRule(BaseModel):
    id: UUID
    rule_id: UUID
    rule_version: int
    title: str
    category: str
    amount_mode: Literal["fixed", "variable"]
    expected_amount_krw: KrwString | None
    economic_type: Literal["expense", "loan", "asset_transfer"]
    account_id: UUID | None
    card_id: UUID | None
    payment_basis: PaymentBasis
    period: Literal["current", "future"]
    effective_from: date
    effective_until: date | None
    anchor_date: date
    frequency: Literal["monthly", "annual", "days"]
    interval_count: int


class LinkedObligation(BaseModel):
    id: UUID
    version: int
    rule_id: UUID
    rule_version_id: UUID
    title: str
    category: str
    scheduled_date: date
    expected_amount_krw: KrwString | None
    actual_paid_krw: KrwString
    status: Literal["unpaid", "partial"]
    account_id: UUID | None
    card_id: UUID | None
    payment_basis: PaymentBasis


class LinkedCard(BaseModel):
    id: UUID
    version: int
    issuer_name: str
    product_name: str
    alias: str | None
    last_four: str | None
    ended_on: date | None
    active_for_closure: bool


class LinkedRulePage(BaseModel):
    items: list[LinkedRule]
    total_count: int
    next_cursor: UUID | None


class LinkedObligationPage(BaseModel):
    items: list[LinkedObligation]
    total_count: int
    next_cursor: UUID | None


class LinkedCardPage(BaseModel):
    items: list[LinkedCard]
    total_count: int
    next_cursor: UUID | None


class PaymentLinksResponse(BaseModel):
    resource_kind: Literal["card", "account"]
    resource_id: UUID
    resource_version: int
    asset_id: UUID | None
    as_of_date: date
    usage_digest: Digest
    requires_confirmation: bool
    coverage: Literal["registered_recurring_only"] = "registered_recurring_only"
    account_withdrawal_total_available: Literal[False] = False
    rules: LinkedRulePage
    obligations: LinkedObligationPage
    cards: LinkedCardPage
