"""Let a mistakenly registered recurring rule be deleted; its history stays immutable otherwise.

The only exception is DELETE of rows that belong to the one rule named by the transaction-local
setting `sallimbook.deleting_rule`, and only revisions that record generation (create or
regenerate). Settlements keep the unconditional protection, so their foreign key to the
occurrence keeps any paid occurrence, and with it the rule, in place.

Revision ID: 0017_rule_delete
Revises: 0016_replacement_override
"""

from alembic import op

revision = "0017_rule_delete"
down_revision = "0016_replacement_override"
branch_labels = None
depends_on = None

HISTORY_TABLES = ("obligation_revisions", "obligation_generations", "obligation_generation_items")

PROTECT_RULE_HISTORY = """
    CREATE FUNCTION protect_rule_history() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE deleting text := nullif(current_setting('sallimbook.deleting_rule', true), '');
    BEGIN
        IF TG_OP = 'DELETE' AND deleting IS NOT NULL THEN
            IF TG_TABLE_NAME = 'obligation_generations' THEN
                IF OLD.rule_id::text = deleting THEN
                    RETURN OLD;
                END IF;
            ELSIF TG_TABLE_NAME = 'obligation_revisions' THEN
                IF OLD.action IN ('create', 'regenerate') AND EXISTS (
                    SELECT 1 FROM scheduled_obligations o
                    WHERE o.household_id = OLD.household_id AND o.id = OLD.obligation_id
                      AND o.rule_id::text = deleting
                ) THEN
                    RETURN OLD;
                END IF;
            ELSIF EXISTS (
                SELECT 1 FROM scheduled_obligations o
                WHERE o.household_id = OLD.household_id AND o.id = OLD.obligation_id
                  AND o.rule_id::text = deleting
            ) THEN
                RETURN OLD;
            END IF;
        END IF;
        RAISE EXCEPTION 'Recurring history is immutable' USING ERRCODE = '55000';
    END $$
"""

# The 0015 body with one change: DELETE of the rule being deleted in this transaction.
PROTECT_RULE_VERSION = """
    CREATE OR REPLACE FUNCTION protect_rule_version() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'DELETE' THEN
            IF OLD.rule_id::text = nullif(current_setting('sallimbook.deleting_rule', true), '')
            THEN
                RETURN OLD;
            END IF;
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

# Exactly the 0015 body, restored on downgrade.
PROTECT_RULE_VERSION_0015 = """
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


def _retrigger(function: str) -> None:
    for table in HISTORY_TABLES:
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )


def upgrade() -> None:
    op.execute(PROTECT_RULE_HISTORY)
    # fixed_settlements stays on protect_recurring_history(), which has no exception.
    _retrigger("protect_rule_history")
    op.execute(PROTECT_RULE_VERSION)


def downgrade() -> None:
    op.execute(PROTECT_RULE_VERSION_0015)
    _retrigger("protect_recurring_history")
    op.execute("DROP FUNCTION protect_rule_history()")
