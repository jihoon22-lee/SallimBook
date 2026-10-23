"""Manual monthly observations with immutable confirmed revisions and explicit corrections."""

from datetime import date, timedelta
from decimal import Decimal
from operator import attrgetter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sallimbook.assets.calculations import AssetValue, asset_totals, owned_valuation
from sallimbook.assets.locking import lock_asset_scope
from sallimbook.assets.models import Asset
from sallimbook.assets.month_models import AssetMonthRecord, AssetMonthRevision, AssetMonthValue
from sallimbook.assets.month_schemas import (
    MonthCarryPrevious,
    MonthConfirm,
    MonthDraft,
    MonthHistoryItem,
    MonthHistoryResponse,
    MonthReference,
    MonthReopen,
    MonthResponse,
    MonthScopeSync,
    MonthTotals,
    MonthValueResponse,
    MonthValueResult,
    MonthValueUpdate,
)
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import Principal, require_version
from sallimbook.core.errors import DomainError
from sallimbook.core.idempotency import IdempotentResult, run_idempotent
from sallimbook.core.pagination import page_after
from sallimbook.core.types import SEOUL, krw_string, month_end, month_start, seoul_month
from sallimbook.identity.service import utcnow

SCOPE_FIELDS = (
    "name",
    "kind",
    "category",
    "ownership_kind",
    "owner_member_id",
    "household_share",
    "amount_basis",
    "inclusion_status",
    "started_on",
    "ended_on",
)


def _month_text(period: date) -> str:
    return f"{period.year:04d}-{period.month:02d}"


def _previous_month(month: str) -> str | None:
    first = month_start(month)
    return None if first == date.min else _month_text(first - timedelta(days=1))


def _record(session: Session, principal: Principal, month: str, *, lock=False):
    query = select(AssetMonthRecord).where(
        AssetMonthRecord.household_id == principal.household_id,
        AssetMonthRecord.period_month == month_start(month),
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    result = session.scalar(query)
    if result is None:
        raise DomainError("MONTH_NOT_FOUND", "이 달의 자산 기록을 먼저 만들어 주세요.", 404)
    return result


def _revision(session: Session, record: AssetMonthRecord, revision_no=None, *, lock=False):
    query = select(AssetMonthRevision).where(
        AssetMonthRevision.household_id == record.household_id,
        AssetMonthRevision.month_id == record.id,
    )
    query = query.where(
        AssetMonthRevision.id == record.current_revision_id
        if revision_no is None
        else AssetMonthRevision.revision_no == revision_no
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    revision = session.scalar(query)
    if revision is None:
        raise DomainError("NOT_FOUND", "월 기록의 변경본을 찾을 수 없습니다.", 404)
    return revision


def _values(session: Session, revision: AssetMonthRevision) -> list[AssetMonthValue]:
    return list(
        session.scalars(
            select(AssetMonthValue)
            .where(
                AssetMonthValue.household_id == revision.household_id,
                AssetMonthValue.revision_id == revision.id,
            )
            .order_by(AssetMonthValue.asset_id)
        )
    )


def _eligible_assets(session: Session, principal: Principal, month: str) -> list[Asset]:
    # An item held on any day of the month remains in that closing month's worksheet.
    # Its final amount (including an explicit zero) is always manually verified.
    return list(
        session.scalars(
            select(Asset)
            .where(
                Asset.household_id == principal.household_id,
                Asset.started_on <= month_end(month),
                (Asset.ended_on.is_(None) | (Asset.ended_on >= month_start(month))),
            )
            .order_by(Asset.id)
        )
    )


def _scope(asset: Asset | AssetMonthValue) -> dict:
    return {field: getattr(asset, field) for field in SCOPE_FIELDS}


def _scope_stale(rows: list[AssetMonthValue], assets: list[Asset]) -> bool:
    existing = {row.asset_id: row for row in rows}
    return set(existing) != {asset.id for asset in assets} or any(
        _scope(existing[asset.id]) != _scope(asset) for asset in assets if asset.id in existing
    )


def _calculation_rows(rows: list[AssetMonthValue]) -> list[AssetValue]:
    return [
        AssetValue(
            str(row.asset_id),
            row.owned_amount_krw,
            row.kind,
            row.verification_state,
            row.inclusion_status == "included",
            row.household_share,
        )
        for row in rows
    ]


def _totals(rows: list[AssetMonthValue]) -> MonthTotals:
    try:
        result = asset_totals(_calculation_rows(rows))
    except ValueError:
        raise DomainError(
            "TOTAL_OUT_OF_RANGE", "합산 가능한 금액 범위를 확인해 주세요.", 422
        ) from None
    return MonthTotals(
        assets_krw=None if result.assets_krw is None else krw_string(result.assets_krw),
        liabilities_krw=None
        if result.liabilities_krw is None
        else krw_string(result.liabilities_krw),
        net_assets_krw=None if result.net_assets_krw is None else krw_string(result.net_assets_krw),
        verified_count=result.verified_count,
        item_count=result.item_count,
        missing_count=sum(
            row.inclusion_status == "included" and row.verification_state == "missing"
            for row in rows
        ),
        carried_count=sum(
            row.inclusion_status == "included" and row.verification_state == "carried_unconfirmed"
            for row in rows
        ),
        provisional=result.provisional,
    )


def _value_response(row: AssetMonthValue) -> MonthValueResponse:
    return MonthValueResponse(
        **(_scope(row) | {"household_share": format(row.household_share, "f")}),
        id=row.id,
        asset_id=row.asset_id,
        source_asset_version=row.source_asset_version,
        input_amount_krw=None if row.input_amount_krw is None else krw_string(row.input_amount_krw),
        owned_amount_krw=None if row.owned_amount_krw is None else krw_string(row.owned_amount_krw),
        as_of_date=row.as_of_date,
        verification_state=row.verification_state,
        origin=row.origin,
        origin_revision_id=row.origin_revision_id,
        change_reason=row.change_reason,
        version=row.version,
    )


def value_order(row) -> tuple[bool, str, UUID]:
    """Display order for month values: assets, then liabilities, each by name then asset id."""
    return (row.kind == "liability", row.name, row.asset_id)


def _response(
    session: Session,
    principal: Principal,
    record: AssetMonthRecord,
    revision: AssetMonthRevision,
    *,
    cursor: UUID | None = None,
    limit: int = 50,
) -> MonthResponse:
    if type(limit) is not int or not 1 <= limit <= 200:
        raise DomainError("INVALID_PAGE_SIZE", "조회 건수를 확인해 주세요.", 422)
    rows = _values(session, revision)
    shown, next_cursor = page_after(
        sorted(rows, key=value_order), cursor=cursor, limit=limit, key=attrgetter("asset_id")
    )
    month = _month_text(record.period_month)
    return MonthResponse(
        month=month,
        revision_id=revision.id,
        revision_no=revision.revision_no,
        version=revision.version,
        state=revision.state,
        previous_revision_id=revision.previous_revision_id,
        reopened_reason=revision.reopened_reason,
        confirmed_at=revision.confirmed_at,
        confirmed_by_member_id=revision.confirmed_by_member_id,
        created_at=revision.created_at,
        totals=_totals(rows),
        scope_stale=revision.state != "confirmed"
        and _scope_stale(rows, _eligible_assets(session, principal, month)),
        values=[_value_response(row) for row in shown],
        next_cursor=next_cursor,
    )


def get_month(
    session: Session,
    principal: Principal,
    month: str,
    *,
    revision_no: int | None = None,
    cursor: UUID | None = None,
    limit: int = 50,
) -> MonthResponse:
    lock_asset_scope(session, principal)
    record = _record(session, principal, month)
    revision = _revision(session, record, revision_no)
    result = _response(session, principal, record, revision, cursor=cursor, limit=limit)
    session.commit()
    return result


def _latest_previous_confirmation(session: Session, principal: Principal, month: str):
    previous = _previous_month(month)
    if previous is None:
        return None
    return session.scalar(
        select(AssetMonthRevision)
        .join(
            AssetMonthRecord,
            (AssetMonthRecord.id == AssetMonthRevision.month_id)
            & (AssetMonthRecord.household_id == AssetMonthRevision.household_id),
        )
        .where(
            AssetMonthRecord.household_id == principal.household_id,
            AssetMonthRecord.period_month == month_start(previous),
            AssetMonthRevision.state == "confirmed",
        )
        .order_by(AssetMonthRevision.revision_no.desc())
        .limit(1)
    )


def _new_value(
    principal: Principal,
    revision: AssetMonthRevision,
    asset: Asset,
    previous: AssetMonthValue | None = None,
) -> AssetMonthValue:
    # A different input basis cannot be copied by guessing an inverse rounded value.
    copied = (
        previous is not None
        and previous.amount_basis == asset.amount_basis
        and previous.input_amount_krw is not None
    )
    amount = previous.input_amount_krw if copied else None
    return AssetMonthValue(
        **_scope(asset),
        household_id=principal.household_id,
        revision_id=revision.id,
        asset_id=asset.id,
        source_asset_version=asset.version,
        input_amount_krw=amount,
        owned_amount_krw=None
        if amount is None
        else owned_valuation(
            amount, household_share=asset.household_share, basis=asset.amount_basis
        ),
        as_of_date=None,
        verification_state="carried_unconfirmed" if copied else "missing",
        origin="carried" if copied else "manual",
        origin_revision_id=previous.revision_id if copied else None,
    )


def _reference(session: Session, principal: Principal, month: str, result: IdempotentResult):
    record = _record(session, principal, month)
    revision = session.scalar(
        select(AssetMonthRevision).where(
            AssetMonthRevision.id == result.resource_id,
            AssetMonthRevision.household_id == principal.household_id,
            AssetMonthRevision.month_id == record.id,
        )
    )
    if revision is None:
        raise DomainError("NOT_FOUND", "원래 월 기록을 찾을 수 없습니다.", 404)
    # IDs/revision number are immutable; the original response version comes from the
    # idempotency record, even when a draft was subsequently edited or reopened.
    return MonthReference(
        month=month,
        revision_id=revision.id,
        revision_no=revision.revision_no,
        version=result.resource_version,
    )


def create_draft(
    session: Session,
    principal: Principal,
    month: str,
    payload: MonthDraft,
    key: str | None,
) -> MonthReference:
    lock_asset_scope(session, principal)

    def execute():
        # Inside execute: a rejected request rolls back, so its key works once the month starts.
        if month_start(month) > month_start(seoul_month(utcnow())):
            raise DomainError("MONTH_IN_FUTURE", "아직 시작하지 않은 달은 기록할 수 없습니다.", 422)
        if (
            session.scalar(
                select(AssetMonthRecord.id).where(
                    AssetMonthRecord.household_id == principal.household_id,
                    AssetMonthRecord.period_month == month_start(month),
                )
            )
            is not None
        ):
            raise DomainError("MONTH_ALREADY_EXISTS", "이미 있는 월 기록을 불러와 주세요.", 409)
        record = AssetMonthRecord(
            household_id=principal.household_id, period_month=month_start(month)
        )
        session.add(record)
        session.flush()
        revision = AssetMonthRevision(
            household_id=principal.household_id,
            month_id=record.id,
            revision_no=1,
            state="draft",
            created_by_member_id=principal.member_id,
        )
        session.add(revision)
        session.flush()
        record.current_revision_id = revision.id
        prior = (
            _latest_previous_confirmation(session, principal, month)
            if payload.copy_previous
            else None
        )
        prior_rows = {} if prior is None else {row.asset_id: row for row in _values(session, prior)}
        rows = [
            _new_value(principal, revision, asset, prior_rows.get(asset.id))
            for asset in _eligible_assets(session, principal, month)
        ]
        session.add_all(rows)
        session.flush()
        _totals(rows)
        record_event(
            session,
            principal,
            entity_type="asset_month",
            entity_id=revision.id,
            action="create",
            before_version=None,
            after_version=revision.version,
            changed_fields=("values", "scope"),
        )
        return IdempotentResult(revision.id, "asset_month_revision", revision.version)

    saved = run_idempotent(
        session,
        principal,
        "asset_month.draft",
        key,
        {"month": month, **payload.model_dump(mode="json")},
        execute,
    )
    result = _reference(session, principal, month, saved)
    session.commit()
    return result


def _editable_revision(session: Session, principal: Principal, month: str):
    lock_asset_scope(session, principal)
    record = _record(session, principal, month, lock=True)
    revision = _revision(session, record, lock=True)
    if revision.state == "confirmed":
        raise DomainError(
            "MONTH_CONFIRMED", "확정한 월은 정정 사유를 남기고 다시 열어 주세요.", 409
        )
    return record, revision


def _require_revision(revision: AssetMonthRevision, requested: UUID) -> None:
    if revision.id != requested:
        raise DomainError(
            "REVISION_CONFLICT", "다른 정정본이 열렸습니다. 현재 월 기록을 다시 불러와 주세요.", 409
        )


def update_value(
    session: Session,
    principal: Principal,
    month: str,
    asset_id: UUID,
    payload: MonthValueUpdate,
    if_match: str | None,
) -> MonthValueResult:
    _, revision = _editable_revision(session, principal, month)
    _require_revision(revision, payload.revision_id)
    value = session.scalar(
        select(AssetMonthValue)
        .where(
            AssetMonthValue.household_id == principal.household_id,
            AssetMonthValue.revision_id == revision.id,
            AssetMonthValue.asset_id == asset_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if value is None:
        raise DomainError("NOT_FOUND", "이 달의 자산 항목을 찾을 수 없습니다.", 404)
    if value.id != payload.value_id:
        raise DomainError(
            "VALUE_CONFLICT", "자산 범위가 갱신되었습니다. 현재 입력 행을 다시 불러와 주세요.", 409
        )
    require_version(value, if_match)
    if payload.as_of_date is not None and (
        not month_start(month) <= payload.as_of_date <= month_end(month)
        or payload.as_of_date > utcnow().astimezone(SEOUL).date()
    ):
        raise DomainError("INVALID_AS_OF_DATE", "선택 월 안의 실제 확인 날짜를 입력해 주세요.", 422)
    if payload.unchanged:
        if value.verification_state != "carried_unconfirmed" or value.input_amount_krw is None:
            raise DomainError(
                "NO_CARRIED_VALUE", "불러온 금액이 있을 때 변동 없음을 확인할 수 있습니다.", 422
            )
    else:
        value.input_amount_krw = (
            None if payload.input_amount_krw is None else Decimal(payload.input_amount_krw)
        )
        value.origin, value.origin_revision_id = "manual", None
    before = revision.version
    value.owned_amount_krw = (
        None
        if value.input_amount_krw is None
        else owned_valuation(
            value.input_amount_krw,
            household_share=value.household_share,
            basis=value.amount_basis,
        )
    )
    value.verification_state = "missing" if value.input_amount_krw is None else "verified"
    value.as_of_date, value.change_reason = payload.as_of_date, payload.change_reason
    revision.updated_at = utcnow()
    session.flush()
    totals = _totals(_values(session, revision))
    record_event(
        session,
        principal,
        entity_type="asset_month",
        entity_id=revision.id,
        action="update",
        before_version=before,
        after_version=revision.version,
        changed_fields=("values",),
    )
    result = MonthValueResult(
        value=_value_response(value), revision_version=revision.version, totals=totals
    )
    session.commit()
    return result


def synchronize_scope(
    session: Session,
    principal: Principal,
    month: str,
    payload: MonthScopeSync,
    if_match: str | None,
) -> MonthReference:
    _, revision = _editable_revision(session, principal, month)
    _require_revision(revision, payload.revision_id)
    require_version(revision, if_match)
    before = revision.version
    existing = {row.asset_id: row for row in _values(session, revision)}
    assets = _eligible_assets(session, principal, month)
    new_ids = {asset.id for asset in assets}
    for asset_id in set(existing) - new_ids:
        session.delete(existing[asset_id])
    for asset in assets:
        value = existing.get(asset.id)
        if value is None:
            session.add(_new_value(principal, revision, asset))
            continue
        changed = _scope(value) != _scope(asset)
        different_basis = value.amount_basis != asset.amount_basis
        for field, content in _scope(asset).items():
            setattr(value, field, content)
        value.source_asset_version = asset.version
        if changed:
            if different_basis:
                # The cleared amount is no longer the carried one, so its origin goes too.
                value.input_amount_krw = None
                value.origin, value.origin_revision_id = "manual", None
            value.owned_amount_krw = (
                None
                if value.input_amount_krw is None
                else owned_valuation(
                    value.input_amount_krw,
                    household_share=value.household_share,
                    basis=value.amount_basis,
                )
            )
            value.verification_state = (
                "missing" if value.input_amount_krw is None else "carried_unconfirmed"
            )
            value.as_of_date = None
    revision.updated_at = utcnow()
    session.flush()
    _totals(_values(session, revision))
    record_event(
        session,
        principal,
        entity_type="asset_month",
        entity_id=revision.id,
        action="sync_scope",
        before_version=before,
        after_version=revision.version,
        changed_fields=("scope", "values"),
    )
    result = MonthReference(
        month=month,
        revision_id=revision.id,
        revision_no=revision.revision_no,
        version=revision.version,
    )
    session.commit()
    return result


def _scope_changed(prior: list[AssetMonthValue], rows: list[AssetMonthValue]) -> bool:
    old = {row.asset_id: row.household_share for row in prior if row.inclusion_status == "included"}
    new = {row.asset_id: row.household_share for row in rows if row.inclusion_status == "included"}
    return old != new


def confirm_month(
    session: Session,
    principal: Principal,
    month: str,
    payload: MonthConfirm,
    if_match: str | None,
    key: str | None,
) -> MonthReference:
    lock_asset_scope(session, principal)

    def execute():
        record = _record(session, principal, month, lock=True)
        revision = _revision(session, record, lock=True)
        _require_revision(revision, payload.revision_id)
        require_version(revision, if_match)
        if revision.state == "confirmed":
            raise DomainError("MONTH_CONFIRMED", "이미 확정한 월입니다.", 409)
        rows = _values(session, revision)
        if revision.state == "draft" and _scope_stale(
            rows, _eligible_assets(session, principal, month)
        ):
            raise DomainError(
                "MONTH_SCOPE_CHANGED", "바뀐 자산 목록과 지분을 다시 불러와 확인해 주세요.", 409
            )
        if _totals(rows).provisional:
            raise DomainError("MONTH_UNVERIFIED", "미입력·미확인 항목을 모두 확인해 주세요.", 409)
        if (
            any(
                row.inclusion_status == "included" and row.as_of_date != month_end(month)
                for row in rows
            )
            and not payload.acknowledge_non_month_end_dates
        ):
            raise DomainError("AS_OF_DATE_ACK_REQUIRED", "월말과 다른 기준일을 확인해 주세요.", 409)
        prior = _latest_previous_confirmation(session, principal, month)
        if (
            prior is not None
            and _scope_changed(_values(session, prior), rows)
            and not payload.acknowledge_scope_change
        ):
            raise DomainError("SCOPE_ACK_REQUIRED", "비교 범위와 지분 변경을 확인해 주세요.", 409)
        before = revision.version
        revision.state = "confirmed"
        revision.confirmed_at = utcnow()
        revision.confirmed_by_member_id = principal.member_id
        session.flush()
        record_event(
            session,
            principal,
            entity_type="asset_month",
            entity_id=revision.id,
            action="confirm",
            before_version=before,
            after_version=revision.version,
            changed_fields=("state",),
        )
        return IdempotentResult(revision.id, "asset_month_revision", revision.version, 200)

    saved = run_idempotent(
        session,
        principal,
        "asset_month.confirm",
        key,
        {"month": month, "if_match": if_match, **payload.model_dump(mode="json")},
        execute,
    )
    result = _reference(session, principal, month, saved)
    session.commit()
    return result


def _untouched_missing(value: AssetMonthValue) -> bool:
    # A row cleared without a reason looks the same; the screen lists rows before applying.
    return (
        value.verification_state == "missing"
        and value.origin == "manual"
        and value.origin_revision_id is None
        and value.as_of_date is None
        and value.change_reason is None
    )


def release_blank_rows(session: Session, principal: Principal, asset_id: UUID) -> bool:
    """Remove a mistaken asset's untouched blank rows from open months before it is deleted.

    Returns False, removing nothing, when any month row keeps it: an entered value or a
    confirmed month. The caller holds the asset scope lock.
    """
    rows = list(
        session.execute(
            select(AssetMonthValue, AssetMonthRevision)
            .join(
                AssetMonthRevision,
                (AssetMonthRevision.id == AssetMonthValue.revision_id)
                & (AssetMonthRevision.household_id == AssetMonthValue.household_id),
            )
            .where(
                AssetMonthValue.household_id == principal.household_id,
                AssetMonthValue.asset_id == asset_id,
            )
            .order_by(AssetMonthRevision.id)
            .with_for_update()
        )
    )
    if any(
        revision.state == "confirmed" or not _untouched_missing(value) for value, revision in rows
    ):
        return False
    for value, revision in rows:
        before = revision.version
        session.delete(value)
        # The month's content changed: an older month version held elsewhere must reload.
        revision.updated_at = utcnow()
        session.flush()
        record_event(
            session,
            principal,
            entity_type="asset_month",
            entity_id=revision.id,
            action="sync_scope",
            before_version=before,
            after_version=revision.version,
            changed_fields=("scope", "values"),
        )
    return True


def carry_previous(
    session: Session,
    principal: Principal,
    month: str,
    payload: MonthCarryPrevious,
    if_match: str | None,
    key: str | None,
) -> MonthReference:
    """Fill untouched missing rows from the previous month's latest confirmation."""
    lock_asset_scope(session, principal)

    def execute():
        record = _record(session, principal, month, lock=True)
        revision = _revision(session, record, lock=True)
        _require_revision(revision, payload.revision_id)
        require_version(revision, if_match)
        if revision.state == "confirmed":
            raise DomainError(
                "MONTH_CONFIRMED", "확정한 월은 정정 사유를 남기고 다시 열어 주세요.", 409
            )
        prior = _latest_previous_confirmation(session, principal, month)
        if prior is None:
            raise DomainError(
                "PREVIOUS_MONTH_UNCONFIRMED",
                "전월 확정 기록이 없습니다. 전월을 먼저 확정해 주세요.",
                409,
            )
        prior_rows = {row.asset_id: row for row in _values(session, prior)}
        before = revision.version
        filled = 0
        for value in _values(session, revision):
            previous = prior_rows.get(value.asset_id)
            if (
                previous is None
                or not _untouched_missing(value)
                or previous.amount_basis != value.amount_basis
                or previous.input_amount_krw is None
            ):
                continue
            value.input_amount_krw = previous.input_amount_krw
            value.owned_amount_krw = owned_valuation(
                previous.input_amount_krw,
                household_share=value.household_share,
                basis=value.amount_basis,
            )
            value.verification_state = "carried_unconfirmed"
            value.origin, value.origin_revision_id = "carried", prior.id
            filled += 1
        if filled:
            revision.updated_at = utcnow()
            session.flush()
            _totals(_values(session, revision))
            record_event(
                session,
                principal,
                entity_type="asset_month",
                entity_id=revision.id,
                action="update",
                before_version=before,
                after_version=revision.version,
                changed_fields=("values", "origin", "origin_revision_id"),
            )
        return IdempotentResult(revision.id, "asset_month_revision", revision.version, 200)

    saved = run_idempotent(
        session,
        principal,
        "asset_month.carry_previous",
        key,
        {"month": month, "if_match": if_match, **payload.model_dump(mode="json")},
        execute,
    )
    result = _reference(session, principal, month, saved)
    session.commit()
    return result


def reopen_month(
    session: Session,
    principal: Principal,
    month: str,
    payload: MonthReopen,
    if_match: str | None,
    key: str | None,
) -> MonthReference:
    lock_asset_scope(session, principal)

    def execute():
        record = _record(session, principal, month, lock=True)
        previous = _revision(session, record, lock=True)
        _require_revision(previous, payload.revision_id)
        require_version(previous, if_match)
        if previous.state != "confirmed":
            raise DomainError(
                "MONTH_NOT_CONFIRMED", "확정한 월만 새 정정본으로 열 수 있습니다.", 409
            )
        revision = AssetMonthRevision(
            household_id=principal.household_id,
            month_id=record.id,
            revision_no=previous.revision_no + 1,
            state="reopened",
            previous_revision_id=previous.id,
            reopened_reason=payload.reason,
            created_by_member_id=principal.member_id,
        )
        session.add(revision)
        session.flush()
        for old in _values(session, previous):
            session.add(
                AssetMonthValue(
                    **_scope(old),
                    household_id=principal.household_id,
                    revision_id=revision.id,
                    asset_id=old.asset_id,
                    source_asset_version=old.source_asset_version,
                    input_amount_krw=old.input_amount_krw,
                    owned_amount_krw=old.owned_amount_krw,
                    as_of_date=old.as_of_date,
                    verification_state=old.verification_state,
                    origin=old.origin,
                    origin_revision_id=old.origin_revision_id,
                    change_reason=old.change_reason,
                )
            )
        record.current_revision_id = revision.id
        session.flush()
        record_event(
            session,
            principal,
            entity_type="asset_month",
            entity_id=revision.id,
            action="reopen",
            before_version=None,
            after_version=revision.version,
            changed_fields=("previous_revision_id", "reopened_reason"),
        )
        return IdempotentResult(revision.id, "asset_month_revision", revision.version)

    saved = run_idempotent(
        session,
        principal,
        "asset_month.reopen",
        key,
        {"month": month, "if_match": if_match, **payload.model_dump(mode="json")},
        execute,
    )
    result = _reference(session, principal, month, saved)
    session.commit()
    return result


def revision_history(
    session: Session,
    principal: Principal,
    month: str,
    *,
    cursor: int | None = None,
    limit: int = 50,
) -> MonthHistoryResponse:
    if (
        type(limit) is not int
        or not 1 <= limit <= 200
        or (cursor is not None and (type(cursor) is not int or cursor < 1))
    ):
        raise DomainError("INVALID_PAGE_SIZE", "조회 범위를 확인해 주세요.", 422)
    record = _record(session, principal, month)
    query = select(AssetMonthRevision).where(
        AssetMonthRevision.household_id == principal.household_id,
        AssetMonthRevision.month_id == record.id,
    )
    if cursor is not None:
        query = query.where(AssetMonthRevision.revision_no < cursor)
    rows = list(
        session.scalars(query.order_by(AssetMonthRevision.revision_no.desc()).limit(limit + 1))
    )
    result = MonthHistoryResponse(
        items=[
            MonthHistoryItem(
                month=month,
                revision_id=row.id,
                revision_no=row.revision_no,
                version=row.version,
                state=row.state,
                previous_revision_id=row.previous_revision_id,
                reopened_reason=row.reopened_reason,
                confirmed_at=row.confirmed_at,
                created_at=row.created_at,
            )
            for row in rows[:limit]
        ],
        next_cursor=rows[limit - 1].revision_no if len(rows) > limit else None,
    )
    session.commit()
    return result
