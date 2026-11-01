"""Atomic first-import provenance; user deletions remain tombstoned."""

import sqlalchemy as sa
from alembic import op

revision = "0027_expense_import"
down_revision = "0026_expense_plans"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "expense_import_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("actor_member_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_date", sa.Date(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("household_id", "id"),
        sa.UniqueConstraint("household_id", "source_id", name="uq_expense_import_batches_source"),
        sa.ForeignKeyConstraint(
            ["household_id", "actor_member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
            name="fk_expense_import_batches_actor_member_id",
        ),
        sa.CheckConstraint("row_count > 0", name=op.f("ck_expense_import_batches_row_count")),
    )
    op.create_table(
        "expense_import_rows",
        sa.Column("household_id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.String(100), primary_key=True),
        sa.Column("source_key", sa.String(100), primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_rule_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id", "source_id"],
            ["expense_import_batches.household_id", "expense_import_batches.source_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "rule_id"],
            ["recurring_rules.household_id", "recurring_rules.id"],
            ondelete="RESTRICT",
            name="fk_expense_import_rows_rule_id",
        ),
        sa.CheckConstraint(
            "(state = 'linked' AND rule_id IS NOT NULL AND rule_id = created_rule_id) "
            "OR (state = 'user_deleted' AND rule_id IS NULL)",
            name=op.f("ck_expense_import_rows_state"),
        ),
    )
    op.execute("""CREATE FUNCTION protect_expense_import() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF TG_TABLE_NAME = 'expense_import_rows' AND TG_OP = 'UPDATE' AND OLD.state = 'linked'
          AND NEW.state = 'user_deleted' AND NEW.rule_id IS NULL
          AND (to_jsonb(OLD) - 'rule_id' - 'state') = (to_jsonb(NEW) - 'rule_id' - 'state')
      THEN RETURN NEW; END IF;
      RAISE EXCEPTION 'Import provenance is immutable' USING ERRCODE = '55000'; END $$""")
    for table in ("expense_import_batches", "expense_import_rows"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_expense_import()"
        )


def downgrade():
    op.execute("LOCK TABLE expense_import_batches IN ACCESS EXCLUSIVE MODE")
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM expense_import_batches)"))
        .scalar()
    ):
        raise RuntimeError("Import provenance exists; destructive downgrade refused")
    op.drop_table("expense_import_rows")
    op.drop_table("expense_import_batches")
    op.execute("DROP FUNCTION protect_expense_import()")
