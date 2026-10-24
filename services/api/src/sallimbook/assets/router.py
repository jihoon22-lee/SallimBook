from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from sallimbook.assets import service
from sallimbook.assets.schemas import (
    AssetArchive,
    AssetCategory,
    AssetCreate,
    AssetKind,
    AssetListResponse,
    AssetPatch,
    AssetResponse,
    InclusionStatus,
    OwnershipKind,
)
from sallimbook.core.name_search import NameQuery
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(prefix="/api/v1/assets", tags=["assets"])
IfMatch = Annotated[str, Header(alias="If-Match")]
ETAG_HEADER = {
    "ETag": {"description": "Quoted record version for If-Match.", "schema": {"type": "string"}}
}
CREATED_HEADERS = {
    **ETAG_HEADER,
    "Location": {"description": "Created asset resource path.", "schema": {"type": "string"}},
}


@router.get("", response_model=AssetListResponse, operation_id="listAssets")
def list_assets(
    principal: PrincipalDependency,
    session: SessionDependency,
    q: NameQuery = None,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    kind: AssetKind | None = None,
    category: AssetCategory | None = None,
    ownership_kind: OwnershipKind | None = None,
    owner_member_id: UUID | None = None,
    inclusion_status: InclusionStatus | None = None,
    status: Literal["active", "archived", "all"] = "active",
) -> AssetListResponse:
    return service.list_assets(
        session,
        principal,
        q=q,
        cursor=cursor,
        limit=limit,
        kind=kind,
        category=category,
        ownership_kind=ownership_kind,
        owner_member_id=owner_member_id,
        inclusion_status=inclusion_status,
        status=status,
    )


@router.post(
    "",
    response_model=AssetResponse,
    status_code=201,
    operation_id="createAsset",
    responses={201: {"headers": CREATED_HEADERS}},
)
def create_asset(
    payload: AssetCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
) -> AssetResponse:
    result = service.create_asset(session, principal, payload)
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Location"] = f"/api/v1/assets/{result.id}"
    return result


@router.get(
    "/{asset_id}",
    response_model=AssetResponse,
    operation_id="getAsset",
    responses={200: {"headers": ETAG_HEADER}},
)
def get_asset(
    asset_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
) -> AssetResponse:
    result = service.get_asset(session, principal, asset_id)
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.patch(
    "/{asset_id}",
    response_model=AssetResponse,
    operation_id="updateAsset",
    responses={200: {"headers": ETAG_HEADER}},
)
def update_asset(
    asset_id: UUID,
    payload: AssetPatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
) -> AssetResponse:
    result = service.update_asset(session, principal, asset_id, payload, if_match)
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.post(
    "/{asset_id}/archive",
    response_model=AssetResponse,
    operation_id="archiveAsset",
    responses={200: {"headers": ETAG_HEADER}},
)
def archive_asset(
    asset_id: UUID,
    payload: AssetArchive,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
) -> AssetResponse:
    result = service.archive_asset(session, principal, asset_id, payload, if_match)
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.delete("/{asset_id}", status_code=204, operation_id="deleteAsset")
def delete_asset(
    asset_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    if_match: IfMatch,
) -> Response:
    service.delete_asset(session, principal, asset_id, if_match)
    return Response(status_code=204)
