from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from sallimbook.assets.schemas import DateOnly
from sallimbook.cashflow.payment_link_schemas import PaymentLinksResponse
from sallimbook.cashflow.payment_links import get_usage
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(prefix="/api/v1", tags=["payment-links"])


def _route(kind, operation_id):
    def handler(
        resource_id: UUID,
        principal: PrincipalDependency,
        session: SessionDependency,
        as_of_date: DateOnly | None = None,
        rule_cursor: UUID | None = None,
        obligation_cursor: UUID | None = None,
        card_cursor: UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        return get_usage(
            session,
            principal,
            kind,
            resource_id,
            as_of_date=as_of_date,
            rule_cursor=rule_cursor,
            obligation_cursor=obligation_cursor,
            card_cursor=card_cursor,
            limit=limit,
        )

    router.add_api_route(
        f"/{kind}s/{{resource_id}}/payment-links",
        handler,
        methods=["GET"],
        response_model=PaymentLinksResponse,
        operation_id=operation_id,
    )


_route("card", "getCardPaymentLinks")
_route("account", "getAccountPaymentLinks")
