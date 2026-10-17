from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Response

from sallimbook.assets import month_service as service
from sallimbook.assets.month_schemas import (
    MonthConfirm,
    MonthDraft,
    MonthHistoryResponse,
    MonthReference,
    MonthReopen,
    MonthResponse,
    MonthScopeSync,
    MonthValueResult,
    MonthValueUpdate,
)
from sallimbook.core.types import YearMonth
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(prefix="/api/v1/asset-months", tags=["asset-months"])
VersionHeader = Annotated[str | None, Header(alias="If-Match")]
IdempotencyHeader = Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)]


def _reference_headers(response: Response, result: MonthReference) -> None:
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Location"] = (
        f"/api/v1/asset-months/{result.month}/revisions/{result.revision_no}"
    )


@router.post(
    "/{month}/draft",
    response_model=MonthReference,
    status_code=201,
    operation_id="createAssetMonthDraft",
)
def create_draft(
    month: YearMonth,
    payload: MonthDraft,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    idempotency_key: IdempotencyHeader = None,
) -> MonthReference:
    result = service.create_draft(session, principal, month, payload, idempotency_key)
    _reference_headers(response, result)
    return result


@router.get("/{month}", response_model=MonthResponse, operation_id="getAssetMonth")
def get_month(
    month: YearMonth,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MonthResponse:
    result = service.get_month(session, principal, month, cursor=cursor, limit=limit)
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.patch(
    "/{month}/values/{asset_id}",
    response_model=MonthValueResult,
    operation_id="updateAssetMonthValue",
)
def update_value(
    month: YearMonth,
    asset_id: UUID,
    payload: MonthValueUpdate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: VersionHeader = None,
) -> MonthValueResult:
    result = service.update_value(session, principal, month, asset_id, payload, if_match)
    response.headers["ETag"] = f'"{result.value.version}"'
    return result


@router.post(
    "/{month}/sync-scope", response_model=MonthReference, operation_id="synchronizeAssetMonthScope"
)
def synchronize_scope(
    month: YearMonth,
    payload: MonthScopeSync,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: VersionHeader = None,
) -> MonthReference:
    result = service.synchronize_scope(session, principal, month, payload, if_match)
    _reference_headers(response, result)
    return result


@router.post("/{month}/confirm", response_model=MonthReference, operation_id="confirmAssetMonth")
def confirm_month(
    month: YearMonth,
    payload: MonthConfirm,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: VersionHeader = None,
    idempotency_key: IdempotencyHeader = None,
) -> MonthReference:
    result = service.confirm_month(session, principal, month, payload, if_match, idempotency_key)
    _reference_headers(response, result)
    return result


@router.post(
    "/{month}/reopen",
    response_model=MonthReference,
    status_code=201,
    operation_id="reopenAssetMonth",
)
def reopen_month(
    month: YearMonth,
    payload: MonthReopen,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: VersionHeader = None,
    idempotency_key: IdempotencyHeader = None,
) -> MonthReference:
    result = service.reopen_month(session, principal, month, payload, if_match, idempotency_key)
    _reference_headers(response, result)
    return result


@router.get(
    "/{month}/revisions",
    response_model=MonthHistoryResponse,
    operation_id="listAssetMonthRevisions",
)
def revision_history(
    month: YearMonth,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MonthHistoryResponse:
    return service.revision_history(session, principal, month, cursor=cursor, limit=limit)


@router.get(
    "/{month}/revisions/{revision_no}",
    response_model=MonthResponse,
    operation_id="getAssetMonthRevision",
)
def get_revision(
    month: YearMonth,
    revision_no: Annotated[int, Path(ge=1)],
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MonthResponse:
    result = service.get_month(
        session, principal, month, revision_no=revision_no, cursor=cursor, limit=limit
    )
    response.headers["ETag"] = f'"{result.version}"'
    return result
