"""Limited cash facts and typed immutable revisions; never an account balance ledger."""

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
)
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin
from sallimbook.core.types import KrwNumeric

KINDS = (
    "salary",
    "bonus",
    "other_income",
    "income_return",
    "fixed_payment",
    "medical_payment",
    "medical_refund",
    "insurance_receipt",
    "insurance_return",
)
INCOME_KINDS = ("salary", "bonus", "other_income")
PROJECTED_INCOME_KINDS = (*INCOME_KINDS, "income_return", "insurance_receipt", "insurance_return")
FLOWS = {
    "salary": "in",
    "bonus": "in",
    "other_income": "in",
    "income_return": "out",
    "fixed_payment": "out",
    "medical_payment": "out",
    "medical_refund": "in",
    "insurance_receipt": "in",
    "insurance_return": "out",
}
REVERSED_KINDS = {
    "income_return": INCOME_KINDS,
    "medical_refund": ("medical_payment",),
    "insurance_return": ("insurance_receipt",),
}


def _cash_constraints(table: str):
    return (
        ForeignKeyConstraint(
            ["household_id", "member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
            name=f"fk_{table}_household_member",
        ),
        ForeignKeyConstraint(
            ["household_id", "account_id"],
            ["financial_accounts.household_id", "financial_accounts.id"],
            ondelete="RESTRICT",
            name=f"fk_{table}_household_account",
        ),
        ForeignKeyConstraint(
            ["household_id", "card_id"],
            ["cards.household_id", "cards.id"],
            ondelete="RESTRICT",
            name=f"fk_{table}_household_card",
        ),
        ForeignKeyConstraint(
            ["household_id", "reverses_id"],
            ["cash_records.household_id", "cash_records.id"],
            ondelete="RESTRICT",
            name=f"fk_{table}_household_reverses",
        ),
        ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
            name=f"fk_{table}_household_created_by",
        ),
        ForeignKeyConstraint(
            ["household_id", "updated_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
            name=f"fk_{table}_household_updated_by",
        ),
        CheckConstraint("amount_krw > 0", name="positive_amount"),
        CheckConstraint("account_id IS NULL OR card_id IS NULL", name="one_payment_method"),
        CheckConstraint(
            "kind NOT IN ('salary', 'bonus', 'other_income', 'income_return', "
            "'insurance_receipt', 'insurance_return') OR card_id IS NULL",
            name="income_not_card",
        ),
        CheckConstraint("EXTRACT(DAY FROM period_month) = 1", name="month_start"),
        CheckConstraint(
            "(date_precision = 'month' AND occurred_on IS NULL) OR "
            "(date_precision = 'day' AND occurred_on IS NOT NULL)",
            name="date_precision",
        ),
        CheckConstraint("state IN ('active', 'void')", name="valid_state"),
        CheckConstraint(
            "(kind IN ('salary', 'bonus', 'other_income', 'medical_refund', 'insurance_receipt') "
            "AND flow = 'in') OR (kind IN ('income_return', 'fixed_payment', 'medical_payment', "
            "'insurance_return') AND flow = 'out')",
            name="kind_matches_flow",
        ),
        CheckConstraint(
            "(kind IN ('income_return', 'medical_refund', 'insurance_return')) = "
            "(reverses_id IS NOT NULL)",
            name="reversal_reference",
        ),
        CheckConstraint(
            "kind NOT IN ('salary', 'bonus', 'other_income', 'income_return') "
            "OR member_id IS NOT NULL",
            name="income_member",
        ),
    )


class CashFields:
    household_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(24))
    flow: Mapped[str] = mapped_column(String(3))
    amount_krw: Mapped[Decimal] = mapped_column(KrwNumeric())
    period_month: Mapped[date]
    occurred_on: Mapped[date | None]
    date_precision: Mapped[str] = mapped_column(String(5))
    member_id: Mapped[UUID | None]
    account_id: Mapped[UUID | None]
    card_id: Mapped[UUID | None]
    reverses_id: Mapped[UUID | None]
    state: Mapped[str] = mapped_column(String(8), default="active")
    note: Mapped[str | None] = mapped_column(String(2000))
    created_by_member_id: Mapped[UUID]
    updated_by_member_id: Mapped[UUID]


class CashRecord(CashFields, EntityMixin, Base):
    __tablename__ = "cash_records"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        *_cash_constraints("cash_records"),
        CheckConstraint("reverses_id IS NULL OR reverses_id <> id", name="not_self_reversal"),
        CheckConstraint("version > 0", name="positive_version"),
        Index("ix_cash_records_household_month_id", "household_id", "period_month", "id"),
        Index("ix_cash_records_household_reverses", "household_id", "reverses_id"),
    )


class IncomeConversion(Base):
    __tablename__ = "income_conversions"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("version = 1", name="immutable_version"),
        CheckConstraint("char_length(btrim(reason)) > 0", name="nonempty_reason"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID]
    created_by_member_id: Mapped[UUID]
    reason: Mapped[str] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CashRecordRevision(CashFields, Base):
    """Domain history contains typed amounts; the general audit stores field names only."""

    __tablename__ = "cash_record_revisions"
    __table_args__ = (
        UniqueConstraint("household_id", "cash_record_id", "version"),
        *_cash_constraints("cash_record_revisions"),
        ForeignKeyConstraint(
            ["household_id", "cash_record_id"],
            ["cash_records.household_id", "cash_records.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["household_id", "conversion_id"],
            ["income_conversions.household_id", "income_conversions.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint(
            "action IN ('create', 'correct', 'void', 'convert_source', 'convert_result')",
            name="valid_action",
        ),
        CheckConstraint(
            "(action IN ('convert_source', 'convert_result')) = (conversion_id IS NOT NULL)",
            name="conversion_reference",
        ),
        CheckConstraint(
            "action = 'create' OR (reason IS NOT NULL AND char_length(btrim(reason)) > 0)",
            name="change_reason",
        ),
        Index("ix_cash_record_revisions_conversion", "household_id", "conversion_id"),
    )
    cash_record_id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    action: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(500))
    conversion_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
