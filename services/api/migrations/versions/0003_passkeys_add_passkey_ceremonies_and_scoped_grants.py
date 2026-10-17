"""add passkey ceremonies and scoped grants

Revision ID: 0003_passkeys
Revises: 0002_identity_auth
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_passkeys"
down_revision = "0002_identity_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_credentials",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_device_id", sa.Uuid(), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("rp_id", sa.String(length=253), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False),
        sa.Column("aaguid", sa.Uuid(), nullable=False),
        sa.Column("transports", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("device_type", sa.String(length=16), nullable=False),
        sa.Column("backed_up", sa.Boolean(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
            "device_type IN ('single_device', 'multi_device')",
            name=op.f("ck_auth_credentials_valid_device_type"),
        ),
        sa.CheckConstraint(
            "octet_length(credential_id) BETWEEN 1 AND 1023",
            name=op.f("ck_auth_credentials_credential_id_length"),
        ),
        sa.CheckConstraint(
            "octet_length(public_key) BETWEEN 1 AND 8192",
            name=op.f("ck_auth_credentials_public_key_length"),
        ),
        sa.CheckConstraint(
            "sign_count BETWEEN 0 AND 4294967295", name=op.f("ck_auth_credentials_valid_sign_count")
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "created_device_id", "user_id"],
            [
                "registered_devices.household_id",
                "registered_devices.id",
                "registered_devices.user_id",
            ],
            name=op.f("fk_auth_credentials_household_id_registered_devices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "user_id"],
            ["household_members.household_id", "household_members.user_id"],
            name=op.f("fk_auth_credentials_household_id_household_members"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_credentials")),
        sa.UniqueConstraint("credential_id", name=op.f("uq_auth_credentials_credential_id")),
        sa.UniqueConstraint(
            "household_id", "id", "user_id", name="uq_auth_credentials_household_id_id_user_id"
        ),
    )
    op.create_table(
        "auth_challenges",
        sa.Column("household_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("pending_device_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("transport", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("challenge_hash", sa.String(length=64), nullable=False),
        sa.Column("binding_hash", sa.String(length=64), nullable=True),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
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
            "(kind = 'login' AND session_id IS NULL AND device_id IS NULL AND "
            "pending_device_id IS NOT NULL AND binding_hash IS NOT NULL AND label IS "
            "NOT NULL AND action IS NULL AND target_id IS NULL) OR (kind = 'register' "
            "AND household_id IS NOT NULL AND user_id IS NOT NULL AND session_id IS "
            "NOT NULL AND device_id IS NOT NULL AND pending_device_id IS NULL AND "
            "binding_hash IS NULL AND label IS NOT NULL AND action IS NULL AND "
            "target_id IS NULL) OR (kind = 'step_up' AND household_id IS NOT NULL AND "
            "user_id IS NOT NULL AND session_id IS NOT NULL AND device_id IS NOT NULL "
            "AND pending_device_id IS NULL AND binding_hash IS NULL AND label IS NULL "
            "AND action IS NOT NULL AND target_id IS NOT NULL)",
            name=op.f("ck_auth_challenges_ceremony_scope"),
        ),
        sa.CheckConstraint(
            "action IS NULL OR action IN ('account.reveal', 'data.export', "
            "'device.revoke', 'household.invite', 'passkey.register', "
            "'passkey.revoke', 'vault.membership', 'vault.key_rotation')",
            name=op.f("ck_auth_challenges_valid_action"),
        ),
        sa.CheckConstraint(
            "kind IN ('register', 'login', 'step_up')", name=op.f("ck_auth_challenges_valid_kind")
        ),
        sa.CheckConstraint(
            "transport IN ('web', 'native')", name=op.f("ck_auth_challenges_valid_transport")
        ),
        sa.CheckConstraint(
            "(household_id IS NULL) = (user_id IS NULL)",
            name=op.f("ck_auth_challenges_paired_identity"),
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "device_id", "user_id"],
            [
                "registered_devices.household_id",
                "registered_devices.id",
                "registered_devices.user_id",
            ],
            name=op.f("fk_auth_challenges_household_id_registered_devices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "session_id"],
            ["auth_sessions.household_id", "auth_sessions.id"],
            name=op.f("fk_auth_challenges_household_id_auth_sessions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "user_id"],
            ["household_members.household_id", "household_members.user_id"],
            name=op.f("fk_auth_challenges_household_id_household_members"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_challenges")),
        sa.UniqueConstraint("binding_hash", name=op.f("uq_auth_challenges_binding_hash")),
        sa.UniqueConstraint("challenge_hash", name=op.f("uq_auth_challenges_challenge_hash")),
        sa.UniqueConstraint("pending_device_id", name=op.f("uq_auth_challenges_pending_device_id")),
    )
    op.create_index(op.f("ix_auth_challenges_expires_at"), "auth_challenges", ["expires_at"])
    op.create_table(
        "auth_step_up_grants",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("credential_record_id", sa.Uuid(), nullable=False),
        sa.Column("grant_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
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
            "purpose IN ('account.reveal', 'data.export', 'device.revoke', "
            "'household.invite', 'passkey.register', 'passkey.revoke', "
            "'vault.membership', 'vault.key_rotation')",
            name=op.f("ck_auth_step_up_grants_valid_purpose"),
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "credential_record_id", "user_id"],
            ["auth_credentials.household_id", "auth_credentials.id", "auth_credentials.user_id"],
            name=op.f("fk_auth_step_up_grants_household_id_auth_credentials"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "device_id", "user_id"],
            [
                "registered_devices.household_id",
                "registered_devices.id",
                "registered_devices.user_id",
            ],
            name=op.f("fk_auth_step_up_grants_household_id_registered_devices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "session_id"],
            ["auth_sessions.household_id", "auth_sessions.id"],
            name=op.f("fk_auth_step_up_grants_household_id_auth_sessions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_step_up_grants")),
        sa.UniqueConstraint("grant_hash", name=op.f("uq_auth_step_up_grants_grant_hash")),
    )
    op.create_index(
        op.f("ix_auth_step_up_grants_expires_at"), "auth_step_up_grants", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_auth_step_up_grants_expires_at"), table_name="auth_step_up_grants")
    op.drop_table("auth_step_up_grants")
    op.drop_index(op.f("ix_auth_challenges_expires_at"), table_name="auth_challenges")
    op.drop_table("auth_challenges")
    op.drop_table("auth_credentials")
