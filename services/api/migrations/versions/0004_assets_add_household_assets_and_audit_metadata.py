"""add household assets and audit metadata

Revision ID: 0004_assets
Revises: 0003_passkeys
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_assets"
down_revision = "0003_passkeys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("owner_member_id", sa.Uuid(), nullable=True),
        sa.Column("ownership_kind", sa.String(length=16), nullable=False),
        sa.Column("household_share", sa.Numeric(), nullable=False),
        sa.Column("amount_basis", sa.String(length=16), nullable=False),
        sa.Column("inclusion_status", sa.String(length=16), nullable=False),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
            "(ownership_kind = 'individual' AND owner_member_id IS NOT NULL) OR "
            "(ownership_kind = 'joint' AND owner_member_id IS NULL)",
            name=op.f("ck_assets_owner_matches_ownership"),
        ),
        sa.CheckConstraint(
            "amount_basis IN ('whole', 'owned')", name=op.f("ck_assets_valid_amount_basis")
        ),
        sa.CheckConstraint(
            "category IN ('real_estate', 'deposit', 'financial', 'loan', 'other')",
            name=op.f("ck_assets_valid_category"),
        ),
        sa.CheckConstraint(
            "inclusion_status IN ('included', 'excluded')", name=op.f("ck_assets_valid_inclusion")
        ),
        sa.CheckConstraint("kind IN ('asset', 'liability')", name=op.f("ck_assets_valid_kind")),
        sa.CheckConstraint(
            "ownership_kind IN ('individual', 'joint')", name=op.f("ck_assets_valid_ownership")
        ),
        sa.CheckConstraint(
            "(ended_on IS NULL) = (archived_at IS NULL)", name=op.f("ck_assets_archive_matches_end")
        ),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name=op.f("ck_assets_nonempty_name")),
        sa.CheckConstraint(
            "ended_on IS NULL OR ended_on >= started_on", name=op.f("ck_assets_valid_dates")
        ),
        sa.CheckConstraint(
            "household_share >= 0 AND household_share <= 1 AND scale(household_share) <= 18",
            name=op.f("ck_assets_valid_household_share"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_assets_positive_version")),
        sa.ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_assets_household_created_by_member",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "owner_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_assets_household_owner_member",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "updated_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_assets_household_updated_by_member",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_assets_household_id_households"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
        sa.UniqueConstraint("household_id", "id", name=op.f("uq_assets_household_id")),
    )
    op.create_index(
        "ix_assets_household_archived_id",
        "assets",
        ["household_id", "archived_at", "id"],
        unique=False,
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("before_version", sa.BigInteger(), nullable=True),
        sa.Column("after_version", sa.BigInteger(), nullable=True),
        sa.Column("safe_diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(safe_diff) = 'object'", name=op.f("ck_audit_events_object_safe_diff")
        ),
        sa.CheckConstraint(
            "after_version IS NULL OR after_version > 0", name=op.f("ck_audit_events_after_version")
        ),
        sa.CheckConstraint(
            "before_version IS NULL OR before_version > 0",
            name=op.f("ck_audit_events_before_version"),
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "actor_id"],
            ["household_members.household_id", "household_members.user_id"],
            name=op.f("fk_audit_events_household_id_household_members"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_household_occurred_id",
        "audit_events",
        ["household_id", "occurred_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_household_occurred_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_assets_household_archived_id", table_name="assets")
    op.drop_table("assets")
