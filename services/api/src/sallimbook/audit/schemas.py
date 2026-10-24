from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    id: UUID
    actor_member_id: UUID
    entity_type: str
    entity_id: UUID
    action: str
    request_id: str | None
    before_version: int | None
    after_version: int | None
    occurred_at: datetime
    changed_fields: list[str]


class AuditListResponse(BaseModel):
    items: list[AuditEventResponse]
    next_cursor: str | None


class ActivityEventResponse(AuditEventResponse):
    target_name: str | None
    target_path: str | None


class ActivityListResponse(BaseModel):
    items: list[ActivityEventResponse]
    next_cursor: str | None
