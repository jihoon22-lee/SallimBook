"""Separate facts for forecasts and compensation; amounts never mutate asset snapshots."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin
from sallimbook.core.types import KrwNumeric


def constraints(table):
    return (
        UniqueConstraint("household_id", "id"),
        *(
            ForeignKeyConstraint(
                ["household_id", name],
                ["household_members.household_id", "household_members.id"],
                ondelete="RESTRICT",
                name=f"fk_{table}_{name}",
            )
            for name in ("member_id", "created_by_member_id", "updated_by_member_id")
        ),
        CheckConstraint("version > 0", name="positive_version"),
    )


class PlanningFields:
    household_id: Mapped[UUID]
    member_id: Mapped[UUID]
    active: Mapped[bool]
    note: Mapped[str | None] = mapped_column(String(2000))
    created_by_member_id: Mapped[UUID]
    updated_by_member_id: Mapped[UUID]


class ExpectedIncome(PlanningFields, EntityMixin, Base):
    __tablename__ = "expected_incomes"
    __table_args__ = (
        *constraints("expected_incomes"),
        UniqueConstraint(
            "household_id", "member_id", "label", name="uq_expected_incomes_member_label"
        ),
        CheckConstraint("amount_krw IS NULL OR amount_krw >= 0", name="nonnegative_amount"),
        CheckConstraint("char_length(btrim(label)) > 0", name="nonempty_label"),
    )
    label: Mapped[str] = mapped_column(String(120))
    amount_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())


class BonusAward(PlanningFields, EntityMixin, Base):
    __tablename__ = "bonus_awards"
    __table_args__ = (
        *constraints("bonus_awards"),
        UniqueConstraint(
            "household_id",
            "member_id",
            "performance_year",
            "award_kind",
            name="uq_bonus_awards_member_year_kind",
        ),
        UniqueConstraint("household_id", "cash_record_id", name="uq_bonus_awards_cash"),
        ForeignKeyConstraint(
            ["household_id", "cash_record_id"],
            ["cash_records.household_id", "cash_records.id"],
            ondelete="RESTRICT",
            name="fk_bonus_awards_cash",
        ),
        CheckConstraint("performance_year BETWEEN 1900 AND 9998", name="valid_year"),
        CheckConstraint("award_kind IN ('tai_h1', 'tai_h2', 'opi')", name="valid_kind"),
        CheckConstraint(
            "payment_month IS NULL OR EXTRACT(DAY FROM payment_month) = 1", name="month_start"
        ),
        CheckConstraint(
            "NOT received OR (payment_month IS NOT NULL AND net_cash_krw IS NOT NULL)",
            name="known_receipt",
        ),
        CheckConstraint(
            "(active AND received AND net_cash_krw > 0) = (cash_record_id IS NOT "
            "NULL) OR (net_cash_krw IS NULL AND cash_record_id IS NULL)",
            name="cash_link",
        ),
        CheckConstraint(
            "payout_rate_percent IS NULL OR payout_rate_percent ~ "
            "'^(0|[1-9][0-9]{0,4})([.][0-9]{1,2})?$'",
            name="valid_rate",
        ),
        *(
            CheckConstraint(f"{name} IS NULL OR {name} >= 0", name=f"nonnegative_{name}")
            for name in ("gross_krw", "net_cash_krw", "stock_grant_value_krw")
        ),
    )
    performance_year: Mapped[int]
    award_kind: Mapped[str] = mapped_column(String(10))
    payment_month: Mapped[date | None]
    gross_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    net_cash_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    stock_grant_value_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    payout_rate_percent: Mapped[str | None] = mapped_column(String(8))
    received: Mapped[bool]
    cash_record_id: Mapped[UUID | None]


class IncomePlanningRevision(Base):
    __tablename__ = "income_planning_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "actor_member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("kind IN ('expected', 'bonus')", name="valid_kind"),
        CheckConstraint("version > 0", name="positive_version"),
    )
    household_id: Mapped[UUID] = mapped_column(primary_key=True)
    resource_id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    actor_member_id: Mapped[UUID]
    reason: Mapped[str | None] = mapped_column(String(500))
    # Validated response snapshot; exact decimal strings, no floats or arbitrary requests.
    snapshot: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
