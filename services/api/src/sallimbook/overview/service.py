"""The household's current status from what is registered; read-only and never complete.

Each held item shows the latest amount the household saved for it, whatever month that was.
Unsaved and long-unchanged items are counted for a gentle notice instead of blocking the
view. Nothing here writes, carries forward or adjusts a month record.
"""

from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from sallimbook.accounts.models import FinancialAccount
from sallimbook.assets.calculations import AssetValue, asset_totals
from sallimbook.assets.locking import lock_asset_scope
from sallimbook.assets.models import Asset
from sallimbook.assets.month_models import AssetMonthRecord, AssetMonthRevision, AssetMonthValue
from sallimbook.cards.models import Card
from sallimbook.cashflow import expense_plan_service, recurring_service
from sallimbook.cashflow import service as cash_service
from sallimbook.cashflow.planning_models import IncomePlanningRevision
from sallimbook.core.authorization import Principal
from sallimbook.core.errors import DomainError
from sallimbook.core.types import SEOUL, krw_string, month_end, month_start
from sallimbook.homecare.models import Appliance
from sallimbook.insurance.event_models import InsuranceClaim
from sallimbook.insurance.models import InsuranceCase, InsurancePolicy
from sallimbook.overview.schemas import (
    HoldingGroup,
    HoldingGroupTotal,
    HoldingsOverview,
    HouseholdOverviewResponse,
    HouseholdTrendsResponse,
    InsuranceOverview,
    InvestmentHolding,
    InvestmentsOverview,
    MonthlyPlanOverview,
    NamedItem,
    NetAssetsPoint,
    OverviewHolding,
    PlanPoint,
    RegisteredItems,
)

# Amounts that usually move every month; slower valuations are never called out of date.
STALE_AFTER_MONTHS = 3
MONTHLY_CATEGORIES = frozenset({"financial", "loan"})
GROUP_ORDER: tuple[HoldingGroup, ...] = (
    "accounts",
    "financial",
    "real_estate",
    "deposit",
    "loan",
    "other",
)
CLAIMS_IN_PROGRESS = ("draft", "submitted", "documents_required", "reviewing")
PREVIEW_LIMIT = 4
# Accounts whose value moves with the market, so money put in is worth comparing.
INVESTMENT_TYPES = frozenset({"brokerage", "pension_savings", "irp", "dc_pension", "isa"})
MAX_TREND_MONTHS = 36


def _total_error() -> DomainError:
    return DomainError("TOTAL_OUT_OF_RANGE", "합산 가능한 금액 범위를 확인해 주세요.", 422)


def percent(part: int, whole: int) -> str | None:
    """`part` over `whole` as a percentage with one decimal; nothing to divide by gives None."""
    if whole <= 0:
        return None
    value = (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), ROUND_HALF_UP)
    # A loss too small to show is "0.0", never "-0.0".
    return "0.0" if value == 0 else str(value)


def _shift_month(month: str, delta: int) -> str:
    first = month_start(month)
    index = first.year * 12 + first.month - 1 + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _month_text(period) -> str:
    return f"{period.year:04d}-{period.month:02d}"


def _months_between(earlier: str, later: str) -> int:
    first, last = month_start(earlier), month_start(later)
    return (last.year - first.year) * 12 + last.month - first.month


def _held_assets(session: Session, principal: Principal, month: str) -> list[Asset]:
    # Held on the month's last day: an item that ended earlier in the month is not current.
    end = month_end(month)
    return list(
        session.scalars(
            select(Asset)
            .where(
                Asset.household_id == principal.household_id,
                Asset.started_on <= end,
                or_(Asset.ended_on.is_(None), Asset.ended_on >= end),
            )
            .order_by(Asset.name, Asset.id)
        )
    )


def _latest_saved(session: Session, principal: Principal, asset_ids, month: str) -> dict:
    """Latest entered amount per asset in each month's current revision up to `month`."""
    if not asset_ids:
        return {}
    rows = session.execute(
        select(AssetMonthRecord.period_month, AssetMonthValue)
        .join(
            AssetMonthRevision,
            (AssetMonthRevision.household_id == AssetMonthRecord.household_id)
            & (AssetMonthRevision.month_id == AssetMonthRecord.id)
            & (AssetMonthRevision.id == AssetMonthRecord.current_revision_id),
        )
        .join(
            AssetMonthValue,
            (AssetMonthValue.household_id == AssetMonthRevision.household_id)
            & (AssetMonthValue.revision_id == AssetMonthRevision.id),
        )
        .where(
            AssetMonthRecord.household_id == principal.household_id,
            AssetMonthRecord.period_month <= month_start(month),
            AssetMonthValue.asset_id.in_(asset_ids),
            # A carried value repeats an earlier entry; the entry itself carries the basis month.
            AssetMonthValue.verification_state == "verified",
            AssetMonthValue.owned_amount_krw.is_not(None),
        )
        .order_by(AssetMonthValue.asset_id, AssetMonthRecord.period_month.desc())
    ).all()
    latest: dict = {}
    for period, value in rows:
        latest.setdefault(value.asset_id, (_month_text(period), value))
    return latest


def _group(asset: Asset, has_account: bool) -> HoldingGroup:
    if has_account:
        return "accounts"
    return asset.category


def _holdings(session: Session, principal: Principal, month: str) -> HoldingsOverview:
    assets = _held_assets(session, principal, month)
    ids = [asset.id for asset in assets]
    accounts = (
        dict(
            session.execute(
                select(FinancialAccount.asset_id, FinancialAccount.id).where(
                    FinancialAccount.household_id == principal.household_id,
                    FinancialAccount.asset_id.in_(ids),
                )
            ).all()
        )
        if ids
        else {}
    )
    latest = _latest_saved(session, principal, ids, month)
    items: list[OverviewHolding] = []
    for asset in assets:
        basis, value = latest.get(asset.id, (None, None))
        included = asset.inclusion_status == "included"
        amount = None if value is None else int(value.owned_amount_krw)
        items.append(
            OverviewHolding(
                asset_id=asset.id,
                account_id=accounts.get(asset.id),
                name=asset.name,
                kind=asset.kind,
                category=asset.category,
                group=_group(asset, asset.id in accounts),
                included=included,
                owned_amount_krw=None if amount is None else krw_string(amount),
                basis_month=basis,
                as_of_date=None if value is None else value.as_of_date,
                stale=bool(
                    included
                    and basis is not None
                    and asset.category in MONTHLY_CATEGORIES
                    and _months_between(basis, month) >= STALE_AFTER_MONTHS
                ),
            )
        )
    order = {group: index for index, group in enumerate(GROUP_ORDER)}
    items.sort(key=lambda item: (order[item.group], item.name, str(item.asset_id)))
    counted = [item for item in items if item.included]
    known = [item for item in counted if item.owned_amount_krw is not None]

    def totals(rows: list[OverviewHolding]):
        # Each asset is one source row, so an account and its asset are never added twice.
        return asset_totals(
            AssetValue(
                str(row.asset_id), int(row.owned_amount_krw), row.kind, household_share=Decimal(1)
            )
            for row in rows
        )

    try:
        overall = totals(known)
        groups = []
        for group in GROUP_ORDER:
            members = [item for item in counted if item.group == group]
            if not members:
                continue
            result = totals([item for item in members if item.owned_amount_krw is not None])
            groups.append(
                HoldingGroupTotal(
                    group=group,
                    count=len(members),
                    known_count=sum(item.owned_amount_krw is not None for item in members),
                    assets_krw=krw_string(result.assets_krw),
                    liabilities_krw=krw_string(result.liabilities_krw),
                )
            )
    except ValueError:
        raise DomainError(
            "TOTAL_OUT_OF_RANGE", "합산 가능한 금액 범위를 확인해 주세요.", 422
        ) from None
    bases = [item.basis_month for item in known if item.basis_month is not None]
    return HoldingsOverview(
        assets_krw=krw_string(overall.assets_krw),
        liabilities_krw=krw_string(overall.liabilities_krw),
        net_assets_krw=krw_string(overall.net_assets_krw),
        item_count=len(counted),
        known_count=len(known),
        missing_count=len(counted) - len(known),
        stale_count=sum(item.stale for item in counted),
        current_count=sum(item.basis_month == month for item in known),
        oldest_basis_month=min(bases) if bases else None,
        groups=groups,
        items=items,
    )


def _registered(session: Session, principal: Principal, model, name_columns) -> RegisteredItems:
    active = (model.household_id == principal.household_id, model.ended_on.is_(None))
    count = session.scalar(select(func.count()).select_from(model).where(*active)) or 0
    rows = session.execute(
        select(model.id, *name_columns)
        .where(*active)
        .order_by(*name_columns, model.id)
        .limit(PREVIEW_LIMIT)
    ).all()
    return RegisteredItems(
        count=count,
        items=[
            NamedItem(id=row[0], name=next(value for value in row[1:] if value)) for row in rows
        ],
    )


def _insurance(session: Session, principal: Principal) -> InsuranceOverview:
    household = principal.household_id
    active = (
        InsurancePolicy.household_id == household,
        InsurancePolicy.status == "active",
    )

    def count(model, *conditions) -> int:
        return session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0

    policies = session.execute(
        select(InsurancePolicy.id, InsurancePolicy.insurer, InsurancePolicy.product_name)
        .where(*active)
        .order_by(InsurancePolicy.insurer, InsurancePolicy.product_name, InsurancePolicy.id)
        .limit(PREVIEW_LIMIT)
    ).all()
    return InsuranceOverview(
        active_policy_count=count(InsurancePolicy, *active),
        open_case_count=count(
            InsuranceCase,
            InsuranceCase.household_id == household,
            InsuranceCase.financial_state == "open",
        ),
        claims_in_progress_count=count(
            InsuranceClaim,
            InsuranceClaim.household_id == household,
            InsuranceClaim.claim_state.in_(CLAIMS_IN_PROGRESS),
        ),
        documents_required_count=count(
            InsuranceClaim,
            InsuranceClaim.household_id == household,
            InsuranceClaim.claim_state == "documents_required",
        ),
        policies=[
            NamedItem(id=row.id, name=f"{row.insurer} · {row.product_name}") for row in policies
        ],
    )


def _investments(
    session: Session, principal: Principal, holdings: HoldingsOverview
) -> InvestmentsOverview:
    """Latest saved value against hand-entered money put in, for investment-type accounts."""
    held = {item.account_id: item for item in holdings.items if item.account_id and item.included}
    accounts = (
        list(
            session.scalars(
                select(FinancialAccount)
                .where(
                    FinancialAccount.household_id == principal.household_id,
                    FinancialAccount.id.in_(held),
                    FinancialAccount.account_type.in_(INVESTMENT_TYPES),
                )
                .order_by(FinancialAccount.id)
            )
        )
        if held
        else []
    )
    items: list[InvestmentHolding] = []
    missing = 0
    try:
        for account in accounts:
            holding = held[account.id]
            if account.contributed_krw is None:
                missing += 1
                continue
            if holding.owned_amount_krw is None or holding.basis_month is None:
                continue
            value, put_in = int(holding.owned_amount_krw), int(account.contributed_krw)
            items.append(
                InvestmentHolding(
                    asset_id=holding.asset_id,
                    account_id=account.id,
                    name=holding.name,
                    account_type=account.account_type,
                    value_krw=krw_string(value),
                    basis_month=holding.basis_month,
                    contributed_krw=krw_string(put_in),
                    contributed_as_of=account.contributed_as_of,
                    gain_krw=krw_string(value - put_in),
                    return_percent=percent(value - put_in, put_in),
                )
            )
        value = sum(int(item.value_krw) for item in items)
        put_in = sum(int(item.contributed_krw) for item in items)
        items.sort(key=lambda item: (-int(item.value_krw), item.name, str(item.account_id)))
        return InvestmentsOverview(
            count=len(items),
            value_krw=krw_string(value),
            contributed_krw=krw_string(put_in),
            gain_krw=krw_string(value - put_in),
            return_percent=percent(value - put_in, put_in),
            missing_contribution_count=missing,
            items=items,
        )
    except ValueError:
        raise _total_error() from None


def _plan_figures(session: Session, principal: Principal, day, income: tuple[int, int, int]):
    """The plan in effect on `day` against (known income, income count, unknown count)."""
    plan = expense_plan_service.plan_summary(session, principal, day)
    # Only plans counted in the monthly total; loan payments and savings stay apart from spending.
    by_type = {row.key: row for row in plan.economic_types}

    def known(key: str) -> int:
        row = by_type.get(key)
        return 0 if row is None else int(row.known_krw)

    expected = income[0]
    spending, loan, transfer = known("expense"), known("loan"), known("asset_transfer")
    try:
        before = krw_string(expected - spending - loan)
        after = krw_string(expected - spending - loan - transfer)
    except ValueError:
        raise _total_error() from None
    return plan, spending, loan, transfer, before, after


def _plan(session: Session, principal: Principal) -> MonthlyPlanOverview:
    day = recurring_service.today()
    income = cash_service.expected_summary(session, principal)
    plan, spending, loan, transfer, before, after = _plan_figures(
        session,
        principal,
        day,
        (int(income.known_amount_krw), income.record_count, income.unknown_count),
    )
    return MonthlyPlanOverview(
        as_of=day,
        expected_income_known_krw=income.known_amount_krw,
        expected_income_count=income.record_count,
        expected_income_unknown_count=income.unknown_count,
        spending_known_krw=str(spending),
        loan_known_krw=str(loan),
        transfer_known_krw=str(transfer),
        planned_unknown_count=plan.included_unknown_count,
        unconverted_count=sum(row.unconverted_count for row in plan.economic_types),
        excluded_known_krw=plan.excluded_known_krw,
        margin_before_transfers_krw=before,
        margin_after_transfers_krw=after,
    )


def _expected_income_history(session: Session, principal: Principal):
    """Every saved state of each expected income, oldest first, for month-end lookups."""
    history: dict = {}
    for row in session.scalars(
        select(IncomePlanningRevision)
        .where(
            IncomePlanningRevision.household_id == principal.household_id,
            IncomePlanningRevision.kind == "expected",
        )
        .order_by(IncomePlanningRevision.resource_id, IncomePlanningRevision.version)
    ):
        history.setdefault(row.resource_id, []).append((row.created_at, row.snapshot))
    return history


def _expected_income_at(history, moment: datetime) -> tuple[int, int, int]:
    """(known total, active count, active without an amount) as registered just before `moment`."""
    known = count = unknown = 0
    for states in history.values():
        current = None
        for created_at, snapshot in states:
            if created_at >= moment:
                break
            current = snapshot
        if current is None or not current.get("active", True):
            continue
        count += 1
        if current.get("amount_krw") is None:
            unknown += 1
        else:
            known += int(current["amount_krw"])
    return known, count, unknown


def _confirmed_months(session: Session, principal: Principal, first: str, last: str) -> set[str]:
    return {
        _month_text(period)
        for period in session.scalars(
            select(AssetMonthRecord.period_month)
            .join(
                AssetMonthRevision,
                (AssetMonthRevision.household_id == AssetMonthRecord.household_id)
                & (AssetMonthRevision.id == AssetMonthRecord.current_revision_id),
            )
            .where(
                AssetMonthRecord.household_id == principal.household_id,
                AssetMonthRecord.period_month >= month_start(first),
                AssetMonthRecord.period_month <= month_start(last),
                AssetMonthRevision.state == "confirmed",
            )
        )
    }


def get_trends(
    session: Session, principal: Principal, to_month: str, months: int
) -> HouseholdTrendsResponse:
    """Month by month, what the registered records said; nothing is written or carried."""
    today = recurring_service.today()
    current = f"{today.year:04d}-{today.month:02d}"
    if to_month > current or not 1 <= months <= MAX_TREND_MONTHS:
        raise DomainError("INVALID_MONTH_RANGE", "조회할 월 범위를 확인해 주세요.", 422)
    lock_asset_scope(session, principal)
    labels = [_shift_month(to_month, delta) for delta in range(1 - months, 1)]
    # Years before 0001 cannot exist; a shorter history simply starts later.
    labels = [label for label in labels if label >= "0001-01"]
    confirmed = _confirmed_months(session, principal, labels[0], labels[-1])
    history = _expected_income_history(session, principal)
    net_assets: list[NetAssetsPoint] = []
    plan: list[PlanPoint] = []
    for month in labels:
        holdings = _holdings(session, principal, month)
        entered = holdings.known_count > 0
        net_assets.append(
            NetAssetsPoint(
                month=month,
                assets_krw=holdings.assets_krw if entered else None,
                liabilities_krw=holdings.liabilities_krw if entered else None,
                net_assets_krw=holdings.net_assets_krw if entered else None,
                item_count=holdings.item_count,
                known_count=holdings.known_count,
                entered_count=holdings.current_count,
                confirmed=month in confirmed,
            )
        )
        # A past month is read at its end; the running month as it stands today.
        day = today if month == current else month_end(month)
        moment = (
            datetime.now(UTC)
            if month == current
            else datetime.combine(day + timedelta(days=1), time.min, SEOUL).astimezone(UTC)
        )
        income = _expected_income_at(history, moment)
        summary, spending, loan, transfer, before, after = _plan_figures(
            session, principal, day, income
        )
        ready = income[1] > income[2]
        plan.append(
            PlanPoint(
                month=month,
                as_of=day,
                income_known_krw=krw_string(income[0]),
                income_count=income[1],
                income_unknown_count=income[2],
                spending_known_krw=str(spending),
                loan_known_krw=str(loan),
                transfer_known_krw=str(transfer),
                planned_unknown_count=summary.included_unknown_count,
                margin_before_transfers_krw=before if ready else None,
                margin_after_transfers_krw=after if ready else None,
                actual_income_krw=cash_service.summary(
                    session, principal, month
                ).totals.earned_net_krw,
            )
        )
    result = HouseholdTrendsResponse(
        to_month=to_month, months=len(labels), net_assets=net_assets, plan=plan
    )
    session.commit()
    return result


def get_overview(session: Session, principal: Principal, month: str) -> HouseholdOverviewResponse:
    # Every writer takes the household row first, so holding it reads one consistent state.
    lock_asset_scope(session, principal)
    result = HouseholdOverviewResponse(
        month=month,
        holdings=(holdings := _holdings(session, principal, month)),
        investments=_investments(session, principal, holdings),
        cards=_registered(session, principal, Card, (Card.alias, Card.product_name)),
        appliances=_registered(session, principal, Appliance, (Appliance.name,)),
        insurance=_insurance(session, principal),
        plan=_plan(session, principal),
    )
    session.commit()
    return result
