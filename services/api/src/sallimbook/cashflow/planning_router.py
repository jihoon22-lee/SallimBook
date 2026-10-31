from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query

from sallimbook.cashflow import planning_service as service
from sallimbook.cashflow.planning_models import BonusAward, ExpectedIncome
from sallimbook.cashflow.planning_schemas import (
    BonusChange,
    BonusInput,
    BonusList,
    BonusResponse,
    ExpectedChange,
    ExpectedInput,
    ExpectedList,
    ExpectedResponse,
)
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(prefix="/api/v1/income-planning", tags=["income"])
Key = Annotated[str, Header(alias="Idempotency-Key", max_length=128)]
Version = Annotated[str, Header(alias="If-Match")]
Limit = Annotated[int, Query(ge=1, le=200)]


@router.get("/expected", response_model=ExpectedList, operation_id="listExpectedIncome")
def list_expected(
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Limit = 100,
):
    return service.list_records(session, principal, ExpectedIncome, cursor, limit)


@router.post(
    "/expected",
    response_model=ExpectedResponse,
    operation_id="createExpectedIncome",
    status_code=201,
)
def create_expected(
    payload: ExpectedInput,
    principal: PrincipalDependency,
    session: SessionDependency,
    idempotency_key: Key,
):
    return service.create_expected(session, principal, payload, idempotency_key)


@router.put(
    "/expected/{record_id}", response_model=ExpectedResponse, operation_id="changeExpectedIncome"
)
def change_expected(
    record_id: UUID,
    payload: ExpectedChange,
    principal: PrincipalDependency,
    session: SessionDependency,
    idempotency_key: Key,
    if_match: Version,
):
    return service.change_expected(
        session, principal, record_id, payload, if_match, idempotency_key
    )


@router.get("/bonuses", response_model=BonusList, operation_id="listBonusAwards")
def list_bonuses(
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Limit = 100,
):
    return service.list_records(session, principal, BonusAward, cursor, limit)


@router.post(
    "/bonuses", response_model=BonusResponse, operation_id="createBonusAward", status_code=201
)
def create_bonus(
    payload: BonusInput,
    principal: PrincipalDependency,
    session: SessionDependency,
    idempotency_key: Key,
):
    return service.create_bonus(session, principal, payload, idempotency_key)


@router.put("/bonuses/{record_id}", response_model=BonusResponse, operation_id="changeBonusAward")
def change_bonus(
    record_id: UUID,
    payload: BonusChange,
    principal: PrincipalDependency,
    session: SessionDependency,
    idempotency_key: Key,
    if_match: Version,
):
    return service.change_bonus(session, principal, record_id, payload, if_match, idempotency_key)
