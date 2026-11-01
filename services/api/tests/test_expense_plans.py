"""Synthetic plan lifecycle, arithmetic, authorization and legacy projections."""

import importlib.util
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_accounts import make_actor
from test_income import headers
from test_recurring import generate

from sallimbook.cashflow import recurring_service
from sallimbook.cashflow.recurring_router import router as legacy_router
from sallimbook.config import Settings
from sallimbook.core.http import install_http_contract

pytestmark = pytest.mark.database


@pytest.fixture
def env(db_engine, monkeypatch):
    monkeypatch.setattr(recurring_service, "utcnow", lambda: datetime(2026, 2, 1, 1, tzinfo=UTC))
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(environment="test", _env_file=None)
    install_http_contract(app)
    app.include_router(legacy_router)
    if importlib.util.find_spec("sallimbook.cashflow.expense_plan_router"):
        from sallimbook.cashflow.expense_plan_router import router

        app.include_router(router)
    actor = make_actor(db_engine)
    return TestClient(app), actor, db_engine


def payload(**kw):
    return (
        dict(
            title="합성 월 계획",
            category="합성 분류",
            expected_amount_krw="10000",
            amount_mode="fixed",
            economic_type="expense",
            frequency="monthly",
            effective_from="2026-02-01",
            tracking_mode="plan_only",
        )
        | kw
    )


def create(client, actor, **kw):
    result = client.post("/api/v1/expense-plans", headers=headers(actor), json=payload(**kw))
    assert result.status_code == 201, result.text
    return result.json()


def get(client, actor, rid):
    r = client.get("/api/v1/expense-plans/" + rid, headers=actor.headers)
    assert r.status_code == 200, r.text
    return r.json()


def summary(client, actor, day="2026-02-01"):
    r = client.get("/api/v1/expense-plan-summary", params={"as_of": day}, headers=actor.headers)
    assert r.status_code == 200, r.text
    return r.json()


def change(client, actor, rid, version, **kw):
    return client.patch(
        "/api/v1/expense-plans/" + rid,
        headers=headers(actor, version=version),
        json=payload() | {"reason": "합성 변경"} | kw,
    )


def test_plan_without_day_has_no_obligations(env):
    c, a, _ = env
    r = create(c, a)
    row = get(c, a, r["id"])
    assert row["versions"][0]["anchor_date"] is None
    assert row["versions"][0]["tracking_mode"] == "plan_only"
    assert generate(c, a, r["id"])["items"] == []
    assert c.get("/api/v1/recurring-rules", headers=a.headers).json()["items"] == []
    assert summary(c, a)["fixed_known_krw"] == "10000"
    assert summary(c, a)["combined_known_krw"] == "10000"
    assert (
        c.get("/api/v1/obligations/summary?month=2026-02", headers=a.headers).json()[
            "actual_amount_krw"
        ]
        == "0"
    )


def test_monthly_rounding_and_exclusions(env):
    c, a, _ = env
    import json
    from pathlib import Path

    fixture = json.loads(
        (
            Path(__file__).resolve().parents[3] / "packages/test-fixtures/expense-plans.json"
        ).read_text()
    )
    data = fixture["rows"]
    for d in data:
        r = c.post("/api/v1/expense-plans", headers=headers(a), json=payload() | d)
        assert r.status_code == 201, r.text
    s = summary(c, a)
    assert (s["fixed_known_krw"], s["budget_known_krw"], s["combined_known_krw"]) == (
        "20001",
        "7000",
        "27001",
    )
    assert s["excluded_known_krw"] == "9000" and s["included_unknown_count"] == 1
    assert s["plan_count"] == 6
    assert all(s[k] == v for k, v in fixture["expected"].items())


@pytest.mark.parametrize(
    "patch",
    [
        {"plan_kind": "budget", "tracking_mode": "scheduled", "anchor_date": "2026-02-05"},
        {"tracking_mode": "scheduled"},
        {"annual_month": 6},
        {"plan_kind": "budget", "frequency": "annual"},
        {"expected_amount_krw": 100},
    ],
)
def test_invalid_plan_terms(env, patch):
    c, a, _ = env
    assert (
        c.post("/api/v1/expense-plans", headers=headers(a), json=payload() | patch).status_code
        == 422
    )


def test_same_day_plan_change_end_and_conflict(env):
    c, a, _ = env
    r = create(c, a)
    updated = change(c, a, r["id"], r["version"], expected_amount_krw="24000")
    assert updated.status_code == 200, updated.text
    v = updated.json()["version"]
    assert change(c, a, r["id"], r["version"]).status_code == 409
    assert summary(c, a)["fixed_known_krw"] == "24000"
    row = get(c, a, r["id"])
    assert len(row["history"]) == 2 and row["history"][0]["revoked_at"] is not None
    end = c.post(
        "/api/v1/expense-plans/" + r["id"] + "/end",
        headers=headers(a, version=v),
        json={"effective_on": "2026-02-01", "reason": "합성 종료"},
    )
    assert end.status_code == 200, end.text
    assert summary(c, a)["plan_count"] == 0
    assert get(c, a, r["id"])["ended_on"] == "2026-02-01"


def test_scoped_plan_and_member_validation(env):
    c, a, engine = env
    other = make_actor(engine)
    r = create(c, a)
    assert c.get("/api/v1/expense-plans/" + r["id"], headers=other.headers).status_code == 404
    bad = c.post(
        "/api/v1/expense-plans",
        headers=headers(a),
        json=payload(subject_member_id=str(other.member_id)),
    )
    assert bad.status_code == 404, bad.text
    mate = make_actor(engine, a.household_id)
    assert c.get("/api/v1/expense-plans/" + r["id"], headers=mate.headers).status_code == 200


def test_legacy_projection_after_plan_to_scheduled(env):
    c, a, _ = env
    r = create(c, a)
    changed = change(
        c,
        a,
        r["id"],
        r["version"],
        tracking_mode="scheduled",
        anchor_date="2026-02-15",
        effective_from="2026-02-02",
    )
    assert changed.status_code == 200, changed.text
    legacy = c.get("/api/v1/recurring-rules/" + r["id"], headers=a.headers)
    assert legacy.status_code == 200, legacy.text
    assert all(
        v["anchor_date"] is not None and "tracking_mode" not in v for v in legacy.json()["versions"]
    )
    assert len(legacy.json()["versions"]) == 1
    bad = c.patch(
        "/api/v1/recurring-rules/" + r["id"],
        headers=headers(a, version=2),
        json=payload()
        | {"reason": "합성 구 앱", "anchor_date": "2026-02-15", "effective_from": "2026-02-03"},
    )
    # legacy request must not silently erase new metadata (unknown fields fail schema too).
    assert bad.status_code in (409, 422)
    generated = generate(c, a, r["id"], start="2026-02-01", end="2026-02-28")
    assert len(generated["items"]) == 1
    assert summary(c, a, "2026-02-02")["fixed_known_krw"] == "10000"


def test_same_day_method_switch_preserves_plan_terms_and_closure(env):
    from sqlalchemy.orm import Session
    from test_income import make_account

    from sallimbook.cashflow.payment_links import get_usage

    c, a, engine = env
    source, target = make_account(engine, a), make_account(engine, a)
    r = create(
        c,
        a,
        account_id=str(source.id),
        budget_treatment="external_support",
        subject_member_id=str(a.member_id),
        note="합성 메모",
    )
    body = dict(
        source_kind="account",
        source_id=str(source.id),
        target_kind="account",
        target_id=str(target.id),
        effective_on="2026-02-01",
    )
    preview = c.post("/api/v1/expense-plan-payment-switch/preview", headers=a.headers, json=body)
    assert preview.status_code == 200, preview.text
    view = preview.json()["items"][0]
    assert view["blocked_reason"] is None
    assert view["periods"][0]["anchor_date"] is None
    result = c.post(
        "/api/v1/expense-plan-payment-switch/" + r["id"],
        headers=headers(a, version=r["version"]),
        json=body | {"reason": "합성 수단 변경", "preview_digest": view["preview_digest"]},
    )
    assert result.status_code == 200, result.text
    version = get(c, a, r["id"])["versions"][0]
    assert version["account_id"] == str(target.id)
    assert version["budget_treatment"] == "external_support" and version["note"] == "합성 메모"
    assert version["expected_amount_krw"] == "10000" and version["subject_member_id"] == str(
        a.member_id
    )
    assert summary(c, a)["excluded_known_krw"] == "10000"
    # Existing payment usage contracts still omit nullable-date plans, but closure sees them.
    with Session(engine) as session:
        principal = a.principal
        usage = get_usage(session, principal, "account", target.id)
        assert usage.requires_confirmation and usage.rules.total_count == 0


def test_plan_boundary_days_and_delete_replay(env):
    from uuid import uuid4

    c, a, _ = env
    r = create(c, a)
    key = str(uuid4())
    edit = payload() | dict(
        reason="합성 다음 기간", effective_from="2026-03-01", expected_amount_krw="27000"
    )
    for _ in range(2):
        resp = c.patch(
            "/api/v1/expense-plans/" + r["id"], headers=headers(a, key=key, version=1), json=edit
        )
        assert resp.status_code == 200, resp.text
    assert summary(c, a, "2026-02-28")["fixed_known_krw"] == "10000"
    assert summary(c, a, "2026-03-01")["fixed_known_krw"] == "27000"
    create(c, a, frequency="days", interval_count=7)
    assert summary(c, a)["unconverted_count"] == 1
    assert c.get("/api/v1/recurring-rules/" + r["id"], headers=a.headers).status_code == 409
    key = str(uuid4())
    for _ in range(2):
        assert (
            c.delete(
                "/api/v1/expense-plans/" + r["id"], headers=headers(a, key=key, version=2)
            ).status_code
            == 204
        )
    assert summary(c, a)["plan_count"] == 1


def test_scheduled_to_plan_preserves_paid_and_manual_occurrences(env):
    from test_recurring import obligation_for, post_rule, settle

    c, a, _ = env
    r = post_rule(c, a)
    generate(c, a, r["id"], end="2026-05-31")
    march = obligation_for(c, a, "2026-03")
    settle(c, a, march, amount="100")
    april = obligation_for(c, a, "2026-04")
    skip = c.post(
        "/api/v1/obligations/" + april["id"] + "/skip",
        headers=headers(a, version=april["version"]),
        json={"reason": "합성 예외"},
    )
    assert skip.status_code == 200
    response = change(c, a, r["id"], r["version"], effective_from="2026-02-01")
    assert response.status_code == 200, response.text
    assert obligation_for(c, a, "2026-01")["schedule_state"] == "active"
    assert obligation_for(c, a, "2026-02")["schedule_state"] == "superseded"
    assert obligation_for(c, a, "2026-03")["actual_amount_krw"] == "100"
    assert obligation_for(c, a, "2026-04")["skipped"]
    assert obligation_for(c, a, "2026-05")["schedule_state"] == "superseded"


def test_new_plan_downgrade_refused_without_data_loss(env):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    c, a, engine = env
    r = create(c, a)
    with engine.connect() as connection:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="destructive downgrade refused"):
            command.downgrade(config, "0025_card_stored_details")
        connection.rollback()
    assert get(c, a, r["id"])["versions"][0]["tracking_mode"] == "plan_only"


def test_legacy_scheduled_edit_preserves_new_metadata(env):
    c, a, _ = env
    r = create(
        c,
        a,
        tracking_mode="scheduled",
        anchor_date="2026-02-15",
        effective_from="2026-01-01",
        budget_treatment="external_support",
        subject_member_id=str(a.member_id),
    )
    body = payload() | dict(
        reason="합성 구 버전 편집", anchor_date="2026-02-15", effective_from="2026-02-01"
    )
    del body["tracking_mode"]
    updated = c.patch(
        "/api/v1/recurring-rules/" + r["id"], headers=headers(a, version=1), json=body
    )
    assert updated.status_code == 200, updated.text
    v = get(c, a, r["id"])["versions"][-1]
    assert v["budget_treatment"] == "external_support" and v["subject_member_id"] == str(
        a.member_id
    )


@pytest.mark.parametrize("frequency,anchor", [("annual", "2026-07-15"), ("monthly", "2026-06-15")])
def test_legacy_edit_rejects_conflict_with_preserved_annual_metadata(env, frequency, anchor):
    c, a, _ = env
    r = create(
        c,
        a,
        tracking_mode="scheduled",
        frequency="annual",
        annual_month=6,
        anchor_date="2026-06-15",
        effective_from="2026-01-01",
    )
    body = payload(frequency=frequency, anchor_date=anchor, reason="합성 구 일정 변경")
    del body["tracking_mode"]
    response = c.patch(
        "/api/v1/recurring-rules/" + r["id"], headers=headers(a, version=1), json=body
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAN_CLIENT_REQUIRED"
    assert get(c, a, r["id"])["version"] == 1
    assert c.get("/api/v1/expense-plans", headers=a.headers).status_code == 200
