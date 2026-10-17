"""Synthetic API, household, concurrency and immutable-inventory integration tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_accounts import make_actor
from test_homecare import vector
from test_income import headers

from sallimbook.assets.models import Asset
from sallimbook.cashflow.models import CashRecord
from sallimbook.config import Settings
from sallimbook.core.http import install_http_contract
from sallimbook.core.idempotency import IdempotencyRecord
from sallimbook.homecare import service
from sallimbook.homecare.models import (
    Appliance,
    Consumable,
    ConsumableReplacement,
    StockMovement,
)
from sallimbook.homecare.router import router

pytestmark = pytest.mark.database
TODAY = "2026-10-17"


@pytest.fixture
def actors(db_engine):
    first = make_actor(db_engine)
    return first, make_actor(db_engine, first.household_id), make_actor(db_engine)


@pytest.fixture
def homecare_app(db_engine, monkeypatch):
    monkeypatch.setattr(service, "utcnow", lambda: datetime(2026, 10, 16, 15, 30, tzinfo=UTC))
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(environment="test", _env_file=None)
    install_http_contract(app)
    app.include_router(router)
    return app


def post_appliance(client, actor, **overrides):
    response = client.post(
        "/api/v1/appliances",
        headers=actor.headers,
        json={"name": "합성 공기청정기", "purchased_on": "2025-01-01"} | overrides,
    )
    assert response.status_code == 201, response.text
    assert response.headers["etag"] == '"1"'
    return response.json()


def post_consumable(client, actor, **overrides):
    response = client.post(
        "/api/v1/consumables",
        headers=actor.headers,
        json={"name": "합성 공용 필터", "unit": "개", "low_stock_threshold": 1} | overrides,
    )
    assert response.status_code == 201, response.text
    return response.json()


def post_link(client, actor, appliance, stock, **overrides):
    response = client.post(
        "/api/v1/appliance-consumables",
        headers=actor.headers,
        json={
            "appliance_id": appliance["id"],
            "consumable_id": stock["id"],
            "interval_unit": "months",
            "interval_count": 1,
        }
        | overrides,
    )
    assert response.status_code == 201, response.text
    return response.json()


def stock_at(client, actor, stock_id):
    response = client.get(f"/api/v1/consumables/{stock_id}", headers=actor.headers)
    assert response.status_code == 200, response.text
    return response.json()


def link_at(client, actor, link_id):
    response = client.get(f"/api/v1/appliance-consumables/{link_id}", headers=actor.headers)
    assert response.status_code == 200, response.text
    return response.json()


def receipt(client, actor, stock, quantity=3, **overrides):
    current = stock_at(client, actor, stock["id"])
    response = client.post(
        f"/api/v1/consumables/{stock['id']}/stock-movements",
        headers=headers(actor, version=current["version"]),
        json={"kind": "receipt", "quantity_delta": quantity, "occurred_on": "2025-01-01"}
        | overrides,
    )
    assert response.status_code == 201, response.text
    return response.json()


def replace(client, actor, link, *, replaced_on="2025-03-02", key=None, **overrides):
    current = link_at(client, actor, link["id"])
    response = client.post(
        f"/api/v1/appliance-consumables/{link['id']}/replacements",
        headers=headers(actor, key, current["stock_version"]),
        json={
            "replaced_on": replaced_on,
            "quantity": 1,
            "link_version": current["version"],
            "clear_next_check_override": False,
        }
        | overrides,
    )
    assert response.status_code == 201, response.text
    return response.json()


def cancel_replacement(client, actor, link, replacement, *, key=None):
    current = stock_at(client, actor, replacement["consumable_id"])
    response = client.post(
        f"/api/v1/appliance-consumables/{link['id']}/replacements/{replacement['replacement_id']}/cancel",
        headers=headers(actor, key, current["version"]),
        json={"occurred_on": TODAY, "reason": "합성 교체 취소"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_appliance_purchase_warranty_end_and_price_do_not_create_assets(
    homecare_app, actors, db_engine
):
    actor = actors[0]
    with TestClient(homecare_app) as client:
        appliance = post_appliance(
            client,
            actor,
            purchase_price_krw="99999999999999999999",
            warranty_until=TODAY,
            manufacturer="합성 제조사",
            model="합성 모델",
            location="합성 방",
            seller="합성 판매처",
        )
        assert appliance["purchase_price_krw"] == "99999999999999999999"
        assert appliance["warranty_status"] == "active" and appliance["as_of"] == TODAY
        path = f"/api/v1/appliances/{appliance['id']}"
        changed = client.patch(
            path,
            headers=headers(actor, version=1),
            json={
                "purchase_price_krw": "0",
                "warranty_until": "2026-10-16",
                "note": "합성 수리 메모",
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["purchase_price_krw"] == "0"
        assert changed.json()["warranty_status"] == "expired"
        assert (
            client.patch(
                path, headers=headers(actor, version=1), json={"name": "합성 충돌"}
            ).status_code
            == 409
        )
        ended = client.patch(path, headers=headers(actor, version=2), json={"ended_on": TODAY})
        assert ended.status_code == 200 and ended.json()["status"] == "ended"
        assert client.get("/api/v1/appliances", headers=actor.headers).json()["items"] == []
        assert (
            client.get("/api/v1/appliances?status=ended", headers=actor.headers).json()["items"][0][
                "id"
            ]
            == appliance["id"]
        )
        assert client.delete(path, headers=actor.headers).status_code == 400
        assert client.get(path, headers=actor.headers).json()["note"] == "합성 수리 메모"
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(Asset)) == 0
        assert session.scalar(select(func.count()).select_from(CashRecord)) == 0
        assert session.scalar(select(func.count()).select_from(Appliance)) == 1


def test_shared_sku_nullable_specs_unique_pair_and_independent_device_intervals(
    homecare_app, actors
):
    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor, sku_or_model="SYNTHETIC-F1")
        for _ in range(2):
            assert post_consumable(client, actor)["sku_or_model"] is None
        duplicate = client.post(
            "/api/v1/consumables",
            headers=actor.headers,
            json={"name": "합성 중복", "unit": "개", "sku_or_model": " SYNTHETIC-F1 "},
        )
        assert (
            duplicate.status_code == 409
            and duplicate.json()["error"]["code"] == "CONSUMABLE_SKU_EXISTS"
        )
        first = post_link(
            client,
            actor,
            post_appliance(client, actor),
            stock,
            interval_unit="days",
            interval_count=30,
        )
        second = post_link(
            client,
            actor,
            post_appliance(client, actor),
            stock,
            interval_unit="months",
            interval_count=3,
        )
        assert (
            first["consumable_id"] == second["consumable_id"]
            and first["interval_count"] != second["interval_count"]
        )
        duplicate = client.post(
            "/api/v1/appliance-consumables",
            headers=actor.headers,
            json={"appliance_id": first["appliance_id"], "consumable_id": stock["id"]},
        )
        assert (
            duplicate.status_code == 409
            and duplicate.json()["error"]["code"] == "APPLIANCE_CONSUMABLE_EXISTS"
        )
        receipt(client, actor, stock, quantity=2)
        replace(client, actor, first)
        assert link_at(client, actor, first["id"])["last_replaced_on"] == "2025-03-02"
        other = link_at(client, actor, second["id"])
        assert other["stock_quantity"] == 1 and other["last_replaced_on"] is None
        assert other["next_check_on"] is None and other["replacement_due"] is None


def test_t20_receipt_preserves_known_replacement_then_replacement_reduces_stock(
    homecare_app, actors, db_engine
):
    actor = actors[0]
    case = vector("T-20")
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        link = post_link(client, actor, post_appliance(client, actor), stock)
        receipt(client, actor, stock, quantity=1)
        replace(client, actor, link, replaced_on=case["inputs"]["last_replaced_on"])
        assert stock_at(client, actor, stock["id"])["stock_quantity"] == 0
        receipt(client, actor, stock, quantity=3, occurred_on="2025-03-01")
        after_receipt = link_at(client, actor, link["id"])
        assert after_receipt["stock_quantity"] == case["expected"]["stock_after_receipt"]
        assert after_receipt["last_replaced_on"] == case["expected"]["last_replaced_after_receipt"]
        replace(client, actor, link, replaced_on="2025-03-02")
        final = link_at(client, actor, link["id"])
        assert final["stock_quantity"] == case["expected"]["final_stock"]
        assert final["last_replaced_on"] == case["expected"]["last_replaced_after_replacement"]
        assert final["next_check_on"] == "2025-04-02"
    with Session(db_engine) as session:
        assert (
            session.scalar(select(func.sum(StockMovement.quantity_delta)))
            == final["stock_quantity"]
        )
        assert session.scalar(select(func.count()).select_from(ConsumableReplacement)) == 2
        assert session.scalar(select(func.count()).select_from(CashRecord)) == 0


def test_t21_concurrent_devices_share_last_unit_under_row_lock(homecare_app, actors, db_engine):
    actor, partner, _ = actors
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        links = [post_link(client, actor, post_appliance(client, actor), stock) for _ in range(2)]
        receipt(client, actor, stock, quantity=1)
        stock_version = stock_at(client, actor, stock["id"])["version"]
    barrier = Barrier(2)

    def consume(index):
        with TestClient(homecare_app) as client:
            barrier.wait()
            return client.post(
                f"/api/v1/appliance-consumables/{links[index]['id']}/replacements",
                headers=headers(
                    (actor, partner)[index], f"synthetic-concurrent-{index}", stock_version
                ),
                json={
                    "replaced_on": TODAY,
                    "quantity": 1,
                    "link_version": 1,
                    "clear_next_check_override": False,
                },
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(consume, (0, 1)))
    expected = vector("T-21")["expected"]
    assert sum(r.status_code == 201 for r in results) == expected["success_count"]
    assert (
        sum(
            r.status_code == 409 and r.json()["error"]["code"] == "INSUFFICIENT_STOCK"
            for r in results
        )
        == expected["insufficient_stock_count"]
    )
    with Session(db_engine) as session:
        assert session.get(Consumable, UUID(stock["id"])).stock_quantity == expected["final_stock"]
        assert (
            session.scalar(select(func.count()).select_from(ConsumableReplacement))
            == expected["replacement_count"]
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(StockMovement)
                .where(StockMovement.kind == "replacement")
            )
            == expected["stock_movement_count"]
        )


def test_t22_replay_returns_original_stock_version_after_later_changes(
    homecare_app, actors, db_engine
):
    actor = actors[0]
    case = vector("T-22")["inputs"]["replacement"]
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        link = post_link(client, actor, post_appliance(client, actor), stock)
        received = receipt(client, actor, stock, quantity=case["initial_stock"])
        path = f"/api/v1/appliance-consumables/{link['id']}/replacements"
        h = headers(actor, case["idempotency_key"], received["stock_version"])
        body = {
            "replaced_on": TODAY,
            "quantity": case["quantity"],
            "link_version": 1,
            "clear_next_check_override": False,
        }
        first = client.post(path, headers=h, json=body)
        assert first.status_code == 201, first.text
        receipt(client, actor, stock, quantity=2)
        for _ in range(case["attempts"]):
            replay = client.post(path, headers=h, json=body)
            assert replay.status_code == 201 and replay.json() == first.json()
            assert replay.headers["etag"] == first.headers["etag"]
        assert (
            client.post(path, headers=h, json=body | {"quantity": 2}).json()["error"]["code"]
            == "IDEMPOTENCY_CONFLICT"
        )
        assert stock_at(client, actor, stock["id"])["stock_quantity"] == 4
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(ConsumableReplacement)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.operation == "homecare.replacement.create")
            )
            == 1
        )


def test_cancelling_older_and_latest_replacements_recomputes_surviving_schedule(
    homecare_app, actors, db_engine
):
    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        link = post_link(client, actor, post_appliance(client, actor), stock)
        receipt(client, actor, stock, quantity=5)
        first = replace(client, actor, link, replaced_on="2025-02-01")
        latest = replace(client, actor, link, replaced_on="2025-03-31")
        older = replace(client, actor, link, replaced_on="2025-01-31")
        assert link_at(client, actor, link["id"])["last_replacement_id"] == latest["replacement_id"]
        cancel_replacement(client, actor, link, first)
        unchanged = link_at(client, actor, link["id"])
        assert (
            unchanged["last_replaced_on"] == "2025-03-31"
            and unchanged["next_check_on"] == "2025-04-30"
        )
        cancel_replacement(client, actor, link, latest)
        restored = link_at(client, actor, link["id"])
        assert restored["last_replacement_id"] == older["replacement_id"]
        assert (
            restored["last_replaced_on"] == "2025-01-31"
            and restored["next_check_on"] == "2025-02-28"
        )
        cancel_replacement(client, actor, link, older)
        empty = link_at(client, actor, link["id"])
        assert empty["stock_quantity"] == 5
        assert empty["last_replaced_on"] is None and empty["next_check_on"] is None
        assert empty["next_check_source"] == "unknown" and empty["replacement_due"] is None
        history = client.get(
            f"/api/v1/appliance-consumables/{link['id']}/replacements", headers=actor.headers
        ).json()["items"]
        assert len(history) == 3 and all(row["cancelled_by_movement_id"] for row in history)
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(ConsumableReplacement)) == 3
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 7
        assert session.scalar(select(func.sum(StockMovement.quantity_delta))) == 5


def test_same_day_replacements_have_stable_id_tie_and_cancel_does_not_lose_other(
    homecare_app, actors
):
    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        link = post_link(client, actor, post_appliance(client, actor), stock)
        receipt(client, actor, stock, quantity=2)
        records = [replace(client, actor, link, replaced_on=TODAY) for _ in range(2)]
        records.sort(key=lambda row: row["replacement_id"])
        assert (
            link_at(client, actor, link["id"])["last_replacement_id"]
            == records[-1]["replacement_id"]
        )
        cancel_replacement(client, actor, link, records[-1])
        assert (
            link_at(client, actor, link["id"])["last_replacement_id"]
            == records[0]["replacement_id"]
        )
        assert link_at(client, actor, link["id"])["last_replaced_on"] == TODAY


def test_override_keep_or_explicit_clear_is_not_rolled_back_by_cancellation(homecare_app, actors):
    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        link = post_link(
            client, actor, post_appliance(client, actor), stock, next_check_override="2025-01-01"
        )
        receipt(client, actor, stock)
        kept = replace(
            client, actor, link, replaced_on="2026-09-01", clear_next_check_override=False
        )
        after_keep = link_at(client, actor, link["id"])
        assert (
            after_keep["next_check_on"] == "2025-01-01"
            and after_keep["next_check_source"] == "override"
        )
        assert after_keep["version"] == 1
        cleared = replace(
            client, actor, link, replaced_on="2026-10-01", clear_next_check_override=True
        )
        after_clear = link_at(client, actor, link["id"])
        assert after_clear["next_check_override"] is None and after_clear["version"] == 2
        assert after_clear["next_check_on"] == "2026-11-01"
        cancel_replacement(client, actor, link, cleared)
        current = link_at(client, actor, link["id"])
        assert current["next_check_override"] is None and current["version"] == 2
        assert current["last_replacement_id"] == kept["replacement_id"]
        assert (
            current["next_check_on"] == "2026-10-01"
            and current["next_check_source"] == "replacement"
        )
        changed = client.patch(
            f"/api/v1/appliance-consumables/{link['id']}",
            headers=headers(actor, version=2),
            json={"next_check_override": "2027-01-01"},
        )
        assert changed.status_code == 200
        cancel_replacement(client, actor, link, kept)
        assert link_at(client, actor, link["id"])["next_check_on"] == "2027-01-01"


def test_cancel_receipt_needs_available_quantity_and_reversal_is_full_once(
    homecare_app, actors, db_engine
):
    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        link = post_link(client, actor, post_appliance(client, actor), stock)
        original = receipt(client, actor, stock, quantity=3)
        replacement = replace(client, actor, link, quantity=2)
        path = f"/api/v1/consumables/{stock['id']}/stock-movements/{original['id']}/cancel"
        body = {"occurred_on": TODAY, "reason": "합성 입고 취소"}
        rejected = client.post(path, headers=headers(actor, version=3), json=body)
        assert (
            rejected.status_code == 409 and rejected.json()["error"]["code"] == "INSUFFICIENT_STOCK"
        )
        assert stock_at(client, actor, stock["id"])["stock_quantity"] == 1
        receipt(client, actor, stock, quantity=2, kind="return_in")
        h = headers(actor, "synthetic-receipt-cancel", 4)
        cancelled = client.post(path, headers=h, json=body)
        assert cancelled.status_code == 200, cancelled.text
        assert stock_at(client, actor, stock["id"])["stock_quantity"] == 0
        assert client.post(path, headers=h, json=body).json() == cancelled.json()
        again = client.post(path, headers=headers(actor, version=5), json=body)
        assert (
            again.status_code == 409
            and again.json()["error"]["code"] == "STOCK_MOVEMENT_ALREADY_REVERSED"
        )
        reverse_path = (
            f"/api/v1/consumables/{stock['id']}/stock-movements/{cancelled.json()['id']}/cancel"
        )
        assert (
            client.post(reverse_path, headers=headers(actor, version=5), json=body).json()["error"][
                "code"
            ]
            == "INVALID_STOCK_REVERSAL"
        )
        source = client.get(
            f"/api/v1/consumables/{stock['id']}/stock-movements/{original['id']}",
            headers=actor.headers,
        ).json()
        assert source["quantity_delta"] == 3 and source["reversed_by"] == cancelled.json()["id"]
        reversal = client.get(cancelled.headers["location"], headers=actor.headers).json()
        assert reversal["quantity_delta"] == -3 and reversal["reversal_of"] == original["id"]
        wrong_route = (
            f"/api/v1/consumables/{stock['id']}/stock-movements/{replacement['id']}/cancel"
        )
        assert (
            client.post(wrong_route, headers=headers(actor, version=5), json=body).json()["error"][
                "code"
            ]
            == "REPLACEMENT_CANCEL_REQUIRED"
        )
    with Session(db_engine) as session:
        assert session.scalar(select(func.sum(StockMovement.quantity_delta))) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(StockMovement)
                .where(StockMovement.kind == "reversal")
            )
            == 1
        )


@pytest.mark.parametrize("ended_target", ["appliance", "consumable", "link"])
def test_ended_resources_block_new_use_but_allow_historical_cancellation(
    homecare_app, actors, ended_target
):
    actor = actors[0]
    with TestClient(homecare_app) as client:
        appliance = post_appliance(client, actor)
        stock = post_consumable(client, actor)
        link = post_link(client, actor, appliance, stock)
        receipt(client, actor, stock)
        replacement = replace(client, actor, link)
        paths = {
            "appliance": f"/api/v1/appliances/{appliance['id']}",
            "consumable": f"/api/v1/consumables/{stock['id']}",
            "link": f"/api/v1/appliance-consumables/{link['id']}",
        }
        version = 3 if ended_target == "consumable" else 1
        response = client.patch(
            paths[ended_target],
            headers=headers(actor, version=version),
            json={"active": False} if ended_target == "link" else {"ended_on": TODAY},
        )
        assert response.status_code == 200, response.text
        current = stock_at(client, actor, stock["id"])
        rejected = client.post(
            f"/api/v1/appliance-consumables/{link['id']}/replacements",
            headers=headers(actor, version=current["version"]),
            json={
                "replaced_on": TODAY,
                "quantity": 1,
                "link_version": 2 if ended_target == "link" else 1,
                "clear_next_check_override": False,
            },
        )
        assert rejected.status_code == 422
        assert client.get("/api/v1/homecare/status", headers=actor.headers).json()["items"] == []
        assert link_at(client, actor, link["id"])["last_replaced_on"] == "2025-03-02"
        cancel_replacement(client, actor, link, replacement)
        assert link_at(client, actor, link["id"])["last_replaced_on"] is None
        assert stock_at(client, actor, stock["id"])["stock_quantity"] == 3
        if ended_target != "link":
            other_appliance = (
                post_appliance(client, actor) if ended_target == "consumable" else appliance
            )
            other_stock = stock if ended_target == "consumable" else post_consumable(client, actor)
            rejected = client.post(
                "/api/v1/appliance-consumables",
                headers=actor.headers,
                json={"appliance_id": other_appliance["id"], "consumable_id": other_stock["id"]},
            )
            assert rejected.status_code == 422
        if ended_target == "consumable":
            rejected = client.post(
                f"/api/v1/consumables/{stock['id']}/stock-movements",
                headers=headers(actor, version=stock_at(client, actor, stock["id"])["version"]),
                json={"kind": "receipt", "quantity_delta": 1, "occurred_on": TODAY},
            )
            assert (
                rejected.status_code == 422
                and rejected.json()["error"]["code"] == "CONSUMABLE_UNAVAILABLE"
            )


def test_stock_and_link_versions_are_both_checked_without_partial_writes(
    homecare_app, actors, db_engine
):
    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        link = post_link(client, actor, post_appliance(client, actor), stock)
        receipt(client, actor, stock)
        changed = client.patch(
            f"/api/v1/appliance-consumables/{link['id']}",
            headers=headers(actor, version=1),
            json={"interval_count": 2},
        )
        assert changed.status_code == 200
        path = f"/api/v1/appliance-consumables/{link['id']}/replacements"
        body = {
            "replaced_on": TODAY,
            "quantity": 1,
            "link_version": 1,
            "clear_next_check_override": False,
        }
        assert (
            client.post(path, headers=headers(actor, version=2), json=body).json()["error"]["code"]
            == "VERSION_CONFLICT"
        )
        assert (
            client.post(
                path, headers=headers(actor, version=1), json=body | {"link_version": 2}
            ).json()["error"]["code"]
            == "VERSION_CONFLICT"
        )
        for bad in ('W/"2"', "2", '"0"', "*"):
            h = headers(actor, version=2) | {"If-Match": bad}
            assert client.post(path, headers=h, json=body | {"link_version": 2}).status_code == 400
        assert stock_at(client, actor, stock["id"])["stock_quantity"] == 3
        assert link_at(client, actor, link["id"])["last_replaced_on"] is None
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(ConsumableReplacement)) == 0
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 1


def test_future_actual_dates_invalid_quantity_overflow_and_reason_reject_atomically(
    homecare_app, actors, db_engine
):
    actor = actors[0]
    with TestClient(homecare_app) as client:
        assert (
            client.post(
                "/api/v1/appliances",
                headers=actor.headers,
                json={"name": "합성", "purchased_on": "2026-10-18"},
            ).status_code
            == 422
        )
        stock = post_consumable(client, actor)
        path = f"/api/v1/consumables/{stock['id']}/stock-movements"
        base = {"kind": "receipt", "quantity_delta": 1, "occurred_on": TODAY}
        for change in (
            {"occurred_on": "2026-10-18"},
            {"quantity_delta": "1"},
            {"quantity_delta": 1.5},
            {"quantity_delta": True},
            {"quantity_delta": 0},
            {"kind": "adjustment"},
            {"kind": "reversal"},
        ):
            assert (
                client.post(path, headers=headers(actor, version=1), json=base | change).status_code
                == 422
            )
        full = client.post(
            path, headers=headers(actor, version=1), json=base | {"quantity_delta": 1_000_000}
        )
        assert full.status_code == 201
        overflow = client.post(path, headers=headers(actor, version=2), json=base)
        assert (
            overflow.status_code == 422
            and overflow.json()["error"]["code"] == "STOCK_LIMIT_EXCEEDED"
        )
        assert stock_at(client, actor, stock["id"])["stock_quantity"] == 1_000_000
        missing_version = headers(actor)
        no_version = client.post(path, headers=missing_version, json=base)
        assert no_version.status_code == 400
        assert no_version.json()["error"]["code"] == "VERSION_REQUIRED"
        missing_key = actor.headers | {"If-Match": '"2"'}
        no_key = client.post(path, headers=missing_key, json=base)
        assert no_key.status_code == 400
        assert no_key.json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 1
        assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1


def test_unit_changes_stop_after_history_even_if_current_stock_zero(homecare_app, actors):
    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        path = f"/api/v1/consumables/{stock['id']}"
        before = client.patch(path, headers=headers(actor, version=1), json={"unit": "팩"})
        assert before.status_code == 200 and before.json()["unit"] == "팩"
        received = receipt(client, actor, stock, quantity=1)
        cancelled = client.post(
            f"{path}/stock-movements/{received['id']}/cancel",
            headers=headers(actor, version=3),
            json={"occurred_on": TODAY, "reason": "합성 취소"},
        )
        assert cancelled.status_code == 200
        blocked = client.patch(path, headers=headers(actor, version=4), json={"unit": "개"})
        assert (
            blocked.status_code == 409
            and blocked.json()["error"]["code"] == "CONSUMABLE_UNIT_IN_USE"
        )
        changed = client.patch(
            path,
            headers=headers(actor, version=4),
            json={
                "name": "합성 새 이름",
                "sku_or_model": "SYNTHETIC-NEW",
                "low_stock_threshold": 0,
            },
        )
        assert changed.status_code == 200 and changed.json()["stock_quantity"] == 0
        assert changed.json()["unit"] == "팩"


def test_stock_cancellation_replays_bind_parent_and_keep_original_result(homecare_app, actors):
    actor, _, foreign = actors
    with TestClient(homecare_app) as client:
        stock, other_stock = post_consumable(client, actor), post_consumable(client, actor)
        received = receipt(client, actor, stock)
        path = f"/api/v1/consumables/{stock['id']}/stock-movements/{received['id']}/cancel"
        h = headers(actor, "synthetic-bound-cancel", 2)
        body = {"occurred_on": TODAY, "reason": "합성 취소"}
        result = client.post(path, headers=h, json=body)
        assert result.status_code == 200
        receipt(client, actor, stock, quantity=1)
        assert client.post(path, headers=h, json=body).json() == result.json()
        wrong_parent = path.replace(stock["id"], other_stock["id"])
        assert client.post(wrong_parent, headers=h, json=body).status_code == 404
        assert (
            client.post(
                path, headers=headers(foreign, "synthetic-bound-cancel", 2), json=body
            ).status_code
            == 404
        )
        assert stock_at(client, actor, stock["id"])["stock_quantity"] == 1


def test_replacement_cancellation_replay_checks_parent_and_does_not_repeat_stock(
    homecare_app, actors
):
    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        links = [post_link(client, actor, post_appliance(client, actor), stock) for _ in range(2)]
        receipt(client, actor, stock)
        original = replace(client, actor, links[0])
        body = {"occurred_on": TODAY, "reason": "합성 취소"}
        h = headers(actor, "synthetic-replacement-cancel", 3)
        path = (
            f"/api/v1/appliance-consumables/{links[0]['id']}/replacements/"
            f"{original['replacement_id']}/cancel"
        )
        first = client.post(path, headers=h, json=body)
        assert first.status_code == 200
        replace(client, actor, links[1])
        assert client.post(path, headers=h, json=body).json() == first.json()
        assert (
            client.post(
                path.replace(links[0]["id"], links[1]["id"]), headers=h, json=body
            ).status_code
            == 404
        )
        assert stock_at(client, actor, stock["id"])["stock_quantity"] == 2
        repeated = client.post(path, headers=headers(actor, version=5), json=body)
        assert (
            repeated.status_code == 409
            and repeated.json()["error"]["code"] == "STOCK_MOVEMENT_ALREADY_REVERSED"
        )


def test_t24_status_is_seoul_today_and_distinguishes_due_buy_low_and_unknown(
    homecare_app, actors, monkeypatch
):
    actor = actors[0]
    with TestClient(homecare_app) as client:
        appliance = post_appliance(client, actor, purchased_on="2025-01-01")
        stock = post_consumable(client, actor, low_stock_threshold=2)
        known = post_link(client, actor, appliance, stock, next_check_override=TODAY)
        unknown = post_link(
            client,
            actor,
            post_appliance(client, actor),
            stock,
            interval_unit="manual",
            interval_count=None,
        )
        receipt(client, actor, stock, quantity=2)
        page = client.get(
            "/api/v1/homecare/status?month=2025-01&as_of=2025-01-01", headers=actor.headers
        ).json()
        assert page["as_of"] == vector("T-24")["expected"]["consumables_as_of"]
        rows = {row["id"]: row for row in page["items"]}
        assert rows[known["id"]]["replacement_due"] is True
        assert rows[known["id"]]["purchase_needed"] is False
        assert rows[known["id"]]["low_stock"] is True
        assert rows[unknown["id"]]["last_replaced_on"] is None
        assert rows[unknown["id"]]["next_check_on"] is None
        assert rows[unknown["id"]]["replacement_due"] is None
        monkeypatch.setattr(service, "utcnow", lambda: datetime(2026, 10, 16, 14, 59, tzinfo=UTC))
        before = client.get("/api/v1/homecare/status", headers=actor.headers).json()
        assert before["as_of"] == "2026-10-16"
        assert all(row["replacement_due"] is not True for row in before["items"])
        monkeypatch.setattr(service, "utcnow", lambda: datetime(2026, 10, 16, 15, 0, tzinfo=UTC))
        after = client.get("/api/v1/homecare/status", headers=actor.headers).json()
        assert after["as_of"] == TODAY
        replace(client, actor, known, quantity=2, replaced_on=TODAY)
        latest = client.get("/api/v1/homecare/status", headers=actor.headers).json()["items"]
        assert all(row["purchase_needed"] is True and row["stock_quantity"] == 0 for row in latest)
        assert link_at(client, actor, unknown["id"])["replacement_due"] is None


def test_every_foreign_household_target_and_relationship_is_not_found(homecare_app, actors):
    actor, _, foreign = actors
    with TestClient(homecare_app) as client:
        appliance = post_appliance(client, foreign)
        stock = post_consumable(client, foreign)
        link = post_link(client, foreign, appliance, stock)
        movement = receipt(client, foreign, stock)
        replacement = replace(client, foreign, link)
        a, c, link_id, m, r = (
            appliance["id"],
            stock["id"],
            link["id"],
            movement["id"],
            replacement["replacement_id"],
        )
        get_paths = [
            f"/appliances/{a}",
            f"/consumables/{c}",
            f"/appliance-consumables/{link_id}",
            f"/consumables/{c}/stock-movements",
            f"/consumables/{c}/stock-movements/{m}",
            f"/appliance-consumables/{link_id}/replacements",
            f"/appliance-consumables/{link_id}/replacements/{r}",
            f"/appliance-consumables?appliance_id={a}",
            f"/appliance-consumables?consumable_id={c}",
            f"/homecare/status?appliance_id={a}",
            f"/homecare/status?consumable_id={c}",
        ]
        for path in get_paths:
            assert client.get("/api/v1" + path, headers=actor.headers).status_code == 404, path
        for path in ("/appliances", "/consumables", "/appliance-consumables", "/homecare/status"):
            assert client.get("/api/v1" + path, headers=actor.headers).json()["items"] == []
        for path, body in [
            (f"/appliances/{a}", {"name": "합성 변조"}),
            (f"/consumables/{c}", {"name": "합성 변조"}),
            (f"/appliance-consumables/{link_id}", {"active": False}),
        ]:
            assert (
                client.patch(
                    "/api/v1" + path, headers=headers(actor, version=1), json=body
                ).status_code
                == 404
            )
        for path, body in [
            (
                f"/consumables/{c}/stock-movements",
                {"kind": "receipt", "quantity_delta": 1, "occurred_on": TODAY},
            ),
            (
                f"/consumables/{c}/stock-movements/{m}/cancel",
                {"occurred_on": TODAY, "reason": "합성 외부 취소"},
            ),
            (
                f"/appliance-consumables/{link_id}/replacements",
                {
                    "replaced_on": TODAY,
                    "quantity": 1,
                    "link_version": 1,
                    "clear_next_check_override": False,
                },
            ),
            (
                f"/appliance-consumables/{link_id}/replacements/{r}/cancel",
                {"occurred_on": TODAY, "reason": "합성 외부 취소"},
            ),
        ]:
            assert (
                client.post(
                    "/api/v1" + path, headers=headers(actor, version=3), json=body
                ).status_code
                == 404
            )
        own_device, own_stock = post_appliance(client, actor), post_consumable(client, actor)
        for a_id, c_id in ((a, own_stock["id"]), (own_device["id"], c), (a, c)):
            assert (
                client.post(
                    "/api/v1/appliance-consumables",
                    headers=actor.headers,
                    json={"appliance_id": a_id, "consumable_id": c_id},
                ).status_code
                == 404
            )
        assert (
            client.post(
                "/api/v1/appliances",
                headers=actor.headers,
                json={"name": "합성", "household_id": str(foreign.household_id)},
            ).status_code
            == 422
        )
        assert stock_at(client, foreign, c)["stock_quantity"] == 2
        assert link_at(client, foreign, link_id)["last_replacement_id"] == r


def test_pagination_is_bounded_stable_and_parent_scoped(homecare_app, actors):
    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        links = [
            post_link(client, actor, post_appliance(client, actor, name=f"합성 기기 {i}"), stock)
            for i in range(4)
        ]
        for _ in range(3):
            receipt(client, actor, stock, quantity=1)
        for _ in range(2):
            replace(client, actor, links[0])
        for path in (
            "/api/v1/appliances",
            "/api/v1/appliance-consumables",
            "/api/v1/homecare/status",
            f"/api/v1/consumables/{stock['id']}/stock-movements",
            f"/api/v1/appliance-consumables/{links[0]['id']}/replacements",
        ):
            ids, cursor = [], None
            while True:
                response = client.get(
                    path,
                    headers=actor.headers,
                    params={"limit": 1} | ({"cursor": cursor} if cursor else {}),
                )
                assert response.status_code == 200, response.text
                page = response.json()
                assert len(page["items"]) <= 1
                ids.extend(row["id"] for row in page["items"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
                assert cursor == page["items"][-1]["id"]
            assert len(ids) == len(set(ids)) and ids == sorted(ids, reverse=True)
            assert client.get(path, headers=actor.headers, params={"limit": 201}).status_code == 422
        wrong_link = f"/api/v1/appliance-consumables/{links[1]['id']}/replacements"
        assert client.get(wrong_link, headers=actor.headers).json()["items"] == []
        assert (
            client.get("/api/v1/appliances?status=invalid", headers=actor.headers).status_code
            == 422
        )


def test_link_and_today_lists_use_batched_reads_instead_of_one_query_per_device(
    homecare_app, actors, db_engine
):
    from sqlalchemy import event

    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        links = [post_link(client, actor, post_appliance(client, actor), stock) for _ in range(8)]
        receipt(client, actor, stock, quantity=8)
        for link in links:
            replace(client, actor, link)
        queries = []

        def count_select(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                queries.append(statement)

        event.listen(db_engine, "before_cursor_execute", count_select)
        try:
            for path in ("/api/v1/appliance-consumables", "/api/v1/homecare/status"):
                queries.clear()
                assert (
                    client.get(path, headers=actor.headers, params={"limit": 1}).status_code == 200
                )
                one = len(queries)
                queries.clear()
                many = client.get(path, headers=actor.headers, params={"limit": 8})
                assert many.status_code == 200 and len(many.json()["items"]) == 8
                assert len(queries) == one
        finally:
            event.remove(db_engine, "before_cursor_execute", count_select)


def test_database_forbids_fact_mutation_target_changes_and_stock_cache_forgery(
    homecare_app, actors, db_engine
):
    from sqlalchemy import delete, update
    from sqlalchemy.exc import DBAPIError

    from sallimbook.homecare.models import ApplianceConsumable

    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock, other_stock = post_consumable(client, actor), post_consumable(client, actor)
        link = post_link(client, actor, post_appliance(client, actor), stock)
        receipt(client, actor, stock)
        replacement = replace(client, actor, link)
    with Session(db_engine) as session:
        statements = [
            update(StockMovement)
            .where(StockMovement.id == UUID(replacement["id"]))
            .values(quantity_delta=-2),
            delete(StockMovement).where(StockMovement.id == UUID(replacement["id"])),
            update(ConsumableReplacement)
            .where(ConsumableReplacement.id == UUID(replacement["replacement_id"]))
            .values(replaced_on=date(2025, 4, 1)),
            delete(ConsumableReplacement).where(
                ConsumableReplacement.id == UUID(replacement["replacement_id"])
            ),
            update(ApplianceConsumable)
            .where(ApplianceConsumable.id == UUID(link["id"]))
            .values(consumable_id=UUID(other_stock["id"])),
            update(Consumable).where(Consumable.id == UUID(stock["id"])).values(stock_quantity=9),
            update(Consumable).where(Consumable.id == UUID(stock["id"])).values(stock_quantity=-1),
            update(Consumable).where(Consumable.id == UUID(stock["id"])).values(unit="팩"),
        ]
        for statement in statements:
            with pytest.raises(DBAPIError):
                session.execute(statement)
                session.commit()
            session.rollback()
        assert session.get(Consumable, UUID(stock["id"])).stock_quantity == 2
        assert session.get(Consumable, UUID(stock["id"])).unit == "개"
        assert session.get(StockMovement, UUID(replacement["id"])).quantity_delta == -1
        assert session.get(
            ConsumableReplacement, UUID(replacement["replacement_id"])
        ).replaced_on == date(2025, 3, 2)


def test_database_reversal_checks_original_full_quantity_and_unique_stock_version(
    homecare_app, actors, db_engine
):
    from sqlalchemy.exc import DBAPIError

    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        original = receipt(client, actor, stock)
    with Session(db_engine) as session:
        # A partial reversal could keep the sum/cache coherent.
        # The immutable source binding must still reject it.
        row = session.get(Consumable, UUID(stock["id"]))
        row.stock_quantity = 2
        row.version += 1
        session.flush()
        session.add(
            StockMovement(
                household_id=actor.household_id,
                consumable_id=row.id,
                created_by_member_id=actor.principal.member_id,
                kind="reversal",
                quantity_delta=-1,
                occurred_on=date(2026, 10, 17),
                reversal_of=UUID(original["id"]),
                reason="합성 잘못된 역수량",
                unit_cost_krw=None,
                purchase_url=None,
                note=None,
                stock_version=row.version,
            )
        )
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()
        row = session.get(Consumable, UUID(stock["id"]))
        assert row.stock_quantity == 3 and row.version == 2
        session.add(
            StockMovement(
                household_id=actor.household_id,
                consumable_id=row.id,
                created_by_member_id=actor.principal.member_id,
                kind="receipt",
                quantity_delta=1,
                occurred_on=date(2026, 10, 17),
                reversal_of=None,
                reason=None,
                unit_cost_krw=None,
                purchase_url=None,
                note=None,
                stock_version=2,
            )
        )
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 1


def test_replacement_fact_and_movement_must_share_sku_date_and_quantity(
    homecare_app, actors, db_engine
):
    from sqlalchemy.exc import DBAPIError

    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock, other_stock = post_consumable(client, actor), post_consumable(client, actor)
        link = post_link(client, actor, post_appliance(client, actor), stock)
        other_link = post_link(client, actor, post_appliance(client, actor), other_stock)
        receipt(client, actor, stock)
    for changes in (
        {"quantity": 2},
        {"replaced_on": date(2025, 2, 1)},
        {"appliance_consumable_id": UUID(other_link["id"])},
    ):
        with Session(db_engine) as session:
            row = session.get(Consumable, UUID(stock["id"]))
            row.stock_quantity -= 1
            row.version += 1
            session.flush()
            movement = StockMovement(
                household_id=actor.household_id,
                consumable_id=row.id,
                created_by_member_id=actor.principal.member_id,
                kind="replacement",
                quantity_delta=-1,
                occurred_on=date(2025, 1, 1),
                reversal_of=None,
                reason=None,
                unit_cost_krw=None,
                purchase_url=None,
                note=None,
                stock_version=row.version,
            )
            session.add(movement)
            session.flush()
            replacement = ConsumableReplacement(
                **(
                    {
                        "household_id": actor.household_id,
                        "created_by_member_id": actor.principal.member_id,
                        "appliance_consumable_id": UUID(link["id"]),
                        "consumable_id": row.id,
                        "stock_movement_id": movement.id,
                        "replaced_on": date(2025, 1, 1),
                        "quantity": 1,
                        "note": None,
                    }
                    | changes
                )
            )
            session.add(replacement)
            with pytest.raises(DBAPIError):
                session.commit()
            session.rollback()
    with Session(db_engine) as session:
        assert session.get(Consumable, UUID(stock["id"])).stock_quantity == 3
        assert session.scalar(select(func.count()).select_from(ConsumableReplacement)) == 0


def test_orphan_replacement_movement_and_direct_nonzero_opening_stock_cannot_commit(
    homecare_app, actors, db_engine
):
    from sqlalchemy.exc import DBAPIError

    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        receipt(client, actor, stock)
    with Session(db_engine) as session:
        row = session.get(Consumable, UUID(stock["id"]))
        row.stock_quantity -= 1
        row.version += 1
        session.flush()
        session.add(
            StockMovement(
                household_id=actor.household_id,
                consumable_id=row.id,
                created_by_member_id=actor.principal.member_id,
                kind="replacement",
                quantity_delta=-1,
                occurred_on=date(2025, 1, 1),
                reversal_of=None,
                reason=None,
                unit_cost_krw=None,
                purchase_url=None,
                note=None,
                stock_version=row.version,
            )
        )
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()
        session.add(
            Consumable(
                household_id=actor.household_id,
                name="합성 위조 기초재고",
                sku_or_model=None,
                unit="개",
                stock_quantity=1,
                low_stock_threshold=0,
                ended_on=None,
                note=None,
                created_by_member_id=actor.principal.member_id,
                updated_by_member_id=actor.principal.member_id,
            )
        )
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()
        assert session.scalar(select(func.count()).select_from(Consumable)) == 1


def test_unauthenticated_and_extra_server_owned_fields_are_rejected(homecare_app, actors):
    with TestClient(homecare_app) as client:
        assert client.get("/api/v1/homecare/status").status_code == 401
        assert client.post("/api/v1/appliances", json={"name": "합성"}).status_code == 401
        actor = actors[0]
        for payload in (
            {"stock_quantity": 3},
            {"household_id": str(actor.household_id)},
            {"version": 100},
        ):
            assert (
                client.post(
                    "/api/v1/consumables",
                    headers=actor.headers,
                    json={"name": "합성", "unit": "개"} | payload,
                ).status_code
                == 422
            )


def test_audit_records_fields_and_actor_without_copying_private_values(
    homecare_app, actors, db_engine
):
    from sallimbook.core.audit import AuditEvent

    actor = actors[0]
    note = "합성 비공개 메모는 감사값에 복제하지 않음"
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor, note=note)
        receipt(
            client,
            actor,
            stock,
            quantity=1,
            note=note,
            unit_cost_krw="99999999999999999999",
            purchase_url="https://synthetic.invalid/item",
        )
    with Session(db_engine) as session:
        events = list(
            session.scalars(select(AuditEvent).where(AuditEvent.household_id == actor.household_id))
        )
        assert {row.entity_type for row in events} >= {"consumable", "stock_movement"}
        assert all(row.actor_id == actor.principal.user_id for row in events)
        assert all(
            note not in str(row.safe_diff) and "99999999999999999999" not in str(row.safe_diff)
            for row in events
        )
        movement = session.scalar(select(StockMovement))
        assert str(movement.unit_cost_krw) == "99999999999999999999"


@pytest.mark.parametrize("kind", ["appliances", "consumables", "appliance-consumables"])
def test_delete_unreferenced_metadata_requires_scope_and_current_version(
    homecare_app, actors, db_engine, kind
):
    from sallimbook.core.audit import AuditEvent

    actor, partner, foreign = actors
    with TestClient(homecare_app) as client:
        if kind == "appliances":
            row = post_appliance(client, actor)
        elif kind == "consumables":
            row = post_consumable(client, actor)
        else:
            row = post_link(
                client, actor, post_appliance(client, actor), post_consumable(client, actor)
            )
        path = f"/api/v1/{kind}/{row['id']}"
        assert client.delete(path, headers=headers(foreign, version=1)).status_code == 404
        assert client.delete(path, headers=actor.headers).status_code == 400
        assert client.delete(path, headers=headers(actor, version=2)).status_code == 409
        deleted = client.delete(path, headers=headers(partner, version=1))
        assert deleted.status_code == 204, deleted.text
        assert deleted.content == b""
        assert client.get(path, headers=actor.headers).status_code == 404
        assert client.delete(path, headers=headers(actor, version=1)).status_code == 404
    with Session(db_engine) as session:
        events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_id == UUID(row["id"]), AuditEvent.action == "delete"
                )
            )
        )
        assert len(events) == 1
        assert events[0].actor_id == partner.principal.user_id
        assert events[0].before_version == 1 and events[0].after_version is None


@pytest.mark.parametrize("kind", ["appliances", "consumables", "appliance-consumables"])
def test_delete_preserves_references_and_cancelled_history(homecare_app, actors, db_engine, kind):
    from sallimbook.core.audit import AuditEvent

    actor = actors[0]
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        if kind == "consumables":
            received = receipt(client, actor, stock, quantity=1)
            cancelled = client.post(
                f"/api/v1/consumables/{stock['id']}/stock-movements/{received['id']}/cancel",
                headers=headers(actor, version=stock_at(client, actor, stock["id"])["version"]),
                json={"occurred_on": TODAY, "reason": "합성 입고 취소"},
            )
            assert cancelled.status_code == 200, cancelled.text
            row = stock_at(client, actor, stock["id"])
            assert row["stock_quantity"] == 0
        else:
            appliance = post_appliance(client, actor)
            link = post_link(client, actor, appliance, stock)
            row = appliance
            if kind == "appliance-consumables":
                receipt(client, actor, stock)
                replaced = replace(client, actor, link)
                cancel_replacement(client, actor, link, replaced)
                row = link_at(client, actor, link["id"])
        path = f"/api/v1/{kind}/{row['id']}"
        response = client.delete(path, headers=headers(actor, version=row["version"]))
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"].endswith("_IN_USE")
        assert client.get(path, headers=actor.headers).status_code == 200
    with Session(db_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_id == UUID(row["id"]), AuditEvent.action == "delete")
            )
            == 0
        )


def test_concurrent_delete_and_new_reference_keep_one_consistent_outcome(homecare_app, actors):
    actor = actors[0]
    with TestClient(homecare_app) as client:
        appliance = post_appliance(client, actor)
        stock = post_consumable(client, actor)
    barrier = Barrier(2)

    def remove():
        with TestClient(homecare_app) as client:
            barrier.wait(timeout=10)
            return client.delete(
                f"/api/v1/appliances/{appliance['id']}", headers=headers(actor, version=1)
            ).status_code

    def connect():
        with TestClient(homecare_app) as client:
            barrier.wait(timeout=10)
            return client.post(
                "/api/v1/appliance-consumables",
                headers=actor.headers,
                json={
                    "appliance_id": appliance["id"],
                    "consumable_id": stock["id"],
                },
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        deletion = pool.submit(remove)
        connection = pool.submit(connect)
        assert (deletion.result(timeout=20), connection.result(timeout=20)) in {
            (204, 404),
            (409, 201),
        }
