from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from sallimbook.identity import people_service as service
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency
from sallimbook.identity.people_schemas import (
    PersonCreate,
    PersonCreatedReference,
    PersonListResponse,
    PersonPatch,
    PersonResponse,
)

router = APIRouter(prefix="/api/v1/household/people", tags=["household-people"])


@router.get("", response_model=PersonListResponse, operation_id="listHouseholdPeople")
def list_people(
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    return service.list_people(session, principal, cursor=cursor, limit=limit)


@router.post(
    "", response_model=PersonCreatedReference, status_code=201, operation_id="createHouseholdPerson"
)
def create_person(
    payload: PersonCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
):
    result = service.create_person(session, principal, payload, key)
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.patch("/{person_id}", response_model=PersonResponse, operation_id="updateHouseholdPerson")
def update_person(
    person_id: UUID,
    payload: PersonPatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: Annotated[str, Header(alias="If-Match")],
):
    result = service.update_person(session, principal, person_id, payload, if_match)
    response.headers["ETag"] = f'"{result.version}"'
    return result
