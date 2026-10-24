"""Account authentication state. Plaintext credentials and tokens have no DB columns."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin


class User(EntityMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("login_name = lower(login_name)", name="canonical_login"),)

    login_name: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(256))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HouseholdMember(EntityMixin, Base):
    __tablename__ = "household_members"
    __table_args__ = (
        UniqueConstraint("household_id", "id", name="uq_household_members_household_id_id"),
        UniqueConstraint(
            "household_id", "user_id", name="uq_household_members_household_id_user_id"
        ),
        CheckConstraint("slot IN (1, 2)", name="two_member_slots"),
        CheckConstraint("role IN ('owner', 'member')", name="valid_role"),
        CheckConstraint("status IN ('active', 'revoked')", name="valid_status"),
        Index(
            "uq_active_household_member_slot",
            "household_id",
            "slot",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id", ondelete="RESTRICT"))
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        unique=True,
    )
    slot: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"))


class Invitation(EntityMixin, Base):
    __tablename__ = "invitations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "created_by_member_id"],
            ["household_members.household_id", "household_members.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("kind IN ('bootstrap', 'partner')", name="valid_kind"),
        CheckConstraint(
            "(kind = 'bootstrap' AND created_by_member_id IS NULL) OR "
            "(kind = 'partner' AND created_by_member_id IS NOT NULL)",
            name="issuer_matches_kind",
        ),
    )

    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id", ondelete="RESTRICT"))
    intended_login: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(16))
    created_by_member_id: Mapped[UUID | None]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RegisteredDevice(EntityMixin, Base):
    __tablename__ = "registered_devices"
    __table_args__ = (
        UniqueConstraint("household_id", "id", "user_id"),
        ForeignKeyConstraint(
            ["household_id", "user_id"],
            ["household_members.household_id", "household_members.user_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("platform IN ('web', 'android')", name="valid_platform"),
        CheckConstraint("status IN ('active', 'revoked')", name="valid_status"),
        CheckConstraint(
            "install_key_hash IS NULL OR (platform = 'android' AND length(install_key_hash) = 64)",
            name="android_install_key",
        ),
        CheckConstraint(
            "install_session_id IS NULL OR install_key_hash IS NOT NULL", name="install_session"
        ),
    )

    household_id: Mapped[UUID]
    user_id: Mapped[UUID]
    label: Mapped[str] = mapped_column(String(80))
    platform: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # SHA-256 of the key an Android install presents to sign in on this row again.
    install_key_hash: Mapped[str | None] = mapped_column(String(64))
    # The session of that install's latest sign-in; the row admits no other session.
    install_session_id: Mapped[UUID | None]


class AuthSession(EntityMixin, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        ForeignKeyConstraint(
            ["household_id", "device_id", "user_id"],
            [
                "registered_devices.household_id",
                "registered_devices.id",
                "registered_devices.user_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("kind IN ('web', 'native')", name="valid_kind"),
        CheckConstraint(
            "(kind = 'web' AND csrf_hash IS NOT NULL AND access_expires_at IS NULL) OR "
            "(kind = 'native' AND csrf_hash IS NULL AND access_expires_at IS NOT NULL)",
            name="transport_credentials",
        ),
    )

    household_id: Mapped[UUID]
    user_id: Mapped[UUID]
    device_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(16))
    session_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str | None] = mapped_column(String(64))
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(EntityMixin, Base):
    """Consumed hashes stay until session retention ends so reuse can revoke the family."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "session_id"],
            ["auth_sessions.household_id", "auth_sessions.id"],
            ondelete="RESTRICT",
        ),
    )

    household_id: Mapped[UUID]
    session_id: Mapped[UUID]
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginThrottle(Base):
    """Persisted admission counters; keys contain only domain-separated SHA-256 hashes."""

    __tablename__ = "login_throttles"
    __table_args__ = (CheckConstraint("attempts >= 0", name="nonnegative_attempts"),)

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer)
