"""Household status from registered records: latest saved amounts, a plan-based margin."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_accounts import asset_payload, create_account, make_actor
from test_asset_months import add_asset, draft, observe
from test_income import headers
from test_insurance_core import case_payload, policy_payload

from sallimbook.accounts.router import router as account_router
from sallimbook.assets.month_router import router as month_router
from sallimbook.assets.router import router as asset_router
from sallimbook.cards.router import router as card_router
from sallimbook.cashflow import recurring_service
from sallimbook.cashflow.expense_plan_router import router as plan_router
from sallimbook.cashflow.planning_router import router as planning_router
from sallimbook.config import Settings
from sallimbook.core.http import install_http_contract
from sallimbook.homecare.router import router as homecare_router
from sallimbook.identity.router import router as identity_router
from sallimbook.insurance.event_router import router as insurance_event_router
from sallimbook.insurance.router import router as insurance_router
from sallimbook.overview.router import router as overview_router

pytestmark = pytest.mark.database
FIXTURE = json.loads(
    (
        Path(__file__).resolve().parents[3] / "packages/test-fixtures/household-overview.json"
    ).read_text(encoding="utf-8")
)
MONTH = FIXTURE["month"]


@pytest.fixture
def env(db_engine, monkeypatch):
    monkeypatch.setattr(recurring_service, "utcnow", lambda: datetime(2026, 3, 15, 1, tzinfo=UTC))
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(environment="test", _env_file=None)
    install_http_contract(app)
    for router in (
        identity_router,
        asset_router,
        account_router,
        month_router,
        plan_router,
        planning_router,
        card_router,
        homecare_router,
        insurance_router,
        insurance_event_router,
        overview_router,
    ):
        app.include_router(router)
    actor = make_actor(db_engine)
    return app, actor, make_actor(db_engine)


def overview(client, actor, month=MONTH):
    response = client.get(
        "/api/v1/household-overview", params={"month": month}, headers=actor.headers
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def register_assets(client, actor):
    ids = {}
    for item in FIXTURE["assets"]:
        fields = {
            key: item[key]
            for key in ("name", "kind", "category", "inclusion_status", "ended_on")
            if key in item
        }
        if item.get("account"):
            ids[item["key"]] = create_account(
                client, actor, asset=asset_payload(**fields), account_number=None
            )["asset"]["id"]
        else:
            ids[item["key"]] = add_asset(client, actor, **fields)["id"]
    months = sorted({month for item in FIXTURE["assets"] for month in item["values"]})
    for month in months:
        draft(client, actor, month, copy=False)
        for item in FIXTURE["assets"]:
            if month in item["values"]:
                end = f"{month}-28"
                observe(client, actor, month, ids[item["key"]], item["values"][month], end)
    return ids


def test_latest_saved_amounts_show_the_household_without_a_month_record(env):
    app, actor, _ = env
    expected = FIXTURE["expected_holdings"]
    with TestClient(app) as client:
        ids = register_assets(client, actor)
        # The selected month has no record of its own: the status still shows every item.
        later = overview(client, actor, "2026-04")["holdings"]
        result = overview(client, actor)
    holdings = result["holdings"]
    for field in (
        "assets_krw",
        "liabilities_krw",
        "net_assets_krw",
        "item_count",
        "known_count",
        "missing_count",
        "stale_count",
        "current_count",
        "oldest_basis_month",
        "groups",
    ):
        assert holdings[field] == expected[field], field
    by_id = {row["asset_id"]: row for row in holdings["items"]}
    assert ids["ended"] not in by_id
    for key, basis in expected["basis"].items():
        assert by_id[ids[key]]["basis_month"] == basis, key
    assert {key for key in ids if ids[key] in by_id and by_id[ids[key]]["stale"]} == set(
        expected["stale"]
    )
    assert by_id[ids["unsaved"]]["owned_amount_krw"] is None
    assert by_id[ids["excluded"]]["included"] is False
    assert by_id[ids["checking"]]["account_id"] and by_id[ids["checking"]]["group"] == "accounts"
    # Groups never add an account's asset twice.
    assert sum(int(g["assets_krw"]) for g in holdings["groups"]) == int(holdings["assets_krw"])
    assert later["net_assets_krw"] == holdings["net_assets_krw"] and later["current_count"] == 0
    # A month before anything was saved has the items but no amounts yet.
    early = None
    with TestClient(app) as client:
        early = overview(client, actor, "2025-05")["holdings"]
    assert early["known_count"] == 0 and early["net_assets_krw"] == "0"
    assert early["missing_count"] == early["item_count"] > 0


def test_plan_margin_keeps_loans_and_savings_apart_from_spending(env):
    app, actor, _ = env
    with TestClient(app) as client:
        for plan in FIXTURE["plans"]:
            body = {
                "title": plan["title"],
                "category": plan["category"],
                "expected_amount_krw": plan["expected_amount_krw"],
                "amount_mode": plan.get("amount_mode", "fixed"),
                "economic_type": plan.get("economic_type", "expense"),
                "frequency": "monthly",
                "effective_from": "2026-03-01",
                "tracking_mode": "plan_only",
                "plan_kind": plan.get("plan_kind", "recurring"),
                "budget_treatment": plan.get("budget_treatment", "included"),
            }
            response = client.post("/api/v1/expense-plans", headers=headers(actor), json=body)
            assert response.status_code == 201, response.text
        for income in FIXTURE["expected_income"]:
            response = client.post(
                "/api/v1/income-planning/expected",
                headers=headers(actor),
                json={"member_id": str(actor.member_id), **income},
            )
            assert response.status_code == 201, response.text
        plan = overview(client, actor)["plan"]
    assert plan["as_of"] == "2026-03-15"
    assert {key: plan[key] for key in FIXTURE["expected_plan"]} == FIXTURE["expected_plan"]


def test_registered_items_and_insurance_status_stay_in_the_household(env):
    app, actor, foreign = env
    with TestClient(app) as client:
        for changes in ({}, {"alias": None, "product_name": "합성 두 번째 카드"}):
            response = client.post(
                "/api/v1/cards",
                headers=actor.headers,
                json={
                    "owner_member_id": str(actor.member_id),
                    "issuer_name": "합성 카드사",
                    "product_name": "합성 카드",
                    "alias": "생활비",
                    "card_type": "credit",
                    "started_on": "2025-01-01",
                    **changes,
                },
            )
            assert response.status_code == 201, response.text
        closed = client.post(
            "/api/v1/cards",
            headers=actor.headers,
            json={
                "owner_member_id": str(actor.member_id),
                "issuer_name": "합성 카드사",
                "product_name": "합성 해지 카드",
                "card_type": "debit",
                "started_on": "2025-01-01",
                "ended_on": "2025-12-31",
            },
        )
        assert closed.status_code == 201, closed.text
        for name in ("합성 냉장고", "합성 정수기"):
            response = client.post("/api/v1/appliances", headers=actor.headers, json={"name": name})
            assert response.status_code == 201, response.text
        policies = []
        for status in ("active", "ended"):
            response = client.post(
                "/api/v1/insurance/policies",
                headers=actor.headers,
                json=policy_payload(status=status),
            )
            assert response.status_code == 201, response.text
            policies.append(response.json())
        case = client.post(
            "/api/v1/insurance/cases", headers=actor.headers, json=case_payload(actor)
        ).json()
        for state in ("draft", "documents_required", "decided"):
            response = client.post(
                "/api/v1/insurance/claims",
                headers=actor.headers,
                json={
                    "case_id": case["id"],
                    "policy_id": policies[0]["id"],
                    "expense_ids": [],
                    "claim_state": state,
                },
            )
            assert response.status_code == 201, response.text
        # Another household's records never appear in this status.
        client.post("/api/v1/appliances", headers=foreign.headers, json={"name": "합성 남의 기기"})
        client.post("/api/v1/insurance/policies", headers=foreign.headers, json=policy_payload())
        mine = overview(client, actor)
        theirs = overview(client, foreign)
        assert client.get("/api/v1/household-overview", params={"month": MONTH}).status_code == 401
        assert (
            client.get(
                "/api/v1/household-overview", params={"month": "2026-13"}, headers=actor.headers
            ).status_code
            == 422
        )
    assert mine["cards"]["count"] == 2
    assert [row["name"] for row in mine["cards"]["items"]] == ["생활비", "합성 두 번째 카드"]
    assert mine["appliances"]["count"] == 2
    assert [row["name"] for row in mine["appliances"]["items"]] == ["합성 냉장고", "합성 정수기"]
    insurance = mine["insurance"]
    assert insurance["active_policy_count"] == 1
    assert insurance["policies"] == [
        {"id": policies[0]["id"], "name": "합성 보험사 · 합성 보험상품"}
    ]
    assert insurance["open_case_count"] == 1
    assert insurance["claims_in_progress_count"] == 2
    assert insurance["documents_required_count"] == 1
    assert theirs["appliances"]["count"] == 1 and theirs["insurance"]["open_case_count"] == 0
    assert theirs["cards"]["count"] == 0 and theirs["holdings"]["item_count"] == 0
