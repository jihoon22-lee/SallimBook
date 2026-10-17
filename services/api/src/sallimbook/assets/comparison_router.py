from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from sallimbook.assets import comparison_service as service
from sallimbook.assets.comparison_schemas import (
    AssetComparisonResponse,
    AssetTrendResponse,
    ComparisonFilters,
)
from sallimbook.assets.schemas import AssetCategory, AssetKind, OwnershipKind
from sallimbook.core.types import YearMonth
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(prefix="/api/v1", tags=["asset-comparison"])


def filters(
    asset_id: UUID | None = None,
    kind: AssetKind | None = None,
    category: AssetCategory | None = None,
    ownership_kind: OwnershipKind | None = None,
    owner_member_id: UUID | None = None,
) -> ComparisonFilters:
    return ComparisonFilters(
        asset_id=asset_id,
        kind=kind,
        category=category,
        ownership_kind=ownership_kind,
        owner_member_id=owner_member_id,
    )


@router.get(
    "/asset-comparison", response_model=AssetComparisonResponse, operation_id="getAssetComparison"
)
def compare_assets(
    principal: PrincipalDependency,
    session: SessionDependency,
    selection: Annotated[ComparisonFilters, Depends(filters)],
    to_month: Annotated[YearMonth, Query(alias="to")],
    from_month: Annotated[YearMonth | None, Query(alias="from")] = None,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AssetComparisonResponse:
    return service.get_comparison(
        session, principal, to_month, from_month, selection, cursor=cursor, limit=limit
    )


@router.get("/asset-trends", response_model=AssetTrendResponse, operation_id="getAssetTrends")
def asset_trends(
    principal: PrincipalDependency,
    session: SessionDependency,
    selection: Annotated[ComparisonFilters, Depends(filters)],
    from_month: Annotated[YearMonth, Query(alias="from")],
    to_month: Annotated[YearMonth, Query(alias="to")],
) -> AssetTrendResponse:
    return service.get_trend(session, principal, from_month, to_month, selection)
