"""Opaque, household-scoped vault storage and immutable rotation snapshots.

Current pointers and availability are separate from retained ciphertext history.
The nonce ledger survives replacement, retirement and aborted rotations. Its
purpose-bearing foreign keys, together with per-table nonce uniqueness, prevent
two ciphertext records from referencing one reservation. Lifecycle/immutability
and complete atomic activation additionally require the migration's DB triggers.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin
from sallimbook.insurance.models import ActorFields, actor_constraints, household_fk
from sallimbook.vault.formats import (
    CARD_CIPHERTEXT_BYTES,
    KEY_CHECK_CIPHERTEXT_BYTES,
    MAX_PBKDF2_ITERATIONS,
    MAX_SAFE_INTEGER,
    MIN_PBKDF2_ITERATIONS,
)


def _bounded(field: str, *, zero: bool = False):
    return CheckConstraint(
        f"{field} BETWEEN {0 if zero else 1} AND {MAX_SAFE_INTEGER}", name=f"{field}_range"
    )


def _version_fk(table: str, field: str = "key_version"):
    return ForeignKeyConstraint(
        ["household_id", field],
        ["vault_versions.household_id", "vault_versions.key_version"],
        ondelete="RESTRICT",
        name=f"fk_{table}_{field}",
    )


def _nonce_constraints(table: str, purpose: str):
    return (
        ForeignKeyConstraint(
            ["household_id", "key_version", "nonce", "purpose"],
            [
                "vault_nonce_reservations.household_id",
                "vault_nonce_reservations.key_version",
                "vault_nonce_reservations.nonce",
                "vault_nonce_reservations.purpose",
            ],
            ondelete="RESTRICT",
            name=f"fk_{table}_nonce",
        ),
        UniqueConstraint("household_id", "key_version", "nonce"),
        CheckConstraint(f"purpose = '{purpose}'", name="purpose"),
        CheckConstraint("octet_length(nonce) = 12", name="nonce_length"),
        CheckConstraint("format_version = 1", name="format_version"),
    )


class OpaqueFields:
    key_version: Mapped[int] = mapped_column(BigInteger)
    format_version: Mapped[int]
    purpose: Mapped[str] = mapped_column(String(12))
    nonce: Mapped[bytes] = mapped_column(LargeBinary)


class VaultState(ActorFields, EntityMixin, Base):
    __tablename__ = "vault_states"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("household_id"),
        *actor_constraints("vault_states"),
        _version_fk("vault_states", "current_key_version"),
        _bounded("current_key_version"),
        _bounded("next_key_version"),
        CheckConstraint("next_key_version > current_key_version", name="next_key_version"),
    )
    current_key_version: Mapped[int] = mapped_column(BigInteger)
    next_key_version: Mapped[int] = mapped_column(BigInteger)
    rotation_required: Mapped[bool]


class VaultVersion(ActorFields, EntityMixin, Base):
    __tablename__ = "vault_versions"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("household_id", "key_version"),
        *actor_constraints("vault_versions"),
        _version_fk("vault_versions", "source_key_version"),
        _bounded("key_version"),
        CheckConstraint("state IN ('staging','current','retired','aborted')", name="state"),
        CheckConstraint(
            "(key_version = 1 AND source_key_version IS NULL) OR "
            "(key_version > 1 AND source_key_version >= 1 AND source_key_version < key_version)",
            name="source_key_version",
        ),
        CheckConstraint("expected_card_count >= 0", name="card_count"),
        CheckConstraint("expected_member_count BETWEEN 1 AND 2", name="member_count"),
        CheckConstraint(
            "(state IN ('current','retired')) = (activated_at IS NOT NULL)", name="activated_at"
        ),
        CheckConstraint("(state = 'retired') = (retired_at IS NOT NULL)", name="retired_at"),
        CheckConstraint("(state = 'aborted') = (aborted_at IS NOT NULL)", name="aborted_at"),
        Index(
            "uq_vault_versions_current",
            "household_id",
            unique=True,
            postgresql_where=text("state = 'current'"),
        ),
        Index(
            "uq_vault_versions_staging",
            "household_id",
            unique=True,
            postgresql_where=text("state = 'staging'"),
        ),
    )
    key_version: Mapped[int] = mapped_column(BigInteger)
    source_key_version: Mapped[int | None] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(8))
    expected_card_count: Mapped[int]
    expected_member_count: Mapped[int]
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aborted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VaultMembership(ActorFields, EntityMixin, Base):
    __tablename__ = "vault_memberships"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("household_id", "member_id"),
        *actor_constraints("vault_memberships"),
        household_fk("vault_memberships", "member_id", "household_members"),
        _version_fk("vault_memberships", "joined_key_version"),
        CheckConstraint("status IN ('active','revoked')", name="status"),
        CheckConstraint("(status = 'revoked') = (revoked_at IS NOT NULL)", name="revoked_at"),
    )
    member_id: Mapped[UUID]
    joined_key_version: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(8))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VaultNonceReservation(Base):
    __tablename__ = "vault_nonce_reservations"
    __table_args__ = (
        _version_fk("vault_nonce_reservations"),
        UniqueConstraint("household_id", "key_version", "nonce", "purpose"),
        CheckConstraint("purpose IN ('card','member','recovery','key_check')", name="purpose"),
        CheckConstraint("octet_length(nonce) = 12", name="nonce_length"),
    )
    household_id: Mapped[UUID] = mapped_column(primary_key=True)
    key_version: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    purpose: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VaultKeyCheck(OpaqueFields, ActorFields, EntityMixin, Base):
    __tablename__ = "vault_key_checks"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("household_id", "key_version"),
        *actor_constraints("vault_key_checks"),
        _version_fk("vault_key_checks"),
        *_nonce_constraints("vault_key_checks", "key_check"),
        CheckConstraint(
            f"octet_length(ciphertext) = {KEY_CHECK_CIPHERTEXT_BYTES}", name="ciphertext_length"
        ),
    )
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)


class VaultMemberWrapping(OpaqueFields, ActorFields, EntityMixin, Base):
    __tablename__ = "vault_member_wrappings"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("household_id", "id", "member_id", "key_version"),
        UniqueConstraint("household_id", "member_id", "key_version", "generation"),
        *actor_constraints("vault_member_wrappings"),
        household_fk("vault_member_wrappings", "member_id", "household_members"),
        _version_fk("vault_member_wrappings"),
        *_nonce_constraints("vault_member_wrappings", "member"),
        _bounded("generation"),
        CheckConstraint("state IN ('offered','current','replaced')", name="state"),
        CheckConstraint("kdf = 'PBKDF2-HMAC-SHA256'", name="kdf"),
        CheckConstraint(
            f"iterations BETWEEN {MIN_PBKDF2_ITERATIONS} AND {MAX_PBKDF2_ITERATIONS}",
            name="iterations",
        ),
        CheckConstraint("octet_length(salt) = 16", name="salt_length"),
        CheckConstraint("octet_length(wrapped_hvk) = 48", name="wrapped_length"),
        Index(
            "uq_vault_member_wrappings_current",
            "household_id",
            "member_id",
            "key_version",
            unique=True,
            postgresql_where=text("state = 'current'"),
        ),
    )
    member_id: Mapped[UUID]
    generation: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(8))
    kdf: Mapped[str] = mapped_column(String(24))
    iterations: Mapped[int]
    salt: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_hvk: Mapped[bytes] = mapped_column(LargeBinary)


class VaultRecoveryWrapping(OpaqueFields, ActorFields, EntityMixin, Base):
    __tablename__ = "vault_recovery_wrappings"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("household_id", "key_version", "generation"),
        *actor_constraints("vault_recovery_wrappings"),
        _version_fk("vault_recovery_wrappings"),
        *_nonce_constraints("vault_recovery_wrappings", "recovery"),
        _bounded("generation"),
        CheckConstraint("kdf = 'HKDF-SHA256'", name="kdf"),
        CheckConstraint("octet_length(salt) = 16", name="salt_length"),
        CheckConstraint("octet_length(wrapped_hvk) = 48", name="wrapped_length"),
        Index(
            "uq_vault_recovery_wrappings_current",
            "household_id",
            "key_version",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )
    generation: Mapped[int] = mapped_column(BigInteger)
    kdf: Mapped[str] = mapped_column(String(24))
    salt: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_hvk: Mapped[bytes] = mapped_column(LargeBinary)
    is_current: Mapped[bool]


class CardSecretEnvelope(OpaqueFields, ActorFields, EntityMixin, Base):
    __tablename__ = "card_secret_envelopes"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("household_id", "card_id", "key_version", "revision"),
        UniqueConstraint("household_id", "id", "card_id", "key_version", "revision"),
        *actor_constraints("card_secret_envelopes"),
        household_fk("card_secret_envelopes", "card_id", "cards"),
        _version_fk("card_secret_envelopes"),
        *_nonce_constraints("card_secret_envelopes", "card"),
        _bounded("revision"),
        CheckConstraint("payload_schema_version = 1", name="payload_schema"),
        CheckConstraint("last_four ~ '^[0-9]{4}$'", name="last_four"),
        CheckConstraint(
            f"octet_length(ciphertext) = {CARD_CIPHERTEXT_BYTES}", name="ciphertext_length"
        ),
        Index(
            "uq_card_secret_envelopes_current",
            "household_id",
            "card_id",
            "key_version",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )
    card_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(BigInteger)
    payload_schema_version: Mapped[int]
    last_four: Mapped[str] = mapped_column(String(4))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    is_current: Mapped[bool]


class VaultShareOffer(ActorFields, EntityMixin, Base):
    __tablename__ = "vault_share_offers"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        *actor_constraints("vault_share_offers"),
        household_fk("vault_share_offers", "source_member_id", "household_members"),
        household_fk("vault_share_offers", "target_member_id", "household_members"),
        _version_fk("vault_share_offers"),
        ForeignKeyConstraint(
            ["household_id", "wrapping_id", "target_member_id", "key_version"],
            [
                "vault_member_wrappings.household_id",
                "vault_member_wrappings.id",
                "vault_member_wrappings.member_id",
                "vault_member_wrappings.key_version",
            ],
            ondelete="RESTRICT",
            name="fk_vault_share_offers_target_wrap",
        ),
        UniqueConstraint("wrapping_id"),
        CheckConstraint("source_member_id <> target_member_id", name="two_members"),
        CheckConstraint("state IN ('pending','accepted','cancelled','expired')", name="state"),
        CheckConstraint("(state <> 'pending') = (closed_at IS NOT NULL)", name="closed_at"),
        CheckConstraint("expires_at > created_at", name="expiry"),
        Index(
            "uq_vault_share_offers_pending",
            "household_id",
            "target_member_id",
            unique=True,
            postgresql_where=text("state = 'pending'"),
        ),
    )
    source_member_id: Mapped[UUID]
    target_member_id: Mapped[UUID]
    key_version: Mapped[int] = mapped_column(BigInteger)
    wrapping_id: Mapped[UUID]
    state: Mapped[str] = mapped_column(String(9))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VaultRotationCard(ActorFields, EntityMixin, Base):
    __tablename__ = "vault_rotation_cards"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("household_id", "key_version", "card_id"),
        *actor_constraints("vault_rotation_cards"),
        _version_fk("vault_rotation_cards"),
        household_fk("vault_rotation_cards", "card_id", "cards"),
        ForeignKeyConstraint(
            [
                "household_id",
                "source_envelope_id",
                "card_id",
                "source_key_version",
                "source_revision",
            ],
            [
                "card_secret_envelopes.household_id",
                "card_secret_envelopes.id",
                "card_secret_envelopes.card_id",
                "card_secret_envelopes.key_version",
                "card_secret_envelopes.revision",
            ],
            ondelete="RESTRICT",
            name="fk_vault_rotation_cards_source_envelope",
        ),
        CheckConstraint("source_key_version < key_version", name="source_key_version"),
    )
    key_version: Mapped[int] = mapped_column(BigInteger)
    card_id: Mapped[UUID]
    source_envelope_id: Mapped[UUID]
    source_key_version: Mapped[int] = mapped_column(BigInteger)
    source_revision: Mapped[int] = mapped_column(BigInteger)


class VaultRotationMember(ActorFields, EntityMixin, Base):
    __tablename__ = "vault_rotation_members"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("household_id", "key_version", "member_id"),
        *actor_constraints("vault_rotation_members"),
        _version_fk("vault_rotation_members"),
        ForeignKeyConstraint(
            ["household_id", "member_id"],
            ["vault_memberships.household_id", "vault_memberships.member_id"],
            ondelete="RESTRICT",
            name="fk_vault_rotation_members_membership",
        ),
        _bounded("source_membership_version"),
    )
    key_version: Mapped[int] = mapped_column(BigInteger)
    member_id: Mapped[UUID]
    source_membership_version: Mapped[int] = mapped_column(BigInteger)
