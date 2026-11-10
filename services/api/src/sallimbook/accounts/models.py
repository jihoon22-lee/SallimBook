"""One account per financial asset; ownership, closure and amounts belong to the asset."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin
from sallimbook.core.types import KrwNumeric


class FinancialAccount(EntityMixin, Base):
    __tablename__ = "financial_accounts"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("asset_id"),
        ForeignKeyConstraint(
            ["household_id", "asset_id"], ["assets.household_id", "assets.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
            name="fk_accounts_household_created_by_member",
        ),
        ForeignKeyConstraint(
            ["household_id", "updated_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
            name="fk_accounts_household_updated_by_member",
        ),
        CheckConstraint(
            "account_type IN ('checking', 'savings', 'term_deposit', 'brokerage', "
            "'pension_savings', 'irp', 'dc_pension', 'isa', 'cma', 'other')",
            name="valid_type",
        ),
        CheckConstraint("char_length(btrim(institution_name)) > 0", name="nonempty_institution"),
        CheckConstraint(
            "(account_number_ciphertext IS NULL AND number_nonce IS NULL "
            "AND number_key_version IS NULL AND last_four IS NULL) OR "
            "(account_number_ciphertext IS NOT NULL AND number_nonce IS NOT NULL "
            "AND number_key_version IS NOT NULL AND last_four IS NOT NULL "
            "AND octet_length(account_number_ciphertext) BETWEEN 21 AND 80 "
            "AND octet_length(number_nonce) = 12 AND number_key_version > 0 "
            "AND last_four ~ '^[a-zA-Z0-9]{4}$')",
            name="valid_number_envelope",
        ),
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint(
            "(contributed_krw IS NULL AND contributed_as_of IS NULL) "
            "OR (contributed_krw IS NOT NULL AND contributed_krw >= 0)",
            name="contribution",
        ),
        Index("ix_financial_accounts_household_type_id", "household_id", "account_type", "id"),
    )

    household_id: Mapped[UUID]
    asset_id: Mapped[UUID]
    institution_name: Mapped[str] = mapped_column(String(120))
    account_type: Mapped[str] = mapped_column(String(24))
    account_number_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    number_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    number_key_version: Mapped[int | None]
    last_four: Mapped[str | None] = mapped_column(String(4))
    purpose: Mapped[str | None] = mapped_column(String(500))
    opened_on: Mapped[date | None]
    # Money the household put in so far, entered by hand; never derived from records.
    contributed_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    contributed_as_of: Mapped[date | None]
    created_by_member_id: Mapped[UUID]
    updated_by_member_id: Mapped[UUID]
