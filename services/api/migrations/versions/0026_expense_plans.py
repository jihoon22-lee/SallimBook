"""Optional-day monthly expense plans on the existing recurring version model."""

import sqlalchemy as sa
from alembic import op

revision = "0026_expense_plans"
down_revision = "0025_card_stored_details"
branch_labels = None
depends_on = None

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
                OR NOT (EXISTS (
                    SELECT 1 FROM recurring_rule_versions earlier
                    WHERE earlier.household_id = NEW.household_id
                      AND earlier.rule_id = NEW.rule_id
                      AND earlier.revoked_at IS NULL
                      AND earlier.effective_from < NEW.effective_from
                ) OR (OLD.tracking_mode = 'plan_only' AND NOT EXISTS (
                    SELECT 1 FROM scheduled_obligations o
                    WHERE o.household_id = OLD.household_id AND o.rule_version_id = OLD.id
                ))) THEN
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
OLD_PROTECT = """
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


def upgrade():
    op.alter_column("recurring_rule_versions", "anchor_date", nullable=True)
    for name, length, default in (
        ("tracking_mode", 12, "scheduled"),
        ("plan_kind", 12, "recurring"),
        ("budget_treatment", 20, "included"),
    ):
        op.add_column(
            "recurring_rule_versions",
            sa.Column(name, sa.String(length), nullable=False, server_default=default),
        )
    op.add_column(
        "recurring_rule_versions", sa.Column("subject_member_id", sa.Uuid(), nullable=True)
    )
    op.add_column("recurring_rule_versions", sa.Column("annual_month", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_recurring_rule_versions_subject_member_id",
        "recurring_rule_versions",
        "household_members",
        ["household_id", "subject_member_id"],
        ["household_id", "id"],
        ondelete="RESTRICT",
    )
    for name, condition in (
        ("tracking_mode", "tracking_mode IN ('scheduled', 'plan_only')"),
        ("plan_kind", "plan_kind IN ('recurring', 'budget')"),
        (
            "budget_treatment",
            "budget_treatment IN ('included', 'external_support', 'payroll', 'reference_only')",
        ),
        ("scheduled_anchor", "tracking_mode <> 'scheduled' OR anchor_date IS NOT NULL"),
        (
            "annual_month",
            "annual_month IS NULL OR (frequency = 'annual' AND annual_month BETWEEN 1 AND 12 "
            "AND (anchor_date IS NULL OR extract(month from anchor_date) = annual_month))",
        ),
        (
            "budget_monthly",
            "plan_kind <> 'budget' OR (tracking_mode = 'plan_only' "
            "AND frequency = 'monthly' AND interval_count = 1)",
        ),
    ):
        op.create_check_constraint(
            op.f("ck_recurring_rule_versions_" + name), "recurring_rule_versions", condition
        )
    op.execute(PROTECT_RULE_VERSION)


def downgrade():
    # New data is not representable in the old contract. Never silently discard it.
    op.execute("LOCK TABLE recurring_rule_versions IN ACCESS EXCLUSIVE MODE")
    exists = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM recurring_rule_versions "
                "WHERE tracking_mode <> 'scheduled' OR plan_kind <> 'recurring' "
                "OR budget_treatment <> 'included' OR subject_member_id IS NOT NULL "
                "OR annual_month IS NOT NULL)"
            )
        )
        .scalar()
    )
    if exists:
        raise RuntimeError(
            "Expense plan data requires a compatible API; destructive downgrade refused"
        )
    op.execute(OLD_PROTECT)
    for name in (
        "tracking_mode",
        "plan_kind",
        "budget_treatment",
        "scheduled_anchor",
        "annual_month",
        "budget_monthly",
    ):
        op.drop_constraint(
            op.f("ck_recurring_rule_versions_" + name), "recurring_rule_versions", type_="check"
        )
    op.drop_constraint(
        "fk_recurring_rule_versions_subject_member_id",
        "recurring_rule_versions",
        type_="foreignkey",
    )
    for name in (
        "tracking_mode",
        "plan_kind",
        "budget_treatment",
        "subject_member_id",
        "annual_month",
    ):
        op.drop_column("recurring_rule_versions", name)
    op.alter_column("recurring_rule_versions", "anchor_date", nullable=False)
