"""Actual medical/insurance sources, immutable correction chains and typed claim evidence."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin
from sallimbook.core.types import KrwNumeric
from sallimbook.insurance.models import ActorFields, actor_constraints, household_fk


def cash_constraints(table):
    return (
        UniqueConstraint("cash_record_id"),
        household_fk(table, "cash_record_id", "cash_records"),
        UniqueConstraint("correction_of_id"),
        household_fk(table, "correction_of_id", table),
        CheckConstraint(
            "correction_of_id IS NULL OR correction_of_id <> id", name="not_self_correction"
        ),
    )


def nonnegative(field):
    return CheckConstraint(f"{field} IS NULL OR {field} >= 0", name=f"{field}_nonnegative")


class MedicalExpense(ActorFields, EntityMixin, Base):
    __tablename__ = "medical_expenses"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint(
            "household_id", "case_id", "id", name="uq_medical_expenses_household_case_id"
        ),
        *actor_constraints("medical_expenses"),
        *cash_constraints("medical_expenses"),
        household_fk("medical_expenses", "case_id", "insurance_cases"),
        ForeignKeyConstraint(
            ["household_id", "case_id", "node_id"],
            ["medical_nodes.household_id", "medical_nodes.case_id", "medical_nodes.id"],
            ondelete="RESTRICT",
            name="fk_medical_expenses_same_case_node",
        ),
        nonnegative("gross_medical_krw"),
        nonnegative("public_coverage_krw"),
        CheckConstraint(
            "(correction_of_id IS NULL) = (correction_reason IS NULL)", name="correction_reason"
        ),
        Index("ix_medical_expenses_household_case_id", "household_id", "case_id", "id"),
    )
    case_id: Mapped[UUID]
    node_id: Mapped[UUID]
    cash_record_id: Mapped[UUID]
    provider_name: Mapped[str | None] = mapped_column(String(120))
    receipt_reference: Mapped[str | None] = mapped_column(String(120))
    gross_medical_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    public_coverage_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    correction_of_id: Mapped[UUID | None]
    correction_reason: Mapped[str | None] = mapped_column(String(500))


class MedicalExpenseLine(Base):
    __tablename__ = "medical_expense_lines"
    __table_args__ = (
        household_fk("medical_expense_lines", "expense_id", "medical_expenses"),
        CheckConstraint("amount_krw >= 0", name="nonnegative_amount"),
        CheckConstraint("char_length(btrim(label)) > 0", name="nonempty_label"),
        CheckConstraint("char_length(btrim(detail_type)) > 0", name="nonempty_detail_type"),
        Index("ix_medical_expense_lines_household_expense", "household_id", "expense_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID]
    expense_id: Mapped[UUID]
    label: Mapped[str] = mapped_column(String(120))
    amount_krw: Mapped[Decimal] = mapped_column(KrwNumeric())
    detail_type: Mapped[str] = mapped_column(String(40))


class MedicalRefund(ActorFields, EntityMixin, Base):
    __tablename__ = "medical_refunds"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        *actor_constraints("medical_refunds"),
        *cash_constraints("medical_refunds"),
        household_fk("medical_refunds", "expense_id", "medical_expenses"),
        CheckConstraint("char_length(btrim(reason)) > 0", name="nonempty_reason"),
        Index("ix_medical_refunds_household_expense_id", "household_id", "expense_id", "id"),
    )
    expense_id: Mapped[UUID]
    cash_record_id: Mapped[UUID]
    reason: Mapped[str] = mapped_column(String(500))
    correction_of_id: Mapped[UUID | None]


class ClaimFields:
    case_id: Mapped[UUID]
    policy_id: Mapped[UUID]
    claim_reference: Mapped[str | None] = mapped_column(String(120))
    submitted_on: Mapped[date | None]
    requested_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    decided_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    claim_state: Mapped[str] = mapped_column(String(24))
    decision_note: Mapped[str | None] = mapped_column(String(2000))


def claim_constraints(table):
    return (
        household_fk(table, "case_id", "insurance_cases"),
        household_fk(table, "policy_id", "insurance_policies"),
        nonnegative("requested_krw"),
        nonnegative("decided_krw"),
        CheckConstraint(
            "claim_state IN ('draft','submitted','documents_required','reviewing',"
            "'decided','closed','withdrawn')",
            name="claim_state",
        ),
    )


class InsuranceClaim(ClaimFields, ActorFields, EntityMixin, Base):
    __tablename__ = "insurance_claims"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint(
            "household_id", "case_id", "id", name="uq_insurance_claims_household_case_id"
        ),
        UniqueConstraint(
            "household_id",
            "case_id",
            "policy_id",
            "id",
            name="uq_insurance_claims_household_case_policy_id",
        ),
        *actor_constraints("insurance_claims"),
        *claim_constraints("insurance_claims"),
        Index("ix_insurance_claims_household_case_id", "household_id", "case_id", "id"),
        Index("ix_insurance_claims_household_policy_id", "household_id", "policy_id", "id"),
    )


class ClaimExpense(Base):
    __tablename__ = "claim_expenses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "case_id", "claim_id"],
            ["insurance_claims.household_id", "insurance_claims.case_id", "insurance_claims.id"],
            ondelete="RESTRICT",
            name="fk_claim_expenses_same_case_claim",
        ),
        ForeignKeyConstraint(
            ["household_id", "case_id", "expense_id"],
            ["medical_expenses.household_id", "medical_expenses.case_id", "medical_expenses.id"],
            ondelete="RESTRICT",
            name="fk_claim_expenses_same_case_expense",
        ),
    )
    claim_id: Mapped[UUID] = mapped_column(primary_key=True)
    expense_id: Mapped[UUID] = mapped_column(primary_key=True)
    household_id: Mapped[UUID]
    case_id: Mapped[UUID]


class InsuranceClaimRevision(ClaimFields, Base):
    __tablename__ = "insurance_claim_revisions"
    __table_args__ = (
        UniqueConstraint(
            "household_id",
            "case_id",
            "claim_id",
            "version",
            name="uq_claim_revisions_household_case_version",
        ),
        household_fk("insurance_claim_revisions", "claim_id", "insurance_claims"),
        household_fk("insurance_claim_revisions", "changed_by_member_id", "household_members"),
        *claim_constraints("insurance_claim_revisions"),
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint(
            "version = 1 OR (reason IS NOT NULL AND char_length(btrim(reason)) > 0)",
            name="change_reason",
        ),
    )
    claim_id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    household_id: Mapped[UUID]
    changed_by_member_id: Mapped[UUID]
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String(500))


class ClaimRevisionExpense(Base):
    __tablename__ = "claim_revision_expenses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "case_id", "claim_id", "claim_version"],
            [
                "insurance_claim_revisions.household_id",
                "insurance_claim_revisions.case_id",
                "insurance_claim_revisions.claim_id",
                "insurance_claim_revisions.version",
            ],
            ondelete="RESTRICT",
            name="fk_claim_revision_expenses_revision",
        ),
        ForeignKeyConstraint(
            ["household_id", "case_id", "expense_id"],
            ["medical_expenses.household_id", "medical_expenses.case_id", "medical_expenses.id"],
            ondelete="RESTRICT",
            name="fk_claim_revision_expenses_same_case_expense",
        ),
    )
    claim_id: Mapped[UUID] = mapped_column(primary_key=True)
    claim_version: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    expense_id: Mapped[UUID] = mapped_column(primary_key=True)
    household_id: Mapped[UUID]
    case_id: Mapped[UUID]


class InsurancePayout(ActorFields, EntityMixin, Base):
    __tablename__ = "insurance_payouts"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        *actor_constraints("insurance_payouts"),
        *cash_constraints("insurance_payouts"),
        CheckConstraint(
            "(correction_of_id IS NULL) = (correction_reason IS NULL)", name="correction_reason"
        ),
        Index("ix_insurance_payouts_household_id", "household_id", "id"),
    )
    cash_record_id: Mapped[UUID]
    insurer_note: Mapped[str | None] = mapped_column(String(1000))
    correction_of_id: Mapped[UUID | None]
    correction_reason: Mapped[str | None] = mapped_column(String(500))


class AllocationFields:
    payout_id: Mapped[UUID]
    case_id: Mapped[UUID]
    policy_id: Mapped[UUID | None]
    claim_id: Mapped[UUID | None]
    benefit_type: Mapped[str] = mapped_column(String(16))
    amount_krw: Mapped[Decimal] = mapped_column(KrwNumeric())


def allocation_constraints(table):
    return (
        household_fk(table, "payout_id", "insurance_payouts"),
        household_fk(table, "case_id", "insurance_cases"),
        household_fk(table, "policy_id", "insurance_policies"),
        ForeignKeyConstraint(
            ["household_id", "case_id", "policy_id", "claim_id"],
            [
                "insurance_claims.household_id",
                "insurance_claims.case_id",
                "insurance_claims.policy_id",
                "insurance_claims.id",
            ],
            ondelete="RESTRICT",
            name=f"fk_{table}_same_case_policy_claim",
        ),
        CheckConstraint("claim_id IS NULL OR policy_id IS NOT NULL", name="claim_has_policy"),
        CheckConstraint("benefit_type IN ('reimbursement','fixed','other')", name="benefit_type"),
        CheckConstraint("amount_krw > 0", name="positive_amount"),
    )


class PayoutAllocation(AllocationFields, ActorFields, EntityMixin, Base):
    __tablename__ = "payout_allocations"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint(
            "household_id", "payout_id", "id", name="uq_payout_allocations_household_payout_id"
        ),
        *actor_constraints("payout_allocations"),
        *allocation_constraints("payout_allocations"),
        Index("ix_payout_allocations_household_case_id", "household_id", "case_id", "id"),
    )


class PayoutAllocationRevision(AllocationFields, Base):
    __tablename__ = "payout_allocation_revisions"
    __table_args__ = (
        household_fk("payout_allocation_revisions", "allocation_id", "payout_allocations"),
        household_fk("payout_allocation_revisions", "changed_by_member_id", "household_members"),
        *allocation_constraints("payout_allocation_revisions"),
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint(
            "version = 1 OR (reason IS NOT NULL AND char_length(btrim(reason)) > 0)",
            name="change_reason",
        ),
    )
    allocation_id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    household_id: Mapped[UUID]
    changed_by_member_id: Mapped[UUID]
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String(500))


class InsuranceReturn(ActorFields, EntityMixin, Base):
    __tablename__ = "insurance_returns"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        *actor_constraints("insurance_returns"),
        *cash_constraints("insurance_returns"),
        ForeignKeyConstraint(
            ["household_id", "payout_id", "original_allocation_id"],
            [
                "payout_allocations.household_id",
                "payout_allocations.payout_id",
                "payout_allocations.id",
            ],
            ondelete="RESTRICT",
            name="fk_insurance_returns_original_allocation",
        ),
        CheckConstraint("char_length(btrim(reason)) > 0", name="nonempty_reason"),
        Index("ix_insurance_returns_household_payout_id", "household_id", "payout_id", "id"),
    )
    payout_id: Mapped[UUID]
    original_allocation_id: Mapped[UUID]
    cash_record_id: Mapped[UUID]
    reason: Mapped[str] = mapped_column(String(500))
    correction_of_id: Mapped[UUID | None]
