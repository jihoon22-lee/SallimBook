from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from sallimbook.identity.dependencies import (
    PeopleCapability,
    PrincipalDependency,
    SessionDependency,
)
from sallimbook.insurance import service
from sallimbook.insurance.schemas import (
    CaseHistoryResponse,
    CaseInput,
    CaseListResponse,
    CasePatch,
    CaseResponse,
    CoverageInput,
    CoverageListResponse,
    CoveragePatch,
    CoverageResponse,
    FinancialState,
    MedicalNodeInput,
    MedicalNodeListResponse,
    MedicalNodePatch,
    MedicalNodeResponse,
    PolicyCreate,
    PolicyListResponse,
    PolicyPatch,
    PolicyResponse,
    PolicyRevealResponse,
    PolicyStatus,
    PremiumLinkCreate,
    PremiumLinkListResponse,
    PremiumLinkPatch,
    PremiumLinkResponse,
    TreatmentState,
)

router = APIRouter(prefix="/api/v1/insurance", tags=["insurance"])
IfMatch = Annotated[str, Header(alias="If-Match")]
Limit = Annotated[int, Query(ge=1, le=200)]
ETAG_HEADERS = {
    "ETag": {"description": "Quoted resource version for If-Match.", "schema": {"type": "string"}}
}
CREATED_HEADERS = {
    **ETAG_HEADERS,
    "Location": {"description": "Created resource path.", "schema": {"type": "string"}},
}


def _etag(response, result, location=None):
    response.headers["ETag"] = f'"{result.version}"'
    if location is not None:
        response.headers["Location"] = location
    return result


@router.post(
    "/policies",
    response_model=PolicyResponse,
    status_code=201,
    operation_id="createInsurancePolicy",
    responses={201: {"headers": CREATED_HEADERS}},
)
def create_policy(
    payload: PolicyCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    people_supported: PeopleCapability,
    request: Request,
    response: Response,
):
    result = service.create_policy(
        session,
        principal,
        payload,
        request.app.state.settings.field_encryption_key_file,
        request_id=request.state.request_id,
        people_supported=people_supported,
    )
    return _etag(response, result, f"/api/v1/insurance/policies/{result.id}")


@router.get("/policies", response_model=PolicyListResponse, operation_id="listInsurancePolicies")
def list_policies(
    principal: PrincipalDependency,
    session: SessionDependency,
    status: PolicyStatus | None = None,
    insured_member_id: UUID | None = None,
    policyholder_member_id: UUID | None = None,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_policies(
        session,
        principal,
        status=status,
        insured_member_id=insured_member_id,
        policyholder_member_id=policyholder_member_id,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/policies/{policy_id}",
    response_model=PolicyResponse,
    operation_id="getInsurancePolicy",
    responses={200: {"headers": ETAG_HEADERS}},
)
def get_policy(
    policy_id: UUID, principal: PrincipalDependency, session: SessionDependency, response: Response
):
    return _etag(response, service.get_policy(session, principal, policy_id))


@router.patch(
    "/policies/{policy_id}",
    response_model=PolicyResponse,
    operation_id="updateInsurancePolicy",
    responses={200: {"headers": ETAG_HEADERS}},
)
def update_policy(
    policy_id: UUID,
    payload: PolicyPatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    people_supported: PeopleCapability,
    request: Request,
    response: Response,
    if_match: IfMatch,
):
    return _etag(
        response,
        service.update_policy(
            session,
            principal,
            policy_id,
            payload,
            if_match,
            request.app.state.settings.field_encryption_key_file,
            request_id=request.state.request_id,
            people_supported=people_supported,
        ),
    )


@router.post(
    "/policies/{policy_id}/reveal",
    response_model=PolicyRevealResponse,
    operation_id="revealInsurancePolicyNumber",
)
def reveal_policy_number(
    policy_id: UUID, principal: PrincipalDependency, session: SessionDependency, request: Request
):
    return service.reveal_policy_number(
        session,
        principal,
        policy_id,
        request.app.state.settings.field_encryption_key_file,
        request_id=request.state.request_id,
    )


@router.post(
    "/policies/{policy_id}/coverages",
    response_model=CoverageResponse,
    status_code=201,
    operation_id="createInsuranceCoverage",
    responses={201: {"headers": CREATED_HEADERS}},
)
def create_coverage(
    policy_id: UUID,
    payload: CoverageInput,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    result = service.create_coverage(session, principal, policy_id, payload)
    return _etag(response, result, f"/api/v1/insurance/policies/{policy_id}/coverages/{result.id}")


@router.get(
    "/policies/{policy_id}/coverages",
    response_model=CoverageListResponse,
    operation_id="listInsuranceCoverages",
)
def list_coverages(
    policy_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    active: bool | None = None,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_coverages(
        session, principal, policy_id, active=active, cursor=cursor, limit=limit
    )


@router.patch(
    "/policies/{policy_id}/coverages/{coverage_id}",
    response_model=CoverageResponse,
    operation_id="updateInsuranceCoverage",
    responses={200: {"headers": ETAG_HEADERS}},
)
def update_coverage(
    policy_id: UUID,
    coverage_id: UUID,
    payload: CoveragePatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
):
    return _etag(
        response,
        service.update_coverage(session, principal, policy_id, coverage_id, payload, if_match),
    )


@router.post(
    "/policies/{policy_id}/premium-links",
    response_model=PremiumLinkResponse,
    status_code=201,
    operation_id="createPolicyPremiumLink",
    responses={201: {"headers": CREATED_HEADERS}},
)
def create_premium_link(
    policy_id: UUID,
    payload: PremiumLinkCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    result = service.create_premium_link(session, principal, policy_id, payload)
    return _etag(
        response, result, f"/api/v1/insurance/policies/{policy_id}/premium-links/{result.id}"
    )


@router.get(
    "/policies/{policy_id}/premium-links",
    response_model=PremiumLinkListResponse,
    operation_id="listPolicyPremiumLinks",
)
def list_premium_links(
    policy_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    active: bool | None = None,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_premium_links(
        session, principal, policy_id, active=active, cursor=cursor, limit=limit
    )


@router.patch(
    "/policies/{policy_id}/premium-links/{link_id}",
    response_model=PremiumLinkResponse,
    operation_id="updatePolicyPremiumLink",
    responses={200: {"headers": ETAG_HEADERS}},
)
def update_premium_link(
    policy_id: UUID,
    link_id: UUID,
    payload: PremiumLinkPatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
):
    return _etag(
        response,
        service.update_premium_link(session, principal, policy_id, link_id, payload, if_match),
    )


@router.post(
    "/cases",
    response_model=CaseResponse,
    status_code=201,
    operation_id="createInsuranceCase",
    responses={201: {"headers": CREATED_HEADERS}},
)
def create_case(
    payload: CaseInput,
    principal: PrincipalDependency,
    session: SessionDependency,
    people_supported: PeopleCapability,
    response: Response,
):
    result = service.create_case(
        session,
        principal,
        payload,
        people_supported=people_supported,
    )
    return _etag(response, result, f"/api/v1/insurance/cases/{result.id}")


@router.get("/cases", response_model=CaseListResponse, operation_id="listInsuranceCases")
def list_cases(
    principal: PrincipalDependency,
    session: SessionDependency,
    patient_member_id: UUID | None = None,
    treatment_state: TreatmentState | None = None,
    financial_state: FinancialState | None = None,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_cases(
        session,
        principal,
        patient_member_id=patient_member_id,
        treatment_state=treatment_state,
        financial_state=financial_state,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/cases/{case_id}",
    response_model=CaseResponse,
    operation_id="getInsuranceCase",
    responses={200: {"headers": ETAG_HEADERS}},
)
def get_case(
    case_id: UUID, principal: PrincipalDependency, session: SessionDependency, response: Response
):
    return _etag(response, service.get_case(session, principal, case_id))


@router.patch(
    "/cases/{case_id}",
    response_model=CaseResponse,
    operation_id="updateInsuranceCase",
    responses={200: {"headers": ETAG_HEADERS}},
)
def update_case(
    case_id: UUID,
    payload: CasePatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    people_supported: PeopleCapability,
    response: Response,
    if_match: IfMatch,
):
    return _etag(
        response,
        service.update_case(
            session,
            principal,
            case_id,
            payload,
            if_match,
            people_supported=people_supported,
        ),
    )


@router.get(
    "/cases/{case_id}/history",
    response_model=CaseHistoryResponse,
    operation_id="insuranceCaseHistory",
)
def case_history(
    case_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: Annotated[int | None, Query(ge=1)] = None,
    limit: Limit = 50,
):
    return service.case_history(session, principal, case_id, cursor=cursor, limit=limit)


@router.post(
    "/cases/{case_id}/nodes",
    response_model=MedicalNodeResponse,
    status_code=201,
    operation_id="createMedicalNode",
    responses={201: {"headers": CREATED_HEADERS}},
)
def create_node(
    case_id: UUID,
    payload: MedicalNodeInput,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    result = service.create_node(session, principal, case_id, payload)
    return _etag(response, result, f"/api/v1/insurance/cases/{case_id}/nodes/{result.id}")


@router.get(
    "/cases/{case_id}/nodes",
    response_model=MedicalNodeListResponse,
    operation_id="listMedicalNodes",
)
def list_nodes(
    case_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_nodes(session, principal, case_id, cursor=cursor, limit=limit)


@router.get(
    "/cases/{case_id}/nodes/{node_id}",
    response_model=MedicalNodeResponse,
    operation_id="getMedicalNode",
    responses={200: {"headers": ETAG_HEADERS}},
)
def get_node(
    case_id: UUID,
    node_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    return _etag(response, service.get_node(session, principal, case_id, node_id))


@router.patch(
    "/cases/{case_id}/nodes/{node_id}",
    response_model=MedicalNodeResponse,
    operation_id="updateMedicalNode",
    responses={200: {"headers": ETAG_HEADERS}},
)
def update_node(
    case_id: UUID,
    node_id: UUID,
    payload: MedicalNodePatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
):
    return _etag(
        response, service.update_node(session, principal, case_id, node_id, payload, if_match)
    )


@router.delete(
    "/cases/{case_id}/nodes/{node_id}", status_code=204, operation_id="deleteMedicalNode"
)
def delete_node(
    case_id: UUID,
    node_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    if_match: IfMatch,
):
    service.delete_node(session, principal, case_id, node_id, if_match)
    return Response(status_code=204)


@router.delete("/policies/{policy_id}", status_code=204, operation_id="deleteInsurancePolicy")
def delete_policy(
    policy_id: UUID, principal: PrincipalDependency, session: SessionDependency, if_match: IfMatch
):
    service.delete_policy(session, principal, policy_id, if_match)
    return Response(status_code=204)


@router.delete("/cases/{case_id}", status_code=204, operation_id="deleteInsuranceCase")
def delete_case(
    case_id: UUID, principal: PrincipalDependency, session: SessionDependency, if_match: IfMatch
):
    service.delete_case(session, principal, case_id, if_match)
    return Response(status_code=204)
