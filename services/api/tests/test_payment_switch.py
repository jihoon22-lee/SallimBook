"""Synthetic method-only changes preserve recurrence and paid/manual snapshots."""

from datetime import date
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_accounts import make_actor
from test_income import close_account, headers, make_account
from test_recurring import generate, obligation_for, post_rule, rule_payload, settle

from sallimbook.cashflow import recurring_service
from sallimbook.cashflow.payment_switch_router import router
from sallimbook.cashflow.payment_switch_schemas import PaymentSwitchInput
from sallimbook.cashflow.recurring_models import RecurringRuleVersion
from sallimbook.cashflow.recurring_router import router as recurring_router
from sallimbook.config import Settings
from sallimbook.core.http import install_http_contract


def payload(**changes):
    return dict(
        source_kind="account",
        source_id=str(uuid4()),
        target_kind="card",
        target_id=str(uuid4()),
        effective_on="2026-02-01",
        **changes,
    )


def test_switch_contract_has_no_money_or_secret_write_fields():
    app = FastAPI()
    app.include_router(router)
    spec = app.openapi()
    assert {op["operationId"] for path in spec["paths"].values() for op in path.values()} == {
        "previewPaymentSwitch",
        "applyPaymentSwitch",
    }
    assert set(PaymentSwitchInput.model_fields) == {
        "source_kind",
        "source_id",
        "target_kind",
        "target_id",
        "effective_on",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"effective_on": "2026-02-30"},
        {"effective_on": "2026-01-01T00:00:00Z"},
        {"target_kind": "cash"},
        {"cvc": "123"},
        {"effective_on": 0},
    ],
)
def test_switch_input_rejects_invalid_values(change):
    with pytest.raises(ValidationError):
        PaymentSwitchInput.model_validate(payload() | change)


def test_switch_rejects_identical_source_and_target():
    value = payload()
    with pytest.raises(ValidationError):
        PaymentSwitchInput.model_validate(
            value | {"target_kind": value["source_kind"], "target_id": value["source_id"]}
        )


@pytest.fixture
def setup(db_engine, monkeypatch):
    monkeypatch.setattr(recurring_service, "today", lambda: date(2026, 2, 1))
    actor = make_actor(db_engine)
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(environment="test", _env_file=None)
    install_http_contract(app)
    app.include_router(router)
    app.include_router(recurring_router)
    source, target = make_account(db_engine, actor), make_account(db_engine, actor)
    body = payload() | dict(
        source_id=str(source.id), target_kind="account", target_id=str(target.id)
    )
    return app, actor, source, target, body


def preview(client, actor, body, **query):
    result = client.post(
        "/api/v1/payment-switch/preview", headers=actor.headers, json=body, params=query
    )
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    return result.json()


def apply(client, actor, body, row, *, key=None):
    return client.post(
        f"/api/v1/payment-switch/rules/{row['id']}",
        headers=headers(actor, key, row["version"]),
        json=body | {"preview_digest": row["preview_digest"], "reason": "합성 연결 정리"},
    )


@pytest.mark.database
class TestPaymentSwitch:
    def test_preserves_future_terms_paid_manual_and_past_snapshots(self, setup, db_engine):
        app, actor, source, target, body = setup
        with TestClient(app) as client:
            rule = post_rule(client, actor, account_id=str(source.id))
            changed = client.patch(
                f"/api/v1/recurring-rules/{rule['id']}",
                headers=headers(actor, version=1),
                json=rule_payload()
                | {
                    "account_id": str(source.id),
                    "effective_from": "2026-04-01",
                    "expected_amount_krw": "77000",
                    "reason": "합성 미래 요금",
                    "note": "합성 메모",
                    "frequency": "monthly",
                    "anchor_date": "2026-01-31",
                },
            )
            assert changed.status_code == 200, changed.text
            generate(client, actor, rule["id"], end="2026-06-30")
            january = obligation_for(client, actor, "2026-01")
            february = obligation_for(client, actor, "2026-02")
            april = obligation_for(client, actor, "2026-04")
            settle(client, actor, april, amount="100", account_id=str(source.id))
            april = obligation_for(client, actor, "2026-04")
            skipped = client.post(
                f"/api/v1/obligations/{february['id']}/skip",
                headers=headers(actor, version=february["version"]),
                json={"reason": "합성 예외"},
            )
            assert skipped.status_code == 200
            february = obligation_for(client, actor, "2026-02")
            row = preview(client, actor, body)["items"][0]
            assert len(row["periods"]) == 2
            assert row["preserved_past_count"] == 1
            assert row["preserved_paid_count"] == 1
            assert row["preserved_manual_count"] == 1
            assert row["update_occurrence_count"] == 3
            key = str(uuid4())
            result = apply(client, actor, body, row, key=key)
            assert result.status_code == 200, result.text
            assert apply(client, actor, body, row, key=key).json() == result.json()
            assert preview(client, actor, body)["items"] == []
            for month, original in [
                ("2026-01", january),
                ("2026-02", february),
                ("2026-04", april),
            ]:
                assert obligation_for(client, actor, month) == original
            assert obligation_for(client, actor, "2026-03")["account_id"] == str(target.id)
            may = obligation_for(client, actor, "2026-05")
            assert may["account_id"] == str(target.id) and may["expected_amount_krw"] == "77000"
            versions = client.get(
                f"/api/v1/recurring-rules/{rule['id']}", headers=actor.headers
            ).json()["versions"]
            assert [
                (v["effective_from"], v["effective_until"], v["expected_amount_krw"])
                for v in versions
            ] == [
                ("2026-01-01", "2026-02-01", "33000"),
                ("2026-02-01", "2026-04-01", "33000"),
                ("2026-04-01", None, "77000"),
            ]
            assert versions[-1]["note"] == "합성 메모"
        with Session(db_engine) as session:
            assert (
                len(
                    list(
                        session.scalars(
                            select(RecurringRuleVersion).where(
                                RecurringRuleVersion.rule_id == rule["id"],
                                RecurringRuleVersion.revoked_at.is_not(None),
                            )
                        )
                    )
                )
                == 1
            )

    def test_row_fingerprint_conflict_leaves_other_row_applicable(self, setup):
        app, actor, source, target, body = setup
        with TestClient(app) as client:
            first = post_rule(client, actor, account_id=str(source.id))
            second = post_rule(client, actor, account_id=str(source.id))
            generate(client, actor, first["id"])
            rows = {row["id"]: row for row in preview(client, actor, body)["items"]}
            occurrence = obligation_for(client, actor, "2026-02")
            settle(client, actor, occurrence, amount="1")
            conflict = apply(client, actor, body, rows[first["id"]])
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "PAYMENT_LINKS_CHANGED"
            assert apply(client, actor, body, rows[second["id"]]).status_code == 200
            refreshed = preview(client, actor, body)["items"]
            assert len(refreshed) == 1 and refreshed[0]["id"] == first["id"]
            assert apply(client, actor, body, refreshed[0]).status_code == 200

    def test_scopes_closed_target_dates_and_first_period(self, setup, db_engine):
        app, actor, source, target, body = setup
        outsider = make_actor(db_engine)
        foreign = make_account(db_engine, outsider)
        with TestClient(app) as client:
            post_rule(client, actor, account_id=str(source.id), effective_from="2026-02-01")
            value = preview(client, actor, body)["items"][0]
            assert value["blocked_reason"] == "INITIAL_PERIOD_START"
            assert apply(client, actor, body, value).status_code == 409
            for field in ["source_id", "target_id"]:
                assert (
                    client.post(
                        "/api/v1/payment-switch/preview",
                        headers=actor.headers,
                        json=body | {field: str(foreign.id)},
                    ).status_code
                    == 404
                )
            assert apply(client, outsider, body, value).status_code == 404
            assert (
                client.post(
                    "/api/v1/payment-switch/preview",
                    headers=actor.headers,
                    json=body | {"effective_on": "2026-01-31"},
                ).status_code
                == 409
            )
            close_account(db_engine, actor, target, "2026-02-02")
            assert (
                client.post(
                    "/api/v1/payment-switch/preview", headers=actor.headers, json=body
                ).status_code
                == 422
            )

    def test_pages_and_target_version_change_invalidate_preview(self, setup, db_engine):
        app, actor, source, target, body = setup
        with TestClient(app) as client:
            for _ in range(3):
                post_rule(client, actor, account_id=str(source.id))
            first = preview(client, actor, body, limit=2)
            last = preview(client, actor, body, limit=2, cursor=first["next_cursor"])
            assert (
                len(first["items"]) == 2 and len(last["items"]) == 1 and last["next_cursor"] is None
            )
            from sallimbook.assets.models import Asset

            with Session(db_engine) as session:
                asset = session.get(Asset, target.asset_id)
                asset.version += 1
                session.commit()
            assert apply(client, actor, body, first["items"][0]).status_code == 409

    def test_card_source_and_indirect_account_card_links_are_distinct(self, setup, db_engine):
        from sallimbook.cards import service as cards
        from sallimbook.cards.schemas import CardCreate

        app, actor, source, target, body = setup
        with Session(db_engine) as session:
            card = cards.create_card(
                session,
                actor.principal,
                CardCreate(
                    owner_member_id=actor.member_id,
                    issuer_name="합성",
                    product_name="합성 카드",
                    card_type="credit",
                    settlement_account_id=source.id,
                ),
            )
        with TestClient(app) as client:
            direct = post_rule(client, actor, account_id=str(source.id))
            indirect = post_rule(client, actor, card_id=str(card.id))
            assert [row["id"] for row in preview(client, actor, body)["items"]] == [direct["id"]]
            card_body = body | dict(source_kind="card", source_id=str(card.id))
            rows = preview(client, actor, card_body)["items"]
            assert [row["id"] for row in rows] == [indirect["id"]]
            assert apply(client, actor, card_body, rows[0]).status_code == 200
            rule = client.get(
                f"/api/v1/recurring-rules/{indirect['id']}", headers=actor.headers
            ).json()
            assert rule["versions"][-1]["account_id"] == str(target.id)
            assert rule["versions"][-1]["card_id"] is None
            assert rule["versions"][0]["card_id"] == str(card.id)

    def test_preserves_future_period_with_a_different_method(self, setup):
        app, actor, source, target, body = setup
        with TestClient(app) as client:
            rule = post_rule(client, actor, account_id=str(source.id))
            path = f"/api/v1/recurring-rules/{rule['id']}"
            changed = client.patch(
                path,
                headers=headers(actor, version=1),
                json=rule_payload()
                | {
                    "effective_from": "2026-03-01",
                    "reason": "합성 다른 계획",
                    "account_id": str(target.id),
                    "expected_amount_krw": "60000",
                    "frequency": "annual",
                },
            )
            assert changed.status_code == 200
            original = client.get(path, headers=actor.headers).json()["versions"][-1]
            row = preview(client, actor, body)["items"][0]
            assert len(row["periods"]) == 1
            assert apply(client, actor, body, row).status_code == 200
            assert client.get(path, headers=actor.headers).json()["versions"][-1] == original

    def test_couple_race_same_key_replays_changed_key_and_cross_scope_fail(self, setup, db_engine):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        app, actor, source, target, body = setup
        partner = make_actor(db_engine, actor.household_id)
        outsider = make_actor(db_engine)
        with TestClient(app) as client:
            post_rule(client, actor, account_id=str(source.id))
            row = preview(client, actor, body)["items"][0]
        barrier = Barrier(2)

        def write(who):
            with TestClient(app) as client:
                barrier.wait(timeout=5)
                return apply(client, who, body, row)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, [actor, partner]))
        assert sorted(result.status_code for result in results) == [200, 409]
        with TestClient(app) as client:
            post_rule(client, actor, account_id=str(source.id))
            new = preview(client, actor, body)["items"][0]
            key = str(uuid4())
            result = apply(client, actor, body, new, key=key)
            assert result.status_code == 200
            assert apply(client, actor, body, new, key=key).json() == result.json()
            assert (
                apply(
                    client, actor, body | {"effective_on": "2026-02-02"}, new, key=key
                ).status_code
                == 409
            )
            assert apply(client, outsider, body, new, key=key).status_code == 404
            foreign = post_rule(client, outsider)
            assert apply(client, actor, body, new | {"id": foreign["id"]}).status_code == 404
            assert (
                client.post(
                    "/api/v1/payment-switch/preview",
                    headers=actor.headers,
                    json=body,
                    params={"cursor": foreign["id"]},
                ).status_code
                == 404
            )
