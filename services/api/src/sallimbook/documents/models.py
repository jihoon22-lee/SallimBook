"""Encrypted private documents and concrete household-scoped attachment targets."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin
from sallimbook.insurance.models import ActorFields, actor_constraints, household_fk

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
TARGET_TABLES = {
    "policy": "insurance_policies",
    "case": "insurance_cases",
    "medical_node": "medical_nodes",
    "expense": "medical_expenses",
    "claim": "insurance_claims",
    "appliance": "appliances",
    "asset": "assets",
}


class Document(ActorFields, EntityMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        *actor_constraints("documents"),
        UniqueConstraint("storage_key"),
        UniqueConstraint("encryption_key_version", "nonce", name="uq_documents_key_nonce"),
        CheckConstraint("state IN ('pending','ready','deleted')", name="state"),
        CheckConstraint("mime_type IN ('application/pdf','image/jpeg','image/png')", name="mime"),
        CheckConstraint(f"size_bytes BETWEEN 1 AND {MAX_DOCUMENT_BYTES}", name="size"),
        CheckConstraint("checksum_sha256 ~ '^[0-9a-f]{64}$'", name="checksum"),
        CheckConstraint("char_length(btrim(original_name)) BETWEEN 1 AND 255", name="name"),
        CheckConstraint(
            "(storage_key IS NULL AND encryption_key_version IS NULL AND nonce IS NULL "
            "AND stored_at IS NULL) OR (storage_key IS NOT NULL "
            "AND encryption_key_version IS NOT NULL "
            "AND nonce IS NOT NULL AND storage_key ~ '^[0-9a-f]{32}[.]sbdoc$' "
            "AND encryption_key_version > 0 AND octet_length(nonce) = 12 "
            "AND stored_at IS NOT NULL)",
            name="envelope_shape",
        ),
        CheckConstraint("state <> 'ready' OR storage_key IS NOT NULL", name="ready_content"),
        CheckConstraint("state <> 'pending' OR storage_key IS NULL", name="pending_no_content"),
        CheckConstraint("(state = 'deleted') = (deleted_at IS NOT NULL)", name="deleted_at"),
        CheckConstraint(
            "state <> 'deleted' OR (deletion_reason IS NOT NULL "
            "AND char_length(btrim(deletion_reason)) > 0)",
            name="deletion_reason",
        ),
        Index("ix_documents_household_state_id", "household_id", "state", "id"),
        Index("ix_documents_pending_expiry", "state", "pending_expires_at"),
        Index("ix_documents_orphaned_at", "orphaned_at"),
    )
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(8))
    pending_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    orphaned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    storage_key: Mapped[str | None] = mapped_column(String(38))
    encryption_key_version: Mapped[int | None]
    nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    stored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_reason: Mapped[str | None] = mapped_column(String(500))


class DocumentLink(ActorFields, EntityMixin, Base):
    __tablename__ = "document_links"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        *actor_constraints("document_links"),
        household_fk("document_links", "document_id", "documents"),
        *(
            household_fk("document_links", name + "_id", table)
            for name, table in TARGET_TABLES.items()
        ),
        CheckConstraint(
            "num_nonnulls(policy_id, case_id, medical_node_id, expense_id, claim_id, "
            "appliance_id, asset_id) = 1",
            name="one_typed_target",
        ),
        CheckConstraint("active = (ended_at IS NULL)", name="active_end_pair"),
        CheckConstraint(
            "active OR (end_reason IS NOT NULL AND char_length(btrim(end_reason)) > 0)",
            name="ended_reason",
        ),
        Index(
            "ix_document_links_household_document", "household_id", "document_id", "active", "id"
        ),
        *(
            Index(
                f"uq_document_links_active_{name}",
                "household_id",
                "document_id",
                name + "_id",
                unique=True,
                postgresql_where=text(f"active AND {name}_id IS NOT NULL"),
            )
            for name in TARGET_TABLES
        ),
    )
    document_id: Mapped[UUID]
    policy_id: Mapped[UUID | None]
    case_id: Mapped[UUID | None]
    medical_node_id: Mapped[UUID | None]
    expense_id: Mapped[UUID | None]
    claim_id: Mapped[UUID | None]
    appliance_id: Mapped[UUID | None]
    asset_id: Mapped[UUID | None]
    active: Mapped[bool]
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(500))
