"""Authorization inputs come only from server-validated sessions and memberships."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sallimbook.core.database import Base
from sallimbook.core.errors import DomainError


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    member_id: UUID
    household_id: UUID
    session_id: UUID
    device_id: UUID
    role: Literal["owner", "member"]
    transport: Literal["web", "native"]
    authenticated_at: datetime


def scoped_entity[T: Base](
    session: Session,
    model: type[T],
    entity_id: UUID,
    principal: Principal,
    *,
    for_update: bool = False,
) -> T:
    """Use this for reads and writes; inaccessible and absent objects both return 404."""
    if not hasattr(model, "household_id"):
        raise TypeError("Only household-scoped models are supported")
    query = select(model).where(model.id == entity_id, model.household_id == principal.household_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    entity = session.scalar(query)
    if entity is None:
        raise DomainError("NOT_FOUND", "요청한 항목을 찾을 수 없습니다.", 404)
    return entity


def require_version(entity: Base, if_match: str | None) -> None:
    if if_match is None:
        raise DomainError("VERSION_REQUIRED", "수정할 버전을 지정해 주세요.", 400)
    if not re.fullmatch(r'"[1-9][0-9]{0,18}"', if_match):
        raise DomainError("INVALID_VERSION", "버전 형식을 확인해 주세요.", 400)
    if int(if_match[1:-1]) != entity.version:
        raise DomainError("VERSION_CONFLICT", "다른 기기에서 수정했습니다.", 409, entity.version)


def require_recent_login(principal: Principal, *, now: datetime | None = None) -> None:
    """A verified account login sets authenticated_at; refresh and scoped grants never extend it."""
    now = now or datetime.now(UTC)
    age = now - principal.authenticated_at
    if age < timedelta(0) or age > timedelta(minutes=5):
        raise DomainError("REAUTHENTICATION_REQUIRED", "다시 로그인한 후 진행해 주세요.", 403)


def require_owner(principal: Principal) -> None:
    if principal.role != "owner":
        raise DomainError("FORBIDDEN", "허용되지 않은 요청입니다.", 403)
