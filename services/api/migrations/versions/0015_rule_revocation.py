"""Rule version revocation and the derived manual override flag.

Revision ID: 0015_rule_revocation
Revises: 0014_vault
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_rule_revocation"
down_revision = "0014_vault"
branch_labels = None
depends_on = None

# Alembic does not compare exclusion or check constraints; these mirror recurring_models.py.
EXCLUDE = (
    "ALTER TABLE recurring_rule_versions ADD CONSTRAINT ex_recurring_rule_versions_period "
    "EXCLUDE USING gist (household_id public.gist_uuid_ops WITH =, "
    "rule_id public.gist_uuid_ops WITH =, "
    "daterange(effective_from, effective_until, '[)') WITH &&){where}"
)
PROTECT_0009 = """
    CREATE OR REPLACE FUNCTION protect_rule_version() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Rule versions are immutable' USING ERRCODE = '55000';
        END IF;
        IF NEW.effective_until IS NULL OR
            (OLD.effective_until IS NOT NULL AND
             NEW.effective_until >= OLD.effective_until) OR
            (to_jsonb(OLD) - 'effective_until') IS DISTINCT FROM
            (to_jsonb(NEW) - 'effective_until') THEN
            RAISE EXCEPTION 'Only the rule period end can be shortened'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END $$
"""
PROTECT_0015 = """
    CREATE OR REPLACE FUNCTION protect_rule_version() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Rule versions are immutable' USING ERRCODE = '55000';
        END IF;
        IF OLD.revoked_at IS NOT NULL THEN
            RAISE EXCEPTION 'Revoked rule versions are immutable' USING ERRCODE = '55000';
        END IF;
        IF NEW.revoked_at IS NOT NULL THEN
            IF (to_jsonb(OLD) - 'revoked_at') IS DISTINCT FROM (to_jsonb(NEW) - 'revoked_at')
                OR NOT EXISTS (
                    SELECT 1 FROM recurring_rule_versions earlier
                    WHERE earlier.household_id = NEW.household_id
                      AND earlier.rule_id = NEW.rule_id
                      AND earlier.revoked_at IS NULL
                      AND earlier.effective_from < NEW.effective_from
                ) THEN
                RAISE EXCEPTION 'Only a later rule version can be revoked, without other changes'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END IF;
        IF NEW.effective_until IS NULL OR
            (OLD.effective_until IS NOT NULL AND
             NEW.effective_until >= OLD.effective_until) OR
            (to_jsonb(OLD) - 'effective_until') IS DISTINCT FROM
            (to_jsonb(NEW) - 'effective_until') THEN
            RAISE EXCEPTION 'Only the rule period end can be shortened'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END $$
"""
EXCEPTION = "skipped OR manually_completed OR scheduled_date <> nominal_date"
NORMALIZE = (
    f"UPDATE scheduled_obligations SET manual_override = ({EXCEPTION}) "
    f"WHERE manual_override IS DISTINCT FROM ({EXCEPTION})"
)


def upgrade() -> None:
    # Existing versions were never revoked, so the nullable column needs no backfill.
    op.add_column(
        "recurring_rule_versions",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "ALTER TABLE recurring_rule_versions DROP CONSTRAINT ex_recurring_rule_versions_period"
    )
    op.execute(EXCLUDE.format(where=" WHERE (revoked_at IS NULL)"))
    op.drop_constraint(
        "uq_rule_versions_household_rule_start", "recurring_rule_versions", type_="unique"
    )
    op.create_index(
        "uq_rule_versions_household_rule_start",
        "recurring_rule_versions",
        ["household_id", "rule_id", "effective_from"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.execute(PROTECT_0015)
    # Only the derived flag changes; version, updated_at and the immutable history stay as recorded.
    op.execute(NORMALIZE)
    op.create_check_constraint(
        op.f("ck_scheduled_obligations_manual_override_derived"),
        "scheduled_obligations",
        f"manual_override = ({EXCEPTION})",
    )


def downgrade() -> None:
    # The full start/period constraints cannot hold revoked rows; refuse instead of losing them.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM recurring_rule_versions "
        "WHERE revoked_at IS NOT NULL) THEN "
        "RAISE EXCEPTION 'Revoked rule versions block downgrade' USING ERRCODE = '55000'; "
        "END IF; END $$"
    )
    op.drop_constraint(
        op.f("ck_scheduled_obligations_manual_override_derived"),
        "scheduled_obligations",
        type_="check",
    )
    op.execute(PROTECT_0009)
    op.drop_index("uq_rule_versions_household_rule_start", table_name="recurring_rule_versions")
    op.create_unique_constraint(
        "uq_rule_versions_household_rule_start",
        "recurring_rule_versions",
        ["household_id", "rule_id", "effective_from"],
    )
    op.execute(
        "ALTER TABLE recurring_rule_versions DROP CONSTRAINT ex_recurring_rule_versions_period"
    )
    op.execute(EXCLUDE.format(where=""))
    op.drop_column("recurring_rule_versions", "revoked_at")
