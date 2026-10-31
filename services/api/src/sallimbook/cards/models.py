"""Household card metadata; secrets belong only to separate encrypted vault envelopes."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin
from sallimbook.core.types import KrwNumeric


class Card(EntityMixin, Base):
    __tablename__ = "cards"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        ForeignKeyConstraint(
            ["household_id", "owner_member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
            name="fk_cards_household_owner",
        ),
        ForeignKeyConstraint(
            ["household_id", "settlement_account_id"],
            ["financial_accounts.household_id", "financial_accounts.id"],
            ondelete="RESTRICT",
            name="fk_cards_household_settlement_account",
        ),
        ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
            name="fk_cards_household_created_by",
        ),
        ForeignKeyConstraint(
            ["household_id", "updated_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
            name="fk_cards_household_updated_by",
        ),
        CheckConstraint("card_type IN ('credit', 'debit')", name="valid_type"),
        CheckConstraint("char_length(btrim(issuer_name)) > 0", name="nonempty_issuer"),
        CheckConstraint("char_length(btrim(product_name)) > 0", name="nonempty_product"),
        CheckConstraint("last_four IS NULL OR last_four ~ '^[0-9]{4}$'", name="last_four"),
        CheckConstraint(
            "settlement_day IS NULL OR settlement_day BETWEEN 1 AND 31", name="settlement_day"
        ),
        CheckConstraint(
            "started_on IS NULL OR ended_on IS NULL OR started_on <= ended_on", name="valid_dates"
        ),
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint(
            "annual_fee_krw IS NULL OR annual_fee_krw >= 0", name="annual_fee_nonnegative"
        ),
        Index("ix_cards_household_owner_id", "household_id", "owner_member_id", "id"),
        Index("ix_cards_household_settlement_account", "household_id", "settlement_account_id"),
    )
    household_id: Mapped[UUID]
    annual_fee_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    is_family_card: Mapped[bool | None]
    owner_member_id: Mapped[UUID]
    issuer_name: Mapped[str] = mapped_column(String(120))
    product_name: Mapped[str] = mapped_column(String(120))
    alias: Mapped[str | None] = mapped_column(String(80))
    card_type: Mapped[str] = mapped_column(String(8))
    last_four: Mapped[str | None] = mapped_column(String(4))
    settlement_day: Mapped[int | None]
    settlement_account_id: Mapped[UUID | None]
    started_on: Mapped[date | None]
    ended_on: Mapped[date | None]
    note: Mapped[str | None] = mapped_column(String(500))
    created_by_member_id: Mapped[UUID]
    updated_by_member_id: Mapped[UUID]
