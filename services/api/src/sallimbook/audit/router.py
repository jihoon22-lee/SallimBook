from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from sallimbook.audit import service
from sallimbook.audit.schemas import AuditListResponse
from sallimbook.identity.dependencies import (
    PeopleCapability,
    PrincipalDependency,
    SessionDependency,
)

router = APIRouter(prefix="/api/v1", tags=["audit"])


@router.get("/audit-events", response_model=AuditListResponse, operation_id="listAuditEvents")
def list_events(
    principal: PrincipalDependency,
    session: SessionDependency,
    people_supported: PeopleCapability,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    entity_type: Annotated[str | None, Query(max_length=40)] = None,
    entity_id: UUID | None = None,
    actor_member_id: UUID | None = None,
    action: Annotated[str | None, Query(max_length=40)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
):
    response.headers["Cache-Control"] = "no-store"
    return service.list_events(
        session,
        principal,
        limit=limit,
        cursor=cursor,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_member_id=actor_member_id,
        action=action,
        since=since,
        until=until,
        legacy_native=principal.transport == "native" and not people_supported,
    )
