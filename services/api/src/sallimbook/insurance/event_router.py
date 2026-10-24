from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency
from sallimbook.insurance import event_service as service
from sallimbook.insurance.event_schemas import (
    AllocationHistoryResponse,
    AllocationLinkPatch,
    AllocationResponse,
    CaseSummaryResponse,
    ClaimCreate,
    ClaimHistoryResponse,
    ClaimListResponse,
    ClaimPatch,
    ClaimResponse,
    ClaimState,
    EventCashHistoryResponse,
    EventReason,
    EventReference,
    ExpenseCorrection,
    ExpenseCreate,
    ExpenseListResponse,
    ExpenseResponse,
    NodeSummaryResponse,
    PayoutCorrection,
    PayoutCreate,
    PayoutListResponse,
    PayoutResponse,
    RefundCreate,
    RefundListResponse,
    RefundResponse,
    ReturnCreate,
    ReturnListResponse,
    ReturnResponse,
)

router = APIRouter(prefix="/api/v1/insurance", tags=["insurance-events"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]
OptionalIdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", min_length=1, max_length=128)
]
IfMatch = Annotated[str, Header(alias="If-Match")]
Limit = Annotated[int, Query(ge=1, le=200)]
HistoryCursor = Annotated[int | None, Query(ge=1)]
ETAG_HEADERS = {
    "ETag": {
        "description": "Quoted domain resource version for If-Match.",
        "schema": {"type": "string"},
    }
}
CREATED_HEADERS = {
    **ETAG_HEADERS,
    "Location": {"description": "Created domain resource path.", "schema": {"type": "string"}},
}


def _etag(response, result, location=None):
    response.headers["ETag"] = f'"{result.version}"'
    if location is not None:
        response.headers["Location"] = location
    return result


def _source_routes(
    collection,
    stem,
    kind,
    create_schema,
    response_schema,
    correction_schema,
    get_service,
    void_service,
    correct_service,
    create_service=None,
):
    def get(
        resource_id: UUID,
        principal: PrincipalDependency,
        session: SessionDependency,
        response: Response,
    ):
        return _etag(response, get_service(session, principal, resource_id))

    def void(
        resource_id: UUID,
        payload: EventReason,
        principal: PrincipalDependency,
        session: SessionDependency,
        response: Response,
        if_match: IfMatch,
        idempotency_key: IdempotencyKey,
    ):
        return _etag(
            response,
            void_service(session, principal, resource_id, payload, if_match, idempotency_key),
        )

    def correct(
        resource_id: UUID,
        payload: correction_schema,
        principal: PrincipalDependency,
        session: SessionDependency,
        response: Response,
        if_match: IfMatch,
        idempotency_key: IdempotencyKey,
    ):
        result = correct_service(
            session, principal, resource_id, payload, if_match, idempotency_key
        )
        return _etag(response, result, f"/api/v1/insurance/{collection}/{result.id}")

    def history(
        resource_id: UUID,
        principal: PrincipalDependency,
        session: SessionDependency,
        cursor: HistoryCursor = None,
        limit: Limit = 50,
    ):
        return service.event_cash_history(
            session, principal, kind, resource_id, cursor=cursor, limit=limit
        )

    base = f"/{collection}/{{resource_id}}"
    router.add_api_route(
        base,
        get,
        methods=["GET"],
        response_model=response_schema,
        operation_id=f"get{stem}",
        responses={200: {"headers": ETAG_HEADERS}},
    )
    router.add_api_route(
        base + "/void",
        void,
        methods=["POST"],
        response_model=EventReference,
        operation_id=f"void{stem}",
        responses={200: {"headers": ETAG_HEADERS}},
    )
    router.add_api_route(
        base + "/correct",
        correct,
        methods=["POST"],
        response_model=EventReference,
        status_code=201,
        operation_id=f"correct{stem}",
        responses={201: {"headers": CREATED_HEADERS}},
    )
    router.add_api_route(
        base + "/history",
        history,
        methods=["GET"],
        response_model=EventCashHistoryResponse,
        operation_id=f"{stem[0].lower() + stem[1:]}History",
    )
    if create_service is not None:

        def create(
            payload: create_schema,
            principal: PrincipalDependency,
            session: SessionDependency,
            response: Response,
            idempotency_key: IdempotencyKey,
        ):
            result = create_service(session, principal, payload, idempotency_key)
            return _etag(response, result, f"/api/v1/insurance/{collection}/{result.id}")

        router.add_api_route(
            f"/{collection}",
            create,
            methods=["POST"],
            response_model=EventReference,
            status_code=201,
            operation_id=f"create{stem}",
            responses={201: {"headers": CREATED_HEADERS}},
        )


_source_routes(
    "medical-expenses",
    "MedicalExpense",
    "medical_expense",
    ExpenseCreate,
    ExpenseResponse,
    ExpenseCorrection,
    service.get_expense,
    service.void_expense,
    service.correct_expense,
    service.create_expense,
)
_source_routes(
    "medical-refunds",
    "MedicalRefund",
    "medical_refund",
    RefundCreate,
    RefundResponse,
    RefundCreate,
    service.get_refund,
    service.void_refund,
    service.correct_refund,
)
_source_routes(
    "payouts",
    "InsurancePayout",
    "insurance_payout",
    PayoutCreate,
    PayoutResponse,
    PayoutCorrection,
    service.get_payout,
    service.void_payout,
    service.correct_payout,
    service.create_payout,
)
_source_routes(
    "returns",
    "InsuranceReturn",
    "insurance_return",
    ReturnCreate,
    ReturnResponse,
    ReturnCreate,
    service.get_return,
    service.void_return,
    service.correct_return,
)


@router.get(
    "/medical-expenses", response_model=ExpenseListResponse, operation_id="listMedicalExpenses"
)
def list_expenses(
    principal: PrincipalDependency,
    session: SessionDependency,
    case_id: UUID | None = None,
    node_id: UUID | None = None,
    state: Literal["active", "void"] | None = None,
    claim_policy_id: UUID | None = None,
    claimed: bool | None = None,
    unclaimed_any_policy: bool = False,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_expenses(
        session,
        principal,
        case_id=case_id,
        node_id=node_id,
        state=state,
        claim_policy_id=claim_policy_id,
        claimed=claimed,
        unclaimed_any_policy=unclaimed_any_policy,
        cursor=cursor,
        limit=limit,
    )


@router.post(
    "/medical-expenses/{resource_id}/refunds",
    response_model=EventReference,
    status_code=201,
    operation_id="createMedicalRefund",
    responses={201: {"headers": CREATED_HEADERS}},
)
def create_refund(
    resource_id: UUID,
    payload: RefundCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    result = service.create_refund(
        session, principal, resource_id, payload, if_match, idempotency_key
    )
    return _etag(response, result, f"/api/v1/insurance/medical-refunds/{result.id}")


@router.get(
    "/medical-expenses/{resource_id}/refunds",
    response_model=RefundListResponse,
    operation_id="listMedicalRefunds",
)
def list_refunds(
    resource_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_refunds(session, principal, resource_id, cursor=cursor, limit=limit)


@router.get("/payouts", response_model=PayoutListResponse, operation_id="listInsurancePayouts")
def list_payouts(
    principal: PrincipalDependency,
    session: SessionDependency,
    case_id: UUID | None = None,
    policy_id: UUID | None = None,
    claim_id: UUID | None = None,
    state: Literal["active", "void"] | None = None,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_payouts(
        session,
        principal,
        case_id=case_id,
        policy_id=policy_id,
        claim_id=claim_id,
        state=state,
        cursor=cursor,
        limit=limit,
    )


@router.post(
    "/payouts/{resource_id}/returns",
    response_model=EventReference,
    status_code=201,
    operation_id="createInsuranceReturn",
    responses={201: {"headers": CREATED_HEADERS}},
)
def create_return(
    resource_id: UUID,
    payload: ReturnCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    result = service.create_return(
        session, principal, resource_id, payload, if_match, idempotency_key
    )
    return _etag(response, result, f"/api/v1/insurance/returns/{result.id}")


@router.get(
    "/payouts/{resource_id}/returns",
    response_model=ReturnListResponse,
    operation_id="listInsuranceReturns",
)
def list_returns(
    resource_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_returns(session, principal, resource_id, cursor=cursor, limit=limit)


@router.post(
    "/claims",
    response_model=ClaimResponse,
    status_code=201,
    operation_id="createInsuranceClaim",
    responses={201: {"headers": CREATED_HEADERS}},
)
def create_claim(
    payload: ClaimCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    idempotency_key: OptionalIdempotencyKey = None,
):
    result = service.create_claim(session, principal, payload, idempotency_key)
    return _etag(response, result, f"/api/v1/insurance/claims/{result.id}")


@router.get("/claims", response_model=ClaimListResponse, operation_id="listInsuranceClaims")
def list_claims(
    principal: PrincipalDependency,
    session: SessionDependency,
    case_id: UUID | None = None,
    policy_id: UUID | None = None,
    claim_state: ClaimState | None = None,
    expense_id: UUID | None = None,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_claims(
        session,
        principal,
        case_id=case_id,
        policy_id=policy_id,
        claim_state=claim_state,
        expense_id=expense_id,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/claims/{claim_id}",
    response_model=ClaimResponse,
    operation_id="getInsuranceClaim",
    responses={200: {"headers": ETAG_HEADERS}},
)
def get_claim(
    claim_id: UUID, principal: PrincipalDependency, session: SessionDependency, response: Response
):
    return _etag(response, service.get_claim(session, principal, claim_id))


@router.patch(
    "/claims/{claim_id}",
    response_model=ClaimResponse,
    operation_id="updateInsuranceClaim",
    responses={200: {"headers": ETAG_HEADERS}},
)
def update_claim(
    claim_id: UUID,
    payload: ClaimPatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
):
    return _etag(response, service.update_claim(session, principal, claim_id, payload, if_match))


@router.get(
    "/claims/{claim_id}/history",
    response_model=ClaimHistoryResponse,
    operation_id="insuranceClaimHistory",
)
def claim_history(
    claim_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: HistoryCursor = None,
    limit: Limit = 50,
):
    return service.claim_history(session, principal, claim_id, cursor=cursor, limit=limit)


@router.get(
    "/payout-allocations/{allocation_id}",
    response_model=AllocationResponse,
    operation_id="getPayoutAllocation",
    responses={200: {"headers": ETAG_HEADERS}},
)
def get_allocation(
    allocation_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    return _etag(response, service.get_allocation(session, principal, allocation_id))


@router.patch(
    "/payout-allocations/{allocation_id}",
    response_model=EventReference,
    operation_id="linkPayoutAllocation",
    responses={200: {"headers": ETAG_HEADERS}},
)
def link_allocation(
    allocation_id: UUID,
    payload: AllocationLinkPatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _etag(
        response,
        service.update_allocation_links(
            session, principal, allocation_id, payload, if_match, idempotency_key
        ),
    )


@router.get(
    "/payout-allocations/{allocation_id}/history",
    response_model=AllocationHistoryResponse,
    operation_id="payoutAllocationHistory",
)
def allocation_history(
    allocation_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: HistoryCursor = None,
    limit: Limit = 50,
):
    return service.allocation_history(session, principal, allocation_id, cursor=cursor, limit=limit)


@router.get(
    "/cases/{case_id}/summary",
    response_model=CaseSummaryResponse,
    operation_id="insuranceCaseSummary",
)
def case_summary(case_id: UUID, principal: PrincipalDependency, session: SessionDependency):
    return service.case_summary(session, principal, case_id)


@router.get(
    "/cases/{case_id}/nodes/{node_id}/summary",
    response_model=NodeSummaryResponse,
    operation_id="medicalNodeSummary",
)
def node_summary(
    case_id: UUID, node_id: UUID, principal: PrincipalDependency, session: SessionDependency
):
    return service.node_summary(session, principal, case_id, node_id)
