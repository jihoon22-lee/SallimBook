"""Asset metadata operations; all monetary snapshots remain separate sources."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sallimbook.accounts.models import FinancialAccount
from sallimbook.assets.locking import lock_asset_scope
from sallimbook.assets.models import Asset
from sallimbook.assets.month_models import AssetMonthValue
from sallimbook.assets.schemas import (
    AssetArchive,
    AssetCategory,
    AssetCreate,
    AssetKind,
    AssetListResponse,
    AssetPatch,
    AssetResponse,
    InclusionStatus,
    OwnershipKind,
)
from sallimbook.cashflow.payment_link_schemas import CLOSURE_FIELDS
from sallimbook.cashflow.payment_links import require_closure
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import Principal, require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.identity.auth_models import HouseholdMember
from sallimbook.insurance.models import InsurancePolicy


def _editable_values(asset: Asset) -> dict:
    values = {name: getattr(asset, name) for name in AssetCreate.model_fields}
    values["household_share"] = format(asset.household_share, "f")
    return values


def asset_response(asset: Asset) -> AssetResponse:
    return AssetResponse(
        **_editable_values(asset),
        id=asset.id,
        household_id=asset.household_id,
        status="active" if asset.archived_at is None else "archived",
        archived_at=asset.archived_at,
        created_by_member_id=asset.created_by_member_id,
        updated_by_member_id=asset.updated_by_member_id,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        version=asset.version,
    )


def _validate_owner(session: Session, principal: Principal, owner_id: UUID | None) -> None:
    if owner_id is None:
        return
    owner = scoped_entity(session, HouseholdMember, owner_id, principal, for_update=True)
    if owner.status != "active":
        raise DomainError("OWNER_UNAVAILABLE", "현재 가계 구성원을 선택해 주세요.", 422)


def _save(session: Session, asset: Asset) -> AssetResponse:
    session.flush()
    result = asset_response(asset)
    session.commit()
    return result


def prepare_asset(session: Session, principal: Principal, payload: AssetCreate) -> Asset:
    """Create within the caller's transaction; account creation can share this commit."""
    lock_asset_scope(session, principal)
    _validate_owner(session, principal, payload.owner_member_id)
    values = payload.model_dump()
    values["household_share"] = Decimal(payload.household_share)
    asset = Asset(
        **values,
        household_id=principal.household_id,
        created_by_member_id=principal.member_id,
        updated_by_member_id=principal.member_id,
        archived_at=datetime.now(UTC) if payload.ended_on is not None else None,
    )
    session.add(asset)
    session.flush()
    record_event(
        session,
        principal,
        entity_type="asset",
        entity_id=asset.id,
        action="create",
        before_version=None,
        after_version=asset.version,
        changed_fields=payload.model_fields_set - CLOSURE_FIELDS,
    )
    return asset


def create_asset(session: Session, principal: Principal, payload: AssetCreate) -> AssetResponse:
    asset = prepare_asset(session, principal, payload)
    return _save(session, asset)


def get_asset(session: Session, principal: Principal, asset_id: UUID) -> AssetResponse:
    asset = scoped_entity(session, Asset, asset_id, principal)
    result = asset_response(asset)
    session.commit()
    return result


def list_assets(
    session: Session,
    principal: Principal,
    *,
    cursor: UUID | None = None,
    limit: int = 50,
    kind: AssetKind | None = None,
    category: AssetCategory | None = None,
    ownership_kind: OwnershipKind | None = None,
    owner_member_id: UUID | None = None,
    inclusion_status: InclusionStatus | None = None,
    status: str = "active",
) -> AssetListResponse:
    if type(limit) is not int or not 1 <= limit <= 200:
        raise DomainError("INVALID_PAGE_SIZE", "조회 건수를 확인해 주세요.", 422)
    if status not in {"active", "archived", "all"}:
        raise DomainError("INVALID_STATUS", "조회 상태를 확인해 주세요.", 422)
    query = select(Asset).where(Asset.household_id == principal.household_id)
    if owner_member_id is not None:
        scoped_entity(session, HouseholdMember, owner_member_id, principal)
    filters = {
        "kind": kind,
        "category": category,
        "ownership_kind": ownership_kind,
        "owner_member_id": owner_member_id,
        "inclusion_status": inclusion_status,
    }
    for field, value in filters.items():
        if value is not None:
            query = query.where(getattr(Asset, field) == value)
    if status == "active":
        query = query.where(Asset.archived_at.is_(None))
    elif status == "archived":
        query = query.where(Asset.archived_at.is_not(None))
    if cursor is not None:
        query = query.where(Asset.id < cursor)
    rows = list(session.scalars(query.order_by(Asset.id.desc()).limit(limit + 1)))
    result = AssetListResponse(
        items=[asset_response(asset) for asset in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )
    session.commit()
    return result


def update_asset(
    session: Session,
    principal: Principal,
    asset_id: UUID,
    payload: AssetPatch,
    if_match: str | None,
    *,
    action: str = "update",
) -> AssetResponse:
    lock_asset_scope(session, principal)
    asset = scoped_entity(session, Asset, asset_id, principal, for_update=True)
    require_version(asset, if_match)
    previous_version = asset.version
    merged = _editable_values(asset) | payload.model_dump(
        exclude_unset=True, exclude=CLOSURE_FIELDS
    )
    try:
        candidate = AssetCreate.model_validate(merged)
    except ValidationError:
        raise DomainError("INVALID_ASSET", "소유자와 시작·종료일을 확인해 주세요.", 422) from None
    if (
        candidate.kind != asset.kind
        and session.scalar(
            select(AssetMonthValue.id)
            .where(
                AssetMonthValue.household_id == principal.household_id,
                AssetMonthValue.asset_id == asset.id,
            )
            .limit(1)
        )
        is not None
    ):
        raise DomainError(
            "ASSET_KIND_IN_USE", "월 기록이 있는 자산의 자산·부채 구분은 바꿀 수 없습니다.", 409
        )
    if (candidate.kind != "asset" or candidate.category != "financial") and session.scalar(
        select(InsurancePolicy.id)
        .where(
            InsurancePolicy.household_id == principal.household_id,
            InsurancePolicy.valuation_asset_id == asset.id,
        )
        .limit(1)
    ) is not None:
        raise DomainError(
            "INSURANCE_ASSET_REQUIRED",
            "보험 평가액 연결을 해제한 뒤 자산 구분을 변경해 주세요.",
            422,
        )
    # Account edits and asset lifecycle changes share Asset -> FinancialAccount order.
    account = session.scalar(
        select(FinancialAccount)
        .where(
            FinancialAccount.household_id == principal.household_id,
            FinancialAccount.asset_id == asset.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if account is not None:
        if candidate.kind != "asset" or candidate.category != "financial":
            raise DomainError(
                "FINANCIAL_ASSET_REQUIRED", "계좌와 연결된 자산은 금융 자산으로 유지해 주세요.", 422
            )
        if (
            candidate.ended_on is not None
            and account.opened_on is not None
            and candidate.ended_on < account.opened_on
        ):
            raise DomainError(
                "INVALID_ACCOUNT_DATES", "계좌 개설일 이후의 종료일을 선택해 주세요.", 422
            )
    if (
        account is not None
        and candidate.ended_on is not None
        and candidate.ended_on != asset.ended_on
    ):
        require_closure(session, principal, "account", account.id, payload, candidate.ended_on)
    if candidate.owner_member_id != asset.owner_member_id:
        _validate_owner(session, principal, candidate.owner_member_id)
    for field, value in candidate.model_dump().items():
        setattr(asset, field, Decimal(value) if field == "household_share" else value)
    asset.updated_by_member_id = principal.member_id
    if candidate.ended_on is None:
        asset.archived_at = None
    elif asset.archived_at is None:
        asset.archived_at = datetime.now(UTC)
    session.flush()
    record_event(
        session,
        principal,
        entity_type="asset",
        entity_id=asset.id,
        action=action,
        before_version=previous_version,
        after_version=asset.version,
        changed_fields=payload.model_fields_set - CLOSURE_FIELDS,
    )
    return _save(session, asset)


def archive_asset(
    session: Session,
    principal: Principal,
    asset_id: UUID,
    payload: AssetArchive,
    if_match: str | None,
) -> AssetResponse:
    # The same edit/validation path preserves the row and every historical FK.
    return update_asset(
        session,
        principal,
        asset_id,
        AssetPatch(**payload.model_dump(exclude_unset=True)),
        if_match,
        action="archive",
    )


def delete_asset(
    session: Session, principal: Principal, asset_id: UUID, if_match: str | None
) -> None:
    lock_asset_scope(session, principal)
    asset = scoped_entity(session, Asset, asset_id, principal, for_update=True)
    require_version(asset, if_match)
    record_event(
        session,
        principal,
        entity_type="asset",
        entity_id=asset.id,
        action="delete",
        before_version=asset.version,
        after_version=None,
    )
    session.delete(asset)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if getattr(exc.orig, "sqlstate", None) in {"23001", "23503"}:
            raise DomainError(
                "ASSET_IN_USE",
                "연결된 기록이 있어 삭제할 수 없습니다. 사용 종료를 선택해 주세요.",
                409,
            ) from None
        raise
