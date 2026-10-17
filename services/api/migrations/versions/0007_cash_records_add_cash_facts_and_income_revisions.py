"""add limited cash facts and income revisions

Revision ID: 0007_cash_records
Revises: 0006_asset_months
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_cash_records"
down_revision = "0006_asset_months"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "income_conversions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_member_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(btrim(reason)) > 0", name=op.f("ck_income_conversions_nonempty_reason")
        ),
        sa.CheckConstraint("version = 1", name=op.f("ck_income_conversions_immutable_version")),
        sa.ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name=op.f("fk_income_conversions_household_id_household_members"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_income_conversions")),
        sa.UniqueConstraint("household_id", "id", name=op.f("uq_income_conversions_household_id")),
    )
    op.create_table(
        "cash_records",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("flow", sa.String(length=3), nullable=False),
        sa.Column("amount_krw", sa.Numeric(precision=20, scale=0), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=True),
        sa.Column("date_precision", sa.String(length=5), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("reverses_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=8), nullable=False),
        sa.Column("note", sa.String(length=2000), nullable=True),
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
            "(date_precision = 'month' AND occurred_on IS NULL) OR (date_precision = "
            "'day' AND occurred_on IS NOT NULL)",
            name=op.f("ck_cash_records_date_precision"),
        ),
        sa.CheckConstraint(
            "(kind IN ('income_return', 'medical_refund', 'insurance_return')) = "
            "(reverses_id IS NOT NULL)",
            name=op.f("ck_cash_records_reversal_reference"),
        ),
        sa.CheckConstraint(
            "(kind IN ('salary', 'bonus', 'other_income', 'medical_refund', "
            "'insurance_receipt') AND flow = 'in') OR (kind IN ('income_return', "
            "'fixed_payment', 'medical_payment', 'insurance_return') AND flow = 'out')",
            name=op.f("ck_cash_records_kind_matches_flow"),
        ),
        sa.CheckConstraint(
            "kind NOT IN ('salary', 'bonus', 'other_income', 'income_return') OR "
            "member_id IS NOT NULL",
            name=op.f("ck_cash_records_income_member"),
        ),
        sa.CheckConstraint("state IN ('active', 'void')", name=op.f("ck_cash_records_valid_state")),
        sa.CheckConstraint(
            "EXTRACT(DAY FROM period_month) = 1", name=op.f("ck_cash_records_month_start")
        ),
        sa.CheckConstraint("amount_krw > 0", name=op.f("ck_cash_records_positive_amount")),
        sa.CheckConstraint(
            "reverses_id IS NULL OR reverses_id <> id",
            name=op.f("ck_cash_records_not_self_reversal"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_cash_records_positive_version")),
        sa.ForeignKeyConstraint(
            ["household_id", "account_id"],
            ["financial_accounts.household_id", "financial_accounts.id"],
            name="fk_cash_records_household_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_cash_records_household_created_by",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_cash_records_household_member",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "reverses_id"],
            ["cash_records.household_id", "cash_records.id"],
            name="fk_cash_records_household_reverses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "updated_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_cash_records_household_updated_by",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cash_records")),
        sa.UniqueConstraint("household_id", "id", name=op.f("uq_cash_records_household_id")),
    )
    op.create_index(
        "ix_cash_records_household_month_id",
        "cash_records",
        ["household_id", "period_month", "id"],
        unique=False,
    )
    op.create_index(
        "ix_cash_records_household_reverses",
        "cash_records",
        ["household_id", "reverses_id"],
        unique=False,
    )
    op.create_table(
        "cash_record_revisions",
        sa.Column("cash_record_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("conversion_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("flow", sa.String(length=3), nullable=False),
        sa.Column("amount_krw", sa.Numeric(precision=20, scale=0), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=True),
        sa.Column("date_precision", sa.String(length=5), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("reverses_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=8), nullable=False),
        sa.Column("note", sa.String(length=2000), nullable=True),
        sa.Column("created_by_member_id", sa.Uuid(), nullable=False),
        sa.Column("updated_by_member_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(action IN ('convert_source', 'convert_result')) = (conversion_id IS NOT NULL)",
            name=op.f("ck_cash_record_revisions_conversion_reference"),
        ),
        sa.CheckConstraint(
            "(date_precision = 'month' AND occurred_on IS NULL) OR (date_precision = "
            "'day' AND occurred_on IS NOT NULL)",
            name=op.f("ck_cash_record_revisions_date_precision"),
        ),
        sa.CheckConstraint(
            "(kind IN ('income_return', 'medical_refund', 'insurance_return')) = "
            "(reverses_id IS NOT NULL)",
            name=op.f("ck_cash_record_revisions_reversal_reference"),
        ),
        sa.CheckConstraint(
            "(kind IN ('salary', 'bonus', 'other_income', 'medical_refund', "
            "'insurance_receipt') AND flow = 'in') OR (kind IN ('income_return', "
            "'fixed_payment', 'medical_payment', 'insurance_return') AND flow = 'out')",
            name=op.f("ck_cash_record_revisions_kind_matches_flow"),
        ),
        sa.CheckConstraint(
            "action = 'create' OR (reason IS NOT NULL AND char_length(btrim(reason)) > 0)",
            name=op.f("ck_cash_record_revisions_change_reason"),
        ),
        sa.CheckConstraint(
            "action IN ('create', 'correct', 'void', 'convert_source', 'convert_result')",
            name=op.f("ck_cash_record_revisions_valid_action"),
        ),
        sa.CheckConstraint(
            "kind NOT IN ('salary', 'bonus', 'other_income', 'income_return') OR "
            "member_id IS NOT NULL",
            name=op.f("ck_cash_record_revisions_income_member"),
        ),
        sa.CheckConstraint(
            "state IN ('active', 'void')", name=op.f("ck_cash_record_revisions_valid_state")
        ),
        sa.CheckConstraint(
            "EXTRACT(DAY FROM period_month) = 1", name=op.f("ck_cash_record_revisions_month_start")
        ),
        sa.CheckConstraint("amount_krw > 0", name=op.f("ck_cash_record_revisions_positive_amount")),
        sa.CheckConstraint("version > 0", name=op.f("ck_cash_record_revisions_positive_version")),
        sa.ForeignKeyConstraint(
            ["household_id", "account_id"],
            ["financial_accounts.household_id", "financial_accounts.id"],
            name="fk_cash_record_revisions_household_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "cash_record_id"],
            ["cash_records.household_id", "cash_records.id"],
            name=op.f("fk_cash_record_revisions_household_id_cash_records"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "conversion_id"],
            ["income_conversions.household_id", "income_conversions.id"],
            name=op.f("fk_cash_record_revisions_household_id_income_conversions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_cash_record_revisions_household_created_by",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_cash_record_revisions_household_member",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "reverses_id"],
            ["cash_records.household_id", "cash_records.id"],
            name="fk_cash_record_revisions_household_reverses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "updated_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_cash_record_revisions_household_updated_by",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("cash_record_id", "version", name=op.f("pk_cash_record_revisions")),
        sa.UniqueConstraint(
            "household_id",
            "cash_record_id",
            "version",
            name=op.f("uq_cash_record_revisions_household_id"),
        ),
    )
    op.create_index(
        "ix_cash_record_revisions_conversion",
        "cash_record_revisions",
        ["household_id", "conversion_id"],
        unique=False,
    )
    op.execute("""
        CREATE FUNCTION protect_cash_history() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Cash history is immutable' USING ERRCODE = '55000';
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER cash_record_revision_immutable
        BEFORE UPDATE OR DELETE ON cash_record_revisions
        FOR EACH ROW EXECUTE FUNCTION protect_cash_history()
    """)
    op.execute("""
        CREATE TRIGGER income_conversion_immutable
        BEFORE UPDATE OR DELETE ON income_conversions
        FOR EACH ROW EXECUTE FUNCTION protect_cash_history()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER cash_record_revision_immutable ON cash_record_revisions")
    op.execute("DROP TRIGGER income_conversion_immutable ON income_conversions")
    op.execute("DROP FUNCTION protect_cash_history()")
    op.drop_index("ix_cash_record_revisions_conversion", table_name="cash_record_revisions")
    op.drop_table("cash_record_revisions")
    op.drop_index("ix_cash_records_household_reverses", table_name="cash_records")
    op.drop_index("ix_cash_records_household_month_id", table_name="cash_records")
    op.drop_table("cash_records")
    op.drop_table("income_conversions")
