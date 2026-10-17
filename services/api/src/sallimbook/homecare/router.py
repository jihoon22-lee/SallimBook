from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from sallimbook.homecare import service
from sallimbook.homecare.schemas import (
    ApplianceConsumableCreate,
    ApplianceConsumableListResponse,
    ApplianceConsumablePatch,
    ApplianceConsumableResponse,
    ApplianceInput,
    ApplianceListResponse,
    AppliancePatch,
    ApplianceResponse,
    ConsumableInput,
    ConsumableListResponse,
    ConsumablePatch,
    ConsumableResponse,
    HomecareStatusResponse,
    ReplacementCreate,
    ReplacementListResponse,
    ReplacementResponse,
    StatusFilter,
    StockCancellation,
    StockMovementCreate,
    StockMovementListResponse,
    StockMovementResponse,
    StockMutationReference,
)
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(prefix="/api/v1", tags=["homecare"])
IfMatch = Annotated[str, Header(alias="If-Match")]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]
Limit = Annotated[int, Query(ge=1, le=200)]
ETAG_HEADERS = {
    "ETag": {"description": "Quoted metadata version for If-Match.", "schema": {"type": "string"}}
}
STOCK_HEADERS = {
    "ETag": {
        "description": "Captured consumable version; refetch after replay before another edit.",
        "schema": {"type": "string"},
    }
}


def _metadata(response, result, location=None):
    response.headers["ETag"] = f'"{result.version}"'
    if location is not None:
        response.headers["Location"] = location
    return result


def _stock(response, result):
    response.headers["ETag"] = f'"{result.stock_version}"'
    response.headers["Location"] = (
        f"/api/v1/consumables/{result.consumable_id}/stock-movements/{result.id}"
    )
    return result


@router.get("/appliances", response_model=ApplianceListResponse, operation_id="listAppliances")
def list_appliances(
    principal: PrincipalDependency,
    session: SessionDependency,
    status: StatusFilter = "active",
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_appliances(session, principal, status=status, cursor=cursor, limit=limit)


@router.post(
    "/appliances",
    response_model=ApplianceResponse,
    status_code=201,
    operation_id="createAppliance",
    responses={201: {"headers": ETAG_HEADERS}},
)
def create_appliance(
    payload: ApplianceInput,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    result = service.create_appliance(session, principal, payload)
    return _metadata(response, result, f"/api/v1/appliances/{result.id}")


@router.get(
    "/appliances/{appliance_id}",
    response_model=ApplianceResponse,
    operation_id="getAppliance",
    responses={200: {"headers": ETAG_HEADERS}},
)
def get_appliance(
    appliance_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    return _metadata(response, service.get_appliance(session, principal, appliance_id))


@router.patch(
    "/appliances/{appliance_id}",
    response_model=ApplianceResponse,
    operation_id="updateAppliance",
    responses={200: {"headers": ETAG_HEADERS}},
)
def update_appliance(
    appliance_id: UUID,
    payload: AppliancePatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
):
    return _metadata(
        response, service.update_appliance(session, principal, appliance_id, payload, if_match)
    )


@router.get("/consumables", response_model=ConsumableListResponse, operation_id="listConsumables")
def list_consumables(
    principal: PrincipalDependency,
    session: SessionDependency,
    status: StatusFilter = "active",
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_consumables(session, principal, status=status, cursor=cursor, limit=limit)


@router.post(
    "/consumables",
    response_model=ConsumableResponse,
    status_code=201,
    operation_id="createConsumable",
    responses={201: {"headers": ETAG_HEADERS}},
)
def create_consumable(
    payload: ConsumableInput,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    result = service.create_consumable(session, principal, payload)
    return _metadata(response, result, f"/api/v1/consumables/{result.id}")


@router.get(
    "/consumables/{consumable_id}",
    response_model=ConsumableResponse,
    operation_id="getConsumable",
    responses={200: {"headers": ETAG_HEADERS}},
)
def get_consumable(
    consumable_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    return _metadata(response, service.get_consumable(session, principal, consumable_id))


@router.patch(
    "/consumables/{consumable_id}",
    response_model=ConsumableResponse,
    operation_id="updateConsumable",
    responses={200: {"headers": ETAG_HEADERS}},
)
def update_consumable(
    consumable_id: UUID,
    payload: ConsumablePatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
):
    return _metadata(
        response, service.update_consumable(session, principal, consumable_id, payload, if_match)
    )


@router.get(
    "/appliance-consumables",
    response_model=ApplianceConsumableListResponse,
    operation_id="listApplianceConsumables",
)
def list_links(
    principal: PrincipalDependency,
    session: SessionDependency,
    appliance_id: UUID | None = None,
    consumable_id: UUID | None = None,
    active: bool | None = None,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_appliance_consumables(
        session,
        principal,
        appliance_id=appliance_id,
        consumable_id=consumable_id,
        active=active,
        cursor=cursor,
        limit=limit,
    )


@router.post(
    "/appliance-consumables",
    response_model=ApplianceConsumableResponse,
    status_code=201,
    operation_id="createApplianceConsumable",
    responses={201: {"headers": ETAG_HEADERS}},
)
def create_link(
    payload: ApplianceConsumableCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    result = service.create_appliance_consumable(session, principal, payload)
    return _metadata(response, result, f"/api/v1/appliance-consumables/{result.id}")


@router.get(
    "/appliance-consumables/{link_id}",
    response_model=ApplianceConsumableResponse,
    operation_id="getApplianceConsumable",
    responses={200: {"headers": ETAG_HEADERS}},
)
def get_link(
    link_id: UUID, principal: PrincipalDependency, session: SessionDependency, response: Response
):
    return _metadata(response, service.get_appliance_consumable(session, principal, link_id))


@router.patch(
    "/appliance-consumables/{link_id}",
    response_model=ApplianceConsumableResponse,
    operation_id="updateApplianceConsumable",
    responses={200: {"headers": ETAG_HEADERS}},
)
def update_link(
    link_id: UUID,
    payload: ApplianceConsumablePatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
):
    return _metadata(
        response,
        service.update_appliance_consumable(session, principal, link_id, payload, if_match),
    )


@router.get(
    "/consumables/{consumable_id}/stock-movements",
    response_model=StockMovementListResponse,
    operation_id="listStockMovements",
)
def list_movements(
    consumable_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_stock_movements(
        session, principal, consumable_id, cursor=cursor, limit=limit
    )


@router.post(
    "/consumables/{consumable_id}/stock-movements",
    response_model=StockMutationReference,
    status_code=201,
    operation_id="createStockMovement",
    responses={201: {"headers": STOCK_HEADERS}},
)
def create_movement(
    consumable_id: UUID,
    payload: StockMovementCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _stock(
        response,
        service.create_stock_movement(
            session, principal, consumable_id, payload, if_match, idempotency_key
        ),
    )


@router.get(
    "/consumables/{consumable_id}/stock-movements/{movement_id}",
    response_model=StockMovementResponse,
    operation_id="getStockMovement",
)
def get_movement(
    consumable_id: UUID,
    movement_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
):
    return service.get_stock_movement(session, principal, consumable_id, movement_id)


@router.post(
    "/consumables/{consumable_id}/stock-movements/{movement_id}/cancel",
    response_model=StockMutationReference,
    operation_id="cancelStockMovement",
    responses={200: {"headers": STOCK_HEADERS}},
)
def cancel_movement(
    consumable_id: UUID,
    movement_id: UUID,
    payload: StockCancellation,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _stock(
        response,
        service.cancel_stock_movement(
            session, principal, consumable_id, movement_id, payload, if_match, idempotency_key
        ),
    )


@router.get(
    "/appliance-consumables/{link_id}/replacements",
    response_model=ReplacementListResponse,
    operation_id="listConsumableReplacements",
)
def list_replacements(
    link_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_replacements(session, principal, link_id, cursor=cursor, limit=limit)


@router.post(
    "/appliance-consumables/{link_id}/replacements",
    response_model=StockMutationReference,
    status_code=201,
    operation_id="createConsumableReplacement",
    responses={201: {"headers": STOCK_HEADERS}},
)
def create_replacement(
    link_id: UUID,
    payload: ReplacementCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _stock(
        response,
        service.create_replacement(session, principal, link_id, payload, if_match, idempotency_key),
    )


@router.get(
    "/appliance-consumables/{link_id}/replacements/{replacement_id}",
    response_model=ReplacementResponse,
    operation_id="getConsumableReplacement",
)
def get_replacement(
    link_id: UUID, replacement_id: UUID, principal: PrincipalDependency, session: SessionDependency
):
    return service.get_replacement(session, principal, link_id, replacement_id)


@router.post(
    "/appliance-consumables/{link_id}/replacements/{replacement_id}/cancel",
    response_model=StockMutationReference,
    operation_id="cancelConsumableReplacement",
    responses={200: {"headers": STOCK_HEADERS}},
)
def cancel_replacement(
    link_id: UUID,
    replacement_id: UUID,
    payload: StockCancellation,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _stock(
        response,
        service.cancel_replacement(
            session, principal, link_id, replacement_id, payload, if_match, idempotency_key
        ),
    )


@router.get(
    "/homecare/status", response_model=HomecareStatusResponse, operation_id="getHomecareStatus"
)
def get_status(
    principal: PrincipalDependency,
    session: SessionDependency,
    appliance_id: UUID | None = None,
    consumable_id: UUID | None = None,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.homecare_status(
        session,
        principal,
        appliance_id=appliance_id,
        consumable_id=consumable_id,
        cursor=cursor,
        limit=limit,
    )
