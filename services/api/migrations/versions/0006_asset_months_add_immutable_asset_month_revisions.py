"""add immutable asset month revisions

Revision ID: 0006_asset_months
Revises: 0005_accounts
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_asset_months"
down_revision = "0005_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_months",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("current_revision_id", sa.Uuid(), nullable=True),
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
            "extract(day from period_month) = 1", name=op.f("ck_asset_months_first_day")
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_asset_months_positive_version")),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_asset_months_household_id_households"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_months")),
        sa.UniqueConstraint("household_id", "id", name="uq_asset_months_household_identity"),
        sa.UniqueConstraint(
            "household_id", "period_month", name="uq_asset_months_household_period"
        ),
    )
    op.create_table(
        "asset_month_revisions",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("month_id", sa.Uuid(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("previous_revision_id", sa.Uuid(), nullable=True),
        sa.Column("reopened_reason", sa.String(length=1000), nullable=True),
        sa.Column("created_by_member_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_by_member_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
            "(state = 'confirmed' AND confirmed_at IS NOT NULL AND confirmed_by_member_id "
            "IS NOT NULL) OR (state <> 'confirmed' AND confirmed_at IS NULL AND "
            "confirmed_by_member_id IS NULL)",
            name=op.f("ck_asset_month_revisions_confirmation_metadata"),
        ),
        sa.CheckConstraint(
            "state IN ('draft', 'reopened', 'confirmed')",
            name=op.f("ck_asset_month_revisions_valid_state"),
        ),
        sa.CheckConstraint(
            "(revision_no = 1 AND previous_revision_id IS NULL AND reopened_reason IS NULL) "
            "OR (revision_no > 1 AND previous_revision_id IS NOT NULL AND reopened_reason "
            "IS NOT NULL AND char_length(btrim(reopened_reason)) > 0)",
            name=op.f("ck_asset_month_revisions_revision_history"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_asset_month_revisions_positive_version")),
        sa.ForeignKeyConstraint(
            ["household_id", "confirmed_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_asset_month_revisions_confirmer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_asset_month_revisions_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "month_id", "previous_revision_id"],
            [
                "asset_month_revisions.household_id",
                "asset_month_revisions.month_id",
                "asset_month_revisions.id",
            ],
            name="fk_asset_month_revisions_previous",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "month_id"],
            ["asset_months.household_id", "asset_months.id"],
            name=op.f("fk_asset_month_revisions_household_id_asset_months"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_month_revisions")),
        sa.UniqueConstraint(
            "household_id", "id", name="uq_asset_month_revisions_household_identity"
        ),
        sa.UniqueConstraint(
            "household_id", "month_id", "id", name="uq_asset_month_revisions_month_identity"
        ),
        sa.UniqueConstraint("month_id", "revision_no", name="uq_asset_month_revisions_number"),
    )
    op.create_table(
        "asset_values",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_version", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("ownership_kind", sa.String(length=16), nullable=False),
        sa.Column("owner_member_id", sa.Uuid(), nullable=True),
        sa.Column("household_share", sa.Numeric(), nullable=False),
        sa.Column("amount_basis", sa.String(length=16), nullable=False),
        sa.Column("inclusion_status", sa.String(length=16), nullable=False),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column(
            "input_amount_krw",
            sa.Numeric(precision=20, scale=0),
            nullable=True,
        ),
        sa.Column(
            "owned_amount_krw",
            sa.Numeric(precision=20, scale=0),
            nullable=True,
        ),
        sa.Column("as_of_date", sa.Date(), nullable=True),
        sa.Column("verification_state", sa.String(length=24), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("origin_revision_id", sa.Uuid(), nullable=True),
        sa.Column("change_reason", sa.String(length=1000), nullable=True),
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
            name=op.f("ck_asset_values_owner_matches_ownership"),
        ),
        sa.CheckConstraint(
            "(verification_state = 'missing' AND input_amount_krw IS NULL) OR "
            "(verification_state = 'carried_unconfirmed' AND input_amount_krw IS NOT NULL) "
            "OR (verification_state = 'verified' AND input_amount_krw IS NOT NULL AND "
            "as_of_date IS NOT NULL)",
            name=op.f("ck_asset_values_valid_verification"),
        ),
        sa.CheckConstraint(
            "amount_basis IN ('whole', 'owned')", name=op.f("ck_asset_values_valid_amount_basis")
        ),
        sa.CheckConstraint(
            "inclusion_status IN ('included', 'excluded')",
            name=op.f("ck_asset_values_valid_inclusion"),
        ),
        sa.CheckConstraint(
            "kind IN ('asset', 'liability')", name=op.f("ck_asset_values_valid_kind")
        ),
        sa.CheckConstraint(
            "origin IN ('manual', 'carried')", name=op.f("ck_asset_values_valid_origin")
        ),
        sa.CheckConstraint(
            "(input_amount_krw IS NULL) = (owned_amount_krw IS NULL) AND (input_amount_krw "
            "IS NULL OR (input_amount_krw >= 0 AND owned_amount_krw >= 0))",
            name=op.f("ck_asset_values_valid_amounts"),
        ),
        sa.CheckConstraint(
            "ended_on IS NULL OR ended_on >= started_on", name=op.f("ck_asset_values_valid_dates")
        ),
        sa.CheckConstraint(
            "household_share >= 0 AND household_share <= 1 AND scale(household_share) <= 18",
            name=op.f("ck_asset_values_valid_household_share"),
        ),
        sa.CheckConstraint(
            "source_asset_version > 0 AND version > 0",
            name=op.f("ck_asset_values_positive_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "asset_id"],
            ["assets.household_id", "assets.id"],
            name=op.f("fk_asset_values_household_id_assets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "origin_revision_id"],
            ["asset_month_revisions.household_id", "asset_month_revisions.id"],
            name="fk_asset_values_origin_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "owner_member_id"],
            ["household_members.household_id", "household_members.id"],
            name="fk_asset_values_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "revision_id"],
            ["asset_month_revisions.household_id", "asset_month_revisions.id"],
            name="fk_asset_values_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_values")),
        sa.UniqueConstraint("household_id", "id", name=op.f("uq_asset_values_household_id")),
        sa.UniqueConstraint("revision_id", "asset_id", name=op.f("uq_asset_values_revision_id")),
    )
    op.create_index(
        "ix_asset_values_household_asset_revision",
        "asset_values",
        ["household_id", "asset_id", "revision_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_asset_months_current_revision",
        "asset_months",
        "asset_month_revisions",
        ["household_id", "id", "current_revision_id"],
        ["household_id", "month_id", "id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )
    # Services already lock Household -> Month -> Revision. These database barriers
    # also reject accidental direct overwrites of a confirmed historical observation.
    op.execute("""
        CREATE FUNCTION protect_asset_month_revision() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF (NEW.revision_no = 1 AND NEW.state <> 'draft') OR
                    (NEW.revision_no > 1 AND NEW.state <> 'reopened') THEN
                    RAISE EXCEPTION 'A revision must start unconfirmed' USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.state = 'confirmed' THEN
                RAISE EXCEPTION 'A confirmed revision is immutable' USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            IF (OLD.id, OLD.household_id, OLD.month_id, OLD.revision_no,
                OLD.previous_revision_id, OLD.reopened_reason, OLD.created_by_member_id,
                OLD.created_at) IS DISTINCT FROM
                (NEW.id, NEW.household_id, NEW.month_id, NEW.revision_no,
                NEW.previous_revision_id, NEW.reopened_reason, NEW.created_by_member_id,
                NEW.created_at) THEN
                RAISE EXCEPTION 'A revision origin is immutable' USING ERRCODE = '55000';
            END IF;
            IF NEW.state <> OLD.state AND NEW.state <> 'confirmed' THEN
                RAISE EXCEPTION 'An existing revision can only be confirmed'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER asset_month_revision_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON asset_month_revisions
        FOR EACH ROW EXECUTE FUNCTION protect_asset_month_revision()
    """)
    op.execute("""
        CREATE FUNCTION protect_asset_month_value() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            target_household uuid;
            target_revision uuid;
            revision_state text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                target_household := OLD.household_id;
                target_revision := OLD.revision_id;
            ELSE
                target_household := NEW.household_id;
                target_revision := NEW.revision_id;
            END IF;
            IF TG_OP = 'UPDATE' AND
                (OLD.id, OLD.household_id, OLD.revision_id, OLD.asset_id) IS DISTINCT FROM
                (NEW.id, NEW.household_id, NEW.revision_id, NEW.asset_id) THEN
                RAISE EXCEPTION 'A value identity is immutable' USING ERRCODE = '55000';
            END IF;
            SELECT state INTO revision_state FROM asset_month_revisions
                WHERE household_id = target_household AND id = target_revision FOR UPDATE;
            IF revision_state = 'confirmed' THEN
                RAISE EXCEPTION 'A confirmed value is immutable' USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER asset_month_value_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON asset_values
        FOR EACH ROW EXECUTE FUNCTION protect_asset_month_value()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER asset_month_value_immutable ON asset_values")
    op.execute("DROP TRIGGER asset_month_revision_immutable ON asset_month_revisions")
    op.execute("DROP FUNCTION protect_asset_month_value()")
    op.execute("DROP FUNCTION protect_asset_month_revision()")
    op.drop_constraint("fk_asset_months_current_revision", "asset_months", type_="foreignkey")
    op.drop_index("ix_asset_values_household_asset_revision", table_name="asset_values")
    op.drop_table("asset_values")
    op.drop_table("asset_month_revisions")
    op.drop_table("asset_months")
