"""add recurring rules obligations and fixed settlements

Revision ID: 0009_recurring
Revises: 0008_cards
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_recurring"
down_revision = "0008_cards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL 18.6 bundles btree_gist 1.8, shared outside isolated test schemas.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public VERSION '1.8'")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_extension e JOIN pg_namespace n ON e.extnamespace = n.oid
                WHERE e.extname = 'btree_gist' AND n.nspname = 'public' AND e.extversion = '1.8'
            ) THEN
                RAISE EXCEPTION 'btree_gist 1.8 must be installed in public';
            END IF;
        END $$
    """)
    op.create_table(
        "recurring_rules",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_member_id", sa.Uuid(), nullable=False),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column("end_reason", sa.String(length=500), nullable=True),
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
            "(ended_on IS NULL) = (end_reason IS NULL)", name=op.f("ck_recurring_rules_end_reason")
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_recurring_rules_positive_version")),
        sa.ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_recurring_rules_created_by_member_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recurring_rules")),
        sa.UniqueConstraint("household_id", "id", name=op.f("uq_recurring_rules_household_id")),
    )
    op.create_index(
        "ix_recurring_rules_household_id", "recurring_rules", ["household_id", "id"], unique=False
    )
    op.create_table(
        "obligation_generations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_member_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "end_date >= start_date", name=op.f("ck_obligation_generations_date_order")
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_obligation_generations_created_by_member_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "rule_id"],
            ["recurring_rules.household_id", "recurring_rules.id"],
            name="fk_obligation_generations_rule_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_obligation_generations")),
        sa.UniqueConstraint(
            "household_id", "id", name=op.f("uq_obligation_generations_household_id")
        ),
    )
    op.create_table(
        "recurring_rule_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("frequency", sa.String(length=8), nullable=False),
        sa.Column("interval_count", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("amount_mode", sa.String(length=8), nullable=False),
        sa.Column("expected_amount_krw", sa.Numeric(precision=20, scale=0), nullable=True),
        sa.Column("economic_type", sa.String(length=16), nullable=False),
        sa.Column("loan_asset_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("card_id", sa.Uuid(), nullable=True),
        sa.Column("currency_reference", sa.String(length=3), nullable=True),
        sa.Column("foreign_amount_reference", sa.String(length=40), nullable=True),
        sa.Column("note", sa.String(length=2000), nullable=True),
        postgresql.ExcludeConstraint(
            (sa.column("household_id"), "="),
            (sa.column("rule_id"), "="),
            (sa.text("daterange(effective_from, effective_until, '[)')"), "&&"),
            using="gist",
            name="ex_recurring_rule_versions_period",
            ops={"household_id": "public.gist_uuid_ops", "rule_id": "public.gist_uuid_ops"},
        ),
        sa.CheckConstraint(
            "amount_mode <> 'fixed' OR expected_amount_krw IS NOT NULL",
            name=op.f("ck_recurring_rule_versions_fixed_amount"),
        ),
        sa.CheckConstraint(
            "amount_mode IN ('fixed', 'variable')",
            name=op.f("ck_recurring_rule_versions_amount_mode"),
        ),
        sa.CheckConstraint(
            "economic_type IN ('expense', 'loan', 'asset_transfer')",
            name=op.f("ck_recurring_rule_versions_economic_type"),
        ),
        sa.CheckConstraint(
            "frequency IN ('monthly', 'annual', 'days')",
            name=op.f("ck_recurring_rule_versions_frequency"),
        ),
        sa.CheckConstraint(
            "loan_asset_id IS NULL OR economic_type = 'loan'",
            name=op.f("ck_recurring_rule_versions_loan_reference"),
        ),
        sa.CheckConstraint(
            "(currency_reference IS NULL) = (foreign_amount_reference IS NULL)",
            name=op.f("ck_recurring_rule_versions_foreign_reference_pair"),
        ),
        sa.CheckConstraint(
            "account_id IS NULL OR card_id IS NULL",
            name=op.f("ck_recurring_rule_versions_one_payment_method"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(title)) > 0", name=op.f("ck_recurring_rule_versions_nonempty_title")
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name=op.f("ck_recurring_rule_versions_positive_period"),
        ),
        sa.CheckConstraint(
            "expected_amount_krw IS NULL OR expected_amount_krw >= 0",
            name=op.f("ck_recurring_rule_versions_nonnegative_expected"),
        ),
        sa.CheckConstraint(
            "interval_count BETWEEN 1 AND 3650",
            name=op.f("ck_recurring_rule_versions_positive_interval"),
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "account_id"],
            ["financial_accounts.household_id", "financial_accounts.id"],
            name="fk_recurring_rule_versions_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "card_id"],
            ["cards.household_id", "cards.id"],
            name="fk_recurring_rule_versions_card_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "loan_asset_id"],
            ["assets.household_id", "assets.id"],
            name="fk_recurring_rule_versions_loan_asset_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "rule_id"],
            ["recurring_rules.household_id", "recurring_rules.id"],
            name="fk_recurring_rule_versions_rule_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recurring_rule_versions")),
        sa.UniqueConstraint(
            "household_id", "id", name=op.f("uq_recurring_rule_versions_household_id")
        ),
        sa.UniqueConstraint(
            "household_id",
            "rule_id",
            "effective_from",
            name="uq_rule_versions_household_rule_start",
        ),
        sa.UniqueConstraint(
            "household_id", "rule_id", "id", name="uq_rule_versions_household_rule_id"
        ),
    )
    op.create_table(
        "scheduled_obligations",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("nominal_date", sa.Date(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("schedule_state", sa.String(length=12), nullable=False),
        sa.Column("manual_override", sa.Boolean(), nullable=False),
        sa.Column("skipped", sa.Boolean(), nullable=False),
        sa.Column("manually_completed", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("amount_mode", sa.String(length=8), nullable=False),
        sa.Column("expected_amount_krw", sa.Numeric(precision=20, scale=0), nullable=True),
        sa.Column("economic_type", sa.String(length=16), nullable=False),
        sa.Column("loan_asset_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("card_id", sa.Uuid(), nullable=True),
        sa.Column("currency_reference", sa.String(length=3), nullable=True),
        sa.Column("foreign_amount_reference", sa.String(length=40), nullable=True),
        sa.Column("note", sa.String(length=2000), nullable=True),
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
            "amount_mode <> 'fixed' OR expected_amount_krw IS NOT NULL",
            name=op.f("ck_scheduled_obligations_fixed_amount"),
        ),
        sa.CheckConstraint(
            "amount_mode IN ('fixed', 'variable')",
            name=op.f("ck_scheduled_obligations_amount_mode"),
        ),
        sa.CheckConstraint(
            "economic_type IN ('expense', 'loan', 'asset_transfer')",
            name=op.f("ck_scheduled_obligations_economic_type"),
        ),
        sa.CheckConstraint(
            "loan_asset_id IS NULL OR economic_type = 'loan'",
            name=op.f("ck_scheduled_obligations_loan_reference"),
        ),
        sa.CheckConstraint(
            "schedule_state IN ('active', 'superseded')",
            name=op.f("ck_scheduled_obligations_schedule_state"),
        ),
        sa.CheckConstraint(
            "(currency_reference IS NULL) = (foreign_amount_reference IS NULL)",
            name=op.f("ck_scheduled_obligations_foreign_reference_pair"),
        ),
        sa.CheckConstraint(
            "NOT (skipped AND manually_completed)",
            name=op.f("ck_scheduled_obligations_exclusive_status"),
        ),
        sa.CheckConstraint(
            "account_id IS NULL OR card_id IS NULL",
            name=op.f("ck_scheduled_obligations_one_payment_method"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(title)) > 0", name=op.f("ck_scheduled_obligations_nonempty_title")
        ),
        sa.CheckConstraint(
            "expected_amount_krw IS NULL OR expected_amount_krw >= 0",
            name=op.f("ck_scheduled_obligations_nonnegative_expected"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_scheduled_obligations_positive_version")),
        sa.ForeignKeyConstraint(
            ["household_id", "account_id"],
            ["financial_accounts.household_id", "financial_accounts.id"],
            name="fk_scheduled_obligations_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "card_id"],
            ["cards.household_id", "cards.id"],
            name="fk_scheduled_obligations_card_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "loan_asset_id"],
            ["assets.household_id", "assets.id"],
            name="fk_scheduled_obligations_loan_asset_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "rule_id", "rule_version_id"],
            [
                "recurring_rule_versions.household_id",
                "recurring_rule_versions.rule_id",
                "recurring_rule_versions.id",
            ],
            name=op.f("fk_scheduled_obligations_household_id_recurring_rule_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_obligations")),
        sa.UniqueConstraint(
            "household_id", "id", name=op.f("uq_scheduled_obligations_household_id")
        ),
        sa.UniqueConstraint(
            "household_id",
            "rule_id",
            "nominal_date",
            name="uq_obligations_household_rule_occurrence",
        ),
    )
    op.create_index(
        "ix_obligations_household_scheduled",
        "scheduled_obligations",
        ["household_id", "scheduled_date", "id"],
        unique=False,
    )
    op.create_table(
        "fixed_settlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("cash_record_id", sa.Uuid(), nullable=False),
        sa.Column("economic_type", sa.String(length=16), nullable=False),
        sa.Column("principal_krw", sa.Numeric(precision=20, scale=0), nullable=False),
        sa.Column("consumption_krw", sa.Numeric(precision=20, scale=0), nullable=False),
        sa.Column("asset_transfer_krw", sa.Numeric(precision=20, scale=0), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(economic_type = 'loan' AND asset_transfer_krw = 0) OR "
            "(economic_type = 'expense' AND principal_krw = 0 AND asset_transfer_krw = 0) OR "
            "(economic_type = 'asset_transfer' AND principal_krw = 0 AND consumption_krw = 0)",
            name=op.f("ck_fixed_settlements_breakdown_type"),
        ),
        sa.CheckConstraint(
            "economic_type IN ('expense', 'loan', 'asset_transfer')",
            name=op.f("ck_fixed_settlements_economic_type"),
        ),
        sa.CheckConstraint(
            "principal_krw >= 0 AND consumption_krw >= 0 AND asset_transfer_krw >= 0",
            name=op.f("ck_fixed_settlements_nonnegative_breakdown"),
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "cash_record_id"],
            ["cash_records.household_id", "cash_records.id"],
            name="fk_fixed_settlements_cash_record_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "obligation_id"],
            ["scheduled_obligations.household_id", "scheduled_obligations.id"],
            name="fk_fixed_settlements_obligation_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fixed_settlements")),
        sa.UniqueConstraint("cash_record_id", name=op.f("uq_fixed_settlements_cash_record_id")),
        sa.UniqueConstraint("household_id", "id", name=op.f("uq_fixed_settlements_household_id")),
    )
    op.create_table(
        "obligation_revisions",
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("nominal_date", sa.Date(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("schedule_state", sa.String(length=12), nullable=False),
        sa.Column("manual_override", sa.Boolean(), nullable=False),
        sa.Column("skipped", sa.Boolean(), nullable=False),
        sa.Column("manually_completed", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("amount_mode", sa.String(length=8), nullable=False),
        sa.Column("expected_amount_krw", sa.Numeric(precision=20, scale=0), nullable=True),
        sa.Column("economic_type", sa.String(length=16), nullable=False),
        sa.Column("loan_asset_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("card_id", sa.Uuid(), nullable=True),
        sa.Column("currency_reference", sa.String(length=3), nullable=True),
        sa.Column("foreign_amount_reference", sa.String(length=40), nullable=True),
        sa.Column("note", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "action IN ('create', 'regenerate', 'reschedule', 'skip', 'unskip', "
            "'complete', 'reopen', 'settle', 'void_settlement')",
            name=op.f("ck_obligation_revisions_action"),
        ),
        sa.CheckConstraint(
            "amount_mode <> 'fixed' OR expected_amount_krw IS NOT NULL",
            name=op.f("ck_obligation_revisions_fixed_amount"),
        ),
        sa.CheckConstraint(
            "amount_mode IN ('fixed', 'variable')", name=op.f("ck_obligation_revisions_amount_mode")
        ),
        sa.CheckConstraint(
            "economic_type IN ('expense', 'loan', 'asset_transfer')",
            name=op.f("ck_obligation_revisions_economic_type"),
        ),
        sa.CheckConstraint(
            "loan_asset_id IS NULL OR economic_type = 'loan'",
            name=op.f("ck_obligation_revisions_loan_reference"),
        ),
        sa.CheckConstraint(
            "schedule_state IN ('active', 'superseded')",
            name=op.f("ck_obligation_revisions_schedule_state"),
        ),
        sa.CheckConstraint(
            "(currency_reference IS NULL) = (foreign_amount_reference IS NULL)",
            name=op.f("ck_obligation_revisions_foreign_reference_pair"),
        ),
        sa.CheckConstraint(
            "NOT (skipped AND manually_completed)",
            name=op.f("ck_obligation_revisions_exclusive_status"),
        ),
        sa.CheckConstraint(
            "account_id IS NULL OR card_id IS NULL",
            name=op.f("ck_obligation_revisions_one_payment_method"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(title)) > 0", name=op.f("ck_obligation_revisions_nonempty_title")
        ),
        sa.CheckConstraint(
            "expected_amount_krw IS NULL OR expected_amount_krw >= 0",
            name=op.f("ck_obligation_revisions_nonnegative_expected"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_obligation_revisions_positive_version")),
        sa.ForeignKeyConstraint(
            ["household_id", "account_id"],
            ["financial_accounts.household_id", "financial_accounts.id"],
            name="fk_obligation_revisions_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "card_id"],
            ["cards.household_id", "cards.id"],
            name="fk_obligation_revisions_card_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "loan_asset_id"],
            ["assets.household_id", "assets.id"],
            name="fk_obligation_revisions_loan_asset_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "obligation_id"],
            ["scheduled_obligations.household_id", "scheduled_obligations.id"],
            name="fk_obligation_revisions_obligation_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "rule_id", "rule_version_id"],
            [
                "recurring_rule_versions.household_id",
                "recurring_rule_versions.rule_id",
                "recurring_rule_versions.id",
            ],
            name=op.f("fk_obligation_revisions_household_id_recurring_rule_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("obligation_id", "version", name=op.f("pk_obligation_revisions")),
        sa.UniqueConstraint(
            "household_id",
            "obligation_id",
            "version",
            name=op.f("uq_obligation_revisions_household_id"),
        ),
    )
    op.create_table(
        "obligation_generation_items",
        sa.Column("generation_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_version", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id", "generation_id"],
            ["obligation_generations.household_id", "obligation_generations.id"],
            name="fk_obligation_generation_items_generation_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "obligation_id", "obligation_version"],
            [
                "obligation_revisions.household_id",
                "obligation_revisions.obligation_id",
                "obligation_revisions.version",
            ],
            name=op.f("fk_obligation_generation_items_household_id_obligation_revisions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "generation_id", "obligation_id", name=op.f("pk_obligation_generation_items")
        ),
    )

    op.execute("""
        CREATE FUNCTION protect_recurring_history() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'Recurring history is immutable' USING ERRCODE = '55000';
        END $$
    """)
    for table in (
        "obligation_revisions",
        "fixed_settlements",
        "obligation_generations",
        "obligation_generation_items",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_recurring_history()"
        )
    op.execute("""
        CREATE FUNCTION protect_rule_version() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Rule versions are immutable' USING ERRCODE = '55000';
            END IF;
            IF OLD.effective_until IS NOT NULL OR NEW.effective_until IS NULL OR
                (to_jsonb(OLD) - 'effective_until') IS DISTINCT FROM
                (to_jsonb(NEW) - 'effective_until') THEN
                RAISE EXCEPTION 'Only the open rule period can be closed once'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER rule_version_immutable BEFORE UPDATE OR DELETE ON recurring_rule_versions
        FOR EACH ROW EXECUTE FUNCTION protect_rule_version()
    """)
    op.execute("""
        CREATE FUNCTION validate_fixed_settlement() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE source_kind text; source_flow text; source_amount numeric; source_state text;
                planned_type text;
        BEGIN
            SELECT kind, flow, amount_krw, state
                INTO source_kind, source_flow, source_amount, source_state
                FROM cash_records WHERE id = NEW.cash_record_id AND household_id = NEW.household_id
                FOR UPDATE;
            SELECT economic_type INTO planned_type FROM scheduled_obligations
                WHERE id = NEW.obligation_id AND household_id = NEW.household_id;
            IF source_kind IS DISTINCT FROM 'fixed_payment' OR source_flow IS DISTINCT FROM 'out'
                OR source_state IS DISTINCT FROM 'active'
                OR planned_type IS DISTINCT FROM NEW.economic_type
                OR source_amount IS DISTINCT FROM
                    (NEW.principal_krw + NEW.consumption_krw + NEW.asset_transfer_krw) THEN
                RAISE EXCEPTION 'Settlement must match its actual cash fact and obligation'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER fixed_settlement_matches_cash BEFORE INSERT ON fixed_settlements
        FOR EACH ROW EXECUTE FUNCTION validate_fixed_settlement()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER fixed_settlement_matches_cash ON fixed_settlements")
    op.execute("DROP FUNCTION validate_fixed_settlement()")
    op.execute("DROP TRIGGER rule_version_immutable ON recurring_rule_versions")
    op.execute("DROP FUNCTION protect_rule_version()")
    for table in (
        "obligation_revisions",
        "fixed_settlements",
        "obligation_generations",
        "obligation_generation_items",
    ):
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
    op.execute("DROP FUNCTION protect_recurring_history()")
    # Do not drop the database-wide extension: other schemas may still use its operator classes.
    op.drop_table("obligation_generation_items")
    op.drop_table("obligation_revisions")
    op.drop_table("fixed_settlements")
    op.drop_index("ix_obligations_household_scheduled", table_name="scheduled_obligations")
    op.drop_table("scheduled_obligations")
    op.drop_table("recurring_rule_versions")
    op.drop_table("obligation_generations")
    op.drop_index("ix_recurring_rules_household_id", table_name="recurring_rules")
    op.drop_table("recurring_rules")
