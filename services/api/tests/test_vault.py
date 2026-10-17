"""Real PostgreSQL/auth vault lifecycle; opaque patterns are not encryption proofs."""

import base64
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import timedelta
from threading import Event
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_accounts import make_actor
from test_income import headers
from test_passkeys import NATIVE_ORIGIN, NATIVE_POLICY, SyntheticAuthenticator
from webauthn.helpers import base64url_to_bytes

from sallimbook.cards.router import router as card_router
from sallimbook.config import Settings
from sallimbook.core.audit import AuditEvent
from sallimbook.core.http import install_http_contract
from sallimbook.core.idempotency import IdempotencyRecord
from sallimbook.identity import service as identity
from sallimbook.identity.auth_models import AuthSession
from sallimbook.identity.passkeys import service as passkeys
from sallimbook.identity.passkeys.models import StepUpPurpose
from sallimbook.identity.passkeys.schemas import (
    AssertionVerification,
    RegisterOptionsRequest,
    RegisterVerification,
    StepUpOptionsRequest,
)
from sallimbook.vault import service
from sallimbook.vault.models import (
    CardSecretEnvelope,
    VaultMemberWrapping,
    VaultNonceReservation,
    VaultShareOffer,
    VaultVersion,
)
from sallimbook.vault.router import router

pytestmark = pytest.mark.database


def opaque(size, seed):
    # Public counters deliberately do not represent real keys or encrypted secrets.
    value = seed.to_bytes(8, "big")
    raw = (value * ((size + 7) // 8))[:size]
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def member_wrap(actor, *, key_version=1, generation=1, seed=1):
    return {
        "format_version": 1,
        "key_version": key_version,
        "member_id": str(actor.member_id),
        "generation": generation,
        "kdf": "PBKDF2-HMAC-SHA256",
        "iterations": 600_000,
        "salt": opaque(16, seed),
        "nonce": opaque(12, seed),
        "wrapped_hvk": opaque(48, seed),
    }


def recovery_wrap(*, key_version=1, generation=1, seed=2):
    return {
        "format_version": 1,
        "key_version": key_version,
        "generation": generation,
        "kdf": "HKDF-SHA256",
        "salt": opaque(16, seed),
        "nonce": opaque(12, seed),
        "wrapped_hvk": opaque(48, seed),
    }


def key_check(*, key_version=1, seed=3):
    return {
        "format_version": 1,
        "key_version": key_version,
        "nonce": opaque(12, seed),
        "ciphertext": opaque(45, seed),
    }


def card_secret(*, key_version=1, seed=20, last_four="0000"):
    return {
        "format_version": 1,
        "key_version": key_version,
        "payload_schema_version": 1,
        "nonce": opaque(12, seed),
        "ciphertext": opaque(43, seed),
        "last_four": last_four,
    }


def initial_payload(actor):
    return {
        "key_check": key_check(),
        "member_wrapping": member_wrap(actor),
        "recovery_wrapping": recovery_wrap(),
    }


def step_up(session, actor, purpose, target):
    authenticator = SyntheticAuthenticator.create()
    options = passkeys.registration_options(
        session, actor.principal, RegisterOptionsRequest(label="합성 보관함 패스키"), NATIVE_POLICY
    )
    passkeys.register_credential(
        session,
        actor.principal,
        RegisterVerification(
            challenge_id=options.challenge_id,
            credential=authenticator.registration(
                base64url_to_bytes(options.public_key["challenge"]), origin=NATIVE_ORIGIN
            ),
        ),
        NATIVE_POLICY,
    )
    options = passkeys.step_up_options(
        session,
        actor.principal,
        StepUpOptionsRequest(purpose=purpose, target_id=target),
        NATIVE_POLICY,
    )
    return passkeys.verify_step_up(
        session,
        actor.principal,
        AssertionVerification(
            challenge_id=options.challenge_id,
            credential=authenticator.assertion(
                base64url_to_bytes(options.public_key["challenge"]),
                actor.user_id,
                origin=NATIVE_ORIGIN,
            ),
        ),
        NATIVE_POLICY,
    )


@pytest.fixture
def actors(db_engine):
    first = make_actor(db_engine)
    return first, make_actor(db_engine, first.household_id), make_actor(db_engine)


@pytest.fixture
def vault_app(db_engine):
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(environment="test", _env_file=None)
    install_http_contract(app)
    app.include_router(card_router)
    app.include_router(router)
    return app


def status(client, actor):
    response = client.get("/api/v1/vault/status", headers=actor.headers)
    assert response.status_code == 200, response.text
    return response.json()


def initialize(client, actor, *, key=None):
    response = client.post(
        "/api/v1/vault/initialize", json=initial_payload(actor), headers=headers(actor, key)
    )
    assert response.status_code == 201, response.text
    return response.json()


def card(client, actor, *, archived=False):
    response = client.post(
        "/api/v1/cards",
        headers=actor.headers,
        json={
            "owner_member_id": str(actor.member_id),
            "issuer_name": "합성 카드사",
            "product_name": "합성 카드",
            "card_type": "credit",
            "ended_on": "2025-01-01" if archived else None,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def card_detail(client, actor, card_id):
    response = client.get(f"/api/v1/cards/{card_id}", headers=actor.headers)
    assert response.status_code == 200, response.text
    return response.json()


def write_secret(client, actor, row, *, payload=None, key=None, version=None):
    return client.put(
        f"/api/v1/cards/{row['id']}/secret-envelope",
        json=payload or card_secret(),
        headers=headers(actor, key, version or row["version"]),
    )


def own_wrap(client, actor):
    response = client.get("/api/v1/vault/wrappings/me", headers=actor.headers)
    assert response.status_code == 200, response.text
    return response.json()["wrapping"]


def share(client, source, target, *, seed=10, key=None):
    current = status(client, source)
    member = next(row for row in current["members"] if row["member_id"] == str(target.member_id))
    response = client.post(
        "/api/v1/vault/shares",
        headers=headers(source, key, current["version"]),
        json={
            "wrapping": member_wrap(
                target,
                key_version=current["current_key_version"],
                seed=seed,
                generation=member["next_wrapping_generation"],
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def accept(client, actor, offer, *, key=None):
    response = client.post(
        f"/api/v1/vault/shares/{offer['id']}/accept",
        headers=headers(actor, key, offer["version"]),
        json={
            "key_version": status(client, actor)["current_key_version"],
            "key_check_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def start_rotation(client, actor, *, key=None):
    response = client.post(
        "/api/v1/vault/rotations",
        json={"reason": "routine"},
        headers=headers(actor, key, status(client, actor)["version"]),
    )
    assert response.status_code == 201, response.text
    return rotation_detail(client, actor, response.json()["id"])


def rotation_detail(client, actor, rotation_id):
    response = client.get(f"/api/v1/vault/rotations/{rotation_id}", headers=actor.headers)
    assert response.status_code == 200, response.text
    return response.json()


def prepare(client, actor, rotation, members, *, seed=100):
    key_version = rotation["key_version"]
    response = client.post(
        f"/api/v1/vault/rotations/{rotation['id']}/prepare",
        headers=headers(actor, version=rotation["version"]),
        json={
            "key_check": key_check(key_version=key_version, seed=seed),
            "member_wrappings": [
                member_wrap(
                    member,
                    key_version=key_version,
                    seed=seed + 1 + i,
                )
                for i, member in enumerate(members)
            ],
            "recovery_wrapping": recovery_wrap(
                key_version=key_version,
                seed=seed + 10,
            ),
        },
    )
    assert response.status_code == 200, response.text
    return rotation_detail(client, actor, rotation["id"])


def stage(client, actor, rotation, target, *, seed=120):
    response = client.put(
        f"/api/v1/vault/rotations/{rotation['id']}/cards/{target['card_id']}",
        headers=headers(actor, version=rotation["version"]),
        json={
            "source_envelope_id": target["source_envelope_id"],
            "source_revision": target["source_revision"],
            "envelope": card_secret(
                key_version=rotation["key_version"], seed=seed, last_four=target["last_four"]
            ),
        },
    )
    assert response.status_code == 200, response.text
    return rotation_detail(client, actor, rotation["id"])


def finalize(client, actor, rotation, *, key=None):
    return client.post(
        f"/api/v1/vault/rotations/{rotation['id']}/finalize",
        headers=headers(actor, key, rotation["version"]),
        json={
            "key_version": rotation["key_version"],
            "key_check_confirmed": True,
        },
    )


def test_initialize_card_envelope_and_masked_metadata(vault_app, actors):
    first, partner, _ = actors
    with TestClient(vault_app) as client:
        assert not status(client, first)["initialized"]
        reference = initialize(client, first, key="initialize-once")
        assert initialize(client, first, key="initialize-once") == reference
        current = status(client, first)
        assert current["own_membership"] == "active" and current["current_key_version"] == 1
        assert status(client, partner)["own_membership"] == "not_enrolled"
        row = card(client, first)
        assert row["has_secret"] is False
        saved = write_secret(client, first, row, key="save-once")
        assert saved.status_code == 200, saved.text
        assert write_secret(client, first, row, key="save-once").json() == saved.json()
        metadata = card_detail(client, partner, row["id"])
        assert metadata["has_secret"] and metadata["last_four"] == "0000"
        assert not {"ciphertext", "nonce", "wrapped_hvk", "pan", "expiry"} & metadata.keys()
        read = client.get(f"/api/v1/cards/{row['id']}/secret-envelope", headers=first.headers)
        assert read.status_code == 200 and read.json()["ciphertext"] == card_secret()["ciphertext"]
        assert read.headers["cache-control"] == "no-store" and read.headers["pragma"] == "no-cache"
        assert read.headers["etag"] == f'"{saved.json()["version"]}"'
        assert own_wrap(client, first)["member_id"] == str(first.member_id)
        changed = client.patch(
            f"/api/v1/cards/{row['id']}",
            json={"last_four": "1111"},
            headers=headers(first, version=metadata["version"]),
        )
        assert changed.status_code == 409
        assert changed.json()["error"]["code"] == "CARD_SECRET_PROTECTED"
        deleted = client.delete(
            f"/api/v1/cards/{row['id']}", headers=headers(first, version=metadata["version"])
        )
        assert deleted.status_code == 409
    with Session(vault_app.state.engine) as session:
        events = list(session.scalars(select(AuditEvent)))
        assert events and all(set(event.safe_diff) == {"changed_fields"} for event in events)
        assert all(opaque(43, 20) not in str(event.safe_diff) for event in events)
        record = session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.key == "save-once")
        )
        assert record.resource_type == "card" and record.resource_version == saved.json()["version"]


def test_unshared_and_foreign_household_cannot_fetch_opaque_data(vault_app, actors):
    first, partner, foreign = actors
    with TestClient(vault_app) as client:
        initialize(client, first)
        initialize(client, foreign)
        row = card(client, first)
        assert write_secret(client, first, row).status_code == 200
        for path in [
            "/vault/wrappings/me",
            "/vault/recovery-wrap",
            f"/cards/{row['id']}/secret-envelope",
        ]:
            denied = client.get("/api/v1" + path, headers=partner.headers)
            assert denied.status_code == 403 and "ciphertext" not in denied.text
        assert (
            client.get(
                f"/api/v1/cards/{row['id']}/secret-envelope", headers=foreign.headers
            ).status_code
            == 404
        )
        assert write_secret(client, foreign, row).status_code == 404
        assert (
            client.delete(
                f"/api/v1/cards/{row['id']}/secret-envelope", headers=headers(foreign, version=1)
            ).status_code
            == 404
        )
        assert client.get("/api/v1/vault/wrappings/me").status_code == 401
        assert client.get("/api/v1/vault/shares", headers=foreign.headers).json()["items"] == []


def test_share_requires_recipient_auth_and_explicit_acceptance(vault_app, actors):
    first, partner, foreign = actors
    with TestClient(vault_app) as client:
        initialize(client, first)
        offer = share(client, first, partner)
        path = f"/api/v1/vault/shares/{offer['id']}"
        assert client.get(path + "/wrapping", headers=first.headers).status_code == 403
        assert client.get(path + "/wrapping", headers=foreign.headers).status_code in {404, 409}
        pending = client.get(path + "/wrapping", headers=partner.headers)
        assert pending.status_code == 200, pending.text
        assert pending.json()["wrapping"]["member_id"] == str(partner.member_id)
        assert client.get("/api/v1/vault/wrappings/me", headers=partner.headers).status_code == 403
        for actor, body, expected in [
            (first, {"key_version": 1, "key_check_confirmed": True}, 403),
            (partner, {"key_version": 1, "key_check_confirmed": False}, 422),
            (partner, {"key_version": 2, "key_check_confirmed": True}, 409),
        ]:
            response = client.post(
                path + "/accept", json=body, headers=headers(actor, version=offer["version"])
            )
            assert response.status_code == expected
        accepted = accept(client, partner, offer, key="accept-once")
        assert accept(client, partner, offer, key="accept-once") == accepted
        assert status(client, partner)["own_membership"] == "active"
        assert (
            own_wrap(client, partner)["wrapped_hvk"] == member_wrap(partner, seed=10)["wrapped_hvk"]
        )
        assert own_wrap(client, first)["wrapped_hvk"] != own_wrap(client, partner)["wrapped_hvk"]


def test_expired_share_reissue_advances_generation_and_keeps_nonce(vault_app, actors, monkeypatch):
    first, partner, _ = actors
    monkeypatch.setattr(service, "SHARE_LIFETIME", timedelta(microseconds=1))
    with TestClient(vault_app) as client:
        initialize(client, first)
        expired = share(client, first, partner)
        assert (
            client.get(
                f"/api/v1/vault/shares/{expired['id']}/wrapping", headers=partner.headers
            ).status_code
            == 409
        )
        monkeypatch.setattr(service, "SHARE_LIFETIME", timedelta(minutes=15))
        replacement = share(client, first, partner, seed=11)
        wrapping = client.get(
            f"/api/v1/vault/shares/{replacement['id']}/wrapping", headers=partner.headers
        ).json()["wrapping"]
        assert wrapping["generation"] == 2
        accept(client, partner, replacement)
    with Session(vault_app.state.engine) as session:
        assert session.get(VaultShareOffer, UUID(expired["id"])).state == "expired"
        assert (
            len(
                list(
                    session.scalars(
                        select(VaultMemberWrapping).where(
                            VaultMemberWrapping.member_id == partner.member_id,
                        )
                    )
                )
            )
            == 2
        )


def test_password_rewrap_only_changes_own_wrapping_and_rejects_nonce_or_salt_reuse(
    vault_app, actors
):
    first, partner, _ = actors
    with TestClient(vault_app) as client:
        initialize(client, first)
        accept(client, partner, share(client, first, partner))
        original = own_wrap(client, first)
        partner_original = own_wrap(client, partner)
        payload = {
            "wrapping": member_wrap(first, generation=2, seed=30),
            "key_check_confirmed": True,
        }
        result = client.put(
            "/api/v1/vault/wrappings/me",
            json=payload,
            headers=headers(first, "rewrap-once", original["version"]),
        )
        assert result.status_code == 200, result.text
        assert own_wrap(client, partner) == partner_original
        assert (
            client.put(
                "/api/v1/vault/wrappings/me",
                json=payload,
                headers=headers(first, "rewrap-once", original["version"]),
            ).json()
            == result.json()
        )
        for changed, code in [
            ({"nonce": original["nonce"]}, "VAULT_NONCE_REUSED"),
            ({"salt": original["salt"]}, "VAULT_SALT_REUSED"),
        ]:
            bad = {
                "wrapping": member_wrap(first, generation=3, seed=31) | changed,
                "key_check_confirmed": True,
            }
            response = client.put(
                "/api/v1/vault/wrappings/me",
                json=bad,
                headers=headers(first, version=own_wrap(client, first)["version"]),
            )
            assert response.status_code == 409 and response.json()["error"]["code"] == code
        assert own_wrap(client, first)["generation"] == 2


def test_recovery_is_atomic_and_never_accepts_recovery_code(vault_app, actors):
    first = actors[0]
    with TestClient(vault_app) as client:
        initialize(client, first)
        original = own_wrap(client, first)
        recovery_original = client.get("/api/v1/vault/recovery-wrap", headers=first.headers).json()
        payload = {
            "member_wrapping": member_wrap(first, generation=2, seed=40),
            "recovery_wrapping": recovery_wrap(generation=2, seed=41),
            "key_check_confirmed": True,
        }
        bad = payload | {
            "recovery_wrapping": payload["recovery_wrapping"] | {"nonce": opaque(12, 3)}
        }
        response = client.post(
            "/api/v1/vault/recover",
            json=bad,
            headers=headers(first, version=status(client, first)["version"]),
        )
        assert response.status_code == 409
        assert own_wrap(client, first) == original
        assert (
            client.get("/api/v1/vault/recovery-wrap", headers=first.headers).json()
            == recovery_original
        )
        supplied_code = client.post(
            "/api/v1/vault/recover",
            json=payload | {"recovery_code": "PUBLIC TEST"},
            headers=headers(first, version=status(client, first)["version"]),
        )
        assert supplied_code.status_code == 422 and "PUBLIC TEST" not in supplied_code.text
        success = client.post(
            "/api/v1/vault/recover",
            json=payload,
            headers=headers(first, version=status(client, first)["version"]),
        )
        assert success.status_code == 200, success.text
        assert own_wrap(client, first)["generation"] == 2
        assert (
            client.get("/api/v1/vault/recovery-wrap", headers=first.headers).json()["wrapping"][
                "generation"
            ]
            == 2
        )


def test_management_requires_recent_account_authentication(vault_app, actors):
    first = actors[0]
    with TestClient(vault_app) as client:
        initialize(client, first)
        with Session(vault_app.state.engine) as session:
            auth = session.get(AuthSession, first.principal.session_id)
            auth.authenticated_at = identity.utcnow() - timedelta(minutes=6)
            session.commit()
        assert client.get("/api/v1/vault/wrappings/me", headers=first.headers).status_code == 200
        assert client.get("/api/v1/vault/recovery-wrap", headers=first.headers).status_code == 403
        response = client.post(
            "/api/v1/vault/rotations",
            json={"reason": "routine"},
            headers=headers(first, version=status(client, first)["version"]),
        )
        assert response.status_code == 403


def test_nonce_is_unique_across_crypto_purposes(vault_app, actors):
    first = actors[0]
    with TestClient(vault_app) as client:
        initialize(client, first)
        row = card(client, first)
        response = write_secret(client, first, row, payload=card_secret(seed=3))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "VAULT_NONCE_REUSED"
        assert card_detail(client, first, row["id"])["has_secret"] is False


def test_empty_card_rotation_still_requires_both_new_member_wraps(vault_app, actors):
    first, partner, _ = actors
    with TestClient(vault_app) as client:
        initialize(client, first)
        accept(client, partner, share(client, first, partner))
        rotation = start_rotation(client, first)
        assert rotation["cards"] == [] and len(rotation["members"]) == 2
        partial = client.post(
            f"/api/v1/vault/rotations/{rotation['id']}/prepare",
            headers=headers(first, version=rotation["version"]),
            json={
                "key_check": key_check(key_version=2, seed=100),
                "member_wrappings": [member_wrap(first, key_version=2, seed=101)],
                "recovery_wrapping": recovery_wrap(key_version=2, seed=110),
            },
        )
        assert partial.status_code == 409
        assert status(client, first)["current_key_version"] == 1
        rotation = prepare(client, first, rotation, [first, partner])
        assert own_wrap(client, first)["key_version"] == 1
        staged = client.get(
            f"/api/v1/vault/rotations/{rotation['id']}/wrappings/me", headers=partner.headers
        )
        assert staged.status_code == 200 and staged.json()["wrapping"]["key_version"] == 2
        result = finalize(client, first, rotation, key="finalize-once")
        assert result.status_code == 200, result.text
        assert finalize(client, first, rotation, key="finalize-once").json() == result.json()
        assert status(client, first)["current_key_version"] == 2
        assert own_wrap(client, partner)["key_version"] == 2
        assert (
            client.get(
                f"/api/v1/vault/rotations/{rotation['id']}/wrappings/me", headers=partner.headers
            ).status_code
            == 409
        )
    with Session(vault_app.state.engine) as session:
        versions = list(
            session.scalars(
                select(VaultVersion)
                .where(
                    VaultVersion.household_id == first.household_id,
                )
                .order_by(VaultVersion.key_version)
            )
        )
        assert [row.state for row in versions] == ["retired", "current"]
        old_members = list(
            session.scalars(
                select(VaultMemberWrapping).where(
                    VaultMemberWrapping.household_id == first.household_id,
                    VaultMemberWrapping.key_version == 1,
                )
            )
        )
        assert {row.state for row in old_members} == {"current"}


def test_rotation_snapshots_archived_cards_and_freezes_concurrent_secret_changes(vault_app, actors):
    first, partner, _ = actors
    with TestClient(vault_app) as client:
        initialize(client, first)
        rows = [card(client, first), card(client, first, archived=True)]
        for index, row in enumerate(rows):
            assert (
                write_secret(client, first, row, payload=card_secret(seed=20 + index)).status_code
                == 200
            )
        rotation = start_rotation(client, first)
        assert {row["card_id"] for row in rotation["cards"]} == {row["id"] for row in rows}
        current_card = card_detail(client, first, rows[0]["id"])
        assert (
            write_secret(client, first, current_card, payload=card_secret(seed=30)).status_code
            == 409
        )
        assert (
            client.delete(
                f"/api/v1/cards/{current_card['id']}/secret-envelope",
                headers=headers(first, version=current_card["version"]),
            ).status_code
            == 409
        )
        current_wrap = own_wrap(client, first)
        rewrap = client.put(
            "/api/v1/vault/wrappings/me",
            headers=headers(first, version=current_wrap["version"]),
            json={
                "wrapping": member_wrap(first, generation=2, seed=31),
                "key_check_confirmed": True,
            },
        )
        assert rewrap.status_code == 409
        new_share = client.post(
            "/api/v1/vault/shares",
            headers=headers(first, version=status(client, first)["version"]),
            json={"wrapping": member_wrap(partner, seed=32)},
        )
        assert new_share.status_code == 409
        rotation = prepare(client, first, rotation, [first])
        rotation = stage(client, first, rotation, rotation["cards"][0])
        incomplete = finalize(client, first, rotation)
        assert incomplete.status_code == 409
        assert status(client, first)["current_key_version"] == 1
        read = client.get(f"/api/v1/cards/{rows[0]['id']}/secret-envelope", headers=first.headers)
        assert read.json()["key_version"] == 1
        rotation = stage(client, first, rotation, rotation["cards"][1], seed=121)
        complete = finalize(client, first, rotation)
        assert complete.status_code == 200, complete.text
        for row in rows:
            assert (
                client.get(
                    f"/api/v1/cards/{row['id']}/secret-envelope", headers=first.headers
                ).json()["key_version"]
                == 2
            )


def test_abort_burns_key_version_and_retains_prepared_nonce_reservations(vault_app, actors):
    first = actors[0]
    with TestClient(vault_app) as client:
        initialize(client, first)
        rotation = prepare(client, first, start_rotation(client, first), [first])
        aborted = client.post(
            f"/api/v1/vault/rotations/{rotation['id']}/abort",
            json={},
            headers=headers(first, "abort-once", rotation["version"]),
        )
        assert aborted.status_code == 200, aborted.text
        replay = client.post(
            f"/api/v1/vault/rotations/{rotation['id']}/abort",
            json={},
            headers=headers(first, "abort-once", rotation["version"]),
        )
        assert replay.json() == aborted.json()
        assert status(client, first)["current_key_version"] == 1
        assert own_wrap(client, first)["key_version"] == 1
        assert (
            client.get(
                f"/api/v1/vault/rotations/{rotation['id']}/wrappings/me", headers=first.headers
            ).status_code
            == 409
        )
        newer = start_rotation(client, first)
        assert newer["key_version"] == 3 and newer["source_key_version"] == 1
    with Session(vault_app.state.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(VaultNonceReservation)
                .where(
                    VaultNonceReservation.household_id == first.household_id,
                    VaultNonceReservation.key_version == 2,
                )
            )
            == 3
        )
        old = session.get(VaultVersion, UUID(rotation["id"]))
        assert old.state == "aborted"


def test_revoke_blocks_all_opaque_access_and_requires_rotation_before_new_writes(vault_app, actors):
    first, partner, _ = actors
    with TestClient(vault_app) as client:
        initialize(client, first)
        accept(client, partner, share(client, first, partner))
        row = card(client, first)
        saved = write_secret(client, partner, row, key="partner-write")
        assert saved.status_code == 200
        membership = next(
            m for m in status(client, first)["members"] if m["member_id"] == str(partner.member_id)
        )
        revoked = client.post(
            f"/api/v1/vault/members/{partner.member_id}/revoke",
            json={},
            headers=headers(first, version=membership["version"]),
        )
        assert revoked.status_code == 200, revoked.text
        assert status(client, first)["rotation_required"] is True
        for path in [
            "/vault/wrappings/me",
            "/vault/recovery-wrap",
            f"/cards/{row['id']}/secret-envelope",
        ]:
            assert client.get("/api/v1" + path, headers=partner.headers).status_code == 403
        assert write_secret(client, partner, row, key="partner-write").status_code == 403
        own = next(
            m for m in status(client, first)["members"] if m["member_id"] == str(first.member_id)
        )
        last = client.post(
            f"/api/v1/vault/members/{first.member_id}/revoke",
            json={},
            headers=headers(first, version=own["version"]),
        )
        assert last.status_code == 409 and last.json()["error"]["code"] == "VAULT_LAST_MEMBER"
        current = card_detail(client, first, row["id"])
        assert write_secret(client, first, current, payload=card_secret(seed=31)).status_code == 409
        own_current = own_wrap(client, first)
        assert (
            client.put(
                "/api/v1/vault/wrappings/me",
                headers=headers(first, version=own_current["version"]),
                json={
                    "wrapping": member_wrap(first, generation=2, seed=32),
                    "key_check_confirmed": True,
                },
            ).status_code
            == 200
        )
        rotation = prepare(client, first, start_rotation(client, first), [first])
        assert len(rotation["members"]) == 1
        rotation = stage(client, first, rotation, rotation["cards"][0])
        assert finalize(client, first, rotation).status_code == 200
        assert status(client, first)["rotation_required"] is False
        accept(client, partner, share(client, first, partner, seed=200))
        assert own_wrap(client, partner)["key_version"] == 2


def test_explicit_secret_delete_purges_current_retired_and_aborted_ciphertexts(vault_app, actors):
    first = actors[0]
    with TestClient(vault_app) as client:
        initialize(client, first)
        row = card(client, first)
        assert write_secret(client, first, row).status_code == 200
        aborted = prepare(client, first, start_rotation(client, first), [first])
        aborted = stage(client, first, aborted, aborted["cards"][0])
        assert (
            client.post(
                f"/api/v1/vault/rotations/{aborted['id']}/abort",
                json={},
                headers=headers(first, version=aborted["version"]),
            ).status_code
            == 200
        )
        activated = prepare(client, first, start_rotation(client, first), [first], seed=200)
        activated = stage(client, first, activated, activated["cards"][0], seed=220)
        assert finalize(client, first, activated).status_code == 200
        current = card_detail(client, first, row["id"])
        with Session(vault_app.state.engine) as session:
            nonce_count = session.scalar(select(func.count()).select_from(VaultNonceReservation))
        deleted = client.delete(
            f"/api/v1/cards/{row['id']}/secret-envelope",
            headers=headers(first, "purge-once", current["version"]),
        )
        assert deleted.status_code == 200, deleted.text
        replay = client.delete(
            f"/api/v1/cards/{row['id']}/secret-envelope",
            headers=headers(first, "purge-once", current["version"]),
        )
        assert replay.json() == deleted.json()
        metadata = card_detail(client, first, row["id"])
        assert metadata["has_secret"] is False and metadata["last_four"] == "0000"
        assert (
            client.get(
                f"/api/v1/cards/{row['id']}/secret-envelope", headers=first.headers
            ).status_code
            == 404
        )
        assert (
            client.patch(
                f"/api/v1/cards/{row['id']}",
                json={"last_four": "1111"},
                headers=headers(first, version=metadata["version"]),
            ).status_code
            == 200
        )
    with Session(vault_app.state.engine) as session:
        envelopes = list(
            session.scalars(
                select(CardSecretEnvelope).where(
                    CardSecretEnvelope.card_id == UUID(row["id"]),
                )
            )
        )
        assert len(envelopes) == 3
        assert all(
            e.ciphertext is None and e.purged_at is not None and not e.is_current for e in envelopes
        )
        assert (
            session.scalar(select(func.count()).select_from(VaultNonceReservation)) == nonce_count
        )
        purged_id = envelopes[0].id
    with Session(vault_app.state.engine) as session:
        with pytest.raises(DBAPIError):
            session.execute(
                text(
                    "UPDATE card_secret_envelopes SET ciphertext=:value, purged_at=NULL "
                    "WHERE id=:id"
                ),
                {"value": b"x" * 43, "id": purged_id},
            )
            session.commit()
        session.rollback()


@pytest.mark.parametrize(
    "kind", ["nonce_delete", "ciphertext_replace", "wrap_replace", "current_drop"]
)
def test_database_rejects_bypassing_opaque_history_and_current_key_invariants(
    vault_app, actors, kind
):
    first = actors[0]
    with TestClient(vault_app) as client:
        initialize(client, first)
        row = card(client, first)
        assert write_secret(client, first, row).status_code == 200
    statements = {
        "nonce_delete": "DELETE FROM vault_nonce_reservations WHERE household_id=:hh",
        "ciphertext_replace": "UPDATE card_secret_envelopes "
        "SET ciphertext=repeat('x',43)::bytea WHERE household_id=:hh",
        "wrap_replace": "UPDATE vault_member_wrappings "
        "SET wrapped_hvk=repeat('x',48)::bytea WHERE household_id=:hh",
        "current_drop": "UPDATE vault_recovery_wrappings "
        "SET is_current=false, version=version+1 WHERE household_id=:hh",
    }
    with Session(vault_app.state.engine) as session:
        with pytest.raises(DBAPIError):
            session.execute(text(statements[kind]), {"hh": first.household_id})
            session.commit()
        session.rollback()


@pytest.mark.parametrize("target", ["session", "device"])
def test_revocation_barrier_wins_before_opaque_read(vault_app, actors, target):
    first = actors[0]
    with TestClient(vault_app) as client:
        initialize(client, first)
    entered = Event()

    def read():
        entered.set()
        with TestClient(vault_app) as client:
            return client.get("/api/v1/vault/wrappings/me", headers=first.headers)

    with vault_app.state.engine.connect() as connection, ThreadPoolExecutor(max_workers=1) as pool:
        transaction = connection.begin()
        if target == "session":
            connection.execute(
                text("UPDATE auth_sessions SET revoked_at=now() WHERE id=:id"),
                {"id": first.principal.session_id},
            )
        else:
            connection.execute(
                text(
                    "UPDATE registered_devices SET status='revoked', revoked_at=now() WHERE id=:id"
                ),
                {"id": first.principal.device_id},
            )
        future = pool.submit(read)
        try:
            assert entered.wait(3)
            with pytest.raises(FutureTimeout):
                future.result(timeout=0.2)
            transaction.commit()
            response = future.result(timeout=5)
            assert response.status_code == 401 and "wrapped_hvk" not in response.text
        finally:
            if transaction.is_active:
                transaction.rollback()


def test_step_up_grant_is_one_use_and_bound_to_vault_purpose_and_target(vault_app, actors):
    first, _, foreign = actors
    with TestClient(vault_app) as client:
        initialize(client, first)
        with Session(vault_app.state.engine) as session:
            wrong_purpose = step_up(
                session, first, StepUpPurpose.ACCOUNT_REVEAL, first.household_id
            )
            wrong_target = step_up(
                session, first, StepUpPurpose.VAULT_KEY_ROTATION, foreign.household_id
            )
            correct = step_up(session, first, StepUpPurpose.VAULT_KEY_ROTATION, first.household_id)
            auth = session.get(AuthSession, first.principal.session_id)
            auth.authenticated_at = identity.utcnow() - timedelta(minutes=6)
            session.commit()
        for grant in [wrong_purpose, wrong_target]:
            response = client.get(
                "/api/v1/vault/recovery-wrap",
                headers=first.headers | {"X-Step-Up-Token": grant.grant_token},
            )
            assert response.status_code == 403 and "wrapped_hvk" not in response.text
        grant_headers = first.headers | {"X-Step-Up-Token": correct.grant_token}
        assert client.get("/api/v1/vault/recovery-wrap", headers=grant_headers).status_code == 200
        assert client.get("/api/v1/vault/recovery-wrap", headers=grant_headers).status_code == 403


def test_card_secret_revision_cas_and_changed_idempotent_payload(vault_app, actors):
    first = actors[0]
    with TestClient(vault_app) as client:
        initialize(client, first)
        row = card(client, first)
        saved = write_secret(client, first, row, key="original-write")
        assert saved.status_code == 200
        changed = card_secret(seed=21, last_four="1111")
        replay = write_secret(client, first, row, payload=changed, key="original-write")
        assert (
            replay.status_code == 409 and replay.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        )
        stale = write_secret(client, first, row, payload=changed)
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "VERSION_CONFLICT"
        current = card_detail(client, first, row["id"])
        updated = write_secret(client, first, current, payload=changed)
        assert updated.status_code == 200
        detail = client.get(
            f"/api/v1/cards/{row['id']}/secret-envelope", headers=first.headers
        ).json()
        assert detail["revision"] == 2 and detail["last_four"] == "1111"
        assert card_detail(client, first, row["id"])["last_four"] == "1111"
