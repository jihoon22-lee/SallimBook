from typing import Annotated

from fastapi import APIRouter, Query

from sallimbook.core.types import YearMonth
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency
from sallimbook.overview import service
from sallimbook.overview.schemas import HouseholdOverviewResponse

router = APIRouter(prefix="/api/v1", tags=["household-overview"])


@router.get(
    "/household-overview",
    response_model=HouseholdOverviewResponse,
    operation_id="getHouseholdOverview",
)
def household_overview(
    principal: PrincipalDependency,
    session: SessionDependency,
    month: Annotated[YearMonth, Query()],
) -> HouseholdOverviewResponse:
    return service.get_overview(session, principal, month)
