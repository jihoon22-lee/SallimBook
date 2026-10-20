"""Shared synthetic vectors plus authenticated comparison/trend API checks."""

from datetime import UTC, datetime
from functools import partial
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_accounts import make_actor
from test_asset_calculations import CATALOG, vector
from test_asset_months import add_asset, confirm, draft, observe, read_month

from sallimbook.assets.comparison_router import router as comparison_router
from sallimbook.assets.comparison_schemas import ComparisonFilters
from sallimbook.assets.comparison_service import (
    Snapshot,
    compare_snapshots,
    month_series,
    trend_point,
)
from sallimbook.assets.month_router import router as month_router
from sallimbook.assets.month_schemas import MonthValueResponse
from sallimbook.assets.router import router as asset_router
from sallimbook.config import Settings
from sallimbook.core.errors import DomainError
from sallimbook.core.http import install_http_contract
from sallimbook.identity.router import router as identity_router


def row(amount, *, asset_id=None, kind="asset", share="1", included=True, state="verified", **more):
    value = MonthValueResponse(
        id=uuid4(),
        asset_id=asset_id or uuid4(),
        name="합성 비교 자산",
        kind=kind,
        category="financial" if kind == "asset" else "loan",
        ownership_kind="joint",
        owner_member_id=None,
        household_share=share,
        amount_basis="owned",
        inclusion_status="included" if included else "excluded",
        started_on="2025-01-01",
        ended_on=None,
        source_asset_version=1,
        input_amount_krw=amount,
        owned_amount_krw=amount,
        as_of_date="2026-01-31" if state == "verified" else None,
        verification_state=state,
        origin="manual",
        origin_revision_id=None,
        change_reason=None,
        version=1,
    )
    return MonthValueResponse.model_validate(value.model_dump() | more)


def snapshot(month, values, state="confirmed"):
    return Snapshot(
        month,
        uuid4(),
        1,
        1,
        state,
        datetime(2026, 3, 1, tzinfo=UTC) if state == "confirmed" else None,
        tuple(values),
    )


def comparison(previous, current, filters=None):
    return compare_snapshots(
        previous, current, "2026-01", "2026-02", filters or ComparisonFilters(), limit=200
    )


def test_shared_t01_t02_t03_t04_use_owned_source_once():
    values, expected = vector(1)
    current = snapshot(
        "2026-02", [row(values["assets_krw"]), row(values["liabilities_krw"], kind="liability")]
    )
    result = comparison(None, current)
    assert result.current.totals.net_assets_krw == expected["net_assets_krw"]
    assert result.state == "no_previous_month" and result.total_delta_krw is None
    for number in (2, 3, 4):
        values, expected = vector(number)
        amount = values.get("amount_krw") or expected["household_total_krw"]
        source = row(amount, share="0.5" if number == 3 else "1")
        result = comparison(None, snapshot("2026-02", [source]))
        assert result.current.totals.assets_krw == expected["household_total_krw"]
        assert result.item_count == result.current.totals.item_count == 1


@pytest.mark.parametrize(
    "case", CATALOG["edge_cases"]["snapshot_states"], ids=lambda item: item["name"]
)
def test_shared_missing_zero_carried_and_verified(case):
    source = uuid4()
    previous = snapshot("2026-01", [row(case["previous_krw"], asset_id=source)])
    current_row = row(case["current_krw"], asset_id=source, state=case["verification_state"])
    current = snapshot("2026-02", [current_row], "confirmed" if case["can_confirm"] else "draft")
    result = comparison(previous, current)
    assert result.total_delta_krw == case["expected_delta_krw"]
    point = trend_point("2026-02", current, ComparisonFilters())
    assert point.observed_amount_krw == case["current_krw"]
    assert point.confirmed_amount_krw == (case["current_krw"] if case["can_confirm"] else None)
    assert (
        result.change_percent is None
        if not case["can_confirm"]
        else result.change_percent is not None
    )


def test_shared_t07_late_scope_added_and_removed_are_not_inferred_savings():
    values, expected = vector(7)
    previous = snapshot(
        "2026-01",
        [row(item["amount_krw"], asset_id=UUID(item["asset_id"])) for item in values["previous"]],
    )
    current = snapshot(
        "2026-02",
        [row(item["amount_krw"], asset_id=UUID(item["asset_id"])) for item in values["current"]],
    )
    result = comparison(previous, current)
    assert result.total_delta_krw == expected["total_delta_krw"]
    assert result.common_scope_delta_krw == expected["common_scope_delta_krw"]
    assert result.scope_changed is True
    added = next(item for item in result.items if item.membership == "added")
    assert added.scope_reason == "previously_held_added"
    assert added.before is None and added.amount_delta_krw is None
    assert added.net_assets_effect_krw == "10000000"
    assert (
        "savings" not in result.model_dump_json() and "return_rate" not in result.model_dump_json()
    )


def test_share_change_does_not_enter_common_scope_and_liability_reduction_is_positive_effect():
    home, loan = uuid4(), uuid4()
    previous = snapshot(
        "2026-01",
        [row("500", asset_id=home, share="0.5"), row("100", asset_id=loan, kind="liability")],
    )
    current = snapshot(
        "2026-02",
        [row("1000", asset_id=home, share="1"), row("80", asset_id=loan, kind="liability")],
    )
    result = comparison(previous, current)
    assert result.total_delta_krw == "520" and result.common_scope_delta_krw == "20"
    assert result.changed_share_asset_ids == [home]
    debt = next(item for item in result.items if item.asset_id == loan)
    assert debt.amount_delta_krw == "-20" and debt.net_assets_effect_krw == "20"
    changed = next(item for item in result.items if item.asset_id == home)
    assert changed.amount_delta_krw == "500" and not changed.same_scope


@pytest.mark.parametrize(
    "prior,now,percent,reason",
    [
        ("0", "1", None, "zero_previous_total"),
        ("3", "4", "33.33", None),
        ("8", "9", "12.50", None),
        ("400", "399", "-0.25", None),
    ],
)
def test_percent_uses_decimal_and_never_divides_zero(prior, now, percent, reason):
    source = uuid4()
    result = comparison(
        snapshot("2026-01", [row(prior, asset_id=source)]),
        snapshot("2026-02", [row(now, asset_id=source)]),
    )
    assert result.change_percent == percent and result.change_percent_unavailable_reason == reason


def test_negative_net_base_and_large_exact_integer_change():
    source = uuid4()
    result = comparison(
        snapshot("2026-01", [row("100", asset_id=source, kind="liability")]),
        snapshot("2026-02", [row("90", asset_id=source, kind="liability")]),
    )
    assert result.total_delta_krw == "10" and result.change_percent is None
    assert result.change_percent_unavailable_reason == "negative_previous_total"
    result = comparison(
        snapshot("2026-01", [row("9007199254740993", asset_id=source)]),
        snapshot("2026-02", [row("9007199254740994", asset_id=source)]),
    )
    assert result.total_delta_krw == "1" and result.items[0].amount_delta_krw == "1"
    assert result.change_percent == "0.00"


def test_date_warnings_and_historical_filters_do_not_use_live_metadata():
    owner = uuid4()
    values = [
        row("10", as_of_date="2026-02-20", ownership_kind="individual", owner_member_id=owner),
        row("20", as_of_date="2026-02-28"),
    ]
    current = snapshot("2026-02", values)
    result = comparison(None, current)
    assert result.current.dates.mixed_dates is True
    assert result.current.dates.non_month_end_asset_ids == [values[0].asset_id]
    result = comparison(None, current, ComparisonFilters(owner_member_id=owner))
    assert result.current.totals.assets_krw == "10" and result.current.dates.mixed_dates is False
    assert result.item_count == 1


def test_excluded_asset_detail_retains_observation_but_never_enters_household_total():
    source = uuid4()
    previous = snapshot("2026-01", [row("10", asset_id=source, included=False)])
    current = snapshot("2026-02", [row("20", asset_id=source, included=False)])
    result = comparison(previous, current, ComparisonFilters(asset_id=source))
    assert result.current.totals.net_assets_krw == "0"
    assert result.items[0].membership == "excluded" and result.items[0].amount_delta_krw == "10"
    assert result.items[0].net_assets_effect_krw == "0"
    point = trend_point("2026-02", current, ComparisonFilters(asset_id=source))
    assert point.confirmed_amount_krw == "20" and point.included_in_total is False


@pytest.mark.parametrize("state", ["draft", "confirmed", "reopened"])
@pytest.mark.parametrize("observed_on", [None, "2026-02-20", "2026-02-28"])
def test_selected_excluded_dates_follow_observation_not_total_or_confirmation(state, observed_on):
    excluded = row(
        None if observed_on is None else "20",
        included=False,
        state="missing" if observed_on is None else "verified",
        as_of_date=observed_on,
    )
    included = row("100", as_of_date="2026-02-28")
    current = snapshot("2026-02", [excluded, included], state)
    previous = snapshot(
        "2026-01", [row("10", asset_id=excluded.asset_id, included=False, as_of_date="2026-01-15")]
    )
    selected = comparison(previous, current, ComparisonFilters(asset_id=excluded.asset_id))
    assert selected.current.state == state
    assert selected.current.totals.net_assets_krw == "0"
    assert selected.current.totals.item_count == 0
    assert selected.previous.dates.non_month_end_asset_ids == [excluded.asset_id]
    assert selected.current.dates.missing_date_asset_ids == (
        [excluded.asset_id] if observed_on is None else []
    )
    assert selected.current.dates.non_month_end_asset_ids == (
        [excluded.asset_id] if observed_on == "2026-02-20" else []
    )
    # Another asset's different date and the previous month's date are not mixed into this period.
    assert selected.current.dates.mixed_dates is False
    assert selected.items[0].after == excluded
    assert selected.total_delta_krw == ("0" if state == "confirmed" else None)
    assert selected.items[0].net_assets_effect_krw == ("0" if state == "confirmed" else None)
    general = comparison(previous, current)
    assert general.current.totals.net_assets_krw == "100"
    assert general.current.dates.model_dump() == {
        "non_month_end_asset_ids": [],
        "missing_date_asset_ids": [],
        "mixed_dates": False,
    }
    point = trend_point("2026-02", current, ComparisonFilters(asset_id=excluded.asset_id))
    assert point.dates == selected.current.dates
    assert point.confirmed_amount_krw == (
        "20" if state == "confirmed" and observed_on is not None else None
    )


@pytest.mark.parametrize(
    "scope", ["other_asset", "kind", "category", "ownership_kind", "owner_member_id"]
)
def test_selected_excluded_date_diagnostics_still_require_every_historical_filter(scope):
    owner = uuid4()
    excluded = row(
        "20",
        included=False,
        as_of_date="2026-02-20",
        ownership_kind="individual",
        owner_member_id=owner,
    )
    filters = {"asset_id": excluded.asset_id}
    filters.update(
        {
            "other_asset": {"asset_id": uuid4()},
            "kind": {"kind": "liability"},
            "category": {"category": "real_estate"},
            "ownership_kind": {"ownership_kind": "joint"},
            "owner_member_id": {"owner_member_id": uuid4()},
        }[scope]
    )
    result = comparison(None, snapshot("2026-02", [excluded]), ComparisonFilters(**filters))
    assert result.item_count == result.current.totals.item_count == 0
    assert result.current.dates.model_dump() == {
        "non_month_end_asset_ids": [],
        "missing_date_asset_ids": [],
        "mixed_dates": False,
    }


def test_general_mixed_dates_include_only_matching_included_observations():
    current = snapshot(
        "2026-02",
        [
            row("10", as_of_date="2026-02-20"),
            row("20", as_of_date="2026-02-28"),
            row(None, included=False, state="missing"),
        ],
    )
    result = comparison(None, current)
    assert result.current.dates.mixed_dates is True
    assert result.current.dates.missing_date_asset_ids == []
    assert result.current.dates.non_month_end_asset_ids == [current.values[0].asset_id]
    assert result.current.totals.net_assets_krw == "30"


def test_missing_month_reopened_and_filtered_out_are_distinct_gaps():
    source = uuid4()
    filters = ComparisonFilters(asset_id=source)
    assert trend_point("2026-02", None, filters).value_state == "missing_month"
    current = snapshot("2026-02", [row("20", asset_id=source)], "reopened")
    point = trend_point("2026-02", current, filters)
    assert point.observed_amount_krw == "20" and point.confirmed_amount_krw is None
    assert point.value_state == "unconfirmed" and point.state == "reopened"
    assert (
        trend_point(
            "2026-02", current, ComparisonFilters(asset_id=source, kind="liability")
        ).value_state
        == "outside_filter"
    )
    assert (
        trend_point("2026-02", current, ComparisonFilters(asset_id=uuid4())).value_state
        == "missing_item"
    )
    result = comparison(snapshot("2026-01", [row("10", asset_id=source)]), None)
    assert result.state == "current_missing" and result.total_delta_krw is None
    assert result.removed_asset_ids == [] and result.items[0].membership == "unavailable"


def test_continuous_range_handles_year_boundary_and_enforces_bound():
    assert month_series("2025-12", "2026-02") == ["2025-12", "2026-01", "2026-02"]
    assert month_series("9999-12", "9999-12") == ["9999-12"]
    for first, last in [("2026-02", "2026-01"), ("2000-01", "2010-01")]:
        with pytest.raises(DomainError, match="INVALID_TREND_RANGE"):
            month_series(first, last)


@pytest.fixture
def comparison_app(db_engine):
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(environment="test", _env_file=None)
    install_http_contract(app)
    for router in (identity_router, asset_router, month_router, comparison_router):
        app.include_router(router)
    return app


@pytest.fixture
def actor(db_engine):
    return make_actor(db_engine)


def api_compare(client, actor, **params):
    return client.get(
        "/api/v1/asset-comparison",
        params={"from": "2026-01", "to": "2026-02", **params},
        headers=actor.headers,
    )


@pytest.mark.database
class TestComparisonDatabase:
    def test_manual_months_common_scope_and_trends(self, comparison_app, actor):
        with TestClient(comparison_app) as client:
            home = add_asset(
                client,
                actor,
                name="합성 비교 주택",
                category="real_estate",
                amount_basis="whole",
                household_share="0.5",
            )
            draft(client, actor, "2026-01")
            observe(client, actor, "2026-01", home["id"], "600000001", "2026-01-31")
            assert confirm(client, actor, "2026-01").status_code == 200
            extra = add_asset(client, actor, name="합성 뒤늦은 등록", started_on="2025-01-01")
            draft(client, actor, "2026-02")
            observe(client, actor, "2026-02", home["id"], "600000003", "2026-02-28")
            observe(client, actor, "2026-02", extra["id"], "10000000", "2026-02-28")
            assert (
                confirm(client, actor, "2026-02", acknowledge_scope_change=True).status_code == 200
            )
            response = api_compare(client, actor)
            assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
            result = response.json()
            assert (
                result["total_delta_krw"] == "10000001" and result["common_scope_delta_krw"] == "1"
            )
            assert result["added_asset_ids"] == [extra["id"]]
            trend = client.get(
                "/api/v1/asset-trends",
                params={"from": "2025-12", "to": "2026-03"},
                headers=actor.headers,
            )
            assert trend.status_code == 200
            points = trend.json()["points"]
            assert [point["month"] for point in points] == [
                "2025-12",
                "2026-01",
                "2026-02",
                "2026-03",
            ]
            assert [point["confirmed_amount_krw"] for point in points] == [
                None,
                "300000001",
                "310000002",
                None,
            ]
            assert points[0]["totals"] is None

    def test_selected_excluded_dates_survive_draft_and_confirmation_without_changing_totals(
        self, comparison_app, actor
    ):
        with TestClient(comparison_app) as client:
            excluded = add_asset(client, actor, inclusion_status="excluded")
            included = add_asset(client, actor, name="합성 포함 자산")
            draft(client, actor, "2026-01")
            observe(client, actor, "2026-01", included["id"], "100", "2026-01-31")
            assert confirm(client, actor, "2026-01").status_code == 200
            draft(client, actor, "2026-02")
            observe(client, actor, "2026-02", included["id"], "120", "2026-02-28")
            selected = api_compare(client, actor, asset_id=excluded["id"]).json()
            assert selected["state"] == "unconfirmed"
            assert selected["previous"]["dates"]["missing_date_asset_ids"] == [excluded["id"]]
            assert selected["current"]["dates"]["missing_date_asset_ids"] == [excluded["id"]]
            observe(client, actor, "2026-02", excluded["id"], "999", "2026-02-20")
            for confirmed in (False, True):
                if confirmed:
                    assert confirm(client, actor, "2026-02").status_code == 200
                selected = api_compare(client, actor, asset_id=excluded["id"]).json()
                assert selected["current"]["state"] == ("confirmed" if confirmed else "draft")
                assert selected["current"]["dates"] == {
                    "non_month_end_asset_ids": [excluded["id"]],
                    "missing_date_asset_ids": [],
                    "mixed_dates": False,
                }
                assert selected["current"]["totals"]["net_assets_krw"] == "0"
                assert selected["items"][0]["after"]["owned_amount_krw"] == "999"
                assert selected["items"][0]["after_in_scope"] is False
                general = api_compare(client, actor).json()
                assert general["current"]["totals"]["net_assets_krw"] == "120"
                assert general["current"]["dates"] == {
                    "non_month_end_asset_ids": [],
                    "missing_date_asset_ids": [],
                    "mixed_dates": False,
                }
                mismatch = api_compare(
                    client, actor, asset_id=excluded["id"], kind="liability"
                ).json()
                assert mismatch["items"] == []
                assert mismatch["current"]["dates"]["non_month_end_asset_ids"] == []
            assert general["total_delta_krw"] == "20"

    def test_foreign_assets_owners_and_anonymous_access_fail_closed(
        self, comparison_app, actor, db_engine
    ):
        foreign = make_actor(db_engine)
        with TestClient(comparison_app) as client:
            other_asset = add_asset(client, foreign)
            for endpoint in ("asset-comparison", "asset-trends"):
                base = {"from": "2026-01", "to": "2026-02"}
                assert client.get(f"/api/v1/{endpoint}", params=base).status_code == 401
                for field, value in [
                    ("asset_id", other_asset["id"]),
                    ("owner_member_id", str(foreign.member_id)),
                ]:
                    response = client.get(
                        f"/api/v1/{endpoint}", params={**base, field: value}, headers=actor.headers
                    )
                    assert (
                        response.status_code == 404
                        and "no-store" in response.headers["cache-control"]
                    )

    def test_live_metadata_change_and_reopen_never_replace_historical_scope(
        self, comparison_app, actor
    ):
        with TestClient(comparison_app) as client:
            home = add_asset(client, actor, household_share="0.5", amount_basis="whole")
            for month, date, amount in [
                ("2026-01", "2026-01-31", "1000"),
                ("2026-02", "2026-02-28", "1200"),
            ]:
                draft(client, actor, month)
                observe(client, actor, month, home["id"], amount, date)
                assert confirm(client, actor, month).status_code == 200
            changed = client.patch(
                f"/api/v1/assets/{home['id']}",
                json={"household_share": "1", "name": "합성 현재 이름"},
                headers={**actor.headers, "If-Match": f'"{home["version"]}"'},
            )
            assert changed.status_code == 200
            result = api_compare(client, actor).json()
            assert (
                result["total_delta_krw"] == "100"
                and result["items"][0]["after"]["name"] == home["name"]
            )
            current = read_month(client, actor, "2026-02")
            opened = client.post(
                "/api/v1/asset-months/2026-02/reopen",
                json={"revision_id": current["revision_id"], "reason": "합성 비교 중 정정"},
                headers={
                    **actor.headers,
                    "If-Match": f'"{current["version"]}"',
                    "Idempotency-Key": uuid4().hex,
                },
            )
            assert opened.status_code == 201
            result = api_compare(client, actor).json()
            assert result["state"] == "unconfirmed" and result["total_delta_krw"] is None
            assert result["current"]["state"] == "reopened"
            trend = client.get(
                "/api/v1/asset-trends",
                params={"from": "2026-02", "to": "2026-02", "asset_id": home["id"]},
                headers=actor.headers,
            ).json()
            assert trend["points"][0]["observed_amount_krw"] == "600"
            assert trend["points"][0]["confirmed_amount_krw"] is None

    def test_request_validation_and_missing_month_are_explicit(self, comparison_app, actor):
        with TestClient(comparison_app) as client:
            response = api_compare(client, actor)
            assert response.status_code == 200 and response.json()["state"] == "current_missing"
            for params in (
                {"from": "2026-02", "to": "2026-02"},
                {"from": "0000-01"},
                {"limit": 201},
                {"kind": "invented"},
            ):
                assert api_compare(client, actor, **params).status_code == 422
            assert (
                client.get(
                    "/api/v1/asset-trends",
                    params={"from": "2000-01", "to": "2026-02"},
                    headers=actor.headers,
                ).status_code
                == 422
            )

    def test_historical_owner_filter_and_pagination_keep_global_filtered_totals(
        self, comparison_app, actor, db_engine
    ):
        partner = make_actor(db_engine, household_id=actor.household_id)
        with TestClient(comparison_app) as client:
            personal = add_asset(
                client,
                actor,
                name="합성 소유 이동",
                ownership_kind="individual",
                owner_member_id=str(actor.member_id),
            )
            joint = add_asset(client, actor, name="합성 공동 유지")
            draft(client, actor, "2026-01")
            for item in (personal, joint):
                observe(client, actor, "2026-01", item["id"], "100", "2026-01-31")
            assert confirm(client, actor, "2026-01").status_code == 200
            assert (
                client.patch(
                    f"/api/v1/assets/{personal['id']}",
                    json={"owner_member_id": str(partner.member_id)},
                    headers={**actor.headers, "If-Match": f'"{personal["version"]}"'},
                ).status_code
                == 200
            )
            draft(client, actor, "2026-02")
            for item in (personal, joint):
                observe(client, actor, "2026-02", item["id"], "120", "2026-02-28")
            assert confirm(client, actor, "2026-02").status_code == 200
            first = api_compare(client, actor, limit=1).json()
            second = api_compare(client, actor, limit=1, cursor=first["next_cursor"]).json()
            assert first["total_delta_krw"] == second["total_delta_krw"] == "40"
            assert first["item_count"] == second["item_count"] == 2
            assert first["items"][0]["asset_id"] != second["items"][0]["asset_id"]
            assert second["next_cursor"] is None
            filtered = api_compare(client, actor, owner_member_id=str(actor.member_id)).json()
            assert filtered["previous"]["totals"]["assets_krw"] == "100"
            assert filtered["current"]["totals"]["assets_krw"] == "0"
            assert filtered["scope_changed"] is True and filtered["total_delta_krw"] == "-100"
            item = filtered["items"][0]
            assert (
                item["membership"] == "removed"
                and item["scope_reason"] == "filter_membership_changed"
            )
            assert item["before"]["owner_member_id"] == str(actor.member_id)
            assert item["after"]["owner_member_id"] == str(partner.member_id)
            assert item["amount_delta_krw"] is None
            invalid = api_compare(
                client, actor, ownership_kind="joint", owner_member_id=str(actor.member_id)
            )
            assert invalid.status_code == 422

    def test_archived_asset_missing_next_month_is_scope_removal_not_zero_valuation(
        self, comparison_app, actor
    ):
        with TestClient(comparison_app) as client:
            closed = add_asset(client, actor, ended_on="2026-01-31")
            draft(client, actor, "2026-01")
            observe(client, actor, "2026-01", closed["id"], "100", "2026-01-31")
            assert confirm(client, actor, "2026-01").status_code == 200
            draft(client, actor, "2026-02")
            assert (
                confirm(client, actor, "2026-02", acknowledge_scope_change=True).status_code == 200
            )
            result = api_compare(client, actor).json()
            assert result["total_delta_krw"] == "-100" and result["common_scope_delta_krw"] == "0"
            item = result["items"][0]
            assert (
                item["membership"] == "removed"
                and item["scope_reason"] == "ended_before_current_period"
            )
            assert item["after"] is None and item["amount_delta_krw"] is None
            trend = client.get(
                "/api/v1/asset-trends",
                params={"from": "2026-01", "to": "2026-02", "asset_id": closed["id"]},
                headers=actor.headers,
            ).json()
            assert trend["points"][1]["value_state"] == "missing_item"
            assert trend["points"][1]["confirmed_amount_krw"] is None

    def test_excluded_missing_value_and_explicit_zero_have_distinct_detail_trend_points(
        self, comparison_app, actor
    ):
        with TestClient(comparison_app) as client:
            reference = add_asset(client, actor, inclusion_status="excluded")
            draft(client, actor, "2026-01")
            assert confirm(client, actor, "2026-01").status_code == 200
            draft(client, actor, "2026-02")
            observe(client, actor, "2026-02", reference["id"], "0", "2026-02-28")
            assert confirm(client, actor, "2026-02").status_code == 200
            result = api_compare(client, actor, asset_id=reference["id"]).json()
            assert result["total_delta_krw"] == "0"
            assert result["items"][0]["membership"] == "excluded"
            assert result["items"][0]["amount_delta_krw"] is None
            trend = client.get(
                "/api/v1/asset-trends",
                params={"from": "2026-01", "to": "2026-02", "asset_id": reference["id"]},
                headers=actor.headers,
            ).json()
            first, second = trend["points"]
            assert first["state"] == "confirmed" and first["value_state"] == "missing_value"
            assert first["confirmed_amount_krw"] is None
            assert second["confirmed_amount_krw"] == "0" and second["included_in_total"] is False


def test_items_list_assets_before_liabilities_by_name_across_pages():
    keys = [UUID(int=n) for n in (5, 4, 3, 2, 1)]
    current = snapshot(
        "2026-02",
        [
            row("100", asset_id=keys[0], name="나 예금"),
            row("100", asset_id=keys[1], kind="liability", name="가 대출"),
            row("100", asset_id=keys[2], name="가 예금"),
            row("100", asset_id=keys[3], name="나 예금"),
            row("100", asset_id=keys[4], kind="liability", name="다 대출"),
        ],
    )
    read = partial(compare_snapshots, None, current, "2026-01", "2026-02", ComparisonFilters())
    pages, cursor = [], None
    while True:
        result = read(cursor=cursor, limit=2)
        pages.append([item.asset_id for item in result.items])
        cursor = result.next_cursor
        if cursor is None:
            break
    assert pages == [[keys[2], keys[3]], [keys[0], keys[1]], [keys[4]]]
    with pytest.raises(DomainError) as error:
        read(cursor=uuid4(), limit=2)
    assert (error.value.code, error.value.status) == ("NOT_FOUND", 404)
