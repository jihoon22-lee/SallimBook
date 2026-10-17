"""Transaction-bound audit metadata. Callers cannot supply arbitrary value snapshots."""

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from sallimbook.core.authorization import Principal
from sallimbook.core.database import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "actor_id"],
            ["household_members.household_id", "household_members.user_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("before_version IS NULL OR before_version > 0", name="before_version"),
        CheckConstraint("after_version IS NULL OR after_version > 0", name="after_version"),
        CheckConstraint("jsonb_typeof(safe_diff) = 'object'", name="object_safe_diff"),
        Index("ix_audit_events_household_occurred_id", "household_id", "occurred_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[UUID]
    action: Mapped[str] = mapped_column(String(40))
    request_id: Mapped[str | None] = mapped_column(String(128))
    before_version: Mapped[int | None] = mapped_column(BigInteger)
    after_version: Mapped[int | None] = mapped_column(BigInteger)
    safe_diff: Mapped[dict] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


def record_event(
    session: Session,
    principal: Principal,
    *,
    entity_type: Literal[
        "asset",
        "financial_account",
        "asset_month",
        "cash_record",
        "income_conversion",
        "recurring_rule",
        "obligation",
        "fixed_settlement",
        "card",
        "insurance_policy",
        "insurance_coverage",
        "policy_premium_link",
        "insurance_case",
        "medical_node",
        "appliance",
        "consumable",
        "appliance_consumable",
        "stock_movement",
        "consumable_replacement",
    ],
    entity_id: UUID,
    action: Literal[
        "create",
        "update",
        "archive",
        "delete",
        "reveal",
        "correct",
        "void",
        "convert",
        "confirm",
        "reopen",
        "sync_scope",
        "regenerate",
        "reschedule",
        "skip",
        "unskip",
        "complete",
        "settle",
        "void_settlement",
    ],
    before_version: int | None,
    after_version: int | None,
    changed_fields: Iterable[str] = (),
    request_id: str | None = None,
) -> AuditEvent:
    """Append in the caller's transaction; this helper never commits or accepts secret values."""
    fields = sorted(set(changed_fields))
    if len(fields) > 64 or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) for key in fields):
        raise ValueError("Audit field names must be schema identifiers")
    if request_id is not None and not re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", request_id):
        raise ValueError("Audit request identifier is invalid")
    if entity_type not in {
        "asset",
        "financial_account",
        "asset_month",
        "cash_record",
        "income_conversion",
        "recurring_rule",
        "obligation",
        "fixed_settlement",
        "card",
        "insurance_policy",
        "insurance_coverage",
        "policy_premium_link",
        "insurance_case",
        "medical_node",
        "appliance",
        "consumable",
        "appliance_consumable",
        "stock_movement",
        "consumable_replacement",
    } or action not in {
        "create",
        "update",
        "archive",
        "delete",
        "reveal",
        "correct",
        "void",
        "convert",
        "confirm",
        "reopen",
        "sync_scope",
        "regenerate",
        "reschedule",
        "skip",
        "unskip",
        "complete",
        "settle",
        "void_settlement",
    }:
        raise ValueError("Audit operation is not registered")
    event = AuditEvent(
        household_id=principal.household_id,
        actor_id=principal.user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        request_id=request_id,
        before_version=before_version,
        after_version=after_version,
        safe_diff={"changed_fields": fields},
    )
    session.add(event)
    return event
