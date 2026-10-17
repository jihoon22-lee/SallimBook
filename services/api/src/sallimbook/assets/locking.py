"""Serialize changes to the household's asset set with month confirmation."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from sallimbook.core.authorization import Principal
from sallimbook.core.errors import DomainError
from sallimbook.identity.models import Household


def lock_asset_scope(session: Session, principal: Principal) -> Household:
    # Session authentication precedes this. All scope-changing writers then take
    # Household -> Month/Revision (if any) -> Asset -> FinancialAccount.
    household = session.scalar(
        select(Household)
        .where(Household.id == principal.household_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if household is None:
        raise DomainError("NOT_FOUND", "가계를 찾을 수 없습니다.", 404)
    return household
