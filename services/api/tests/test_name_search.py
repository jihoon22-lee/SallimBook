"""Synthetic literal-name search, household scope and pages beyond the first fifty."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_accounts import account_payload, asset_payload, make_actor
from test_cards import payload as card_payload
from test_income import headers
from test_insurance_core import case_payload, policy_payload
from test_recurring import rule_payload

from sallimbook.accounts.router import router as accounts
from sallimbook.assets.router import router as assets
from sallimbook.cards.router import router as cards
from sallimbook.cashflow.recurring_router import router as recurring
from sallimbook.config import Settings
from sallimbook.core.http import install_http_contract
from sallimbook.homecare.router import router as homecare
from sallimbook.insurance.router import router as insurance

PATHS = (
    "assets",
    "accounts",
    "cards",
    "insurance/policies",
    "insurance/cases",
    "appliances",
    "consumables",
    "recurring-rules",
)


def application(engine=None):
    app = FastAPI()
    app.state.engine = engine
    app.state.settings = Settings(environment="test", _env_file=None)
    install_http_contract(app)
    for router in (accounts, assets, cards, recurring, homecare, insurance):
        app.include_router(router)
    return app


def test_name_query_contract_is_bounded_on_reviewed_name_queries_only():
    spec = application().openapi()
    name_paths = (*PATHS, "consumable-orders", "homecare/purchase-plan")
    for path in name_paths:
        query = next(
            p for p in spec["paths"][f"/api/v1/{path}"]["get"]["parameters"] if p["name"] == "q"
        )
        assert query["in"] == "query" and not query["required"]
        assert query["schema"]["anyOf"][0] == {"type": "string", "maxLength": 120}
    assert all(
        p["name"] != "q"
        for path, methods in spec["paths"].items()
        if path.removeprefix("/api/v1/") not in name_paths
        for operation in methods.values()
        for p in operation.get("parameters", [])
    )


def create(client, actor, path, name):
    payload = {
        "assets": lambda: asset_payload(name=name),
        "accounts": lambda: account_payload(asset=asset_payload(name=name), account_number=None),
        "cards": lambda: card_payload(actor, product_name=name, alias=None),
        "insurance/policies": lambda: policy_payload(product_name=name),
        "insurance/cases": lambda: case_payload(actor, title=name),
        "appliances": lambda: {"name": name},
        "consumables": lambda: {"name": name, "unit": "개", "low_stock_threshold": 0},
        "recurring-rules": lambda: rule_payload() | {"title": name},
    }[path]()
    result = client.post(f"/api/v1/{path}", headers=headers(actor), json=payload)
    assert result.status_code == 201, result.text
    return result.json()["id"]


@pytest.mark.database
@pytest.mark.parametrize("path", PATHS)
def test_search_finds_old_rows_escapes_wildcards_and_keeps_household_pages(db_engine, path):
    actor = make_actor(db_engine)
    foreign = make_actor(db_engine)
    with TestClient(application(db_engine), base_url="https://testserver") as client:
        needle = "합성 Aa %_\\ 이름"
        target = create(client, actor, path, needle)
        foreign_id = create(client, foreign, path, needle)
        for i in range(51):
            create(client, actor, path, f"합성 다른 항목 {i}")
        base = f"/api/v1/{path}"
        first = client.get(base, headers=actor.headers).json()
        assert len(first["items"]) == 50 and first["next_cursor"]
        assert target not in {row["id"] for row in first["items"]}
        for term in (needle, "  %_\\  ", "이름", "%", "_", "aa"):
            found = client.get(base, headers=actor.headers, params={"q": term})
            assert found.status_code == 200, found.text
            assert found.headers["cache-control"] == "no-store"
            assert [row["id"] for row in found.json()["items"]] == [target]
        other_state = {
            "assets": {"status": "archived"},
            "accounts": {"status": "closed"},
            "cards": {"status": "closed"},
            "insurance/policies": {"status": "ended"},
            "insurance/cases": {"treatment_state": "ended"},
            "appliances": {"status": "ended"},
            "consumables": {"status": "ended"},
        }.get(path)
        if other_state:
            filtered = client.get(base, headers=actor.headers, params={"q": needle, **other_state})
            assert filtered.status_code == 200 and not filtered.json()["items"]
        # A matching foreign cursor never becomes a position in this household.
        assert (
            client.get(
                base, headers=actor.headers, params={"q": needle, "cursor": foreign_id}
            ).status_code
            == 404
        )
        assert client.get(base, params={"q": needle}).status_code == 401
        ids = set()
        cursor = None
        while True:
            response = client.get(
                base,
                headers=actor.headers,
                params={"q": "다른 항목", "limit": 20, **({"cursor": cursor} if cursor else {})},
            )
            assert response.status_code == 200, response.text
            rows = response.json()
            current = {row["id"] for row in rows["items"]}
            assert not ids & current
            ids |= current
            cursor = rows["next_cursor"]
            if not cursor:
                break
        assert len(ids) == 51 and target not in ids and foreign_id not in ids
        assert client.get(base, headers=actor.headers, params={"q": "  "}).json() == first
        for invalid in ("가" * 121, "검색\x00어", "검색\n어"):
            assert client.get(base, headers=actor.headers, params={"q": invalid}).status_code == 422


@pytest.mark.database
def test_rule_search_includes_retained_names_once_and_excludes_revoked_names(
    db_engine, monkeypatch
):
    from datetime import UTC, datetime

    from sallimbook.cashflow import recurring_service

    monkeypatch.setattr(recurring_service, "utcnow", lambda: datetime(2026, 2, 1, tzinfo=UTC))
    actor = make_actor(db_engine)
    with TestClient(application(db_engine), base_url="https://testserver") as client:
        identifier = create(client, actor, "recurring-rules", "합성 공동규칙 이전")
        path = f"/api/v1/recurring-rules/{identifier}"
        pending = rule_payload() | {
            "title": "합성 공동규칙 취소예정",
            "effective_from": "2026-04-01",
            "reason": "합성 이름 변경",
        }
        assert (
            client.patch(path, headers=headers(actor, version=1), json=pending).status_code == 200
        )
        corrected = pending | {"title": "합성 공동규칙 새예정"}
        assert (
            client.patch(path, headers=headers(actor, version=2), json=corrected).status_code == 200
        )
        for term in ("공동규칙", "이전", "새예정"):
            found = client.get("/api/v1/recurring-rules", headers=actor.headers, params={"q": term})
            assert found.status_code == 200
            assert [row["id"] for row in found.json()["items"]] == [identifier]
        found = client.get(
            "/api/v1/recurring-rules", headers=actor.headers, params={"q": "취소예정"}
        )
        assert found.status_code == 200 and not found.json()["items"]
