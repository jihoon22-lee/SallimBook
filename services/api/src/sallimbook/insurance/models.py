"""Policy metadata and independent medical-case trees; cash facts live separately."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin
from sallimbook.core.types import KrwNumeric


def household_fk(table: str, field: str, target: str):
    return ForeignKeyConstraint(
        ["household_id", field],
        [f"{target}.household_id", f"{target}.id"],
        ondelete="RESTRICT",
        name=f"fk_{table}_{field}",
    )


def actor_constraints(table: str):
    return (
        household_fk(table, "created_by_member_id", "household_members"),
        household_fk(table, "updated_by_member_id", "household_members"),
        CheckConstraint("version > 0", name="positive_version"),
    )


class ActorFields:
    household_id: Mapped[UUID]
    created_by_member_id: Mapped[UUID]
    updated_by_member_id: Mapped[UUID]


class InsurancePolicy(ActorFields, EntityMixin, Base):
    __tablename__ = "insurance_policies"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        *actor_constraints("insurance_policies"),
        household_fk("insurance_policies", "policyholder_member_id", "household_members"),
        household_fk("insurance_policies", "insured_member_id", "household_people"),
        household_fk("insurance_policies", "valuation_asset_id", "assets"),
        CheckConstraint("char_length(btrim(insurer)) > 0", name="nonempty_insurer"),
        CheckConstraint("char_length(btrim(product_name)) > 0", name="nonempty_product"),
        CheckConstraint("status IN ('active','ended','lapsed')", name="valid_status"),
        CheckConstraint(
            "contract_end IS NULL OR contract_start IS NULL OR contract_end >= contract_start",
            name="contract_period",
        ),
        CheckConstraint(
            "coverage_end IS NULL OR coverage_end >= coverage_start", name="coverage_period"
        ),
        CheckConstraint(
            "payment_end IS NULL OR payment_start IS NULL OR payment_end >= payment_start",
            name="payment_period",
        ),
        CheckConstraint(
            "(policy_number_ciphertext IS NULL AND number_nonce IS NULL "
            "AND number_key_version IS NULL "
            "AND last_four IS NULL) OR (policy_number_ciphertext IS NOT NULL "
            "AND number_nonce IS NOT NULL "
            "AND number_key_version IS NOT NULL AND number_key_version > 0 "
            "AND last_four IS NOT NULL "
            "AND octet_length(policy_number_ciphertext) BETWEEN 21 AND 80 "
            "AND octet_length(number_nonce) = 12 AND last_four ~ '^[A-Za-z0-9]{4}$')",
            name="number_envelope",
        ),
        Index("ix_insurance_policies_household_status_id", "household_id", "status", "id"),
    )
    insurer: Mapped[str] = mapped_column(String(120))
    product_name: Mapped[str] = mapped_column(String(120))
    policyholder_member_id: Mapped[UUID | None]
    insured_member_id: Mapped[UUID | None]
    beneficiary_note: Mapped[str | None] = mapped_column(String(1000))
    contract_start: Mapped[date | None]
    contract_end: Mapped[date | None]
    coverage_start: Mapped[date]
    coverage_end: Mapped[date | None]
    payment_start: Mapped[date | None]
    payment_end: Mapped[date | None]
    status: Mapped[str] = mapped_column(String(8))
    valuation_asset_id: Mapped[UUID | None]
    note: Mapped[str | None] = mapped_column(String(2000))
    policy_number_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    number_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    number_key_version: Mapped[int | None]
    last_four: Mapped[str | None] = mapped_column(String(4))


class InsuranceCoverage(ActorFields, EntityMixin, Base):
    __tablename__ = "insurance_coverages"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        *actor_constraints("insurance_coverages"),
        household_fk("insurance_coverages", "policy_id", "insurance_policies"),
        CheckConstraint("benefit_type IN ('reimbursement','fixed','other')", name="benefit_type"),
        CheckConstraint(
            "insured_amount_krw IS NULL OR insured_amount_krw >= 0", name="nonnegative_amount"
        ),
        CheckConstraint(
            "coverage_end IS NULL OR coverage_start IS NULL OR coverage_end >= coverage_start",
            name="coverage_period",
        ),
        CheckConstraint("char_length(btrim(name)) > 0", name="nonempty_name"),
        Index("ix_insurance_coverages_household_policy_id", "household_id", "policy_id", "id"),
    )
    policy_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(String(120))
    benefit_type: Mapped[str] = mapped_column(String(16))
    insured_amount_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    coverage_start: Mapped[date | None]
    coverage_end: Mapped[date | None]
    note: Mapped[str | None] = mapped_column(String(2000))
    active: Mapped[bool] = mapped_column(Boolean)


class PolicyPremiumLink(ActorFields, EntityMixin, Base):
    __tablename__ = "policy_premium_links"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("rule_id"),
        *actor_constraints("policy_premium_links"),
        household_fk("policy_premium_links", "policy_id", "insurance_policies"),
        household_fk("policy_premium_links", "rule_id", "recurring_rules"),
        CheckConstraint("active = (ended_at IS NULL)", name="active_end_pair"),
        Index("ix_policy_premium_links_household_policy", "household_id", "policy_id", "id"),
    )
    policy_id: Mapped[UUID]
    rule_id: Mapped[UUID]
    active: Mapped[bool] = mapped_column(Boolean)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CaseFields:
    title: Mapped[str] = mapped_column(String(120))
    patient_member_id: Mapped[UUID]
    diagnosis_note: Mapped[str | None] = mapped_column(String(2000))
    diagnosis_code: Mapped[str | None] = mapped_column(String(80))
    start_on: Mapped[date]
    end_on: Mapped[date | None]
    treatment_state: Mapped[str] = mapped_column(String(8))
    financial_state: Mapped[str] = mapped_column(String(8))


def case_constraints(table: str):
    return (
        household_fk(table, "patient_member_id", "household_people"),
        CheckConstraint("char_length(btrim(title)) > 0", name="nonempty_title"),
        CheckConstraint("end_on IS NULL OR end_on >= start_on", name="case_period"),
        CheckConstraint("treatment_state IN ('ongoing','ended')", name="treatment_state"),
        CheckConstraint("financial_state IN ('open','settled')", name="financial_state"),
        CheckConstraint(
            "(treatment_state = 'ended') = (end_on IS NOT NULL)", name="treatment_end_pair"
        ),
    )


class InsuranceCase(CaseFields, ActorFields, EntityMixin, Base):
    __tablename__ = "insurance_cases"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        *actor_constraints("insurance_cases"),
        *case_constraints("insurance_cases"),
        Index("ix_insurance_cases_household_start_id", "household_id", "start_on", "id"),
    )


class InsuranceCaseRevision(CaseFields, Base):
    __tablename__ = "insurance_case_revisions"
    __table_args__ = (
        household_fk("insurance_case_revisions", "case_id", "insurance_cases"),
        household_fk("insurance_case_revisions", "changed_by_member_id", "household_members"),
        *case_constraints("insurance_case_revisions"),
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint(
            "version = 1 OR (reason IS NOT NULL AND char_length(btrim(reason)) > 0)",
            name="change_reason",
        ),
    )
    case_id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    household_id: Mapped[UUID]
    changed_by_member_id: Mapped[UUID]
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String(500))


class MedicalNode(ActorFields, EntityMixin, Base):
    __tablename__ = "medical_nodes"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint(
            "household_id", "case_id", "id", name="uq_medical_nodes_household_case_id"
        ),
        *actor_constraints("medical_nodes"),
        household_fk("medical_nodes", "case_id", "insurance_cases"),
        ForeignKeyConstraint(
            ["household_id", "case_id", "parent_id"],
            ["medical_nodes.household_id", "medical_nodes.case_id", "medical_nodes.id"],
            ondelete="RESTRICT",
            name="fk_medical_nodes_same_case_parent",
        ),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_self_parent"),
        CheckConstraint(
            "kind IN ('outpatient','inpatient','surgery','prescription',"
            "'pharmacy','follow_up','group')",
            name="kind",
        ),
        CheckConstraint("char_length(btrim(label)) > 0", name="nonempty_label"),
        CheckConstraint(
            "end_on IS NULL OR start_on IS NULL OR end_on >= start_on", name="node_period"
        ),
        CheckConstraint("sort_order BETWEEN 0 AND 1000000", name="sort_order"),
        Index("ix_medical_nodes_household_case_id", "household_id", "case_id", "id"),
    )
    case_id: Mapped[UUID]
    parent_id: Mapped[UUID | None]
    kind: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(120))
    provider_name: Mapped[str | None] = mapped_column(String(120))
    start_on: Mapped[date | None]
    end_on: Mapped[date | None]
    sort_order: Mapped[int]
    note: Mapped[str | None] = mapped_column(String(2000))
