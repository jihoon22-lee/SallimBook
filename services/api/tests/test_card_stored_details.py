"""Synthetic direct card detail storage; secrets never appear in general responses."""

import json
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_accounts import key_file as key_file
from test_accounts import make_actor
from test_cards import actor as actor
from test_cards import app as app
from test_cards import create_card, version
from test_vault import initialize, write_secret

from sallimbook.accounts.crypto import KeyRing
from sallimbook.cards import stored_service
from sallimbook.cards.models import CardStoredDetails
from sallimbook.cards.router import router
from sallimbook.cards.schemas import CardStoredDetailsInput
from sallimbook.cards.stored_crypto import checksum_valid, decrypt_details, encrypt_details
from sallimbook.core.audit import AuditEvent
from sallimbook.core.errors import DomainError
from sallimbook.identity.auth_models import AuthSession, RegisteredDevice
from sallimbook.identity.service import utcnow
from sallimbook.vault.router import router as vault_router


def test_direct_details_contract_exists_without_step_up():
    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()
    path = "/api/v1/cards/{card_id}/stored-details"
    assert "put" in schema["paths"].get(path, {})
    assert "delete" in schema["paths"][path]
    reveal = schema["paths"][path + "/reveal"]["post"]
    assert "requestBody" not in reveal
    assert not any(p["name"] == "X-Step-Up-Token" for p in reveal.get("parameters", []))


PAN = "4000000000000002"  # Synthetic Luhn-valid fixture, never real card data.
DETAILS = {"pan": PAN, "expiry_year": 2030, "expiry_month": 3, "cvc": "001"}


@pytest.fixture
def client(app, key_file):
    app.state.settings.field_encryption_key_file = key_file
    app.include_router(vault_router)
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def path(card):
    return f"/api/v1/cards/{card['id']}/stored-details"


def put(client, actor, card, *, details=None, rev=1):
    return client.put(path(card), headers=version(actor, rev), json=details or DETAILS)


def reveal(client, actor, card):
    return client.post(path(card) + "/reveal", headers=actor.headers)


@pytest.mark.parametrize(
    "change",
    [
        {"pan": "１２３４５６７８９０１２３"},
        {"pan": "1" * 12},
        {"pan": "1" * 20},
        {"pan": 4000000000000002},
        {"pan": PAN + "\n"},
        {"cvc": "12"},
        {"cvc": "12345"},
        {"cvc": 123},
        {"cvc": "１２３"},
        {"expiry_year": 1999},
        {"expiry_year": 2200},
        {"expiry_month": 0},
        {"expiry_month": 13},
        {"expiry_month": True},
    ],
)
def test_sensitive_schema_rejects_invalid_input_without_echo(change):
    with pytest.raises(ValidationError) as exc:
        CardStoredDetailsInput(**(DETAILS | change))
    assert PAN not in str(exc.value)
    assert "input_value" not in str(exc.value)


def test_secret_repr_serialization_and_normalization():
    value = CardStoredDetailsInput(**(DETAILS | {"pan": "4000-0000 0000-0002"}))
    assert value.pan.get_secret_value() == PAN
    assert PAN not in repr(value) and "001" not in repr(value)
    assert PAN not in value.model_dump_json() and "001" not in value.model_dump_json()
    assert checksum_valid(PAN)
    assert not checksum_valid("4000000000000001")


@pytest.mark.parametrize("change", ["household", "card", "key_version", "nonce", "ciphertext"])
def test_aad_and_ciphertext_tampering_fail_closed(key_file, change):
    keyring = KeyRing.load(key_file)
    household, card = uuid4(), uuid4()
    sealed = encrypt_details(keyring, household, card, CardStoredDetailsInput(**DETAILS))
    assert len(sealed.ciphertext) == 144
    assert PAN.encode() not in sealed.ciphertext and PAN not in repr(sealed)
    assert decrypt_details(keyring, household, card, sealed).pan.get_secret_value() == PAN
    if change == "household":
        household = uuid4()
    elif change == "card":
        card = uuid4()
    elif change == "key_version":
        sealed = replace(sealed, key_version=2)
    elif change == "nonce":
        sealed = replace(sealed, nonce=bytes(12))
    else:
        sealed = replace(sealed, ciphertext=bytes(144))
    with pytest.raises(DomainError) as exc:
        decrypt_details(keyring, household, card, sealed)
    assert exc.value.code == "CARD_DETAILS_UNAVAILABLE"


def test_roundtrip_no_recent_login_masked_reads_and_ciphertext_only(client, actor, db_engine):
    card = create_card(client, actor)
    with Session(db_engine) as session:
        session.execute(
            update(AuthSession)
            .where(AuthSession.id == actor.principal.session_id)
            .values(authenticated_at=utcnow() - timedelta(days=1))
        )
        session.commit()
    saved = put(client, actor, card)
    assert saved.status_code == 200, saved.text
    assert saved.json()["has_stored_details"] and not saved.json()["has_secret"]
    assert saved.json()["last_four"] == PAN[-4:] and saved.json()["version"] == 2
    opened = reveal(client, actor, card)
    assert opened.status_code == 200, opened.text
    assert opened.json() == DETAILS | {
        "card_id": card["id"],
        "household_id": card["household_id"],
        "checksum_valid": True,
        "version": 2,
    }
    assert opened.headers["cache-control"] == "no-store"
    for response in [
        saved,
        client.get("/api/v1/cards", headers=actor.headers),
        client.get(f"/api/v1/cards/{card['id']}", headers=actor.headers),
    ]:
        assert PAN not in response.text
        assert '"cvc"' not in response.text
    with Session(db_engine) as session:
        stored = session.get(CardStoredDetails, (actor.household_id, UUID(card["id"])))
        assert stored and len(stored.ciphertext) == 144 and PAN.encode() not in stored.ciphertext
        audits = session.scalars(select(AuditEvent).where(AuditEvent.entity_id == UUID(card["id"])))
        for event in audits:
            assert PAN not in json.dumps(event.safe_diff)
            assert "001" not in json.dumps(event.safe_diff)


def test_nonblocking_checksum_conflict_full_replace_and_clear_cvc(client, actor, db_engine):
    card = create_card(client, actor)
    assert (
        put(client, actor, card, details=DETAILS | {"pan": "4000000000000001"}).status_code == 200
    )
    assert reveal(client, actor, card).json()["checksum_valid"] is False
    assert put(client, actor, card).status_code == 409
    assert put(client, actor, card, rev=2, details=DETAILS | {"cvc": None}).status_code == 200
    assert reveal(client, actor, card).json()["cvc"] is None
    patched = client.patch(
        f"/api/v1/cards/{card['id']}", headers=version(actor, 3), json={"last_four": "9999"}
    )
    assert patched.status_code == 409
    assert client.delete(path(card), headers=version(actor, 2)).status_code == 409
    assert client.delete(path(card), headers=version(actor, 3)).status_code == 204
    assert reveal(client, actor, card).status_code == 404
    assert not client.get(f"/api/v1/cards/{card['id']}", headers=actor.headers).json()[
        "has_stored_details"
    ]
    with Session(db_engine) as session:
        assert session.get(CardStoredDetails, (actor.household_id, UUID(card["id"]))) is None


def test_card_deletion_cascades_ciphertext(client, actor, db_engine):
    card = create_card(client, actor)
    assert put(client, actor, card).status_code == 200
    assert (
        client.delete(f"/api/v1/cards/{card['id']}", headers=version(actor, 2)).status_code == 204
    )
    with Session(db_engine) as session:
        assert session.get(CardStoredDetails, (actor.household_id, UUID(card["id"]))) is None


def test_household_isolation_and_shared_household_session(client, actor, db_engine):
    partner = make_actor(db_engine, actor.household_id)
    stranger = make_actor(db_engine)
    card = create_card(client, actor)
    assert put(client, actor, card).status_code == 200
    assert reveal(client, partner, card).json()["pan"] == PAN
    assert put(client, stranger, card, rev=2).status_code == 404
    assert reveal(client, stranger, card).status_code == 404
    assert client.delete(path(card), headers=version(stranger, 2)).status_code == 404
    assert client.post(path(card) + "/reveal").status_code == 401


@pytest.mark.parametrize("failure", ["expired", "revoked", "device"])
def test_locked_authentication_rejects_stale_principal(client, actor, db_engine, key_file, failure):
    card = create_card(client, actor)
    assert put(client, actor, card).status_code == 200
    with Session(db_engine) as session:
        if failure == "device":
            session.execute(
                update(RegisteredDevice)
                .where(RegisteredDevice.id == actor.principal.device_id)
                .values(revoked_at=utcnow(), status="revoked")
            )
        else:
            value = (
                {"expires_at": utcnow() - timedelta(seconds=1)}
                if failure == "expired"
                else {"revoked_at": utcnow()}
            )
            session.execute(
                update(AuthSession)
                .where(AuthSession.id == actor.principal.session_id)
                .values(**value)
            )
        session.commit()
    for operation in (
        lambda s: stored_service.reveal_details(s, actor.principal, UUID(card["id"]), key_file),
        lambda s: stored_service.put_details(
            s, actor.principal, UUID(card["id"]), CardStoredDetailsInput(**DETAILS), '"2"', key_file
        ),
        lambda s: stored_service.delete_details(s, actor.principal, UUID(card["id"]), '"2"'),
    ):
        with Session(db_engine) as session, pytest.raises(DomainError) as exc:
            operation(session)
        assert exc.value.status == 401
    assert reveal(client, actor, card).status_code == 401


def test_validation_and_missing_key_errors_never_log_secrets(client, actor, app, caplog):
    card = create_card(client, actor)
    invalid = put(client, actor, card, details=DETAILS | {"cvc": "001-secret"})
    assert (
        invalid.status_code == 422 and PAN not in invalid.text and "001-secret" not in invalid.text
    )
    app.state.settings.field_encryption_key_file = None
    unavailable = put(client, actor, card)
    assert unavailable.status_code == 503
    assert (
        PAN not in unavailable.text and PAN not in caplog.text and "001-secret" not in caplog.text
    )
    assert not client.get(f"/api/v1/cards/{card['id']}", headers=actor.headers).json()[
        "has_stored_details"
    ]


def test_client_vault_and_stored_details_mutually_exclusive(client, actor):
    initialize(client, actor)
    card = create_card(client, actor)
    assert write_secret(client, actor, card).status_code == 200
    assert put(client, actor, card, rev=2).status_code == 409
    other = create_card(client, actor)
    assert put(client, actor, other).status_code == 200
    assert write_secret(client, actor, other, version=2).status_code == 409
    assert reveal(client, actor, other).json()["pan"] == PAN


@pytest.mark.parametrize("operation", ["encrypt", "decrypt"])
def test_expiration_during_sensitive_work_rolls_back(
    client, actor, db_engine, monkeypatch, operation
):
    from sallimbook.identity import service as identity

    card = create_card(client, actor)
    if operation == "decrypt":
        assert put(client, actor, card).status_code == 200
    original = getattr(stored_service, f"{operation}_details")
    later = utcnow() + timedelta(days=7)

    def expire_after_work(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(identity, "utcnow", lambda: later)
        return result

    monkeypatch.setattr(stored_service, f"{operation}_details", expire_after_work)
    response = put(client, actor, card) if operation == "encrypt" else reveal(client, actor, card)
    assert response.status_code == 401
    assert PAN not in response.text
    with Session(db_engine) as session:
        stored = session.get(CardStoredDetails, (actor.household_id, UUID(card["id"])))
        assert (stored is None) == (operation == "encrypt")
        assert (
            session.scalar(
                select(AuditEvent).where(
                    AuditEvent.entity_id == UUID(card["id"]), AuditEvent.action == "reveal"
                )
            )
            is None
        )


def test_database_rejects_cross_household_detail_relation(client, actor, db_engine):
    from sqlalchemy.exc import IntegrityError

    card = create_card(client, actor)
    stranger = make_actor(db_engine)
    with Session(db_engine) as session, pytest.raises(IntegrityError):
        session.add(
            CardStoredDetails(
                household_id=stranger.household_id,
                card_id=UUID(card["id"]),
                key_version=1,
                nonce=bytes(12),
                ciphertext=bytes(144),
            )
        )
        session.commit()


def test_downgrade_preserves_populated_details_and_allows_empty_table(client, actor, db_engine):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect, text

    card = create_card(client, actor)
    assert put(client, actor, card).status_code == 200
    with db_engine.connect() as connection:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="Cannot downgrade while stored card details exist"):
            command.downgrade(config, "0024_income_planning")
        connection.rollback()
        assert inspect(connection).has_table("card_stored_details")
        assert connection.scalar(text("SELECT count(*) FROM card_stored_details")) == 1
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "0025_card_stored_details"
        )
    assert reveal(client, actor, card).json()["pan"] == PAN
    assert client.delete(path(card), headers=version(actor, 2)).status_code == 204
    with db_engine.connect() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0024_income_planning")
        assert not inspect(connection).has_table("card_stored_details")
        connection.commit()
        command.upgrade(config, "head")
        assert inspect(connection).has_table("card_stored_details")
