"""Synthetic card metadata, cash-method links and household boundaries."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_accounts import create_account, make_actor

from sallimbook.accounts.router import router as account_router
from sallimbook.assets.router import router as asset_router
from sallimbook.cards.models import Card
from sallimbook.cards.router import router
from sallimbook.cards.schemas import CardCreate, CardPatch
from sallimbook.cashflow.models import CashRecord, CashRecordRevision
from sallimbook.cashflow.router import router as income_router
from sallimbook.cashflow.schemas import CashInput, IncomeInput, IncomeReturn
from sallimbook.cashflow.service import prepare_cash_record
from sallimbook.config import Settings
from sallimbook.core.audit import AuditEvent
from sallimbook.core.errors import DomainError
from sallimbook.core.http import install_http_contract
from sallimbook.core.types import SEOUL
from sallimbook.identity.router import router as identity_router
from sallimbook.identity.service import utcnow


def payload(actor=None, **changes):
    return {
        "owner_member_id": str(actor.member_id if actor else uuid4()),
        "issuer_name": "합성 카드사",
        "product_name": "합성 카드",
        "alias": "생활비",
        "card_type": "credit",
        "last_four": "0123",
        "settlement_day": 15,
        "started_on": "2025-01-01",
        **changes,
    }


@pytest.mark.parametrize(
    "field",
    ["pan", "card_number", "expiry", "expiry_month", "expiry_year", "cvc", "cvv", "ciphertext"],
)
def test_general_card_input_rejects_secret_fields(field):
    with pytest.raises(ValidationError):
        CardCreate.model_validate(payload(**{field: "synthetic-invalid-input"}))
    with pytest.raises(ValidationError):
        CardPatch.model_validate({field: "synthetic-invalid-input"})


@pytest.mark.parametrize(
    "changes",
    [
        {"last_four": "12345"},
        {"last_four": "１２３４"},
        {"last_four": 1234},
        {"settlement_day": 0},
        {"settlement_day": 32},
        {"settlement_day": True},
        {"settlement_day": "15"},
        {"ended_on": "2024-01-01"},
        {"issuer_name": " "},
        {"card_type": "unknown"},
    ],
)
def test_card_schema_rejects_invalid_mask_dates_and_terms(changes):
    with pytest.raises(ValidationError):
        CardCreate.model_validate(payload(**changes))


def test_card_openapi_nullability_headers_and_secret_free_response():
    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()
    patch = schema["components"]["schemas"]["CardPatch"]
    required = {"owner_member_id", "issuer_name", "product_name", "card_type"}
    for name, item in patch["properties"].items():
        assert name not in patch.get("required", [])
        assert any(t.get("type") == "null" for t in item.get("anyOf", [])) == (name not in required)
        if name in required:
            with pytest.raises(ValidationError):
                CardPatch.model_validate({name: None})
    assert CardPatch(settlement_account_id=None).model_dump(exclude_unset=True) == {
        "settlement_account_id": None
    }
    response = schema["components"]["schemas"]["CardResponse"]["properties"]
    assert (
        not {
            "pan",
            "card_number",
            "expiry",
            "expiry_month",
            "expiry_year",
            "cvc",
            "cvv",
            "ciphertext",
        }
        & response.keys()
    )
    assert not {"pan", "card_number", "cvc", "cvv", "expiry"} & set(Card.__table__.columns.keys())
    op = schema["paths"]["/api/v1/cards/{card_id}"]["patch"]
    assert next(p for p in op["parameters"] if p["name"] == "If-Match")["required"] is True
    assert "ETag" in op["responses"]["200"]["headers"]


def test_cash_methods_are_exclusive_and_income_cannot_choose_a_card():
    values = {"amount_krw": "1000", "period_month": "2026-01", "date_precision": "month"}
    with pytest.raises(ValidationError):
        CashInput(**values, account_id=uuid4(), card_id=uuid4())
    assert CashInput(**values, card_id=uuid4()).card_id is not None
    with pytest.raises(ValidationError):
        IncomeInput(**values, kind="salary", member_id=uuid4(), card_id=uuid4())
    with pytest.raises(ValidationError):
        IncomeReturn(**values, reason="합성 반환", card_id=uuid4())


@pytest.fixture
def actor(db_engine):
    return make_actor(db_engine)


@pytest.fixture
def app(db_engine):
    application = FastAPI()
    application.state.engine = db_engine
    application.state.settings = Settings(environment="test", _env_file=None)
    install_http_contract(application)
    for r in (identity_router, asset_router, account_router, income_router, router):
        application.include_router(r)
    return application


@pytest.fixture
def client(app):
    with TestClient(app, base_url="https://testserver") as value:
        yield value


def create_card(client, actor, **changes):
    response = client.post("/api/v1/cards", headers=actor.headers, json=payload(actor, **changes))
    assert response.status_code == 201
    assert response.headers["etag"] == '"1"'
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def version(actor, number=1):
    return {**actor.headers, "If-Match": f'"{number}"'}


def test_household_can_manage_both_owners_without_secret_metadata(client, actor, db_engine):
    spouse = make_actor(db_engine, actor.household_id)
    account = create_account(client, actor, account_number=None)
    card = create_card(
        client, actor, owner_member_id=str(spouse.member_id), settlement_account_id=account["id"]
    )
    assert card["owner_member_id"] == str(spouse.member_id)
    assert card["masked_number"] == "**** 0123" and card["settlement_account_status"] == "active"
    for who in (actor, spouse):
        result = client.get("/api/v1/cards/" + card["id"], headers=who.headers)
        assert result.status_code == 200 and result.json() == card
    changed = client.patch(
        "/api/v1/cards/" + card["id"], headers=version(spouse), json={"alias": "합성 변경"}
    )
    assert changed.status_code == 200 and changed.json()["version"] == 2
    stale = client.patch(
        "/api/v1/cards/" + card["id"], headers=version(actor), json={"alias": "덮어쓰기"}
    )
    assert stale.status_code == 409 and stale.json()["error"]["current_version"] == 2
    with Session(db_engine) as session:
        events = list(session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "card")))
        assert len(events) == 2 and all(set(e.safe_diff) == {"changed_fields"} for e in events)


def test_cross_household_ids_cannot_read_write_delete_or_link(client, actor, db_engine):
    other = make_actor(db_engine)
    card = create_card(client, actor)
    account = create_account(client, other, account_number=None)
    url = "/api/v1/cards/" + card["id"]
    assert client.get(url, headers=other.headers).status_code == 404
    assert client.patch(url, headers=version(other), json={"alias": "합성"}).status_code == 404
    assert client.delete(url, headers=version(other)).status_code == 404
    for change in (
        {"owner_member_id": str(other.member_id)},
        {"settlement_account_id": account["id"]},
    ):
        assert client.patch(url, headers=version(actor), json=change).status_code == 404
        assert (
            client.post(
                "/api/v1/cards", headers=actor.headers, json=payload(actor, **change)
            ).status_code
            == 404
        )
    assert (
        client.get(
            "/api/v1/cards", headers=actor.headers, params={"owner_member_id": str(other.member_id)}
        ).status_code
        == 404
    )
    assert client.get("/api/v1/cards", headers=other.headers).json()["items"] == []


def test_filters_pagination_missing_version_and_input_rejections(client, actor):
    for index in range(3):
        create_card(client, actor, card_type="debit" if index == 1 else "credit")
    first = client.get("/api/v1/cards?limit=1", headers=actor.headers).json()
    second = client.get(
        "/api/v1/cards", headers=actor.headers, params={"limit": 1, "cursor": first["next_cursor"]}
    ).json()
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert (
        len(client.get("/api/v1/cards?card_type=credit", headers=actor.headers).json()["items"])
        == 2
    )
    url = "/api/v1/cards/" + first["items"][0]["id"]
    assert (
        client.patch(url, headers=actor.headers, json={"alias": "합성"}).json()["error"]["code"]
        == "VERSION_REQUIRED"
    )
    assert client.get(url).status_code == 401
    assert (
        client.post(
            "/api/v1/cards", headers=actor.headers, json=payload(actor, cvc="synthetic-invalid")
        ).status_code
        == 422
    )
    future = (utcnow().astimezone(SEOUL).date() + timedelta(days=1)).isoformat()
    assert client.patch(url, headers=version(actor), json={"ended_on": future}).status_code == 422
    assert (
        client.patch(url, headers=version(actor), json={"ended_on": "2024-01-01"}).status_code
        == 422
    )


def test_closed_accounts_are_visible_but_cannot_be_new_active_card_links(client, actor):
    account = create_account(client, actor, account_number=None)
    card = create_card(client, actor, settlement_account_id=account["id"])
    close = client.post(
        "/api/v1/assets/" + account["asset_id"] + "/archive",
        headers=version(actor),
        json={"ended_on": "2026-01-31"},
    )
    assert close.status_code == 200
    got = client.get("/api/v1/cards/" + card["id"], headers=actor.headers).json()
    assert got["settlement_account_status"] == "closed" and got["status"] == "active"
    assert (
        client.post(
            "/api/v1/cards",
            headers=actor.headers,
            json=payload(actor, settlement_account_id=account["id"]),
        ).status_code
        == 422
    )
    historical = create_card(
        client, actor, settlement_account_id=account["id"], ended_on="2026-01-31"
    )
    assert historical["status"] == "closed"
    assert (
        client.patch(
            "/api/v1/cards/" + historical["id"], headers=version(actor), json={"ended_on": None}
        ).status_code
        == 422
    )
    corrected = client.patch(
        "/api/v1/cards/" + historical["id"],
        headers=version(actor),
        json={"ended_on": None, "settlement_account_id": None},
    )
    assert corrected.status_code == 200 and corrected.json()["status"] == "active"


def test_referenced_card_closes_without_erasing_cash_history(client, actor, db_engine):
    card = create_card(client, actor)
    with Session(db_engine) as session:
        cash = prepare_cash_record(
            session,
            actor.principal,
            CashInput(
                amount_krw="12000",
                period_month="2026-01",
                date_precision="day",
                occurred_on="2026-01-10",
                card_id=card["id"],
            ),
            kind="fixed_payment",
        )
        cash_id = cash.id
        session.commit()
    url = "/api/v1/cards/" + card["id"]
    blocked = client.delete(url, headers=version(actor))
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "CARD_IN_USE"
    archived = client.post(
        url + "/archive", headers=version(actor), json={"ended_on": "2026-01-31"}
    )
    assert archived.status_code == 200 and archived.json()["version"] == 2
    assert client.get("/api/v1/cards", headers=actor.headers).json()["items"] == []
    assert (
        client.get("/api/v1/cards?status=closed", headers=actor.headers).json()["items"][0]["id"]
        == card["id"]
    )
    with Session(db_engine) as session:
        row = session.get(CashRecord, cash_id)
        history = session.get(CashRecordRevision, (cash_id, 1))
        assert row.card_id == history.card_id == UUID(card["id"]) and int(row.amount_krw) == 12000
        with pytest.raises(DomainError) as unavailable:
            prepare_cash_record(
                session,
                actor.principal,
                CashInput(
                    amount_krw="1",
                    period_month="2026-02",
                    date_precision="month",
                    card_id=card["id"],
                ),
                kind="fixed_payment",
            )
        assert unavailable.value.code == "CARD_UNAVAILABLE"
    assert client.get("/api/v1/income/" + str(cash_id), headers=actor.headers).status_code == 404


def test_unreferenced_mistaken_card_can_be_deleted(client, actor):
    card = create_card(client, actor)
    assert client.delete("/api/v1/cards/" + card["id"], headers=version(actor)).status_code == 204
    assert client.get("/api/v1/cards/" + card["id"], headers=actor.headers).status_code == 404


def test_database_rejects_cross_household_card_owner_and_cash_method(client, actor, db_engine):
    other = make_actor(db_engine)
    card = create_card(client, actor)
    foreign = create_card(client, other)
    account = create_account(client, actor, account_number=None)
    with Session(db_engine) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                update(Card)
                .where(Card.id == UUID(card["id"]))
                .values(owner_member_id=other.member_id)
            )
            session.commit()
        session.rollback()
        cash = prepare_cash_record(
            session,
            actor.principal,
            CashInput(
                amount_krw="1", period_month="2026-01", date_precision="month", card_id=card["id"]
            ),
            kind="fixed_payment",
        )
        cash_id = cash.id
        session.commit()
        for change in (
            {"card_id": UUID(foreign["id"])},
            {"account_id": UUID(account["id"])},
            {"kind": "salary", "flow": "in", "member_id": actor.member_id},
        ):
            with pytest.raises(IntegrityError):
                session.execute(update(CashRecord).where(CashRecord.id == cash_id).values(**change))
                session.commit()
            session.rollback()


def test_parallel_card_updates_have_one_winner(app, client, actor):
    card = create_card(client, actor)
    barrier = Barrier(2)

    def update_alias(label):
        with TestClient(app, base_url="https://testserver") as peer:
            barrier.wait()
            return peer.patch(
                "/api/v1/cards/" + card["id"], headers=version(actor), json={"alias": label}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(update_alias, label) for label in ("합성 A", "합성 B")]
        assert sorted(f.result() for f in futures) == [200, 409]
