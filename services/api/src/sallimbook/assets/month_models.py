"""Revisioned month-end observations, separate from transaction and account metadata."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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
from sallimbook.core.types import KrwNumeric


class AssetMonthRecord(EntityMixin, Base):
    __tablename__ = "asset_months"
    __table_args__ = (
        UniqueConstraint("household_id", "id", name="uq_asset_months_household_identity"),
        UniqueConstraint("household_id", "period_month", name="uq_asset_months_household_period"),
        ForeignKeyConstraint(
            ["household_id", "id", "current_revision_id"],
            [
                "asset_month_revisions.household_id",
                "asset_month_revisions.month_id",
                "asset_month_revisions.id",
            ],
            name="fk_asset_months_current_revision",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
            ondelete="NO ACTION",
        ),
        CheckConstraint("extract(day from period_month) = 1", name="first_day"),
        CheckConstraint("version > 0", name="positive_version"),
    )

    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id", ondelete="RESTRICT"))
    period_month: Mapped[date]
    current_revision_id: Mapped[UUID | None]


class AssetMonthRevision(EntityMixin, Base):
    __tablename__ = "asset_month_revisions"
    __table_args__ = (
        UniqueConstraint("household_id", "id", name="uq_asset_month_revisions_household_identity"),
        UniqueConstraint(
            "household_id", "month_id", "id", name="uq_asset_month_revisions_month_identity"
        ),
        UniqueConstraint("month_id", "revision_no", name="uq_asset_month_revisions_number"),
        ForeignKeyConstraint(
            ["household_id", "month_id"],
            ["asset_months.household_id", "asset_months.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["household_id", "month_id", "previous_revision_id"],
            [
                "asset_month_revisions.household_id",
                "asset_month_revisions.month_id",
                "asset_month_revisions.id",
            ],
            name="fk_asset_month_revisions_previous",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_asset_month_revisions_creator",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["household_id", "confirmed_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_asset_month_revisions_confirmer",
            ondelete="RESTRICT",
        ),
        CheckConstraint("state IN ('draft', 'reopened', 'confirmed')", name="valid_state"),
        CheckConstraint(
            "(revision_no = 1 AND previous_revision_id IS NULL AND reopened_reason IS NULL) "
            "OR (revision_no > 1 AND previous_revision_id IS NOT NULL "
            "AND reopened_reason IS NOT NULL AND char_length(btrim(reopened_reason)) > 0)",
            name="revision_history",
        ),
        CheckConstraint(
            "(state = 'confirmed' AND confirmed_at IS NOT NULL "
            "AND confirmed_by_member_id IS NOT NULL) OR (state <> 'confirmed' "
            "AND confirmed_at IS NULL AND confirmed_by_member_id IS NULL)",
            name="confirmation_metadata",
        ),
        CheckConstraint("version > 0", name="positive_version"),
    )

    household_id: Mapped[UUID]
    month_id: Mapped[UUID]
    revision_no: Mapped[int]
    state: Mapped[str] = mapped_column(String(16))
    previous_revision_id: Mapped[UUID | None]
    reopened_reason: Mapped[str | None] = mapped_column(String(1000))
    created_by_member_id: Mapped[UUID]
    confirmed_by_member_id: Mapped[UUID | None]
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssetMonthValue(EntityMixin, Base):
    __tablename__ = "asset_values"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("revision_id", "asset_id"),
        ForeignKeyConstraint(
            ["household_id", "revision_id"],
            ["asset_month_revisions.household_id", "asset_month_revisions.id"],
            name="fk_asset_values_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["household_id", "origin_revision_id"],
            ["asset_month_revisions.household_id", "asset_month_revisions.id"],
            name="fk_asset_values_origin_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["household_id", "asset_id"],
            ["assets.household_id", "assets.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["household_id", "owner_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_asset_values_owner",
            ondelete="RESTRICT",
        ),
        CheckConstraint("kind IN ('asset', 'liability')", name="valid_kind"),
        CheckConstraint("amount_basis IN ('whole', 'owned')", name="valid_amount_basis"),
        CheckConstraint("inclusion_status IN ('included', 'excluded')", name="valid_inclusion"),
        CheckConstraint(
            "household_share >= 0 AND household_share <= 1 AND scale(household_share) <= 18",
            name="valid_household_share",
        ),
        CheckConstraint(
            "(ownership_kind = 'individual' AND owner_member_id IS NOT NULL) OR "
            "(ownership_kind = 'joint' AND owner_member_id IS NULL)",
            name="owner_matches_ownership",
        ),
        CheckConstraint(
            "(input_amount_krw IS NULL) = (owned_amount_krw IS NULL) AND "
            "(input_amount_krw IS NULL OR (input_amount_krw >= 0 AND owned_amount_krw >= 0))",
            name="valid_amounts",
        ),
        CheckConstraint(
            "(verification_state = 'missing' AND input_amount_krw IS NULL) OR "
            "(verification_state = 'carried_unconfirmed' AND input_amount_krw IS NOT NULL) OR "
            "(verification_state = 'verified' AND input_amount_krw IS NOT NULL "
            "AND as_of_date IS NOT NULL)",
            name="valid_verification",
        ),
        CheckConstraint("origin IN ('manual', 'carried')", name="valid_origin"),
        CheckConstraint("source_asset_version > 0 AND version > 0", name="positive_versions"),
        CheckConstraint("ended_on IS NULL OR ended_on >= started_on", name="valid_dates"),
        Index(
            "ix_asset_values_household_asset_revision", "household_id", "asset_id", "revision_id"
        ),
    )

    household_id: Mapped[UUID]
    revision_id: Mapped[UUID]
    asset_id: Mapped[UUID]
    source_asset_version: Mapped[int] = mapped_column(BigInteger)
    # These fields are the historical observation's scope, not live asset joins.
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(24))
    ownership_kind: Mapped[str] = mapped_column(String(16))
    owner_member_id: Mapped[UUID | None]
    household_share: Mapped[Decimal] = mapped_column(Numeric())
    amount_basis: Mapped[str] = mapped_column(String(16))
    inclusion_status: Mapped[str] = mapped_column(String(16))
    started_on: Mapped[date]
    ended_on: Mapped[date | None]
    input_amount_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    owned_amount_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    as_of_date: Mapped[date | None]
    verification_state: Mapped[str] = mapped_column(String(24))
    origin: Mapped[str] = mapped_column(String(16))
    origin_revision_id: Mapped[UUID | None]
    change_reason: Mapped[str | None] = mapped_column(String(1000))
