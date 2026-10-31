from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from sallimbook.cards import service, stored_service
from sallimbook.cards.schemas import (
    CardArchive,
    CardCreate,
    CardListResponse,
    CardPatch,
    CardResponse,
    CardStoredDetailsInput,
    CardStoredDetailsResponse,
    CardType,
)
from sallimbook.core.name_search import NameQuery
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(prefix="/api/v1/cards", tags=["cards"])
IfMatch = Annotated[str, Header(alias="If-Match")]
ETAG_HEADERS = {
    "ETag": {"description": "Quoted card version for If-Match.", "schema": {"type": "string"}}
}
CREATED_HEADERS = {
    **ETAG_HEADERS,
    "Location": {"description": "Created card path.", "schema": {"type": "string"}},
}


def _etag(response: Response, result: CardResponse) -> CardResponse:
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.post(
    "",
    response_model=CardResponse,
    status_code=201,
    operation_id="createCard",
    responses={201: {"headers": CREATED_HEADERS}},
)
def create(
    payload: CardCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    result = service.create_card(session, principal, payload)
    response.headers["Location"] = f"/api/v1/cards/{result.id}"
    return _etag(response, result)


@router.get("", response_model=CardListResponse, operation_id="listCards")
def list_cards(
    principal: PrincipalDependency,
    session: SessionDependency,
    owner_member_id: UUID | None = None,
    card_type: CardType | None = None,
    settlement_account_id: UUID | None = None,
    status: Literal["active", "closed", "all"] = "active",
    q: NameQuery = None,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    return service.list_cards(
        session,
        principal,
        owner_member_id=owner_member_id,
        card_type=card_type,
        settlement_account_id=settlement_account_id,
        status=status,
        q=q,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/{card_id}",
    response_model=CardResponse,
    operation_id="getCard",
    responses={200: {"headers": ETAG_HEADERS}},
)
def get_card(
    card_id: UUID, principal: PrincipalDependency, session: SessionDependency, response: Response
):
    return _etag(response, service.get_card(session, principal, card_id))


@router.patch(
    "/{card_id}",
    response_model=CardResponse,
    operation_id="updateCard",
    responses={200: {"headers": ETAG_HEADERS}},
)
def update(
    card_id: UUID,
    payload: CardPatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
):
    return _etag(response, service.update_card(session, principal, card_id, payload, if_match))


@router.post(
    "/{card_id}/archive",
    response_model=CardResponse,
    operation_id="archiveCard",
    responses={200: {"headers": ETAG_HEADERS}},
)
def archive(
    card_id: UUID,
    payload: CardArchive,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
):
    return _etag(
        response,
        service.update_card(
            session,
            principal,
            card_id,
            CardPatch(**payload.model_dump(exclude_unset=True)),
            if_match,
            archive=True,
        ),
    )


@router.delete("/{card_id}", status_code=204, operation_id="deleteCard")
def delete(
    card_id: UUID, principal: PrincipalDependency, session: SessionDependency, if_match: IfMatch
):
    service.delete_card(session, principal, card_id, if_match)
    return Response(status_code=204)


@router.put(
    "/{card_id}/stored-details",
    response_model=CardResponse,
    operation_id="putCardStoredDetails",
    responses={200: {"headers": ETAG_HEADERS}},
)
def put_stored_details(
    card_id: UUID,
    payload: CardStoredDetailsInput,
    principal: PrincipalDependency,
    session: SessionDependency,
    request: Request,
    response: Response,
    if_match: IfMatch,
):
    return _etag(
        response,
        stored_service.put_details(
            session,
            principal,
            card_id,
            payload,
            if_match,
            request.app.state.settings.field_encryption_key_file,
            request.state.request_id,
        ),
    )


@router.post(
    "/{card_id}/stored-details/reveal",
    response_model=CardStoredDetailsResponse,
    operation_id="revealCardStoredDetails",
)
def reveal_stored_details(
    card_id: UUID, principal: PrincipalDependency, session: SessionDependency, request: Request
):
    return stored_service.reveal_details(
        session,
        principal,
        card_id,
        request.app.state.settings.field_encryption_key_file,
        request.state.request_id,
    )


@router.delete("/{card_id}/stored-details", status_code=204, operation_id="deleteCardStoredDetails")
def delete_stored_details(
    card_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    request: Request,
    if_match: IfMatch,
):
    stored_service.delete_details(session, principal, card_id, if_match, request.state.request_id)
    return Response(status_code=204)
