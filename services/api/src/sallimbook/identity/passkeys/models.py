from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin


class StepUpPurpose(StrEnum):
    ACCOUNT_REVEAL = "account.reveal"
    DATA_EXPORT = "data.export"
    DEVICE_REVOKE = "device.revoke"
    HOUSEHOLD_INVITE = "household.invite"
    PASSKEY_REGISTER = "passkey.register"
    PASSKEY_REVOKE = "passkey.revoke"
    VAULT_MEMBERSHIP = "vault.membership"
    VAULT_KEY_ROTATION = "vault.key_rotation"


_PURPOSE_SQL = ", ".join(f"'{purpose.value}'" for purpose in StepUpPurpose)


class AuthCredential(EntityMixin, Base):
    __tablename__ = "auth_credentials"
    __table_args__ = (
        UniqueConstraint(
            "household_id", "id", "user_id", name="uq_auth_credentials_household_id_id_user_id"
        ),
        ForeignKeyConstraint(
            ["household_id", "user_id"],
            ["household_members.household_id", "household_members.user_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["household_id", "created_device_id", "user_id"],
            [
                "registered_devices.household_id",
                "registered_devices.id",
                "registered_devices.user_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "octet_length(credential_id) BETWEEN 1 AND 1023", name="credential_id_length"
        ),
        CheckConstraint("octet_length(public_key) BETWEEN 1 AND 8192", name="public_key_length"),
        CheckConstraint("sign_count BETWEEN 0 AND 4294967295", name="valid_sign_count"),
        CheckConstraint(
            "device_type IN ('single_device', 'multi_device')", name="valid_device_type"
        ),
    )

    household_id: Mapped[UUID]
    user_id: Mapped[UUID]
    created_device_id: Mapped[UUID]
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    rp_id: Mapped[str] = mapped_column(String(253))
    label: Mapped[str] = mapped_column(String(80))
    sign_count: Mapped[int] = mapped_column(BigInteger)
    aaguid: Mapped[UUID]
    transports: Mapped[list[str]] = mapped_column(JSONB)
    device_type: Mapped[str] = mapped_column(String(16))
    backed_up: Mapped[bool] = mapped_column(Boolean)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthChallenge(EntityMixin, Base):
    __tablename__ = "auth_challenges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "user_id"],
            ["household_members.household_id", "household_members.user_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["household_id", "session_id"],
            ["auth_sessions.household_id", "auth_sessions.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["household_id", "device_id", "user_id"],
            [
                "registered_devices.household_id",
                "registered_devices.id",
                "registered_devices.user_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("kind IN ('register', 'login', 'step_up')", name="valid_kind"),
        CheckConstraint("transport IN ('web', 'native')", name="valid_transport"),
        CheckConstraint("(household_id IS NULL) = (user_id IS NULL)", name="paired_identity"),
        CheckConstraint(
            "(kind = 'login' AND session_id IS NULL AND device_id IS NULL "
            "AND pending_device_id IS NOT NULL AND binding_hash IS NOT NULL AND label IS NOT NULL "
            "AND action IS NULL AND target_id IS NULL) OR "
            "(kind = 'register' AND household_id IS NOT NULL AND user_id IS NOT NULL "
            "AND session_id IS NOT NULL AND device_id IS NOT NULL "
            "AND pending_device_id IS NULL AND binding_hash IS NULL AND label IS NOT NULL "
            "AND action IS NULL AND target_id IS NULL) OR "
            "(kind = 'step_up' AND household_id IS NOT NULL AND user_id IS NOT NULL "
            "AND session_id IS NOT NULL AND device_id IS NOT NULL "
            "AND pending_device_id IS NULL AND binding_hash IS NULL AND label IS NULL "
            "AND action IS NOT NULL AND target_id IS NOT NULL)",
            name="ceremony_scope",
        ),
        CheckConstraint(f"action IS NULL OR action IN ({_PURPOSE_SQL})", name="valid_action"),
    )

    household_id: Mapped[UUID | None]
    user_id: Mapped[UUID | None]
    session_id: Mapped[UUID | None]
    device_id: Mapped[UUID | None]
    pending_device_id: Mapped[UUID | None] = mapped_column(unique=True)
    kind: Mapped[str] = mapped_column(String(16))
    transport: Mapped[str] = mapped_column(String(16))
    label: Mapped[str | None] = mapped_column(String(80))
    challenge_hash: Mapped[str] = mapped_column(String(64), unique=True)
    binding_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    policy_hash: Mapped[str] = mapped_column(String(64))
    action: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[UUID | None]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StepUpGrant(EntityMixin, Base):
    __tablename__ = "auth_step_up_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "credential_record_id", "user_id"],
            ["auth_credentials.household_id", "auth_credentials.id", "auth_credentials.user_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["household_id", "session_id"],
            ["auth_sessions.household_id", "auth_sessions.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["household_id", "device_id", "user_id"],
            [
                "registered_devices.household_id",
                "registered_devices.id",
                "registered_devices.user_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"purpose IN ({_PURPOSE_SQL})", name="valid_purpose"),
    )

    household_id: Mapped[UUID]
    user_id: Mapped[UUID]
    session_id: Mapped[UUID]
    device_id: Mapped[UUID]
    credential_record_id: Mapped[UUID]
    grant_hash: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[UUID]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
