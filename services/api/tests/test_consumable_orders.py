"""Synthetic shared planning, household access and atomic purchase receipt integration."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_homecare_database import (
    TODAY,
    post_appliance,
    post_consumable,
    post_link,
    receipt,
    stock_at,
)
from test_homecare_database import actors as actors
from test_homecare_database import homecare_app as homecare_app
from test_income import headers

from sallimbook.cashflow.models import CashRecord
from sallimbook.core.idempotency import IdempotencyRecord
from sallimbook.homecare import service
from sallimbook.homecare.models import ConsumableOrder, StockMovement

pytestmark = pytest.mark.database


def create(client, actor, stock, *, key=None, **changes):
    response = client.post(
        "/api/v1/consumable-orders",
        headers=headers(actor, key),
        json={"consumable_id": stock["id"], "quantity": 1} | changes,
    )
    assert response.status_code == 201, response.text
    return response.json()


def get(client, actor, order):
    response = client.get(f"/api/v1/consumable-orders/{order['id']}", headers=actor.headers)
    assert response.status_code == 200, response.text
    return response.json()


def command(client, actor, order, action, payload, *, key=None):
    return client.post(
        f"/api/v1/consumable-orders/{order['id']}/{action}",
        headers=headers(actor, key, order["version"]),
        json=payload,
    )


def submit(client, actor, order):
    response = command(client, actor, order, "submit", {"ordered_on": TODAY})
    assert response.status_code == 200, response.text
    return response.json()


def plan(client, actor, **params):
    response = client.get("/api/v1/homecare/purchase-plan", headers=actor.headers, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_pooled_demand_and_open_orders_never_double_count_physical_stock(
    homecare_app, actors, db_engine
):
    owner, partner, _ = actors
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, owner)
        for name in ("합성 거실 기기", "합성 침실 기기"):
            appliance = post_appliance(client, owner, name=name)
            post_link(client, owner, appliance, stock, next_check_override=TODAY)
        receipt(
            client,
            owner,
            stock,
            quantity=1,
            unit_cost_krw="0",
            purchase_url="https://example.test/filter",
        )
        result = plan(client, partner)
        row = result["items"][0]
        assert result["as_of"] == result["through"] == TODAY
        assert (
            row["demand_quantity"],
            row["consumable"]["stock_quantity"],
            row["shortage_quantity"],
            row["additional_quantity"],
        ) == (2, 1, 1, 1)
        assert len(row["demand_sources"]) == 2
        assert row["last_receipt"]["unit_cost_krw"] == "0"
        first = create(client, owner, stock)
        second = create(client, partner, stock, quantity=2)
        second = submit(client, partner, second)
        row = plan(client, owner)["items"][0]
        assert (row["planned_quantity"], row["ordered_quantity"], row["open_order_count"]) == (
            1,
            2,
            2,
        )
        assert row["shortage_quantity"] == 1 and row["additional_quantity"] == 0
        assert stock_at(client, owner, stock["id"])["stock_quantity"] == 1
        assert get(client, owner, first)["created_by_member_id"] == str(owner.member_id)
        assert get(client, owner, second)["ordered_by_member_id"] == str(partner.member_id)
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 0


def test_projection_handles_overdue_unknown_ended_and_manual_dates_across_pages(
    homecare_app, actors
):
    actor, _, foreign = actors
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        a = post_appliance(client, actor)
        post_link(
            client,
            actor,
            a,
            stock,
            interval_unit="days",
            interval_count=1,
            next_check_override="2020-01-01",
        )
        b = post_appliance(client, actor)
        post_link(client, actor, b, stock, interval_unit="manual", interval_count=None)
        c = post_appliance(client, actor)
        post_link(
            client,
            actor,
            c,
            stock,
            interval_unit="manual",
            interval_count=None,
            next_check_override=TODAY,
        )
        d = post_appliance(client, actor)
        post_link(client, actor, d, stock, next_check_override=TODAY)
        ended = client.patch(
            f"/api/v1/appliances/{d['id']}",
            headers=headers(actor, version=d["version"]),
            json={"ended_on": TODAY},
        )
        assert ended.status_code == 200
        d = ended.json()
        # A link can be retained before the appliance ends; inactive links add no demand.
        e = post_appliance(client, actor)
        post_link(client, actor, e, stock, active=False, next_check_override=TODAY)
        other = post_consumable(client, actor, name="합성 공용 필터")
        row = next(
            x
            for x in plan(client, actor, through="2026-10-19")["items"]
            if x["consumable"]["id"] == stock["id"]
        )
        assert row["demand_quantity"] == 4 and row["unscheduled_link_count"] == 1
        first = plan(client, actor, limit=1)
        second = plan(client, actor, limit=1, cursor=first["next_cursor"])
        assert {first["items"][0]["consumable"]["id"], second["items"][0]["consumable"]["id"]} == {
            stock["id"],
            other["id"],
        }
        assert not second["next_cursor"]
        foreign_stock = post_consumable(client, foreign)
        for params in (
            {"cursor": foreign_stock["id"]},
            {"through": "2026-10-16"},
            {"through": "2027-10-18"},
            {"limit": 201},
        ):
            response = client.get(
                "/api/v1/homecare/purchase-plan", headers=actor.headers, params=params
            )
            assert response.status_code == (404 if "cursor" in params else 422)
        assert plan(client, actor, q="%_")["items"] == []
        assert client.get("/api/v1/homecare/purchase-plan").status_code == 401
        assert d["status"] == "ended"


def test_receive_replay_is_one_stock_fact_and_preserves_original_command_version(
    homecare_app, actors, db_engine
):
    owner, partner, _ = actors
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, owner)
        created = create(
            client,
            owner,
            stock,
            key="synthetic-create",
            quantity=3,
            unit_cost_krw="9007199254740993",
        )
        ordered = submit(client, partner, created)
        response = command(
            client,
            owner,
            ordered,
            "receive",
            {"received_on": TODAY, "stock_version": stock["version"]},
            key="synthetic-receive",
        )
        assert response.status_code == 200, response.text
        received = get(client, partner, created)
        assert received["state"] == "received" and received["received_by_member_id"] == str(
            owner.member_id
        )
        assert stock_at(client, owner, stock["id"])["stock_quantity"] == 3
        replay = command(
            client,
            owner,
            ordered,
            "receive",
            {"received_on": TODAY, "stock_version": stock["version"]},
            key="synthetic-receive",
        )
        assert replay.json() == response.json()
        assert (
            create(
                client,
                owner,
                stock,
                key="synthetic-create",
                quantity=3,
                unit_cost_krw="9007199254740993",
            )
            == created
        )
        extra = receipt(client, partner, stock, quantity=1)
        assert extra["stock_version"] > stock["version"]
        assert (
            command(
                client,
                owner,
                ordered,
                "receive",
                {"received_on": TODAY, "stock_version": stock["version"]},
                key="synthetic-receive",
            ).json()
            == response.json()
        )
        assert (
            command(
                client, partner, received, "receive", {"received_on": TODAY, "stock_version": 3}
            ).status_code
            == 409
        )
        assert (
            command(client, partner, received, "cancel", {"reason": "합성 취소"}).status_code == 409
        )
        assert (
            client.patch(
                f"/api/v1/consumable-orders/{created['id']}",
                headers=headers(owner, version=received["version"]),
                json={"quantity": 9},
            ).status_code
            == 409
        )
        assert (
            plan(client, owner)["items"][0]["last_receipt"]["id"] == received["stock_movement_id"]
        )
        current = stock_at(client, owner, stock["id"])
        cancelled = client.post(
            f"/api/v1/consumables/{stock['id']}/stock-movements/{received['stock_movement_id']}/cancel",
            headers=headers(owner, version=current["version"]),
            json={"occurred_on": TODAY, "reason": "합성 입고 취소"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert get(client, partner, created)["receipt_reversed_by"] == cancelled.json()["id"]
        assert stock_at(client, owner, stock["id"])["stock_quantity"] == 1
        assert plan(client, owner)["items"][0]["last_receipt"]["id"] == extra["id"]
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(StockMovement)
                    .where(StockMovement.kind == "receipt")
                )
                == 2
            )


def test_versions_ownership_validation_and_cancellation_preserve_history(homecare_app, actors):
    owner, partner, foreign = actors
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, owner)
        created = create(client, owner, stock)
        path = f"/api/v1/consumable-orders/{created['id']}"
        for method, url, body in (
            ("GET", path, None),
            ("PATCH", path, {"quantity": 2}),
            ("POST", path + "/submit", {"ordered_on": TODAY}),
            ("POST", path + "/receive", {"received_on": TODAY, "stock_version": 1}),
            ("POST", path + "/cancel", {"reason": "합성"}),
        ):
            assert (
                client.request(
                    method, url, headers=headers(foreign, version=1), json=body
                ).status_code
                == 404
            )
        assert (
            client.post(
                "/api/v1/consumable-orders",
                headers=headers(foreign),
                json={"consumable_id": stock["id"], "quantity": 1},
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/api/v1/consumable-orders",
                headers=foreign.headers,
                params={"consumable_id": stock["id"]},
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/api/v1/consumable-orders",
                headers=foreign.headers,
                params={"cursor": created["id"]},
            ).status_code
            == 404
        )
        assert client.get(path).status_code == 401
        for changes in (
            {"quantity": 0},
            {"quantity": True},
            {"quantity": 1000001},
            {"unit_cost_krw": 1.5},
            {"purchase_url": "http://example.test"},
            {"state": "received"},
            {"household_id": str(foreign.household_id)},
        ):
            assert (
                client.post(
                    "/api/v1/consumable-orders",
                    headers=headers(owner),
                    json={"consumable_id": stock["id"], "quantity": 1} | changes,
                ).status_code
                == 422
            )
        assert (
            command(client, owner, created, "submit", {"ordered_on": "2026-10-18"}).status_code
            == 422
        )
        assert (
            command(
                client, owner, created, "receive", {"received_on": TODAY, "stock_version": 1}
            ).status_code
            == 409
        )
        updated = client.patch(path, headers=headers(partner, version=1), json={"quantity": 2})
        assert updated.status_code == 200, updated.text
        assert (
            client.patch(path, headers=headers(owner, version=1), json={"quantity": 3}).status_code
            == 409
        )
        cancelled = command(
            client,
            owner,
            updated.json(),
            "cancel",
            {"reason": "합성 중복 계획"},
            key="synthetic-cancel",
        )
        assert cancelled.status_code == 200, cancelled.text
        assert (
            command(
                client,
                owner,
                updated.json(),
                "cancel",
                {"reason": "합성 중복 계획"},
                key="synthetic-cancel",
            ).json()
            == cancelled.json()
        )
        assert plan(client, owner)["items"][0]["open_order_count"] == 0
        assert (
            client.patch(
                f"/api/v1/consumables/{stock['id']}",
                headers=headers(owner, version=1),
                json={"unit": "묶음"},
            ).status_code
            == 409
        )
        assert (
            client.delete(
                f"/api/v1/consumables/{stock['id']}", headers=headers(owner, version=1)
            ).status_code
            == 409
        )


def test_two_members_receive_one_order_once_and_failed_transaction_can_retry(
    homecare_app, actors, db_engine, monkeypatch
):
    owner, partner, _ = actors
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, owner)
        order = submit(client, owner, create(client, owner, stock, quantity=2))
    barrier = Barrier(2)

    def receive(actor):
        with TestClient(homecare_app) as client:
            barrier.wait(timeout=10)
            return command(
                client, actor, order, "receive", {"received_on": TODAY, "stock_version": 1}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(receive, (owner, partner)))
    assert sorted(results) == [200, 409]
    with TestClient(homecare_app, raise_server_exceptions=False) as client:
        assert stock_at(client, owner, stock["id"])["stock_quantity"] == 2
        another = submit(client, owner, create(client, owner, stock))
        audit = service._audit

        def fail_after_receipt(
            session, principal, row, entity, action, fields=(), before=None, after=None
        ):
            if entity == "consumable_order" and "stock_movement_id" in fields:
                raise RuntimeError("Synthetic transaction interruption")
            return audit(session, principal, row, entity, action, fields, before, after)

        with monkeypatch.context() as patch:
            patch.setattr(service, "_audit", fail_after_receipt)
            response = command(
                client,
                owner,
                another,
                "receive",
                {"received_on": TODAY, "stock_version": 2},
                key="synthetic-rollback",
            )
            assert response.status_code == 500
        assert stock_at(client, owner, stock["id"])["stock_quantity"] == 2
        assert get(client, owner, another)["state"] == "ordered"
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(IdempotencyRecord)
                    .where(IdempotencyRecord.key == "synthetic-rollback")
                )
                == 0
            )
        response = command(
            client,
            owner,
            another,
            "receive",
            {"received_on": TODAY, "stock_version": 2},
            key="synthetic-rollback",
        )
        assert response.status_code == 200, response.text
        assert stock_at(client, owner, stock["id"])["stock_quantity"] == 3


def test_database_rejects_inconsistent_receipt_and_identity_changes(
    homecare_app, actors, db_engine
):
    owner, _, foreign = actors
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, owner)
        other = post_consumable(client, foreign)
        order = submit(client, owner, create(client, owner, stock, quantity=2))
        movement = receipt(client, owner, stock, quantity=1, occurred_on=TODAY)
    for values in (
        {"consumable_id": UUID(other["id"])},
        {"state": "planned"},
        {
            "state": "received",
            "received_on": date.fromisoformat(TODAY),
            "received_by_member_id": owner.member_id,
            "stock_movement_id": UUID(movement["id"]),
        },
    ):
        with Session(db_engine) as session, pytest.raises(DBAPIError):
            row = session.get(ConsumableOrder, UUID(order["id"]))
            row.version += 1
            for key, value in values.items():
                setattr(row, key, value)
            session.commit()
    with db_engine.begin() as connection, pytest.raises(DBAPIError):
        connection.execute(
            text("DELETE FROM consumable_orders WHERE id = :id"), {"id": UUID(order["id"])}
        )


def test_receipt_date_stock_version_and_capacity_fail_without_partial_completion(
    homecare_app, actors
):
    actor, _, _ = actors
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        order = submit(client, actor, create(client, actor, stock, quantity=2))
        receipt(client, actor, stock, quantity=1)
        stale = command(client, actor, order, "receive", {"received_on": TODAY, "stock_version": 1})
        assert stale.status_code == 409
        for day in ("2026-10-16", "2026-10-18"):
            response = command(
                client, actor, order, "receive", {"received_on": day, "stock_version": 2}
            )
            assert response.status_code == 422
        assert get(client, actor, order)["state"] == "ordered"
        assert stock_at(client, actor, stock["id"])["stock_quantity"] == 1
        receipt(client, actor, stock, quantity=999999)
        response = command(
            client, actor, order, "receive", {"received_on": TODAY, "stock_version": 3}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "STOCK_LIMIT_EXCEEDED"
        assert get(client, actor, order)["state"] == "ordered"
        assert stock_at(client, actor, stock["id"])["stock_quantity"] == 1000000


def test_migration_preserves_existing_stock_and_refuses_to_drop_order_history(
    homecare_app, actors, db_engine
):
    from pathlib import Path

    from alembic import command as migration
    from alembic.config import Config

    actor, _, _ = actors

    def migrate(direction, target):
        with db_engine.connect() as connection:
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            getattr(migration, direction)(config, target)

    migrate("downgrade", "0020_insurance_misregistration")
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, actor)
        fact = receipt(client, actor, stock, quantity=3)
        migrate("upgrade", "head")
        assert stock_at(client, actor, stock["id"])["stock_quantity"] == 3
        assert (
            client.get(
                f"/api/v1/consumables/{stock['id']}/stock-movements/{fact['id']}",
                headers=actor.headers,
            ).status_code
            == 200
        )
        order = create(client, actor, stock)
        with db_engine.connect() as connection:
            original_head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        with pytest.raises(DBAPIError, match="retain purchase order history"):
            migrate("downgrade", "0020_insurance_misregistration")
        assert get(client, actor, order)["state"] == "planned"
        with db_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == original_head
            )


def test_order_activity_uses_current_sku_name_and_preserves_actor_without_notes(
    homecare_app, actors
):
    from sallimbook.audit.router import router as audit_router

    homecare_app.include_router(audit_router)
    owner, partner, foreign = actors
    with TestClient(homecare_app) as client:
        stock = post_consumable(client, owner)
        order = create(client, owner, stock, note="합성 비공개 주문 메모")
        submit(client, partner, order)
        renamed = client.patch(
            f"/api/v1/consumables/{stock['id']}",
            headers=headers(owner, version=1),
            json={"name": "합성 새 필터 이름"},
        )
        assert renamed.status_code == 200
        response = client.get(
            "/api/v1/activity-events",
            headers={**owner.headers, "X-SallimBook-People": "1"},
            params={"entity_type": "consumable_order"},
        )
        assert response.status_code == 200, response.text
        rows = response.json()["items"]
        assert len(rows) == 2
        assert {row["actor_member_id"] for row in rows} == {
            str(owner.member_id),
            str(partner.member_id),
        }
        assert all(
            row["target_name"] == "합성 새 필터 이름"
            and row["target_path"] == f"/consumable-orders/{order['id']}"
            for row in rows
        )
        assert "합성 비공개 주문 메모" not in response.text
        assert (
            client.get(
                "/api/v1/activity-events",
                headers={**foreign.headers, "X-SallimBook-People": "1"},
                params={"entity_type": "consumable_order"},
            ).json()["items"]
            == []
        )
        # Existing installed native clients do not see a vocabulary they cannot parse.
        legacy = client.get("/api/v1/audit-events", headers=owner.headers)
        assert legacy.status_code == 200
        assert not any(row["entity_type"] == "consumable_order" for row in legacy.json()["items"])
