from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from sallimbook.assets.schemas import DateOnly
from sallimbook.core.name_search import NameQuery
from sallimbook.homecare import order_service as service
from sallimbook.homecare.order_schemas import (
    ConsumableOrderCancel,
    ConsumableOrderCreate,
    ConsumableOrderListResponse,
    ConsumableOrderPatch,
    ConsumableOrderReceive,
    ConsumableOrderReference,
    ConsumableOrderResponse,
    ConsumableOrderSubmit,
    OrderFilter,
    PurchasePlanResponse,
)
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(tags=["homecare"])
IfMatch = Annotated[str, Header(alias="If-Match")]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]
Limit = Annotated[int, Query(ge=1, le=200)]
ETAG_HEADERS = {
    "ETag": {
        "description": "Quoted current version, or captured command version on replay.",
        "schema": {"type": "string"},
    }
}
LOCATION_HEADER = {
    "Location": {"description": "Current order resource path.", "schema": {"type": "string"}}
}


def metadata(response, result):
    response.headers["Cache-Control"] = "no-store"
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.get(
    "/homecare/purchase-plan", response_model=PurchasePlanResponse, operation_id="getPurchasePlan"
)
def purchase_plan(
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    through: DateOnly | None = None,
    q: NameQuery = None,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    response.headers["Cache-Control"] = "no-store"
    return service.purchase_plan(
        session, principal, through=through, q=q, cursor=cursor, limit=limit
    )


@router.get(
    "/consumable-orders",
    response_model=ConsumableOrderListResponse,
    operation_id="listConsumableOrders",
)
def list_orders(
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    state: OrderFilter = "open",
    consumable_id: UUID | None = None,
    q: NameQuery = None,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    response.headers["Cache-Control"] = "no-store"
    return service.list_orders(
        session,
        principal,
        state=state,
        consumable_id=consumable_id,
        q=q,
        cursor=cursor,
        limit=limit,
    )


@router.post(
    "/consumable-orders",
    response_model=ConsumableOrderReference,
    status_code=201,
    operation_id="createConsumableOrder",
    responses={201: {"headers": ETAG_HEADERS | LOCATION_HEADER}},
)
def create_order(
    payload: ConsumableOrderCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    key: IdempotencyKey,
):
    result = service.create_order(session, principal, payload, key)
    response.headers["Location"] = f"/api/v1/consumable-orders/{result.id}"
    return metadata(response, result)


@router.get(
    "/consumable-orders/{order_id}",
    response_model=ConsumableOrderResponse,
    operation_id="getConsumableOrder",
    responses={200: {"headers": ETAG_HEADERS}},
)
def get_order(
    order_id: UUID, principal: PrincipalDependency, session: SessionDependency, response: Response
):
    return metadata(response, service.get_order(session, principal, order_id))


@router.patch(
    "/consumable-orders/{order_id}",
    response_model=ConsumableOrderResponse,
    operation_id="updateConsumableOrder",
    responses={200: {"headers": ETAG_HEADERS}},
)
def update_order(
    order_id: UUID,
    payload: ConsumableOrderPatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
):
    return metadata(response, service.update_order(session, principal, order_id, payload, if_match))


@router.post(
    "/consumable-orders/{order_id}/submit",
    response_model=ConsumableOrderReference,
    operation_id="submitConsumableOrder",
    responses={200: {"headers": ETAG_HEADERS}},
)
def submit_order(
    order_id: UUID,
    payload: ConsumableOrderSubmit,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    key: IdempotencyKey,
):
    return metadata(
        response,
        service.order_command(session, principal, order_id, payload, if_match, key, "submit"),
    )


@router.post(
    "/consumable-orders/{order_id}/receive",
    response_model=ConsumableOrderReference,
    operation_id="receiveConsumableOrder",
    responses={200: {"headers": ETAG_HEADERS}},
)
def receive_order(
    order_id: UUID,
    payload: ConsumableOrderReceive,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    key: IdempotencyKey,
):
    return metadata(
        response,
        service.order_command(session, principal, order_id, payload, if_match, key, "receive"),
    )


@router.post(
    "/consumable-orders/{order_id}/cancel",
    response_model=ConsumableOrderReference,
    operation_id="cancelConsumableOrder",
    responses={200: {"headers": ETAG_HEADERS}},
)
def cancel_order(
    order_id: UUID,
    payload: ConsumableOrderCancel,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    key: IdempotencyKey,
):
    return metadata(
        response,
        service.order_command(session, principal, order_id, payload, if_match, key, "cancel"),
    )
