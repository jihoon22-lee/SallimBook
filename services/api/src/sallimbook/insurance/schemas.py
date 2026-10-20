from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator
from pydantic.json_schema import SkipJsonSchema

from sallimbook.accounts.schemas import AccountNumber
from sallimbook.assets.schemas import DateOnly
from sallimbook.cashflow.recurring_schemas import RuleResponse
from sallimbook.cashflow.schemas import InputModel, Note, Reason
from sallimbook.core.types import KrwString, SignedKrwString

Title = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)
]
ShortNote = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=1000)]
DiagnosisCode = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=80)]
type PolicyStatus = Literal["active", "ended", "lapsed"]
type BenefitType = Literal["reimbursement", "fixed", "other"]
type TreatmentState = Literal["ongoing", "ended"]
type FinancialState = Literal["open", "settled"]
type NodeKind = Literal[
    "outpatient", "inpatient", "surgery", "prescription", "pharmacy", "follow_up", "group"
]


def _patch(value, required):
    supplied = value.model_fields_set - {"reason"}
    if not supplied:
        raise ValueError("Supply at least one editable field")
    if any(getattr(value, name) is None for name in supplied & required):
        raise ValueError("Required fields cannot be cleared")
    return value


def _period(start, end):
    if start is not None and end is not None and end < start:
        raise ValueError("An end date cannot precede its start")


class PolicyFields(InputModel):
    insurer: Title
    product_name: Title
    policyholder_member_id: UUID | None = None
    insured_member_id: UUID | None = None
    beneficiary_note: ShortNote | None = Field(default=None, repr=False)
    contract_start: DateOnly | None = None
    contract_end: DateOnly | None = None
    coverage_start: DateOnly
    coverage_end: DateOnly | None = None
    payment_start: DateOnly | None = None
    payment_end: DateOnly | None = None
    status: PolicyStatus = "active"
    valuation_asset_id: UUID | None = None
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def periods(self) -> Self:
        _period(self.contract_start, self.contract_end)
        _period(self.coverage_start, self.coverage_end)
        _period(self.payment_start, self.payment_end)
        return self


class PolicyCreate(PolicyFields):
    policy_number: AccountNumber | None = Field(default=None, repr=False)


class PolicyPatch(InputModel):
    insurer: Title | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    product_name: Title | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    policyholder_member_id: UUID | None = None
    insured_member_id: UUID | None = None
    beneficiary_note: ShortNote | None = Field(default=None, repr=False)
    contract_start: DateOnly | None = None
    contract_end: DateOnly | None = None
    coverage_start: DateOnly | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    coverage_end: DateOnly | None = None
    payment_start: DateOnly | None = None
    payment_end: DateOnly | None = None
    status: PolicyStatus | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    valuation_asset_id: UUID | None = None
    note: Note | None = Field(default=None, repr=False)
    policy_number: AccountNumber | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def patch(self) -> Self:
        return _patch(self, {"insurer", "product_name", "coverage_start", "status"})


class EntityResponse(BaseModel):
    id: UUID
    household_id: UUID
    created_by_member_id: UUID
    updated_by_member_id: UUID
    created_at: datetime
    updated_at: datetime
    version: int


class PolicyResponse(PolicyFields, EntityResponse):
    masked_number: str | None
    has_number: bool


class PolicyListResponse(BaseModel):
    items: list[PolicyResponse]
    next_cursor: UUID | None


class PolicyRevealResponse(BaseModel):
    id: UUID
    policy_number: str = Field(repr=False)
    display_for_seconds: Literal[30] = 30


class CoverageInput(InputModel):
    name: Title
    benefit_type: BenefitType
    insured_amount_krw: KrwString | None = Field(default=None, repr=False)
    coverage_start: DateOnly | None = None
    coverage_end: DateOnly | None = None
    note: Note | None = Field(default=None, repr=False)
    active: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def period(self) -> Self:
        _period(self.coverage_start, self.coverage_end)
        return self


class CoveragePatch(InputModel):
    name: Title | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    benefit_type: BenefitType | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    insured_amount_krw: KrwString | None = Field(default=None, repr=False)
    coverage_start: DateOnly | None = None
    coverage_end: DateOnly | None = None
    note: Note | None = Field(default=None, repr=False)
    active: Annotated[bool, Field(strict=True)] | SkipJsonSchema[None] = Field(
        default_factory=lambda: None
    )

    @model_validator(mode="after")
    def patch(self) -> Self:
        return _patch(self, {"name", "benefit_type", "active"})


class CoverageResponse(CoverageInput, EntityResponse):
    policy_id: UUID


class CoverageListResponse(BaseModel):
    items: list[CoverageResponse]
    next_cursor: UUID | None


class PremiumLinkCreate(InputModel):
    rule_id: UUID


class PremiumLinkPatch(InputModel):
    active: bool = Field(strict=True)


class PremiumLinkResponse(EntityResponse):
    policy_id: UUID
    rule_id: UUID
    active: bool
    ended_at: datetime | None
    rule: RuleResponse


class PremiumLinkListResponse(BaseModel):
    items: list[PremiumLinkResponse]
    next_cursor: UUID | None


class CaseInput(InputModel):
    title: Title
    patient_member_id: UUID
    diagnosis_note: Note | None = Field(default=None, repr=False)
    diagnosis_code: DiagnosisCode | None = Field(default=None, repr=False)
    start_on: DateOnly
    end_on: DateOnly | None = None
    treatment_state: TreatmentState = "ongoing"
    financial_state: FinancialState = "open"

    @model_validator(mode="after")
    def period(self) -> Self:
        _period(self.start_on, self.end_on)
        if (self.treatment_state == "ended") != (self.end_on is not None):
            raise ValueError("An ended treatment has an end date; reopening clears it")
        return self


class CasePatch(InputModel):
    title: Title | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    patient_member_id: UUID | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    diagnosis_note: Note | None = Field(default=None, repr=False)
    diagnosis_code: DiagnosisCode | None = Field(default=None, repr=False)
    start_on: DateOnly | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    end_on: DateOnly | None = None
    treatment_state: TreatmentState | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    financial_state: FinancialState | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    reason: Reason = Field(repr=False)

    @model_validator(mode="after")
    def patch(self) -> Self:
        return _patch(
            self, {"title", "patient_member_id", "start_on", "treatment_state", "financial_state"}
        )


class CaseResponse(CaseInput, EntityResponse):
    pass


class CaseListItem(EntityResponse):
    title: str
    patient_member_id: UUID
    start_on: DateOnly
    end_on: DateOnly | None
    treatment_state: TreatmentState
    financial_state: FinancialState
    # Same insurance_summary result as the case detail's net_burden_krw.
    net_burden_krw: SignedKrwString


class CaseListResponse(BaseModel):
    items: list[CaseListItem]
    next_cursor: UUID | None


class CaseRevisionResponse(CaseInput):
    case_id: UUID
    version: int
    changed_by_member_id: UUID
    changed_at: datetime
    reason: str | None = Field(repr=False)


class CaseHistoryResponse(BaseModel):
    items: list[CaseRevisionResponse]
    next_cursor: int | None


class MedicalNodeInput(InputModel):
    parent_id: UUID | None = None
    kind: NodeKind
    label: Title
    provider_name: Title | None = None
    start_on: DateOnly | None = None
    end_on: DateOnly | None = None
    sort_order: int = Field(default=0, strict=True, ge=0, le=1000000)
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def period(self) -> Self:
        _period(self.start_on, self.end_on)
        return self


class MedicalNodePatch(InputModel):
    parent_id: UUID | None = None
    kind: NodeKind | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    label: Title | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    provider_name: Title | None = None
    start_on: DateOnly | None = None
    end_on: DateOnly | None = None
    sort_order: Annotated[int, Field(strict=True, ge=0, le=1000000)] | SkipJsonSchema[None] = Field(
        default_factory=lambda: None
    )
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def patch(self) -> Self:
        return _patch(self, {"kind", "label", "sort_order"})


class MedicalNodeResponse(MedicalNodeInput, EntityResponse):
    case_id: UUID


class MedicalNodeListResponse(BaseModel):
    items: list[MedicalNodeResponse]
    next_cursor: UUID | None
