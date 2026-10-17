from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from sallimbook.accounts import service
from sallimbook.accounts.schemas import (
    AccountCreate,
    AccountListResponse,
    AccountPatch,
    AccountResponse,
    AccountRevealResponse,
    AccountType,
)
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])
ETAG_HEADERS = {
    "ETag": {"description": "Quoted account version for If-Match.", "schema": {"type": "string"}}
}
CREATED_HEADERS = {
    **ETAG_HEADERS,
    "Location": {"description": "Created account resource path.", "schema": {"type": "string"}},
}


def _key_file(request: Request):
    return request.app.state.settings.field_encryption_key_file


@router.post(
    "",
    response_model=AccountResponse,
    status_code=201,
    operation_id="createAccount",
    responses={201: {"headers": CREATED_HEADERS}},
)
def create_account(
    payload: AccountCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    request: Request,
    response: Response,
) -> AccountResponse:
    result = service.create_account(
        session, principal, payload, _key_file(request), request_id=request.state.request_id
    )
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Location"] = f"/api/v1/accounts/{result.id}"
    return result


@router.get("", response_model=AccountListResponse, operation_id="listAccounts")
def list_accounts(
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    account_type: AccountType | None = None,
    owner_member_id: UUID | None = None,
    status: Literal["active", "closed", "all"] = "active",
) -> AccountListResponse:
    return service.list_accounts(
        session,
        principal,
        cursor=cursor,
        limit=limit,
        account_type=account_type,
        owner_member_id=owner_member_id,
        status=status,
    )


@router.get(
    "/{account_id}",
    response_model=AccountResponse,
    operation_id="getAccount",
    responses={200: {"headers": ETAG_HEADERS}},
)
def get_account(
    account_id: UUID, principal: PrincipalDependency, session: SessionDependency, response: Response
) -> AccountResponse:
    result = service.get_account(session, principal, account_id)
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.patch(
    "/{account_id}",
    response_model=AccountResponse,
    operation_id="updateAccount",
    responses={200: {"headers": ETAG_HEADERS}},
)
def update_account(
    account_id: UUID,
    payload: AccountPatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    request: Request,
    response: Response,
    if_match: Annotated[str, Header(alias="If-Match")],
) -> AccountResponse:
    result = service.update_account(
        session,
        principal,
        account_id,
        payload,
        if_match,
        _key_file(request),
        request_id=request.state.request_id,
    )
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.post(
    "/{account_id}/reveal", response_model=AccountRevealResponse, operation_id="revealAccountNumber"
)
def reveal_account_number(
    account_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    request: Request,
    step_up_token: Annotated[str | None, Header(alias="X-Step-Up-Token", max_length=128)] = None,
) -> AccountRevealResponse:
    return service.reveal_number(
        session,
        principal,
        account_id,
        _key_file(request),
        step_up_token=step_up_token,
        request_id=request.state.request_id,
    )
