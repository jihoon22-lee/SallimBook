"""Household asset identity; valuations live in monthly snapshots added by SB-012."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin


class Asset(EntityMixin, Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        ForeignKeyConstraint(
            ["household_id", "owner_member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
            name="fk_assets_household_owner_member",
        ),
        ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
            name="fk_assets_household_created_by_member",
        ),
        ForeignKeyConstraint(
            ["household_id", "updated_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
            name="fk_assets_household_updated_by_member",
        ),
        CheckConstraint("kind IN ('asset', 'liability')", name="valid_kind"),
        CheckConstraint(
            "category IN ('real_estate', 'deposit', 'financial', 'loan', 'other')",
            name="valid_category",
        ),
        CheckConstraint("char_length(btrim(name)) > 0", name="nonempty_name"),
        CheckConstraint("ownership_kind IN ('individual', 'joint')", name="valid_ownership"),
        CheckConstraint(
            "(ownership_kind = 'individual' AND owner_member_id IS NOT NULL) OR "
            "(ownership_kind = 'joint' AND owner_member_id IS NULL)",
            name="owner_matches_ownership",
        ),
        CheckConstraint(
            "household_share >= 0 AND household_share <= 1 AND scale(household_share) <= 18",
            name="valid_household_share",
        ),
        CheckConstraint("amount_basis IN ('whole', 'owned')", name="valid_amount_basis"),
        CheckConstraint("inclusion_status IN ('included', 'excluded')", name="valid_inclusion"),
        CheckConstraint("ended_on IS NULL OR ended_on >= started_on", name="valid_dates"),
        CheckConstraint("(ended_on IS NULL) = (archived_at IS NULL)", name="archive_matches_end"),
        CheckConstraint("version > 0", name="positive_version"),
        Index("ix_assets_household_archived_id", "household_id", "archived_at", "id"),
    )

    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(120))
    owner_member_id: Mapped[UUID | None]
    ownership_kind: Mapped[str] = mapped_column(String(16))
    # Unconstrained numeric plus a scale CHECK rejects excess precision instead of rounding it.
    household_share: Mapped[Decimal] = mapped_column(Numeric())
    amount_basis: Mapped[str] = mapped_column(String(16))
    inclusion_status: Mapped[str] = mapped_column(String(16))
    started_on: Mapped[date]
    ended_on: Mapped[date | None]
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(2000))
    created_by_member_id: Mapped[UUID]
    updated_by_member_id: Mapped[UUID]
