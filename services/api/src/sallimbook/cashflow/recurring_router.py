from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from sallimbook.cashflow import recurring_service as service
from sallimbook.cashflow.recurring_schemas import (
    FixedSummaryResponse,
    GenerateObligations,
    GenerationResponse,
    MutationReference,
    ObligationAction,
    ObligationHistoryResponse,
    ObligationListResponse,
    ObligationReschedule,
    ObligationResponse,
    RuleChange,
    RuleCreate,
    RuleEnd,
    RuleListResponse,
    RuleResponse,
    SettlementCreate,
    SettlementListResponse,
    SettlementResponse,
)
from sallimbook.core.types import YearMonth
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(prefix="/api/v1", tags=["fixed-costs"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]
IfMatch = Annotated[str, Header(alias="If-Match")]
Limit = Annotated[int, Query(ge=1, le=200)]


def _etag(response, result):
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.get("/recurring-rules", response_model=RuleListResponse, operation_id="listRecurringRules")
def rules(
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_rules(session, principal, cursor=cursor, limit=limit)


@router.post(
    "/recurring-rules",
    response_model=MutationReference,
    status_code=201,
    operation_id="createRecurringRule",
)
def create(
    payload: RuleCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    idempotency_key: IdempotencyKey,
):
    result = service.create_rule(session, principal, payload, idempotency_key)
    response.headers["Location"] = f"/api/v1/recurring-rules/{result.id}"
    return _etag(response, result)


@router.get(
    "/recurring-rules/{rule_id}", response_model=RuleResponse, operation_id="getRecurringRule"
)
def rule(
    rule_id: UUID, principal: PrincipalDependency, session: SessionDependency, response: Response
):
    return _etag(response, service.get_rule(session, principal, rule_id))


@router.patch(
    "/recurring-rules/{rule_id}",
    response_model=MutationReference,
    operation_id="changeRecurringRule",
)
def change(
    rule_id: UUID,
    payload: RuleChange,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _etag(
        response,
        service.change_rule(session, principal, rule_id, payload, if_match, idempotency_key),
    )


@router.post(
    "/recurring-rules/{rule_id}/end",
    response_model=MutationReference,
    operation_id="endRecurringRule",
)
def end(
    rule_id: UUID,
    payload: RuleEnd,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _etag(
        response, service.end_rule(session, principal, rule_id, payload, if_match, idempotency_key)
    )


@router.delete("/recurring-rules/{rule_id}", status_code=204, operation_id="deleteRecurringRule")
def delete_rule(
    rule_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    service.delete_rule(session, principal, rule_id, if_match, idempotency_key)
    return Response(status_code=204)


@router.post(
    "/obligations/generate",
    response_model=GenerationResponse,
    status_code=201,
    operation_id="generateObligations",
)
def generate(
    payload: GenerateObligations,
    principal: PrincipalDependency,
    session: SessionDependency,
    idempotency_key: IdempotencyKey,
):
    return service.generate(session, principal, payload, idempotency_key)


@router.get("/obligations", response_model=ObligationListResponse, operation_id="listObligations")
def obligations(
    principal: PrincipalDependency,
    session: SessionDependency,
    month: YearMonth,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_obligations(session, principal, month, cursor=cursor, limit=limit)


@router.get(
    "/obligations/summary", response_model=FixedSummaryResponse, operation_id="fixedCostSummary"
)
def summary(principal: PrincipalDependency, session: SessionDependency, month: YearMonth):
    return service.summary(session, principal, month)


@router.get(
    "/obligations/{obligation_id}", response_model=ObligationResponse, operation_id="getObligation"
)
def obligation(
    obligation_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    return _etag(response, service.get_obligation(session, principal, obligation_id))


@router.get(
    "/obligations/{obligation_id}/history",
    response_model=ObligationHistoryResponse,
    operation_id="obligationHistory",
)
def history(
    obligation_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: Annotated[int | None, Query(ge=1)] = None,
    limit: Limit = 50,
):
    return service.obligation_history(session, principal, obligation_id, cursor=cursor, limit=limit)


@router.patch(
    "/obligations/{obligation_id}",
    response_model=MutationReference,
    operation_id="rescheduleObligation",
)
def reschedule(
    obligation_id: UUID,
    payload: ObligationReschedule,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _etag(
        response,
        service.obligation_action(
            session,
            principal,
            obligation_id,
            payload,
            if_match,
            idempotency_key,
            action="reschedule",
        ),
    )


def _action_route(action, operation_id):
    def handler(
        obligation_id: UUID,
        payload: ObligationAction,
        principal: PrincipalDependency,
        session: SessionDependency,
        response: Response,
        if_match: IfMatch,
        idempotency_key: IdempotencyKey,
    ):
        return _etag(
            response,
            service.obligation_action(
                session, principal, obligation_id, payload, if_match, idempotency_key, action=action
            ),
        )

    router.add_api_route(
        f"/obligations/{{obligation_id}}/{action}",
        handler,
        methods=["POST"],
        response_model=MutationReference,
        operation_id=operation_id,
    )


for _action, _operation in (
    ("skip", "skipObligation"),
    ("unskip", "unskipObligation"),
    ("complete", "completeObligation"),
    ("reopen", "reopenObligation"),
):
    _action_route(_action, _operation)


@router.post(
    "/obligations/{obligation_id}/settlements",
    response_model=SettlementResponse,
    status_code=201,
    operation_id="settleObligation",
)
def settle(
    obligation_id: UUID,
    payload: SettlementCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    result = service.settle(session, principal, obligation_id, payload, if_match, idempotency_key)
    response.headers["ETag"] = f'"{result.cash.version}"'
    return result


@router.get(
    "/obligations/{obligation_id}/settlements",
    response_model=SettlementListResponse,
    operation_id="listObligationSettlements",
)
def settlements(
    obligation_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_settlements(session, principal, obligation_id, cursor=cursor, limit=limit)


@router.post(
    "/settlements/{settlement_id}/void",
    response_model=SettlementResponse,
    operation_id="voidFixedSettlement",
)
def void(
    settlement_id: UUID,
    payload: ObligationAction,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    result = service.void_settlement(
        session, principal, settlement_id, payload, if_match, idempotency_key
    )
    response.headers["ETag"] = f'"{result.cash.version}"'
    return result


# Declare returned version headers in the generated client contract. Settlement
# versions belong to the cash fact; obligation mutations return their own version.
for _route in router.routes:
    if getattr(_route, "operation_id", None) in {
        "createRecurringRule",
        "getRecurringRule",
        "changeRecurringRule",
        "endRecurringRule",
        "getObligation",
        "rescheduleObligation",
        "skipObligation",
        "unskipObligation",
        "completeObligation",
        "reopenObligation",
        "settleObligation",
        "voidFixedSettlement",
    }:
        _status = _route.status_code or 200
        _description = (
            "Quoted cash fact version for settlement cancellation."
            if _route.operation_id in {"settleObligation", "voidFixedSettlement"}
            else "Quoted resource version for If-Match."
        )
        _headers = {"ETag": {"description": _description, "schema": {"type": "string"}}}
        if _route.operation_id == "createRecurringRule":
            _headers["Location"] = {
                "description": "Created recurring rule path.",
                "schema": {"type": "string"},
            }
        _route.responses[_status] = {"headers": _headers}
