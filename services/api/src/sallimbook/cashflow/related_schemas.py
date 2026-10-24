"""Read-only references; money remains owned by the original domain."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from sallimbook.core.types import KrwString


class IncomeAllocationLink(BaseModel):
    id: UUID
    case_id: UUID
    case_title: str
    amount_krw: KrwString


class IncomeInsuranceSource(BaseModel):
    record_id: UUID
    payout_id: UUID | None
    return_id: UUID | None
    original_allocation_id: UUID | None
    allocations: list[IncomeAllocationLink]


class RulePolicyLink(BaseModel):
    id: UUID
    policy_id: UUID
    product_name: str
    insurer: str
    policy_status: Literal["active", "ended", "lapsed"]
    active: bool
    ended_at: datetime | None


class RuleInsuranceLink(BaseModel):
    rule_id: UUID
    link: RulePolicyLink | None
