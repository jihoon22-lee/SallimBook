from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from sallimbook.cashflow import payment_switch_service as service
from sallimbook.cashflow.payment_switch_schemas import (
    PaymentSwitchApply,
    PaymentSwitchInput,
    PaymentSwitchPreview,
)
from sallimbook.cashflow.recurring_router import IdempotencyKey, IfMatch, _etag
from sallimbook.cashflow.recurring_schemas import MutationReference
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(prefix="/api/v1/payment-switch", tags=["payment-links"])


@router.post("/preview", response_model=PaymentSwitchPreview, operation_id="previewPaymentSwitch")
def preview(
    payload: PaymentSwitchInput,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    return service.preview(session, principal, payload, cursor=cursor, limit=limit)


@router.post(
    "/rules/{rule_id}", response_model=MutationReference, operation_id="applyPaymentSwitch"
)
def apply(
    rule_id: UUID,
    payload: PaymentSwitchApply,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _etag(
        response, service.apply(session, principal, rule_id, payload, if_match, idempotency_key)
    )
