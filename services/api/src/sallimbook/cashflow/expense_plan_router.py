from uuid import UUID

from fastapi import APIRouter, Response

from sallimbook.assets.schemas import DateOnly
from sallimbook.cashflow import expense_plan_service as service
from sallimbook.cashflow import payment_switch_service, recurring_service
from sallimbook.cashflow.expense_plan_schemas import (
    PlanChange,
    PlanCreate,
    PlanListResponse,
    PlanResponse,
    PlanSummaryResponse,
)
from sallimbook.cashflow.payment_switch_schemas import (
    PaymentSwitchApply,
    PaymentSwitchInput,
    PlanPaymentSwitchPreview,
)
from sallimbook.cashflow.recurring_router import IdempotencyKey, IfMatch, Limit, _etag
from sallimbook.cashflow.recurring_schemas import MutationReference, RuleEnd
from sallimbook.core.name_search import NameQuery
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(prefix="/api/v1", tags=["expense-plans"])


@router.get("/expense-plans", response_model=PlanListResponse, operation_id="listExpensePlans")
def plans(
    principal: PrincipalDependency,
    session: SessionDependency,
    q: NameQuery = None,
    cursor: UUID | None = None,
    limit: Limit = 50,
    account_id: UUID | None = None,
    card_id: UUID | None = None,
):
    return service.list_plans(
        session, principal, q=q, cursor=cursor, limit=limit, account_id=account_id, card_id=card_id
    )


@router.post(
    "/expense-plans",
    response_model=MutationReference,
    status_code=201,
    operation_id="createExpensePlan",
)
def create(
    payload: PlanCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    idempotency_key: IdempotencyKey,
):
    result = service.create_plan(session, principal, payload, idempotency_key)
    response.headers["Location"] = f"/api/v1/expense-plans/{result.id}"
    return _etag(response, result)


@router.get("/expense-plans/{plan_id}", response_model=PlanResponse, operation_id="getExpensePlan")
def get(
    plan_id: UUID, principal: PrincipalDependency, session: SessionDependency, response: Response
):
    return _etag(response, service.get_plan(session, principal, plan_id))


@router.patch(
    "/expense-plans/{plan_id}", response_model=MutationReference, operation_id="changeExpensePlan"
)
def change(
    plan_id: UUID,
    payload: PlanChange,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
):
    return _etag(
        response,
        service.change_plan(session, principal, plan_id, payload, if_match, idempotency_key),
    )


@router.post(
    "/expense-plans/{plan_id}/end", response_model=MutationReference, operation_id="endExpensePlan"
)
def end(
    plan_id: UUID,
    payload: RuleEnd,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
):
    return _etag(
        response,
        recurring_service.end_rule(
            session, principal, plan_id, payload, if_match, idempotency_key, plan=True
        ),
    )


@router.delete("/expense-plans/{plan_id}", status_code=204, operation_id="deleteExpensePlan")
def delete(
    plan_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
):
    recurring_service.delete_rule(session, principal, plan_id, if_match, idempotency_key, plan=True)
    return Response(status_code=204)


@router.get(
    "/expense-plan-summary", response_model=PlanSummaryResponse, operation_id="expensePlanSummary"
)
def summary(
    principal: PrincipalDependency, session: SessionDependency, as_of: DateOnly | None = None
):
    return service.summary(session, principal, as_of)


for route in router.routes:
    if route.operation_id in {
        "createExpensePlan",
        "getExpensePlan",
        "changeExpensePlan",
        "endExpensePlan",
    }:
        headers = {
            "ETag": {
                "description": "Quoted resource version for If-Match.",
                "schema": {"type": "string"},
            }
        }
        if route.operation_id == "createExpensePlan":
            headers["Location"] = {
                "description": "Created expense plan path.",
                "schema": {"type": "string"},
            }
        route.responses[route.status_code or 200] = {"headers": headers}


@router.post(
    "/expense-plan-payment-switch/preview",
    response_model=PlanPaymentSwitchPreview,
    operation_id="previewExpensePlanPaymentSwitch",
)
def switch_preview(
    payload: PaymentSwitchInput,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return payment_switch_service.preview(
        session, principal, payload, cursor=cursor, limit=limit, plan=True
    )


@router.post(
    "/expense-plan-payment-switch/{plan_id}",
    response_model=MutationReference,
    operation_id="applyExpensePlanPaymentSwitch",
)
def switch_apply(
    plan_id: UUID,
    payload: PaymentSwitchApply,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _etag(
        response,
        payment_switch_service.apply(
            session, principal, plan_id, payload, if_match, idempotency_key, plan=True
        ),
    )
