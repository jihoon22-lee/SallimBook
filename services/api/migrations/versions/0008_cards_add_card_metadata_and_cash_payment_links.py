"""add card metadata and cash payment links

Revision ID: 0008_cards
Revises: 0007_cash_records
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_cards"
down_revision = "0007_cash_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cards",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("owner_member_id", sa.Uuid(), nullable=False),
        sa.Column("issuer_name", sa.String(length=120), nullable=False),
        sa.Column("product_name", sa.String(length=120), nullable=False),
        sa.Column("alias", sa.String(length=80), nullable=True),
        sa.Column("card_type", sa.String(length=8), nullable=False),
        sa.Column("last_four", sa.String(length=4), nullable=True),
        sa.Column("settlement_day", sa.Integer(), nullable=True),
        sa.Column("settlement_account_id", sa.Uuid(), nullable=True),
        sa.Column("started_on", sa.Date(), nullable=True),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
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
        sa.CheckConstraint("card_type IN ('credit', 'debit')", name=op.f("ck_cards_valid_type")),
        sa.CheckConstraint(
            "last_four IS NULL OR last_four ~ '^[0-9]{4}$'", name=op.f("ck_cards_last_four")
        ),
        sa.CheckConstraint(
            "char_length(btrim(issuer_name)) > 0", name=op.f("ck_cards_nonempty_issuer")
        ),
        sa.CheckConstraint(
            "char_length(btrim(product_name)) > 0", name=op.f("ck_cards_nonempty_product")
        ),
        sa.CheckConstraint(
            "settlement_day IS NULL OR settlement_day BETWEEN 1 AND 31",
            name=op.f("ck_cards_settlement_day"),
        ),
        sa.CheckConstraint(
            "started_on IS NULL OR ended_on IS NULL OR started_on <= ended_on",
            name=op.f("ck_cards_valid_dates"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_cards_positive_version")),
        sa.ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_cards_household_created_by",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "owner_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_cards_household_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "settlement_account_id"],
            ["financial_accounts.household_id", "financial_accounts.id"],
            name="fk_cards_household_settlement_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "updated_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_cards_household_updated_by",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cards")),
        sa.UniqueConstraint("household_id", "id", name=op.f("uq_cards_household_id")),
    )
    op.create_index(
        "ix_cards_household_owner_id",
        "cards",
        ["household_id", "owner_member_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_cards_household_settlement_account",
        "cards",
        ["household_id", "settlement_account_id"],
        unique=False,
    )
    op.add_column("cash_record_revisions", sa.Column("card_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_cash_record_revisions_household_card",
        "cash_record_revisions",
        "cards",
        ["household_id", "card_id"],
        ["household_id", "id"],
        ondelete="RESTRICT",
    )
    op.add_column("cash_records", sa.Column("card_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_cash_records_household_card",
        "cash_records",
        "cards",
        ["household_id", "card_id"],
        ["household_id", "id"],
        ondelete="RESTRICT",
    )

    for table in ("cash_records", "cash_record_revisions"):
        op.create_check_constraint(
            op.f(f"ck_{table}_one_payment_method"), table, "account_id IS NULL OR card_id IS NULL"
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_income_not_card"),
            table,
            "kind NOT IN ('salary', 'bonus', 'other_income', 'income_return', "
            "'insurance_receipt', 'insurance_return') OR card_id IS NULL",
        )


def downgrade() -> None:
    for table in ("cash_records", "cash_record_revisions"):
        op.drop_constraint(op.f(f"ck_{table}_one_payment_method"), table, type_="check")
        op.drop_constraint(op.f(f"ck_{table}_income_not_card"), table, type_="check")
    op.drop_constraint("fk_cash_records_household_card", "cash_records", type_="foreignkey")
    op.drop_column("cash_records", "card_id")
    op.drop_constraint(
        "fk_cash_record_revisions_household_card", "cash_record_revisions", type_="foreignkey"
    )
    op.drop_column("cash_record_revisions", "card_id")
    op.drop_index("ix_cards_household_settlement_account", table_name="cards")
    op.drop_index("ix_cards_household_owner_id", table_name="cards")
    op.drop_table("cards")
