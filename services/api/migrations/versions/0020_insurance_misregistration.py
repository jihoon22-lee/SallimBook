"""Permit pristine insurance misregistration deletion without deleting changed history."""

from alembic import op

revision = "0020_insurance_misregistration"
down_revision = "0019_household_people"
branch_labels = None
depends_on = None


def case_reference(ondelete):
    op.drop_constraint(
        "fk_insurance_case_revisions_case_id", "insurance_case_revisions", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_insurance_case_revisions_case_id",
        "insurance_case_revisions",
        "insurance_cases",
        ["household_id", "case_id"],
        ["household_id", "id"],
        ondelete=ondelete,
    )


def upgrade():
    case_reference("CASCADE")
    op.execute("""
        CREATE OR REPLACE FUNCTION reject_insurance_case_history_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            -- The sole creation snapshot may follow a pristine parent's deletion.
            -- A direct revision delete still sees the parent and is always rejected.
            IF TG_OP = 'DELETE' AND OLD.version = 1 AND NOT EXISTS (
                SELECT 1 FROM insurance_cases
                WHERE household_id = OLD.household_id AND id = OLD.case_id
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Insurance case revisions are immutable' USING ERRCODE = '55000';
        END;
        $$
    """)
    op.execute("""
        CREATE FUNCTION reject_changed_insurance_deletion() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.version <> 1 THEN
                RAISE EXCEPTION 'Changed insurance records must be retained'
                    USING ERRCODE = '23503';
            END IF;
            RETURN OLD;
        END;
        $$
    """)
    for table in ("insurance_cases", "insurance_policies"):
        op.execute(
            f"CREATE TRIGGER {table}_preserve_changed BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_changed_insurance_deletion()"
        )


def downgrade():
    for table in ("insurance_cases", "insurance_policies"):
        op.execute(f"DROP TRIGGER {table}_preserve_changed ON {table}")
    op.execute("DROP FUNCTION reject_changed_insurance_deletion()")
    case_reference("RESTRICT")
    op.execute("""
        CREATE OR REPLACE FUNCTION reject_insurance_case_history_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Insurance case revisions are immutable' USING ERRCODE = '55000';
        END;
        $$
    """)
