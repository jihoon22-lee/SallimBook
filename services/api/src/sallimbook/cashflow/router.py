from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from sallimbook.cashflow import related_service, service
from sallimbook.cashflow.related_schemas import IncomeInsuranceSource
from sallimbook.cashflow.schemas import (
    CashResponse,
    ConversionResponse,
    DuplicateResponse,
    IncomeConvert,
    IncomeCreate,
    IncomeHistoryResponse,
    IncomeKind,
    IncomeListResponse,
    IncomePatch,
    IncomeReturn,
    IncomeSummaryResponse,
    IncomeVoid,
    Precision,
    ProjectedIncomeKind,
)
from sallimbook.core.types import YearMonth
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(prefix="/api/v1/income", tags=["income"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", max_length=128)]
IfMatch = Annotated[str, Header(alias="If-Match")]

ETAG_HEADERS = {
    "ETag": {"description": "Quoted immutable cash record version.", "schema": {"type": "string"}}
}
CREATED_HEADERS = {
    **ETAG_HEADERS,
    "Location": {"description": "Created income resource path.", "schema": {"type": "string"}},
}


def _etag(response: Response, result: CashResponse) -> CashResponse:
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.get("", response_model=IncomeListResponse, operation_id="listIncome")
def list_income(
    principal: PrincipalDependency,
    session: SessionDependency,
    month: YearMonth,
    member_id: UUID | None = None,
    kind: ProjectedIncomeKind | None = None,
    state: Literal["active", "void", "all"] = "active",
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    return service.list_income(
        session,
        principal,
        month,
        member_id=member_id,
        kind=kind,
        state=state,
        cursor=cursor,
        limit=limit,
    )


@router.get("/summary", response_model=IncomeSummaryResponse, operation_id="incomeSummary")
def summary(principal: PrincipalDependency, session: SessionDependency, month: YearMonth):
    return service.summary(session, principal, month)


@router.get(
    "/duplicates", response_model=DuplicateResponse, operation_id="incomeDuplicateCandidates"
)
def duplicates(
    principal: PrincipalDependency,
    session: SessionDependency,
    month: YearMonth,
    kind: IncomeKind,
    member_id: UUID,
    date_precision: Precision,
):
    return service.duplicates(
        session,
        principal,
        month=month,
        kind=kind,
        member_id=member_id,
        date_precision=date_precision,
    )


@router.post(
    "/convert",
    response_model=ConversionResponse,
    status_code=201,
    operation_id="convertIncomePrecision",
)
def convert(
    payload: IncomeConvert,
    principal: PrincipalDependency,
    session: SessionDependency,
    idempotency_key: IdempotencyKey,
):
    return service.convert_income(session, principal, payload, idempotency_key)


@router.post(
    "",
    response_model=CashResponse,
    status_code=201,
    operation_id="createIncome",
    responses={201: {"headers": CREATED_HEADERS}},
)
def create(
    payload: IncomeCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    idempotency_key: IdempotencyKey,
):
    result = service.create_income(session, principal, payload, idempotency_key)
    response.headers["Location"] = f"/api/v1/income/{result.id}"
    return _etag(response, result)


@router.get(
    "/{record_id}",
    response_model=CashResponse,
    operation_id="getIncome",
    responses={200: {"headers": ETAG_HEADERS}},
)
def get_income(
    record_id: UUID, principal: PrincipalDependency, session: SessionDependency, response: Response
):
    return _etag(response, service.get_income(session, principal, record_id))


@router.get(
    "/{record_id}/history", response_model=IncomeHistoryResponse, operation_id="incomeHistory"
)
def history(
    record_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    return service.history(session, principal, record_id, cursor=cursor, limit=limit)


@router.patch(
    "/{record_id}",
    response_model=CashResponse,
    operation_id="correctIncome",
    responses={200: {"headers": ETAG_HEADERS}},
)
def correct(
    record_id: UUID,
    payload: IncomePatch,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _etag(
        response,
        service.correct_income(session, principal, record_id, payload, if_match, idempotency_key),
    )


@router.post(
    "/{record_id}/void",
    response_model=CashResponse,
    operation_id="voidIncome",
    responses={200: {"headers": ETAG_HEADERS}},
)
def void(
    record_id: UUID,
    payload: IncomeVoid,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _etag(
        response,
        service.void_income(session, principal, record_id, payload, if_match, idempotency_key),
    )


@router.post(
    "/{record_id}/returns",
    response_model=CashResponse,
    status_code=201,
    operation_id="returnIncome",
    responses={201: {"headers": CREATED_HEADERS}},
)
def return_income(
    record_id: UUID,
    payload: IncomeReturn,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    result = service.return_income(
        session, principal, record_id, payload, if_match, idempotency_key
    )
    response.headers["Location"] = f"/api/v1/income/{result.id}"
    return _etag(response, result)


@router.get(
    "/{record_id}/insurance-source",
    response_model=IncomeInsuranceSource,
    operation_id="getIncomeInsuranceSource",
)
def insurance_source(record_id: UUID, principal: PrincipalDependency, session: SessionDependency):
    return related_service.income_source(session, principal, record_id)
