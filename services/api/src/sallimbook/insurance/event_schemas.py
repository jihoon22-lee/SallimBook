from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator
from pydantic.json_schema import SkipJsonSchema

from sallimbook.assets.schemas import DateOnly
from sallimbook.cashflow.schemas import CashResponse, InputModel, Note, Reason
from sallimbook.core.types import KrwString, SignedKrwString
from sallimbook.insurance.schemas import BenefitType, EntityResponse, ShortNote, Title

Reference = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)
]
DetailType = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=40)
]
type ClaimState = Literal[
    "draft", "submitted", "documents_required", "reviewing", "decided", "closed", "withdrawn"
]


class EventReference(BaseModel):
    id: UUID
    version: int = Field(ge=1)


class EventReason(InputModel):
    reason: Reason = Field(repr=False)


class ActualPayment(InputModel):
    amount_krw: KrwString = Field(repr=False)
    occurred_on: DateOnly
    account_id: UUID | None = None
    card_id: UUID | None = None
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def actual(self) -> Self:
        if self.amount_krw == "0":
            raise ValueError("An actual payment must be positive")
        if self.account_id is not None and self.card_id is not None:
            raise ValueError("Choose only one actual payment method")
        return self


class ExpenseLineInput(InputModel):
    label: Title
    amount_krw: KrwString = Field(repr=False)
    detail_type: DetailType = "other"


class ExpenseCreate(ActualPayment):
    case_id: UUID
    node_id: UUID
    provider_name: Title | None = None
    receipt_reference: Reference | None = Field(default=None, repr=False)
    gross_medical_krw: KrwString | None = Field(default=None, repr=False)
    public_coverage_krw: KrwString | None = Field(default=None, repr=False)
    lines: list[ExpenseLineInput] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def exact_lines(self) -> Self:
        if self.lines and sum(int(line.amount_krw) for line in self.lines) != int(self.amount_krw):
            raise ValueError("Receipt detail lines must equal the actual payment")
        return self


class ExpenseCorrection(ExpenseCreate, EventReason):
    pass


class RefundCreate(ActualPayment, EventReason):
    pass


class ExpenseLineResponse(ExpenseLineInput):
    id: UUID


class ExpenseListItem(EntityResponse):
    case_id: UUID
    node_id: UUID
    provider_name: str | None
    receipt_reference: str | None = Field(repr=False)
    gross_medical_krw: KrwString | None
    public_coverage_krw: KrwString | None
    correction_of_id: UUID | None
    correction_reason: str | None = Field(repr=False)
    cash: CashResponse
    line_count: int = Field(ge=0)


class ExpenseResponse(ExpenseListItem):
    lines: list[ExpenseLineResponse]


class ExpenseListResponse(BaseModel):
    items: list[ExpenseListItem]
    next_cursor: UUID | None


class RefundResponse(EntityResponse):
    expense_id: UUID
    correction_of_id: UUID | None
    reason: str = Field(repr=False)
    cash: CashResponse


class RefundListResponse(BaseModel):
    items: list[RefundResponse]
    next_cursor: UUID | None


class ClaimFields(InputModel):
    claim_reference: Reference | None = Field(default=None, repr=False)
    submitted_on: DateOnly | None = None
    requested_krw: KrwString | None = Field(default=None, repr=False)
    decided_krw: KrwString | None = Field(default=None, repr=False)
    claim_state: ClaimState = "draft"
    decision_note: Note | None = Field(default=None, repr=False)


class ClaimCreate(ClaimFields):
    case_id: UUID
    policy_id: UUID
    expense_ids: list[UUID] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def unique_expenses(self) -> Self:
        if len(set(self.expense_ids)) != len(self.expense_ids):
            raise ValueError("Each expense may be linked once per claim")
        return self


class ClaimPatch(InputModel):
    claim_reference: Reference | None = Field(default=None, repr=False)
    submitted_on: DateOnly | None = None
    requested_krw: KrwString | None = Field(default=None, repr=False)
    decided_krw: KrwString | None = Field(default=None, repr=False)
    claim_state: ClaimState | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    decision_note: Note | None = Field(default=None, repr=False)
    expense_ids: Annotated[list[UUID], Field(max_length=200)] | SkipJsonSchema[None] = Field(
        default_factory=lambda: None
    )
    reason: Reason = Field(repr=False)

    @model_validator(mode="after")
    def supplied(self) -> Self:
        if not self.model_fields_set - {"reason"}:
            raise ValueError("Supply at least one correction")
        if any(
            getattr(self, name) is None
            for name in self.model_fields_set & {"claim_state", "expense_ids"}
        ):
            raise ValueError("Required claim fields cannot be cleared")
        if self.expense_ids is not None and len(set(self.expense_ids)) != len(self.expense_ids):
            raise ValueError("Each expense may be linked once per claim")
        return self


class ClaimListItem(ClaimFields, EntityResponse):
    case_id: UUID
    policy_id: UUID
    expense_count: int = Field(ge=0)


class ClaimResponse(ClaimListItem):
    expense_ids: list[UUID]
    # Active deposits allocated to this claim, their active returns, and the difference.
    received_krw: KrwString
    returned_krw: KrwString
    net_received_krw: KrwString


class ClaimListResponse(BaseModel):
    items: list[ClaimListItem]
    next_cursor: UUID | None


class ClaimRevisionResponse(ClaimFields):
    claim_id: UUID
    case_id: UUID
    policy_id: UUID
    version: int
    changed_by_member_id: UUID
    changed_at: datetime
    reason: str | None = Field(repr=False)
    expense_ids: list[UUID]


class ClaimHistoryResponse(BaseModel):
    items: list[ClaimRevisionResponse]
    next_cursor: int | None


class AllocationInput(InputModel):
    case_id: UUID
    policy_id: UUID | None = None
    claim_id: UUID | None = None
    benefit_type: BenefitType
    amount_krw: KrwString = Field(repr=False)

    @model_validator(mode="after")
    def valid_allocation(self) -> Self:
        if self.amount_krw == "0":
            raise ValueError("An allocation must be positive")
        if self.claim_id is not None and self.policy_id is None:
            raise ValueError("A claim allocation must identify its matching policy")
        return self


class PayoutCreate(ActualPayment):
    card_id: None = None
    insurer_note: ShortNote | None = Field(default=None, repr=False)
    allocations: list[AllocationInput] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def exact_allocations(self) -> Self:
        if sum(int(row.amount_krw) for row in self.allocations) != int(self.amount_krw):
            raise ValueError("Allocations must equal the actual receipt")
        return self


class PayoutCorrection(PayoutCreate, EventReason):
    pass


class AllocationLinkPatch(InputModel):
    policy_id: UUID | None = None
    claim_id: UUID | None = None
    reason: Reason = Field(repr=False)

    @model_validator(mode="after")
    def supplied(self) -> Self:
        if not self.model_fields_set - {"reason"}:
            raise ValueError("Supply a claim or policy link correction")
        return self


class AllocationResponse(AllocationInput, EntityResponse):
    payout_id: UUID


class AllocationRevisionResponse(AllocationInput):
    allocation_id: UUID
    payout_id: UUID
    version: int
    changed_by_member_id: UUID
    changed_at: datetime
    reason: str | None = Field(repr=False)


class AllocationHistoryResponse(BaseModel):
    items: list[AllocationRevisionResponse]
    next_cursor: int | None


class PayoutListItem(EntityResponse):
    insurer_note: str | None = Field(repr=False)
    correction_of_id: UUID | None
    correction_reason: str | None = Field(repr=False)
    cash: CashResponse
    allocation_count: int = Field(ge=1)


class PayoutResponse(PayoutListItem):
    allocations: list[AllocationResponse]


class PayoutListResponse(BaseModel):
    items: list[PayoutListItem]
    next_cursor: UUID | None


class ReturnCreate(ActualPayment, EventReason):
    card_id: None = None
    original_allocation_id: UUID


class ReturnResponse(EntityResponse):
    payout_id: UUID
    original_allocation_id: UUID
    correction_of_id: UUID | None
    reason: str = Field(repr=False)
    cash: CashResponse


class ReturnListResponse(BaseModel):
    items: list[ReturnResponse]
    next_cursor: UUID | None


class BenefitSummary(BaseModel):
    benefit_type: BenefitType
    received_krw: KrwString
    returned_krw: KrwString
    net_received_krw: KrwString


class CaseSummaryResponse(BaseModel):
    case_id: UUID
    medical_paid_krw: KrwString
    medical_refunded_krw: KrwString
    net_medical_krw: KrwString
    insurance_received_krw: KrwString
    insurance_returned_krw: KrwString
    net_received_krw: KrwString
    net_burden_krw: SignedKrwString
    benefits: list[BenefitSummary]


class NodeSummaryResponse(BaseModel):
    case_id: UUID
    node_id: UUID
    subtree_node_count: int = Field(ge=1)
    medical_paid_krw: KrwString
    medical_refunded_krw: KrwString
    net_medical_krw: KrwString


class EventCashHistoryResponse(BaseModel):
    items: list[CashResponse]
    next_cursor: int | None
