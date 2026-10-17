"""Household-scoped historical projections; never read live amounts or modify snapshots."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sallimbook.assets.calculations import AssetMonth, AssetValue, asset_totals, compare_months
from sallimbook.assets.comparison_schemas import (
    AssetComparisonResponse,
    AssetTrendPoint,
    AssetTrendResponse,
    ComparisonFilters,
    ComparisonItem,
    ComparisonPeriod,
    ObservationDates,
)
from sallimbook.assets.locking import lock_asset_scope
from sallimbook.assets.models import Asset
from sallimbook.assets.month_models import AssetMonthRecord, AssetMonthRevision, AssetMonthValue
from sallimbook.assets.month_schemas import (
    MonthReference,
    MonthState,
    MonthTotals,
    MonthValueResponse,
)
from sallimbook.core.authorization import Principal, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.types import krw_string, month_end, month_start
from sallimbook.identity.auth_models import HouseholdMember


@dataclass(frozen=True)
class Snapshot:
    month: str
    revision_id: UUID
    revision_no: int
    version: int
    state: MonthState
    confirmed_at: datetime | None
    values: tuple[MonthValueResponse, ...]

    def reference(self) -> MonthReference:
        return MonthReference(
            month=self.month,
            revision_id=self.revision_id,
            revision_no=self.revision_no,
            version=self.version,
        )


def _money(value: int | None) -> str | None:
    return None if value is None else krw_string(value)


def _matches(row: MonthValueResponse, filters: ComparisonFilters) -> bool:
    return all(
        getattr(row, field) == value
        for field, value in filters.model_dump().items()
        if value is not None
    )


def _included(row: MonthValueResponse, filters: ComparisonFilters) -> bool:
    return row.inclusion_status == "included" and _matches(row, filters)


def _calculation_values(snapshot: Snapshot, filters: ComparisonFilters) -> tuple[AssetValue, ...]:
    return tuple(
        AssetValue(
            str(row.asset_id),
            None if row.owned_amount_krw is None else int(row.owned_amount_krw),
            row.kind,
            row.verification_state,
            _included(row, filters),
            Decimal(row.household_share),
        )
        for row in snapshot.values
    )


def _totals(snapshot: Snapshot, filters: ComparisonFilters) -> MonthTotals:
    result = asset_totals(_calculation_values(snapshot, filters))
    included = [row for row in snapshot.values if _included(row, filters)]
    return MonthTotals(
        assets_krw=_money(result.assets_krw),
        liabilities_krw=_money(result.liabilities_krw),
        net_assets_krw=_money(result.net_assets_krw),
        verified_count=result.verified_count,
        item_count=result.item_count,
        provisional=result.provisional,
        missing_count=sum(row.verification_state == "missing" for row in included),
        carried_count=sum(row.verification_state == "carried_unconfirmed" for row in included),
    )


def _dates(month: str, rows: list[MonthValueResponse]) -> ObservationDates:
    observed = {row.as_of_date for row in rows if row.as_of_date is not None}
    return ObservationDates(
        non_month_end_asset_ids=sorted(
            row.asset_id
            for row in rows
            if row.as_of_date is not None and row.as_of_date != month_end(month)
        ),
        missing_date_asset_ids=sorted(row.asset_id for row in rows if row.as_of_date is None),
        mixed_dates=len(observed) > 1,
    )


def _period(month: str, snapshot: Snapshot | None, filters: ComparisonFilters) -> ComparisonPeriod:
    if snapshot is None:
        return ComparisonPeriod(
            month=month,
            state="missing",
            revision=None,
            confirmed_at=None,
            totals=None,
            dates=_dates(month, []),
        )
    return ComparisonPeriod(
        month=month,
        state=snapshot.state,
        revision=snapshot.reference(),
        confirmed_at=snapshot.confirmed_at,
        totals=_totals(snapshot, filters),
        dates=_dates(month, [row for row in snapshot.values if _included(row, filters)]),
    )


def _signed(row: MonthValueResponse | None, included: bool) -> int:
    if row is None or not included:
        return 0
    # Only called for an available (fully confirmed) comparison.
    assert row.owned_amount_krw is not None
    return int(row.owned_amount_krw) * (-1 if row.kind == "liability" else 1)


def _scope_reason(membership, before, after, from_month, to_month, share_changed):
    if share_changed:
        return "household_share_changed"
    if membership == "excluded":
        return "excluded_from_total"
    if membership not in {"added", "removed"}:
        return None
    if before is not None and after is not None:
        return (
            "inclusion_changed"
            if before.inclusion_status != after.inclusion_status
            else "filter_membership_changed"
        )
    if membership == "added":
        if from_month is not None and after.started_on <= month_end(from_month):
            return "previously_held_added"
        if from_month is not None and after.started_on > month_end(from_month):
            return "started_after_previous_period"
        return "not_in_previous_scope"
    if before.ended_on is not None and before.ended_on < month_start(to_month):
        return "ended_before_current_period"
    return "not_in_current_scope"


def _percent(state: str, previous_total: str | None, delta: int | None):
    if state != "available":
        return None, state
    assert previous_total is not None and delta is not None
    denominator = int(previous_total)
    if denominator == 0:
        return None, "zero_previous_total"
    if denominator < 0:
        return None, "negative_previous_total"
    with localcontext() as context:
        context.prec = 80
        result = (Decimal(delta) * 100 / Decimal(denominator)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return "0.00" if result == 0 else format(result, ".2f"), None


def compare_snapshots(
    previous: Snapshot | None,
    current: Snapshot | None,
    from_month: str | None,
    to_month: str,
    filters: ComparisonFilters,
    *,
    cursor: UUID | None = None,
    limit: int = 50,
) -> AssetComparisonResponse:
    if not 1 <= limit <= 200:
        raise DomainError("INVALID_PAGE_SIZE", "조회 건수를 확인해 주세요.", 422)
    before_period = None if from_month is None else _period(from_month, previous, filters)
    after_period = _period(to_month, current, filters)
    before = {} if previous is None else {row.asset_id: row for row in previous.values}
    after = {} if current is None else {row.asset_id: row for row in current.values}
    old_scope = {key for key, row in before.items() if _included(row, filters)}
    new_scope = {key for key, row in after.items() if _included(row, filters)}
    both = previous is not None and current is not None
    changed_share = (
        {
            key
            for key in old_scope & new_scope
            if Decimal(before[key].household_share) != Decimal(after[key].household_share)
        }
        if both
        else set()
    )
    added, removed = (new_scope - old_scope, old_scope - new_scope) if both else (set(), set())
    if current is None:
        state, total_delta, common_delta = "current_missing", None, None
    else:
        result = compare_months(
            None
            if previous is None
            else AssetMonth(previous.month, _calculation_values(previous, filters), previous.state),
            AssetMonth(current.month, _calculation_values(current, filters), current.state),
        )
        state, total_delta, common_delta = (
            result.state,
            result.total_delta_krw,
            result.common_scope_delta_krw,
        )
    available = state == "available"
    percent, percent_reason = _percent(
        state,
        None
        if before_period is None or before_period.totals is None
        else before_period.totals.net_assets_krw,
        total_delta,
    )
    keys = old_scope | new_scope
    # An explicit asset detail also projects excluded observations as reference values.
    if filters.asset_id is not None:
        keys |= {key for key, row in [*before.items(), *after.items()] if _matches(row, filters)}
    all_keys = sorted(keys)
    selected = [key for key in all_keys if cursor is None or key > cursor]
    items = []
    for key in selected[:limit]:
        old, new = before.get(key), after.get(key)
        old_in, new_in = key in old_scope, key in new_scope
        membership = (
            "unavailable"
            if not both
            else "common"
            if old_in and new_in
            else "added"
            if new_in
            else "removed"
            if old_in
            else "excluded"
        )
        comparable_values = (
            available
            and old is not None
            and new is not None
            and _matches(old, filters)
            and _matches(new, filters)
            and old.verification_state == new.verification_state == "verified"
            and old.owned_amount_krw is not None
            and new.owned_amount_krw is not None
            and ((old_in and new_in) or filters.asset_id is not None)
        )
        items.append(
            ComparisonItem(
                asset_id=key,
                before=old,
                after=new,
                before_in_scope=old_in,
                after_in_scope=new_in,
                membership=membership,
                share_changed=key in changed_share,
                same_scope=both and old_in and new_in and key not in changed_share,
                scope_reason=_scope_reason(
                    membership, old, new, from_month, to_month, key in changed_share
                ),
                amount_delta_krw=_money(int(new.owned_amount_krw) - int(old.owned_amount_krw))
                if comparable_values
                else None,
                net_assets_effect_krw=_money(_signed(new, new_in) - _signed(old, old_in))
                if available
                else None,
            )
        )
    return AssetComparisonResponse(
        from_month=from_month,
        to_month=to_month,
        filters=filters,
        state=state,
        previous=before_period,
        current=after_period,
        total_delta_krw=_money(total_delta),
        common_scope_delta_krw=_money(common_delta),
        change_percent=percent,
        change_percent_unavailable_reason=percent_reason,
        scope_changed=bool(added or removed or changed_share) if both else None,
        added_asset_ids=sorted(added),
        removed_asset_ids=sorted(removed),
        changed_share_asset_ids=sorted(changed_share),
        item_count=len(all_keys),
        items=items,
        next_cursor=selected[limit - 1] if len(selected) > limit else None,
    )


def month_series(first: str, last: str) -> list[str]:
    start, end = month_start(first), month_start(last)
    start_index, end_index = start.year * 12 + start.month - 1, end.year * 12 + end.month - 1
    if not 0 <= end_index - start_index < 120:
        raise DomainError(
            "INVALID_TREND_RANGE", "시작·종료 월과 최대 120개월 범위를 확인해 주세요.", 422
        )
    return [
        f"{index // 12:04d}-{index % 12 + 1:02d}" for index in range(start_index, end_index + 1)
    ]


def trend_point(
    month: str, snapshot: Snapshot | None, filters: ComparisonFilters
) -> AssetTrendPoint:
    period = _period(month, snapshot, filters)
    observed, confirmed, included, as_of_date = None, None, None, None
    dates = period.dates
    if snapshot is None:
        value_state = "missing_month"
    elif filters.asset_id is not None:
        row = next((row for row in snapshot.values if row.asset_id == filters.asset_id), None)
        if row is None:
            value_state = "missing_item"
        elif not _matches(row, filters):
            value_state = "outside_filter"
        else:
            observed = row.owned_amount_krw
            included = row.inclusion_status == "included"
            as_of_date = row.as_of_date
            dates = _dates(month, [row])
            value_state = (
                "missing_value"
                if observed is None
                else "verified"
                if snapshot.state == "confirmed" and row.verification_state == "verified"
                else "unconfirmed"
            )
            if value_state == "verified":
                confirmed = observed
    else:
        assert period.totals is not None
        observed = period.totals.net_assets_krw
        value_state = (
            "missing_value"
            if observed is None
            else "verified"
            if snapshot.state == "confirmed" and not period.totals.provisional
            else "unconfirmed"
        )
        if value_state == "verified":
            confirmed = observed
    return AssetTrendPoint(
        month=month,
        state=period.state,
        revision=period.revision,
        totals=period.totals,
        value_state=value_state,
        observed_amount_krw=observed,
        confirmed_amount_krw=confirmed,
        included_in_total=included,
        as_of_date=as_of_date,
        dates=dates,
    )


def _validate_filters(session: Session, principal: Principal, filters: ComparisonFilters) -> None:
    if filters.ownership_kind == "joint" and filters.owner_member_id is not None:
        raise DomainError(
            "INVALID_COMPARISON_FILTERS",
            "공동 소유와 개인 소유자 조건을 함께 지정할 수 없습니다.",
            422,
        )
    if filters.asset_id is not None:
        scoped_entity(session, Asset, filters.asset_id, principal)
    if filters.owner_member_id is not None:
        # Historical observations can belong to a now-inactive member of this household.
        scoped_entity(session, HouseholdMember, filters.owner_member_id, principal)


def _project_value(value: AssetMonthValue) -> MonthValueResponse:
    fields = {name: getattr(value, name) for name in MonthValueResponse.model_fields}
    fields["household_share"] = format(value.household_share, "f")
    for name in ("input_amount_krw", "owned_amount_krw"):
        fields[name] = None if fields[name] is None else krw_string(fields[name])
    return MonthValueResponse(**fields)


def _load_snapshots(
    session: Session, principal: Principal, months: list[str]
) -> dict[str, Snapshot]:
    periods = [month_start(month) for month in months]
    records = session.execute(
        select(AssetMonthRecord.period_month, AssetMonthRevision)
        .join(
            AssetMonthRevision,
            (AssetMonthRevision.household_id == AssetMonthRecord.household_id)
            & (AssetMonthRevision.month_id == AssetMonthRecord.id)
            & (AssetMonthRevision.id == AssetMonthRecord.current_revision_id),
        )
        .where(
            AssetMonthRecord.household_id == principal.household_id,
            AssetMonthRevision.household_id == principal.household_id,
            AssetMonthRecord.period_month.in_(periods),
        )
    ).all()
    if not records:
        return {}
    revision_ids = [revision.id for _, revision in records]
    by_revision = {revision_id: [] for revision_id in revision_ids}
    for value in session.scalars(
        select(AssetMonthValue)
        .where(
            AssetMonthValue.household_id == principal.household_id,
            AssetMonthValue.revision_id.in_(revision_ids),
        )
        .order_by(AssetMonthValue.revision_id, AssetMonthValue.asset_id)
    ):
        by_revision[value.revision_id].append(_project_value(value))
    return {
        f"{period.year:04d}-{period.month:02d}": Snapshot(
            f"{period.year:04d}-{period.month:02d}",
            revision.id,
            revision.revision_no,
            revision.version,
            revision.state,
            revision.confirmed_at,
            tuple(by_revision[revision.id]),
        )
        for period, revision in records
    }


def get_comparison(
    session: Session,
    principal: Principal,
    to_month: str,
    from_month: str | None,
    filters: ComparisonFilters,
    *,
    cursor: UUID | None = None,
    limit: int = 50,
) -> AssetComparisonResponse:
    current_start = month_start(to_month)
    if from_month is None and current_start != date.min:
        prior = current_start - timedelta(days=1)
        from_month = f"{prior.year:04d}-{prior.month:02d}"
    if from_month is not None and month_start(from_month) >= current_start:
        raise DomainError(
            "INVALID_COMPARISON_RANGE", "비교할 이전 월은 확인 월보다 앞서야 합니다.", 422
        )
    lock_asset_scope(session, principal)
    _validate_filters(session, principal, filters)
    snapshots = _load_snapshots(
        session, principal, [to_month] + ([from_month] if from_month else [])
    )
    try:
        result = compare_snapshots(
            None if from_month is None else snapshots.get(from_month),
            snapshots.get(to_month),
            from_month,
            to_month,
            filters,
            cursor=cursor,
            limit=limit,
        )
    except ValueError:
        raise DomainError(
            "TOTAL_OUT_OF_RANGE", "비교 가능한 금액 범위를 확인해 주세요.", 422
        ) from None
    session.commit()
    return result


def get_trend(
    session: Session,
    principal: Principal,
    from_month: str,
    to_month: str,
    filters: ComparisonFilters,
) -> AssetTrendResponse:
    months = month_series(from_month, to_month)
    lock_asset_scope(session, principal)
    _validate_filters(session, principal, filters)
    snapshots = _load_snapshots(session, principal, months)
    try:
        result = AssetTrendResponse(
            from_month=from_month,
            to_month=to_month,
            filters=filters,
            series_kind="asset_owned_amount"
            if filters.asset_id is not None
            else "household_net_assets",
            points=[trend_point(month, snapshots.get(month), filters) for month in months],
        )
    except ValueError:
        raise DomainError(
            "TOTAL_OUT_OF_RANGE", "추이를 조회할 금액 범위를 확인해 주세요.", 422
        ) from None
    session.commit()
    return result
