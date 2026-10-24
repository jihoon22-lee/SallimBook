"""Household activity reads reuse audit facts and resolve only public current labels."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session
from test_accounts import make_actor
from test_income import headers
from test_name_search import PATHS, application, create

from sallimbook.audit.activity import TARGETS, project_activity
from sallimbook.audit.router import router
from sallimbook.audit.schemas import AuditEventResponse
from sallimbook.core.audit import AuditEvent


def application_with_activity(engine):
    app = application(engine)
    app.include_router(router)
    return app


def event(kind, identifier):
    return AuditEventResponse(
        id=uuid4(),
        actor_member_id=uuid4(),
        entity_type=kind,
        entity_id=identifier,
        action="update",
        request_id=None,
        before_version=1,
        after_version=2,
        occurred_at=datetime.now(UTC),
        changed_fields=["name"],
    )


@pytest.mark.database
def test_every_target_query_runs_and_missing_sources_have_no_link(db_engine):
    # Run every reviewed join, including rare refund/return/replacement targets, in PostgreSQL.
    actor = make_actor(db_engine)
    with Session(db_engine) as session:
        items = [event(kind, uuid4()) for kind in TARGETS]
        result = project_activity(session, actor.household_id, items, None)
        assert len(result.items) == len(TARGETS)
        assert all(row.target_name is None and row.target_path is None for row in result.items)


@pytest.mark.database
@pytest.mark.parametrize("path", PATHS)
def test_activity_current_names_links_household_actor_and_deleted_source(db_engine, path):
    actor = make_actor(db_engine)
    spouse = make_actor(db_engine, actor.household_id)
    foreign = make_actor(db_engine)
    with TestClient(application_with_activity(db_engine), base_url="https://testserver") as client:
        identifier = create(client, actor, path, "합성 공동 기록")
        other = create(client, foreign, path, "합성 다른 가계")
        response = client.get("/api/v1/activity-events", headers=spouse.headers)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        rows = response.json()["items"]
        row = next(row for row in rows if row["entity_id"] == identifier)
        assert row["actor_member_id"] == str(actor.member_id)
        assert row["target_name"] == "합성 공동 기록"
        assert row["target_path"].endswith(identifier)
        assert all(row["entity_id"] != other for row in rows)
        assert "합성 다른 가계" not in response.text
        assert all("safe_diff" not in row for row in rows)
        assert client.get("/api/v1/activity-events").status_code == 401
        assert (
            client.get(
                "/api/v1/activity-events",
                headers=actor.headers,
                params={"actor_member_id": str(foreign.member_id)},
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/api/v1/activity-events",
                headers=actor.headers,
                params={"actor_member_id": str(spouse.member_id)},
            ).json()["items"]
            == []
        )
        # Simulate a historical pointer with no current object. Do not fake a direct URL.
        with Session(db_engine) as session:
            session.execute(
                update(AuditEvent).where(AuditEvent.id == UUID(row["id"])).values(entity_id=uuid4())
            )
            session.commit()
        missing = client.get("/api/v1/activity-events", headers=actor.headers).json()["items"]
        old = next(item for item in missing if item["id"] == row["id"])
        assert old["target_name"] is None and old["target_path"] is None


@pytest.mark.database
def test_activity_filters_security_before_paging_and_binds_household_filters_and_view(db_engine):
    actor = make_actor(db_engine)
    foreign = make_actor(db_engine)
    app = application_with_activity(db_engine)
    with TestClient(app, base_url="https://testserver") as client:
        identifiers = [create(client, actor, "appliances", f"합성 가전 {i}") for i in range(5)]
        with Session(db_engine) as session:
            now = datetime.now(UTC)
            # Newer security-only records must not consume the first activity page.
            for i in range(5):
                session.add(
                    AuditEvent(
                        household_id=actor.household_id,
                        actor_id=actor.user_id,
                        entity_type="vault",
                        entity_id=uuid4(),
                        action="reveal",
                        before_version=None,
                        after_version=None,
                        safe_diff={"changed_fields": []},
                        occurred_at=now + timedelta(seconds=i),
                    )
                )
            session.commit()
        first = client.get("/api/v1/activity-events?limit=2", headers=actor.headers).json()
        assert len(first["items"]) == 2 and first["next_cursor"]
        assert all(row["entity_type"] == "appliance" for row in first["items"])
        seen = [row["entity_id"] for row in first["items"]]
        cursor = first["next_cursor"]
        for endpoint, auth, extra in [
            ("audit-events", actor, {}),
            ("activity-events", foreign, {}),
            ("activity-events", actor, {"actor_member_id": str(actor.member_id)}),
        ]:
            denied = client.get(
                f"/api/v1/{endpoint}", headers=auth.headers, params={"cursor": cursor, **extra}
            )
            assert denied.status_code == 400
        while cursor:
            page = client.get(
                "/api/v1/activity-events",
                headers=actor.headers,
                params={"limit": 2, "cursor": cursor},
            ).json()
            seen.extend(row["entity_id"] for row in page["items"])
            cursor = page["next_cursor"]
        assert len(seen) == len(set(seen)) == 5 and set(seen) == set(identifiers)
        assert (
            client.get(
                "/api/v1/activity-events",
                headers=actor.headers,
                params={"since": "2099-01-01T00:00:00Z"},
            ).json()["items"]
            == []
        )
        for params in ({"since": "2026-01-01"}, {"limit": 201}, {"entity_type": "unknown"}):
            assert (
                client.get(
                    "/api/v1/activity-events", headers=actor.headers, params=params
                ).status_code
                == 422
            )


@pytest.mark.database
def test_target_join_does_not_resolve_another_households_object(db_engine):
    actor = make_actor(db_engine)
    foreign = make_actor(db_engine)
    with TestClient(application_with_activity(db_engine), base_url="https://testserver") as client:
        identifier = create(client, foreign, "accounts", "합성 다른 가계 이름")
    with Session(db_engine) as session:
        result = project_activity(
            session, actor.household_id, [event("financial_account", UUID(identifier))], None
        )
        assert result.items[0].target_name is None and result.items[0].target_path is None


@pytest.mark.database
def test_spouse_update_resolves_current_name_but_keeps_original_actor_and_timestamp(db_engine):
    actor = make_actor(db_engine)
    spouse = make_actor(db_engine, actor.household_id)
    with TestClient(application_with_activity(db_engine), base_url="https://testserver") as client:
        identifier = create(client, actor, "appliances", "합성 이전 이름")
        changed = client.patch(
            f"/api/v1/appliances/{identifier}",
            headers=headers(spouse, version=1),
            json={"name": "합성 현재 이름", "note": "SYNTHETIC_PRIVATE_NOTE"},
        )
        assert changed.status_code == 200, changed.text
        response = client.get("/api/v1/activity-events", headers=actor.headers)
        rows = response.json()["items"]
        assert len(rows) == 2
        assert [row["actor_member_id"] for row in rows] == [
            str(spouse.member_id),
            str(actor.member_id),
        ]
        assert {row["target_name"] for row in rows} == {"합성 현재 이름"}
        assert "SYNTHETIC_PRIVATE_NOTE" not in response.text
        assert rows[0]["occurred_at"] >= rows[1]["occurred_at"]
        detail = client.get(f"/api/v1/appliances/{identifier}", headers=actor.headers).json()
        assert detail["updated_by_member_id"] == str(spouse.member_id)


@pytest.mark.database
def test_medical_activity_links_use_case_names_and_never_medical_prose(db_engine):
    from test_insurance_events import (
        allocation,
        money,
        new_case,
        new_expense,
        new_node,
        new_payout,
        new_policy,
    )

    from sallimbook.insurance.event_router import router as events

    actor = make_actor(db_engine)
    app = application_with_activity(db_engine)
    app.include_router(events)
    with TestClient(app, base_url="https://testserver") as client:
        case = new_case(client, actor)
        node = new_node(client, actor, case, note="SYNTHETIC_MEDICAL_PROSE")
        expense = new_expense(client, actor, case, node)
        refund = money(
            client,
            actor,
            f"/medical-expenses/{expense['id']}/refunds",
            {
                "amount_krw": "10",
                "occurred_on": "2026-01-31",
                "reason": "합성 환불",
            },
            version=expense["version"],
        )
        payout = new_payout(client, actor, [allocation(case["id"])])
        policy = new_policy(client, actor)
        linked = client.patch(
            f"/api/v1/insurance/payout-allocations/{payout['allocations'][0]['id']}",
            headers=headers(actor, version=1),
            json={"policy_id": policy["id"], "reason": "합성 연결 정정"},
        )
        assert linked.status_code == 200, linked.text
        response = client.get("/api/v1/activity-events", headers=actor.headers)
        assert response.status_code == 200, response.text
        assert "SYNTHETIC_MEDICAL_PROSE" not in response.text
        rows = {row["entity_type"]: row for row in response.json()["items"]}
        assert "cash_record" not in rows  # Domain events already identify the same medical money.
        for kind in ("medical_node", "medical_expense", "medical_refund", "payout_allocation"):
            assert rows[kind]["target_name"] == case["title"]
        assert (
            rows["medical_node"]["target_path"]
            == f"/insurance/cases/{case['id']}/nodes/{node['id']}"
        )
        assert rows["medical_expense"]["target_path"] == f"/insurance/expenses/{expense['id']}"
        assert rows["medical_refund"]["target_path"] == f"/insurance/refunds/{refund['id']}"
        assert rows["payout_allocation"]["target_path"] == f"/insurance/payouts/{payout['id']}"


@pytest.mark.database
def test_shared_stock_and_replacement_activity_keep_actual_sku_and_link(db_engine):
    from test_homecare_database import post_appliance, post_consumable, post_link, receipt, replace

    actor = make_actor(db_engine)
    with TestClient(application_with_activity(db_engine), base_url="https://testserver") as client:
        appliance = post_appliance(client, actor)
        stock = post_consumable(client, actor)
        link = post_link(client, actor, appliance, stock)
        receipt(client, actor, stock)
        replacement = replace(client, actor, link)
        response = client.get("/api/v1/activity-events", headers=actor.headers)
        assert response.status_code == 200, response.text
        rows = response.json()["items"]
        item = next(row for row in rows if row["entity_type"] == "consumable_replacement")
        assert item["target_name"] == stock["name"]
        assert (
            item["target_path"]
            == f"/appliance-consumables/{link['id']}/replacements/{replacement['replacement_id']}"
        )
        movement = next(row for row in rows if row["entity_type"] == "stock_movement")
        assert movement["target_name"] == stock["name"]
        assert (
            movement["target_path"] == f"/consumables/{stock['id']}/stock/{movement['entity_id']}"
        )
