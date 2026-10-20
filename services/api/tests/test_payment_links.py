"""Synthetic payment impact, household boundaries and closure races."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session
from test_accounts import make_actor
from test_cards import create_card, version
from test_income import headers, make_account
from test_pagination import ids, pairs
from test_recurring import generate, post_rule, rule_payload, settle

from sallimbook.assets.router import router as asset_router
from sallimbook.assets.schemas import AssetArchive, AssetPatch
from sallimbook.cards.models import Card
from sallimbook.cards.router import router as card_router
from sallimbook.cards.schemas import CardArchive, CardPatch
from sallimbook.cashflow import payment_links
from sallimbook.cashflow.payment_link_router import router
from sallimbook.cashflow.recurring_models import ObligationRevision, RecurringRuleVersion
from sallimbook.cashflow.recurring_router import router as recurring_router
from sallimbook.cashflow.recurring_schemas import RuleCreate
from sallimbook.config import Settings
from sallimbook.core.audit import AuditEvent
from sallimbook.core.errors import DomainError
from sallimbook.core.http import install_http_contract


@pytest.mark.parametrize("schema", [CardPatch, CardArchive, AssetPatch, AssetArchive])
@pytest.mark.parametrize(
    "invalid",
    [
        {"closure_ack": "true"},
        {"closure_ack": 1},
        {"closure_ack": None},
        {"closure_ack": True},
        {"usage_digest": "a" * 64},
        {"closure_ack": True, "usage_digest": "A" * 64},
        {"closure_ack": True, "usage_digest": "a" * 63},
    ],
)
def test_closure_commands_are_strict_and_paired(schema, invalid):
    with pytest.raises(ValidationError):
        schema.model_validate({"ended_on": "2026-01-31", **invalid})


@pytest.mark.parametrize("schema", [CardPatch, AssetPatch])
def test_acknowledgment_requires_explicit_end_date_and_cannot_be_only_patch(schema):
    for invalid in (
        {"closure_ack": False},
        {"usage_digest": None},
        {"closure_ack": True, "usage_digest": "a" * 64},
        {"closure_ack": True, "usage_digest": "a" * 64, "ended_on": None},
    ):
        with pytest.raises(ValidationError):
            schema.model_validate(invalid)
    assert schema(ended_on="2026-01-31", closure_ack=True, usage_digest="a" * 64).closure_ack


def test_payment_link_contract_is_read_only_and_has_no_secret_fields():
    app = FastAPI()
    app.include_router(router)
    spec = app.openapi()
    for path, operations in spec["paths"].items():
        assert path.endswith("/payment-links") and set(operations) == {"get"}
        assert operations["get"]["operationId"] in {"getCardPaymentLinks", "getAccountPaymentLinks"}
    names = set().union(
        *(set(s.get("properties", {})) for s in spec["components"]["schemas"].values())
    )
    assert not names & {"account_number", "pan", "cvc", "cvv", "ciphertext", "note"}


@pytest.fixture
def setup(db_engine):
    actor = make_actor(db_engine)
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(environment="test", _env_file=None)
    install_http_contract(app)
    for item in (router, card_router, asset_router, recurring_router):
        app.include_router(item)
    return app, actor


def usage(client, actor, kind, identifier, **query):
    response = client.get(
        f"/api/v1/{kind}s/{identifier}/payment-links",
        headers=actor.headers,
        params={"as_of_date": "2026-01-31", **query},
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def link_pages(client, actor, kind, identifier, section):
    name = {"rules": "rule_cursor", "obligations": "obligation_cursor", "cards": "card_cursor"}
    pages, cursor = [], None
    while True:
        query = {"limit": 2} | ({name[section]: cursor} if cursor else {})
        value = usage(client, actor, kind, identifier, **query)[section]
        pages.append(value["items"])
        cursor = value["next_cursor"]
        if cursor is None:
            return pages
        assert cursor == value["items"][-1]["id"]


def closure_body(value, **changes):
    return {
        "ended_on": "2026-01-31",
        "closure_ack": True,
        "usage_digest": value["usage_digest"],
        **changes,
    }


@pytest.mark.database
class TestPaymentLinks:
    def test_link_pages_follow_dates_and_card_entry_order(self, setup, db_engine):
        app, actor = setup
        account = make_account(db_engine, actor)
        order = (3, 1, 4, 0, 2)
        with TestClient(app) as client:
            cards = [
                create_card(client, actor, settlement_account_id=str(account.id))["id"]
                for _ in range(5)
            ]
            starts = ["2026-03-01", "2026-02-01", "2026-03-01", "2026-01-01", "2026-02-01"]
            planned = [
                post_rule(client, actor, card_id=cards[0], effective_from=day)["id"]
                for day in starts
            ]
            anchors = ["2026-01-20", "2026-01-10", "2026-01-20", "2026-01-05", "2026-01-10"]
            due = [
                post_rule(client, actor, card_id=cards[1], anchor_date=day)["id"] for day in anchors
            ]
            for rule in due:
                generate(client, actor, rule, end="2026-01-31")
            rules = link_pages(client, actor, "card", cards[0], "rules")
            assert ids(rules, "rule_id") == pairs([planned[i] for i in order])
            obligations = link_pages(client, actor, "card", cards[1], "obligations")
            assert ids(obligations, "rule_id") == pairs([due[i] for i in order])
            linked = link_pages(client, actor, "account", account.id, "cards")
            assert ids(linked) == pairs(cards[::-1])
            stale = client.get(
                f"/api/v1/cards/{cards[0]}/payment-links",
                headers=actor.headers,
                params={"as_of_date": "2026-01-31", "rule_cursor": str(uuid4())},
            )
            assert stale.status_code == 404 and stale.json()["error"]["code"] == "NOT_FOUND"

    def test_direct_indirect_current_future_and_unpaid_are_separate(self, setup, db_engine):
        app, actor = setup
        account = make_account(db_engine, actor)
        with TestClient(app) as client:
            card = create_card(client, actor, settlement_account_id=str(account.id))
            direct = post_rule(client, actor, account_id=str(account.id))
            indirect = post_rule(client, actor, card_id=card["id"])
            future = post_rule(client, actor, card_id=card["id"], effective_from="2026-03-01")
            post_rule(
                client,
                actor,
                card_id=card["id"],
                effective_until="2026-01-20",
                end_reason="합성 종료",
            )
            for rule in (direct, indirect):
                generate(client, actor, rule["id"], end="2026-01-31")
            value = usage(client, actor, "account", account.id)
            assert value["resource_version"] == account.asset.version
            assert value["asset_id"] == str(account.asset_id)
            assert value["coverage"] == "registered_recurring_only"
            assert value["account_withdrawal_total_available"] is False
            assert value["requires_confirmation"] is True
            assert value["rules"]["total_count"] == 3
            assert {r["payment_basis"] for r in value["rules"]["items"]} == {
                "account_payment_plan",
                "card_approval_plan",
            }
            assert (
                next(r for r in value["rules"]["items"] if r["rule_id"] == future["id"])["period"]
                == "future"
            )
            assert value["obligations"]["total_count"] == 2
            assert all(r["status"] == "unpaid" for r in value["obligations"]["items"])
            assert value["cards"]["items"][0]["active_for_closure"] is True
            own = usage(client, actor, "card", card["id"])
            assert own["rules"]["total_count"] == 2 and own["cards"]["total_count"] == 0

    @pytest.mark.parametrize(
        "kind,archive", [("card", False), ("card", True), ("account", False), ("account", True)]
    )
    def test_patch_and_archive_require_fresh_confirmation_preserve_history(
        self,
        setup,
        db_engine,
        kind,
        archive,
    ):
        app, actor = setup
        account = make_account(db_engine, actor)
        with TestClient(app) as client:
            card = create_card(client, actor)
            identifier = card["id"] if kind == "card" else str(account.id)
            rule = post_rule(client, actor, **{f"{kind}_id": identifier})
            generate(client, actor, rule["id"], end="2026-01-31")
            old = usage(client, actor, kind, identifier)
            url = (
                f"/api/v1/cards/{identifier}"
                if kind == "card"
                else f"/api/v1/assets/{account.asset_id}"
            )
            method = client.post if archive else client.patch
            endpoint = url + ("/archive" if archive else "")
            denied = method(endpoint, headers=version(actor), json={"ended_on": "2026-01-31"})
            assert denied.status_code == 409
            assert denied.json()["error"]["code"] == "PAYMENT_LINK_CONFIRMATION_REQUIRED"
            assert (
                method(
                    endpoint, headers=version(actor), json=closure_body(old, ended_on="2026-02-01")
                ).json()["error"]["code"]
                == "PAYMENT_LINKS_CHANGED"
            )
            post_rule(client, actor, **{f"{kind}_id": identifier})
            stale = method(endpoint, headers=version(actor), json=closure_body(old))
            assert (
                stale.status_code == 409
                and stale.json()["error"]["code"] == "PAYMENT_LINKS_CHANGED"
            )
            current = usage(client, actor, kind, identifier)
            closed = method(endpoint, headers=version(actor), json=closure_body(current))
            assert closed.status_code == 200, closed.text
            assert closed.json()["version"] == 2
            # Ordinary metadata edits on an already closed source need no confirmation.
            edited = client.patch(
                url,
                headers=version(actor, 2),
                json={"alias": "종료 후 이름"} if kind == "card" else {"name": "종료 후 이름"},
            )
            assert edited.status_code == 200, edited.text
            rejected = client.post(
                "/api/v1/recurring-rules",
                headers=headers(actor),
                json=rule_payload() | {f"{kind}_id": identifier},
            )
            assert rejected.status_code == 422
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(RecurringRuleVersion)) == 2
            assert session.scalar(select(func.count()).select_from(ObligationRevision)) == 1
            entity_id = UUID(identifier) if kind == "card" else account.asset_id
            logs = session.scalars(select(AuditEvent).where(AuditEvent.entity_id == entity_id))
            assert all(
                not set(log.safe_diff["changed_fields"]) & {"closure_ack", "usage_digest"}
                for log in logs
            )

    def test_pagination_digest_covers_all_links_and_changes_after_payment(self, setup):
        app, actor = setup
        with TestClient(app) as client:
            card = create_card(client, actor)
            for _ in range(3):
                rule = post_rule(client, actor, card_id=card["id"])
                generate(client, actor, rule["id"], end="2026-01-31")
            first = usage(client, actor, "card", card["id"], limit=1)
            second = usage(
                client,
                actor,
                "card",
                card["id"],
                limit=1,
                rule_cursor=first["rules"]["next_cursor"],
                obligation_cursor=first["obligations"]["next_cursor"],
            )
            assert first["usage_digest"] == second["usage_digest"]
            assert first["rules"]["items"][0]["id"] != second["rules"]["items"][0]["id"]
            assert first["rules"]["total_count"] == second["rules"]["total_count"] == 3
            item = second["obligations"]["items"][0]
            settle(client, actor, item, amount="100", card_id=card["id"])
            current = usage(client, actor, "card", card["id"])
            assert current["usage_digest"] != first["usage_digest"]
            partial = next(r for r in current["obligations"]["items"] if r["id"] == item["id"])
            assert partial["status"] == "partial" and partial["actual_paid_krw"] == "100"
            settle(client, actor, partial, amount="32900", card_id=card["id"])
            assert usage(client, actor, "card", card["id"])["obligations"]["total_count"] == 2

    def test_unknown_and_zero_estimates_remain_distinct_until_explicit_resolution(self, setup):
        app, actor = setup
        with TestClient(app) as client:
            card = create_card(client, actor)
            unknown = post_rule(
                client, actor, card_id=card["id"], amount_mode="variable", expected_amount_krw=None
            )
            zero = post_rule(client, actor, card_id=card["id"], expected_amount_krw="0")
            for rule in (unknown, zero):
                generate(client, actor, rule["id"], end="2026-01-31")
            items = usage(client, actor, "card", card["id"])["obligations"]["items"]
            variable = next(row for row in items if row["rule_id"] == unknown["id"])
            free = next(row for row in items if row["rule_id"] == zero["id"])
            assert variable["expected_amount_krw"] is None
            assert free["expected_amount_krw"] == "0"
            assert variable["status"] == free["status"] == "unpaid"
            settle(client, actor, variable, amount="100", card_id=card["id"])
            current = usage(client, actor, "card", card["id"])
            partial = next(
                row for row in current["obligations"]["items"] if row["id"] == variable["id"]
            )
            assert partial["status"] == "partial" and partial["expected_amount_krw"] is None
            for row, action in ((partial, "complete"), (free, "skip")):
                result = client.post(
                    f"/api/v1/obligations/{row['id']}/{action}",
                    headers=headers(actor, version=row["version"]),
                    json={"reason": "합성 확인"},
                )
                assert result.status_code == 200, result.text
            resolved = usage(client, actor, "card", card["id"])
            assert resolved["obligations"]["total_count"] == 0
            assert resolved["usage_digest"] != current["usage_digest"]
            assert resolved["requires_confirmation"] is True  # Future recurrence still linked.

    def test_foreign_ids_and_bad_queries_fail(self, setup, db_engine):
        app, actor = setup
        outsider = make_actor(db_engine)
        account = make_account(db_engine, actor)
        with TestClient(app) as client:
            card = create_card(client, actor)
            for kind, identifier in (("card", card["id"]), ("account", account.id)):
                path = f"/api/v1/{kind}s/{identifier}/payment-links"
                assert client.get(path, headers=outsider.headers).status_code == 404
                assert client.get(path).status_code == 401
                for query in (
                    "limit=201",
                    "limit=0",
                    "as_of_date=2026-01-01T00:00:00",
                    "rule_cursor=bad",
                    "obligation_cursor=bad",
                    "card_cursor=bad",
                ):
                    assert client.get(path + "?" + query, headers=actor.headers).status_code == 422
                assert (
                    client.get(
                        f"/api/v1/{kind}s/{uuid4()}/payment-links", headers=actor.headers
                    ).status_code
                    == 404
                )

    def test_closed_historical_card_alone_does_not_require_ack(self, setup, db_engine):
        app, actor = setup
        account = make_account(db_engine, actor)
        with TestClient(app) as client:
            create_card(client, actor, settlement_account_id=str(account.id), ended_on="2026-01-01")
            value = usage(client, actor, "account", account.id)
            assert value["cards"]["total_count"] == 1
            assert value["cards"]["items"][0]["active_for_closure"] is False
            assert value["requires_confirmation"] is False
            response = client.post(
                f"/api/v1/assets/{account.asset_id}/archive",
                headers=version(actor),
                json={"ended_on": "2026-01-31"},
            )
            assert response.status_code == 200

    def test_query_count_is_constant_when_link_count_grows(self, setup, db_engine):
        app, actor = setup
        account = make_account(db_engine, actor)
        with TestClient(app) as client:
            counts = []
            for count in (1, 4):
                for _ in range(count):
                    card = create_card(client, actor, settlement_account_id=str(account.id))
                    rule = post_rule(client, actor, card_id=card["id"])
                    generate(client, actor, rule["id"], end="2026-01-31")
                queries = []

                def captured(
                    conn, cursor, statement, parameters, context, executemany, queries=queries
                ):
                    if statement.startswith("SELECT"):
                        queries.append(statement)

                event.listen(db_engine, "before_cursor_execute", captured)
                try:
                    usage(client, actor, "account", account.id)
                finally:
                    event.remove(db_engine, "before_cursor_execute", captured)
                counts.append(len(queries))
            assert counts[0] == counts[1]

    def test_closure_lock_blocks_concurrent_new_rule_until_closed(
        self, setup, db_engine, monkeypatch
    ):
        app, actor = setup
        with TestClient(app) as client:
            card = create_card(client, actor)
        entered, release, writer_started = Event(), Event(), Event()
        original = payment_links.usage
        blocker_pid = []
        writer_pid = []

        def pause_usage(session, principal, kind, resource_id, **kwargs):
            result = original(session, principal, kind, resource_id, **kwargs)
            blocker_pid.append(session.scalar(text("select pg_backend_pid()")))
            entered.set()
            assert release.wait(10)
            return result

        monkeypatch.setattr(payment_links, "usage", pause_usage)
        from sallimbook.cashflow import recurring_service

        original_lock = recurring_service.cash.lock_cash_household

        def capture_writer(session, principal):
            writer_pid.append(session.scalar(text("select pg_backend_pid()")))
            writer_started.set()
            return original_lock(session, principal)

        monkeypatch.setattr(recurring_service.cash, "lock_cash_household", capture_writer)

        def close():
            with TestClient(app) as client:
                return client.post(
                    f"/api/v1/cards/{card['id']}/archive",
                    headers=version(actor),
                    json={"ended_on": "2026-01-31"},
                )

        def create():
            with Session(db_engine) as session:
                try:
                    return recurring_service.create_rule(
                        session,
                        actor.principal,
                        RuleCreate(**rule_payload(card_id=card["id"])),
                        str(uuid4()),
                    )
                except DomainError as error:
                    return error

        with ThreadPoolExecutor(max_workers=2) as pool:
            closer = pool.submit(close)
            try:
                assert entered.wait(10)
                writer = pool.submit(create)
                assert writer_started.wait(10)
                with Session(db_engine) as session:
                    for _ in range(200):
                        blockers = session.scalar(
                            text("select pg_blocking_pids(:pid)"), {"pid": writer_pid[0]}
                        )
                        if blocker_pid[0] in blockers:
                            break
                        session.execute(text("select pg_sleep(0.01)"))
                    assert blocker_pid[0] in blockers
            finally:
                release.set()
            assert closer.result(timeout=10).status_code == 200
            assert writer.result(timeout=10).code == "CARD_UNAVAILABLE"
        with Session(db_engine) as session:
            assert session.get(Card, UUID(card["id"])).ended_on == date(2026, 1, 31)
            assert session.scalar(select(func.count()).select_from(RecurringRuleVersion)) == 0
