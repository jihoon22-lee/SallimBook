"""Atomic idempotency reservations and immutable result references for domain writes.

The caller commits the domain change and this record in the same transaction. A failed
operation must roll back both. Credentials/token-issuing endpoints must not use this store.
"""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from sallimbook.core.authorization import Principal
from sallimbook.core.database import Base, EntityMixin
from sallimbook.core.errors import DomainError


class IdempotencyRecord(EntityMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "actor_id"],
            ["household_members.household_id", "household_members.user_id"],
            ondelete="RESTRICT",
        ),
        # Actor IDs are globally unique, and membership binds each actor to one household.
        UniqueConstraint("actor_id", "operation", "key"),
        CheckConstraint("state IN ('pending', 'completed')", name="valid_state"),
        CheckConstraint(
            "state = 'pending' OR (resource_id IS NOT NULL AND resource_type IS NOT NULL "
            "AND resource_version IS NOT NULL AND response_status IS NOT NULL "
            "AND response_status BETWEEN 200 AND 299)",
            name="completed_reference",
        ),
        CheckConstraint(
            "resource_version IS NULL OR resource_version > 0", name="positive_resource_version"
        ),
    )

    household_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(100))
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    resource_id: Mapped[UUID | None]
    resource_type: Mapped[str | None] = mapped_column(String(80))
    resource_version: Mapped[int | None] = mapped_column(BigInteger)
    response_status: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True)
class IdempotentResult:
    resource_id: UUID
    resource_type: str
    resource_version: int
    status_code: int = 201


def _check_json(value: object) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, list):
        for item in value:
            _check_json(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _check_json(item)
        return
    # Decimal money is serialized to API decimal strings before hashing, never floats.
    raise DomainError("INVALID_PAYLOAD", "입력 형식을 확인해 주세요.", 422)


def payload_hash(payload: object) -> str:
    _check_json(payload)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def run_idempotent(
    session: Session,
    principal: Principal,
    operation: str,
    key: str | None,
    payload: object,
    execute: Callable[[], IdempotentResult],
) -> IdempotentResult:
    """Serialize duplicate submissions with PostgreSQL's unique constraint, not process memory.

    The stored reference includes the original version. A response renderer must resolve that
    immutable version, rather than fetch a resource's potentially newer current representation.
    Records are intentionally retained: deleting them could replay an old financial operation.
    """
    if key is None or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", key):
        raise DomainError("INVALID_IDEMPOTENCY_KEY", "재시도 식별자를 확인해 주세요.", 400)
    if not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,99}", operation):
        raise ValueError("Operation must be a fixed server-defined identifier")
    digest = payload_hash(payload)
    new_id = uuid4()
    inserted = session.scalar(
        insert(IdempotencyRecord)
        .values(
            id=new_id,
            household_id=principal.household_id,
            actor_id=principal.user_id,
            operation=operation,
            key=key,
            request_hash=digest,
            state="pending",
        )
        .on_conflict_do_nothing(index_elements=["actor_id", "operation", "key"])
        .returning(IdempotencyRecord.id)
    )
    record = session.scalar(
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.actor_id == principal.user_id,
            IdempotencyRecord.household_id == principal.household_id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.key == key,
        )
        .with_for_update()
    )
    if record is None:
        raise DomainError("IDEMPOTENCY_CONFLICT", "재시도 식별자를 다시 확인해 주세요.", 409)
    if record.request_hash != digest:
        raise DomainError(
            "IDEMPOTENCY_CONFLICT", "같은 식별자로 다른 내용을 보낼 수 없습니다.", 409
        )
    if inserted is None:
        if record.state != "completed":
            raise DomainError("OPERATION_IN_PROGRESS", "진행 중인 요청을 다시 확인해 주세요.", 409)
        return IdempotentResult(
            resource_id=record.resource_id,
            resource_type=record.resource_type,
            resource_version=record.resource_version,
            status_code=record.response_status,
        )
    result = execute()
    if (
        not isinstance(result, IdempotentResult)
        or not isinstance(result.resource_id, UUID)
        or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", result.resource_type)
        or result.resource_version < 1
        or not 200 <= result.status_code <= 299
    ):
        raise ValueError("An immutable successful domain result reference is required")
    record.resource_id = result.resource_id
    record.resource_type = result.resource_type
    record.resource_version = result.resource_version
    record.response_status = result.status_code
    record.state = "completed"
    record.completed_at = datetime.now(UTC)
    session.flush()
    return result
