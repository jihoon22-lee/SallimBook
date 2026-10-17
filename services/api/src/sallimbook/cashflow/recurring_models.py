"""Versioned schedules and planned obligations, separate from actual cash facts."""

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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin
from sallimbook.core.types import KrwNumeric


def household_fk(table, field, target):
    return ForeignKeyConstraint(
        ["household_id", field],
        [f"{target}.household_id", f"{target}.id"],
        ondelete="RESTRICT",
        name=f"fk_{table}_{field}",
    )


class RecurringRule(EntityMixin, Base):
    __tablename__ = "recurring_rules"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        household_fk("recurring_rules", "created_by_member_id", "household_members"),
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint("(ended_on IS NULL) = (end_reason IS NULL)", name="end_reason"),
        Index("ix_recurring_rules_household_id", "household_id", "id"),
    )
    household_id: Mapped[UUID]
    created_by_member_id: Mapped[UUID]
    ended_on: Mapped[date | None]
    end_reason: Mapped[str | None] = mapped_column(String(500))


class ScheduleFields:
    title: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40))
    amount_mode: Mapped[str] = mapped_column(String(8))
    expected_amount_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    economic_type: Mapped[str] = mapped_column(String(16))
    loan_asset_id: Mapped[UUID | None]
    account_id: Mapped[UUID | None]
    card_id: Mapped[UUID | None]
    currency_reference: Mapped[str | None] = mapped_column(String(3))
    foreign_amount_reference: Mapped[str | None] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(String(2000))


def schedule_constraints(table):
    return (
        household_fk(table, "account_id", "financial_accounts"),
        household_fk(table, "loan_asset_id", "assets"),
        CheckConstraint("loan_asset_id IS NULL OR economic_type = 'loan'", name="loan_reference"),
        household_fk(table, "card_id", "cards"),
        CheckConstraint("account_id IS NULL OR card_id IS NULL", name="one_payment_method"),
        CheckConstraint("amount_mode IN ('fixed', 'variable')", name="amount_mode"),
        CheckConstraint(
            "amount_mode <> 'fixed' OR expected_amount_krw IS NOT NULL", name="fixed_amount"
        ),
        CheckConstraint(
            "expected_amount_krw IS NULL OR expected_amount_krw >= 0", name="nonnegative_expected"
        ),
        CheckConstraint(
            "economic_type IN ('expense', 'loan', 'asset_transfer')", name="economic_type"
        ),
        CheckConstraint(
            "(currency_reference IS NULL) = (foreign_amount_reference IS NULL)",
            name="foreign_reference_pair",
        ),
        CheckConstraint("char_length(btrim(title)) > 0", name="nonempty_title"),
    )


class RecurringRuleVersion(ScheduleFields, Base):
    __tablename__ = "recurring_rule_versions"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint(
            "household_id", "rule_id", "id", name="uq_rule_versions_household_rule_id"
        ),
        UniqueConstraint(
            "household_id",
            "rule_id",
            "effective_from",
            name="uq_rule_versions_household_rule_start",
        ),
        household_fk("recurring_rule_versions", "rule_id", "recurring_rules"),
        *schedule_constraints("recurring_rule_versions"),
        CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from", name="positive_period"
        ),
        CheckConstraint("frequency IN ('monthly', 'annual', 'days')", name="frequency"),
        CheckConstraint("interval_count BETWEEN 1 AND 3650", name="positive_interval"),
        ExcludeConstraint(
            ("household_id", "="),
            ("rule_id", "="),
            (text("daterange(effective_from, effective_until, '[)')"), "&&"),
            name="ex_recurring_rule_versions_period",
            using="gist",
            ops={"household_id": "public.gist_uuid_ops", "rule_id": "public.gist_uuid_ops"},
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    household_id: Mapped[UUID]
    rule_id: Mapped[UUID]
    effective_from: Mapped[date]
    effective_until: Mapped[date | None]
    anchor_date: Mapped[date]
    frequency: Mapped[str] = mapped_column(String(8))
    interval_count: Mapped[int]
    reason: Mapped[str | None] = mapped_column(String(500))


class ObligationFields(ScheduleFields):
    household_id: Mapped[UUID]
    rule_id: Mapped[UUID]
    rule_version_id: Mapped[UUID]
    nominal_date: Mapped[date]
    scheduled_date: Mapped[date]
    schedule_state: Mapped[str] = mapped_column(String(12), default="active")
    manual_override: Mapped[bool] = mapped_column(default=False)
    skipped: Mapped[bool] = mapped_column(default=False)
    manually_completed: Mapped[bool] = mapped_column(default=False)


def obligation_constraints(table):
    return (
        *schedule_constraints(table),
        ForeignKeyConstraint(
            ["household_id", "rule_id", "rule_version_id"],
            [
                "recurring_rule_versions.household_id",
                "recurring_rule_versions.rule_id",
                "recurring_rule_versions.id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("schedule_state IN ('active', 'superseded')", name="schedule_state"),
        CheckConstraint("NOT (skipped AND manually_completed)", name="exclusive_status"),
        CheckConstraint("version > 0", name="positive_version"),
    )


class ScheduledObligation(ObligationFields, EntityMixin, Base):
    __tablename__ = "scheduled_obligations"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint(
            "household_id",
            "rule_id",
            "nominal_date",
            name="uq_obligations_household_rule_occurrence",
        ),
        *obligation_constraints("scheduled_obligations"),
        Index("ix_obligations_household_scheduled", "household_id", "scheduled_date", "id"),
    )


class ObligationRevision(ObligationFields, Base):
    __tablename__ = "obligation_revisions"
    __table_args__ = (
        UniqueConstraint("household_id", "obligation_id", "version"),
        household_fk("obligation_revisions", "obligation_id", "scheduled_obligations"),
        *obligation_constraints("obligation_revisions"),
        CheckConstraint(
            "action IN ('create', 'regenerate', 'reschedule', 'skip', 'unskip', "
            "'complete', 'reopen', 'settle', 'void_settlement')",
            name="action",
        ),
    )
    obligation_id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    action: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FixedSettlement(Base):
    __tablename__ = "fixed_settlements"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("cash_record_id"),
        household_fk("fixed_settlements", "obligation_id", "scheduled_obligations"),
        household_fk("fixed_settlements", "cash_record_id", "cash_records"),
        CheckConstraint(
            "economic_type IN ('expense', 'loan', 'asset_transfer')", name="economic_type"
        ),
        CheckConstraint(
            "principal_krw >= 0 AND consumption_krw >= 0 AND asset_transfer_krw >= 0",
            name="nonnegative_breakdown",
        ),
        CheckConstraint(
            "(economic_type = 'loan' AND asset_transfer_krw = 0) OR "
            "(economic_type = 'expense' AND principal_krw = 0 AND asset_transfer_krw = 0) OR "
            "(economic_type = 'asset_transfer' AND principal_krw = 0 AND consumption_krw = 0)",
            name="breakdown_type",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID]
    obligation_id: Mapped[UUID]
    cash_record_id: Mapped[UUID]
    economic_type: Mapped[str] = mapped_column(String(16))
    principal_krw: Mapped[Decimal] = mapped_column(KrwNumeric())
    consumption_krw: Mapped[Decimal] = mapped_column(KrwNumeric())
    asset_transfer_krw: Mapped[Decimal] = mapped_column(KrwNumeric())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ObligationGeneration(Base):
    __tablename__ = "obligation_generations"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        household_fk("obligation_generations", "created_by_member_id", "household_members"),
        household_fk("obligation_generations", "rule_id", "recurring_rules"),
        CheckConstraint("end_date >= start_date", name="date_order"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID]
    created_by_member_id: Mapped[UUID]
    rule_id: Mapped[UUID | None]
    start_date: Mapped[date]
    end_date: Mapped[date]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ObligationGenerationItem(Base):
    __tablename__ = "obligation_generation_items"
    __table_args__ = (
        household_fk("obligation_generation_items", "generation_id", "obligation_generations"),
        ForeignKeyConstraint(
            ["household_id", "obligation_id", "obligation_version"],
            [
                "obligation_revisions.household_id",
                "obligation_revisions.obligation_id",
                "obligation_revisions.version",
            ],
            ondelete="RESTRICT",
        ),
    )
    generation_id: Mapped[UUID] = mapped_column(primary_key=True)
    obligation_id: Mapped[UUID] = mapped_column(primary_key=True)
    household_id: Mapped[UUID]
    obligation_version: Mapped[int] = mapped_column(BigInteger)
