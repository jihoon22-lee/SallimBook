"""Minimal bootstrap provenance, without copies of private source payloads."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.cashflow.recurring_models import household_fk
from sallimbook.core.database import Base


class ExpenseImportBatch(Base):
    __tablename__ = "expense_import_batches"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("household_id", "source_id", name="uq_expense_import_batches_source"),
        household_fk("expense_import_batches", "actor_member_id", "household_members"),
        CheckConstraint("row_count > 0", name="row_count"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID]
    source_id: Mapped[str] = mapped_column(String(100))
    manifest_hash: Mapped[str] = mapped_column(String(64))
    actor_member_id: Mapped[UUID]
    baseline_date: Mapped[date]
    row_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExpenseImportRow(Base):
    __tablename__ = "expense_import_rows"
    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "source_id"],
            ["expense_import_batches.household_id", "expense_import_batches.source_id"],
            ondelete="RESTRICT",
        ),
        household_fk("expense_import_rows", "rule_id", "recurring_rules"),
        CheckConstraint(
            "(state = 'linked' AND rule_id IS NOT NULL AND rule_id = created_rule_id) "
            "OR (state = 'user_deleted' AND rule_id IS NULL)",
            name="state",
        ),
    )
    household_id: Mapped[UUID] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_rule_id: Mapped[UUID]
    rule_id: Mapped[UUID | None]
    state: Mapped[str] = mapped_column(String(16))
