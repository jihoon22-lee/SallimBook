"""add protected financial accounts

Revision ID: 0005_accounts
Revises: 0004_assets
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_accounts"
down_revision = "0004_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "financial_accounts",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("institution_name", sa.String(length=120), nullable=False),
        sa.Column("account_type", sa.String(length=24), nullable=False),
        sa.Column("account_number_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("number_nonce", sa.LargeBinary(), nullable=True),
        sa.Column("number_key_version", sa.Integer(), nullable=True),
        sa.Column("last_four", sa.String(length=4), nullable=True),
        sa.Column("purpose", sa.String(length=500), nullable=True),
        sa.Column("opened_on", sa.Date(), nullable=True),
        sa.Column("created_by_member_id", sa.Uuid(), nullable=False),
        sa.Column("updated_by_member_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "(account_number_ciphertext IS NULL AND number_nonce IS NULL "
            "AND number_key_version IS NULL AND last_four IS NULL) OR "
            "(account_number_ciphertext IS NOT NULL AND number_nonce IS NOT NULL "
            "AND number_key_version IS NOT NULL AND last_four IS NOT NULL "
            "AND octet_length(account_number_ciphertext) BETWEEN 21 AND 80 "
            "AND octet_length(number_nonce) = 12 AND number_key_version > 0 "
            "AND last_four ~ '^[a-zA-Z0-9]{4}$')",
            name=op.f("ck_financial_accounts_valid_number_envelope"),
        ),
        sa.CheckConstraint(
            "account_type IN ('checking', 'savings', 'term_deposit', 'brokerage', "
            "'pension_savings', 'irp', 'dc_pension', 'isa', 'cma', 'other')",
            name=op.f("ck_financial_accounts_valid_type"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(institution_name)) > 0",
            name=op.f("ck_financial_accounts_nonempty_institution"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_financial_accounts_positive_version")),
        sa.ForeignKeyConstraint(
            ["household_id", "asset_id"],
            ["assets.household_id", "assets.id"],
            name=op.f("fk_financial_accounts_household_id_assets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_accounts_household_created_by_member",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "updated_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_accounts_household_updated_by_member",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_accounts")),
        sa.UniqueConstraint("asset_id", name=op.f("uq_financial_accounts_asset_id")),
        sa.UniqueConstraint("household_id", "id", name=op.f("uq_financial_accounts_household_id")),
    )
    op.create_index(
        "ix_financial_accounts_household_type_id",
        "financial_accounts",
        ["household_id", "account_type", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_financial_accounts_household_type_id", table_name="financial_accounts")
    op.drop_table("financial_accounts")
