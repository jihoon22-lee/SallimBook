"""Separate insurance subjects from the two authenticated household members."""

import sqlalchemy as sa
from alembic import op

revision = "0019_household_people"
down_revision = "0018_install_device"
branch_labels = None
depends_on = None

REFERENCES = (
    ("insurance_policies", "insured_member_id"),
    ("insurance_cases", "patient_member_id"),
    ("insurance_case_revisions", "patient_member_id"),
)


def references(target):
    for table, field in REFERENCES:
        name = f"fk_{table}_{field}"
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name,
            table,
            target,
            ["household_id", field],
            ["household_id", "id"],
            ondelete="RESTRICT",
        )


def upgrade():
    op.create_table(
        "household_people",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid()),
        sa.Column("display_name", sa.String(120)),
        sa.Column("relation", sa.String(8), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_member_id", sa.Uuid(), nullable=False),
        sa.Column("updated_by_member_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.UniqueConstraint("household_id", "id"),
        sa.UniqueConstraint("member_id"),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="RESTRICT"),
        *(
            sa.ForeignKeyConstraint(
                ["household_id", field],
                ["household_members.household_id", "household_members.id"],
                ondelete="RESTRICT",
                name=f"fk_household_people_{field}",
            )
            for field in ("member_id", "created_by_member_id", "updated_by_member_id")
        ),
        sa.CheckConstraint("version > 0", name="positive_version"),
        sa.CheckConstraint(
            "(member_id IS NOT NULL AND id = member_id AND display_name IS NULL "
            "AND relation = 'member' AND archived_at IS NULL) OR "
            "(member_id IS NULL AND display_name IS NOT NULL "
            "AND char_length(btrim(display_name)) > 0 AND relation IN ('child','parent','other'))",
            name="person_kind",
        ),
    )
    # Preserve UUIDs and immutable case revisions, including inactive memberships.
    op.execute("""INSERT INTO household_people
        (id, household_id, member_id, relation, created_by_member_id,
         updated_by_member_id, created_at, updated_at)
        SELECT id, household_id, id, 'member', id, id, created_at, updated_at
        FROM household_members""")
    references("household_people")


def downgrade():
    # Family records or their audit/idempotency evidence must never disappear on rollback.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM household_people WHERE member_id IS NULL) THEN
            RAISE EXCEPTION 'Household family data exists; roll forward instead';
        END IF;
    END $$""")
    references("household_members")
    op.drop_table("household_people")
