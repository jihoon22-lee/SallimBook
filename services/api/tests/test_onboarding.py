"""Synthetic self-start and spouse connection tests; never use real enrollment data."""

import hashlib
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from sallimbook.config import Settings
from sallimbook.core.errors import DomainError
from sallimbook.core.http import install_http_contract
from sallimbook.identity import service
from sallimbook.identity.auth_models import (
    AuthSession,
    HouseholdMember,
    Invitation,
    LoginThrottle,
    User,
)
from sallimbook.identity.dependencies import self_setup_identity_allowed
from sallimbook.identity.models import Household
from sallimbook.identity.router import router
from sallimbook.identity.schemas import ConnectionRequest, SetupRequest

ORIGIN = "https://sallimbook-onboarding.invalid"
IDENTITY = "synthetic-owner@example.invalid"
IDENTITY_HASH = hashlib.sha256(IDENTITY.encode()).hexdigest()
PEER = "192.0.2.15"
PASSWORD = "SYNTHETIC ONLY onboarding passphrase 2026"
INPUT = {"display_name": "합성 첫 사용자", "password": PASSWORD, "device_label": "합성 기기"}


def request_for_setup(settings, *, peer=PEER, headers=None):
    app = FastAPI()
    app.state.settings = settings
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "app": app,
            "client": (peer, 1234),
            "headers": headers or [],
            "scheme": "https",
            "query_string": b"",
            "server": ("synthetic.invalid", 443),
        }
    )


def enabled_settings():
    return Settings(
        environment="test",
        allowed_origins=[ORIGIN],
        self_setup_identity_sha256=IDENTITY_HASH,
        self_setup_proxy_host="node",
    )


@pytest.fixture
def trusted_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PEER, 0)),
        ],
    )


def test_setup_identity_requires_actual_peer_and_single_authenticated_header(trusted_dns):
    headers = [(b"tailscale-user-login", IDENTITY.encode())]
    assert self_setup_identity_allowed(request_for_setup(enabled_settings(), headers=headers))
    for request in (
        request_for_setup(Settings(environment="test"), headers=headers),
        request_for_setup(enabled_settings(), peer="192.0.2.99", headers=headers),
        request_for_setup(enabled_settings(), headers=[]),
        request_for_setup(enabled_settings(), headers=headers * 2),
        request_for_setup(enabled_settings(), headers=[(b"tailscale-user-login", b"wrong")]),
        request_for_setup(
            enabled_settings(), headers=headers + [(b"tailscale-funnel-request", b"?1")]
        ),
        request_for_setup(
            enabled_settings(),
            peer="192.0.2.99",
            headers=headers
            + [
                (b"x-forwarded-for", PEER.encode()),
            ],
        ),
    ):
        assert not self_setup_identity_allowed(request)


def test_setup_identity_fails_closed_when_proxy_dns_fails(monkeypatch):
    def unavailable(*args, **kwargs):
        raise socket.gaierror("synthetic DNS failure")

    monkeypatch.setattr(socket, "getaddrinfo", unavailable)
    request = request_for_setup(
        enabled_settings(),
        headers=[
            (b"tailscale-user-login", IDENTITY.encode()),
        ],
    )
    assert not self_setup_identity_allowed(request)


@pytest.fixture
def onboarding_app(db_engine, trusted_dns):
    app = FastAPI()
    app.state.settings = enabled_settings()
    app.state.engine = db_engine
    install_http_contract(app)
    app.include_router(router)
    return app


def client_for(app):
    return TestClient(app, base_url=ORIGIN, client=(PEER, 1234))


WEB = {"Origin": ORIGIN, "Tailscale-User-Login": IDENTITY}
NATIVE = {"X-SallimBook-Native": "1", "Tailscale-User-Login": IDENTITY}


def start(client, transport="web"):
    return client.post(
        f"/api/v1/auth/{transport}/setup",
        json=INPUT,
        headers=WEB if transport == "web" else NATIVE,
    )


def owner_code(client, started):
    response = client.post(
        "/api/v1/household/connection-code",
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": started.json()["csrf_token"],
        },
    )
    assert response.status_code == 201
    assert len(response.json()["code"]) == 8 and response.json()["code"].isascii()
    assert response.json()["code"].isdigit()
    return response.json()["code"]


@pytest.mark.database
@pytest.mark.parametrize("transport", ["web", "native"])
def test_first_start_creates_one_account_and_authenticated_session(
    onboarding_app, db_engine, transport
):
    with client_for(onboarding_app) as client:
        assert client.get("/api/v1/household/setup", headers=WEB).json() == {"available": True}
        response = start(client, transport)
        assert response.status_code == 201
        if transport == "web":
            cookie = response.headers["set-cookie"]
            assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
            me = client.get("/api/v1/me")
        else:
            assert "set-cookie" not in response.headers
            me = client.get(
                "/api/v1/me",
                headers={
                    "Authorization": "Bearer " + response.json()["access_token"],
                },
            )
        assert me.status_code == 200 and me.json()["role"] == "owner"
        assert client.get("/api/v1/household/setup", headers=WEB).json() == {"available": False}
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(Household)) == 1
        assert session.scalar(select(User.login_name)) == "owner"
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 1


@pytest.mark.database
def test_existing_empty_household_is_preserved_and_operator_codes_revoked(
    onboarding_app, db_engine
):
    with Session(db_engine) as session:
        invitation = service.create_bootstrap_invitation(session, "기존 합성 빈 가계", "owner")
        session.commit()
        household_id = session.scalar(select(Household.id))
        invitation_id = invitation.id
    with client_for(onboarding_app) as client:
        response = start(client)
        assert response.status_code == 201
        assert response.json()["member"]["household_id"] == str(household_id)
        assert start(client).status_code == 409
    with Session(db_engine) as session:
        assert session.get(Household, household_id).name == "기존 합성 빈 가계"
        assert session.get(Invitation, invitation_id).revoked_at is not None


@pytest.mark.database
def test_setup_rejects_untrusted_calls_bad_transport_and_extra_authority_fields(
    onboarding_app, db_engine
):
    with client_for(onboarding_app) as client:
        assert client.get("/api/v1/household/setup").json() == {"available": False}
        assert (
            client.post(
                "/api/v1/auth/web/setup", json=INPUT, headers={"Origin": ORIGIN}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/auth/web/setup",
                json=INPUT,
                headers={
                    **WEB,
                    "Origin": "https://evil.invalid",
                },
            ).status_code
            == 403
        )
        assert client.post("/api/v1/auth/native/setup", json=INPUT, headers=WEB).status_code == 403
        assert (
            client.post(
                "/api/v1/auth/web/setup", json={**INPUT, "role": "owner"}, headers=WEB
            ).status_code
            == 422
        )
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.database
def test_setup_never_reopens_for_disabled_users_or_revoked_members(onboarding_app, db_engine):
    with client_for(onboarding_app) as client:
        assert start(client).status_code == 201
    with Session(db_engine) as session:
        session.scalar(select(User)).disabled_at = service.utcnow()
        session.scalar(select(HouseholdMember)).status = "revoked"
        session.commit()
    with client_for(onboarding_app) as client:
        assert client.get("/api/v1/household/setup", headers=WEB).json() == {"available": False}
        assert start(client).status_code == 409


@pytest.mark.database
def test_concurrent_first_starts_cannot_create_two_households_or_owners(db_engine):
    barrier = Barrier(2)

    def attempt(index):
        with Session(db_engine) as session:
            barrier.wait(timeout=5)
            try:
                service.setup_household(session, SetupRequest(**INPUT), f"synthetic-{index}", "web")
                return "created"
            except DomainError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, range(2)))
    assert sorted(outcomes) == ["SETUP_COMPLETE", "created"]
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(Household)) == 1


@pytest.mark.database
@pytest.mark.parametrize("transport", ["web", "native"])
def test_partner_connection_signs_in_immediately_and_consumes_code(
    onboarding_app, db_engine, transport
):
    with client_for(onboarding_app) as owner, client_for(onboarding_app) as partner:
        started = start(owner)
        code = owner_code(owner, started)
        payload = {**INPUT, "display_name": "합성 배우자", "code": code}
        response = partner.post(
            f"/api/v1/auth/{transport}/connect",
            json=payload,
            headers=WEB if transport == "web" else NATIVE,
        )
        assert response.status_code == 201
        headers = (
            {}
            if transport == "web"
            else {"Authorization": "Bearer " + response.json()["access_token"]}
        )
        me = partner.get("/api/v1/me", headers=headers)
        assert me.status_code == 200 and me.json()["role"] == "member"
        assert (
            partner.post("/api/v1/auth/web/connect", json=payload, headers=WEB).status_code == 400
        )
        assert (
            owner.post(
                "/api/v1/household/connection-code",
                headers={
                    "Origin": ORIGIN,
                    "X-CSRF-Token": started.json()["csrf_token"],
                },
            ).status_code
            == 409
        )
    with Session(db_engine) as session:
        assert set(session.scalars(select(User.login_name))) == {"owner", "partner"}
        assert session.scalar(select(func.count()).select_from(Household)) == 1


@pytest.mark.database
def test_reissued_and_expired_connection_codes_are_rejected(onboarding_app, db_engine):
    with client_for(onboarding_app) as owner, client_for(onboarding_app) as partner:
        started = start(owner)
        old = owner_code(owner, started)
        new = owner_code(owner, started)
        assert old != new
        assert (
            partner.post(
                "/api/v1/auth/web/connect", json={**INPUT, "code": old}, headers=WEB
            ).status_code
            == 400
        )
        with Session(db_engine) as session:
            row = session.scalar(
                select(Invitation).where(Invitation.token_hash == service.token_hash("invite", new))
            )
            row.expires_at = service.utcnow() - timedelta(seconds=1)
            session.commit()
        assert (
            partner.post(
                "/api/v1/auth/web/connect", json={**INPUT, "code": new}, headers=WEB
            ).status_code
            == 400
        )


@pytest.mark.database
def test_code_guess_limit_cannot_be_bypassed_by_different_peer_addresses(db_engine):
    for index in range(6):
        with Session(db_engine) as session:
            with pytest.raises(DomainError) as failure:
                service.connect_household(
                    session,
                    ConnectionRequest(**INPUT, code="12345678"),
                    f"synthetic-{index}",
                    "web",
                )
            assert failure.value.code == (
                "INVALID_CONNECTION_CODE" if index < 5 else "RATE_LIMITED"
            )


@pytest.mark.database
def test_session_issue_failure_rolls_back_first_enrollment(onboarding_app, db_engine, monkeypatch):
    def failed(*args, **kwargs):
        raise DomainError("DATABASE_UNAVAILABLE", "합성 실패", 503)

    monkeypatch.setattr(service, "issue_session", failed)
    with client_for(onboarding_app) as client:
        assert start(client).status_code == 503
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0
        assert session.scalar(select(func.count()).select_from(HouseholdMember)) == 0
        assert session.scalar(select(func.count()).select_from(Household)) == 0


def busy_password_work(monkeypatch):
    monkeypatch.setattr(service, "_password_slots", threading.BoundedSemaphore(1))
    service._password_slots.acquire()


@pytest.mark.database
def test_busy_password_work_during_start_does_not_use_up_attempts(
    onboarding_app, db_engine, monkeypatch
):
    busy_password_work(monkeypatch)
    with client_for(onboarding_app) as owner:
        response = start(owner)
    assert response.status_code == 429 and response.json()["error"]["code"] == "AUTH_BUSY"
    with Session(db_engine) as session:
        assert [row.attempts for row in session.scalars(select(LoginThrottle))] == [0]
        assert session.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.database
def test_busy_password_work_during_connection_does_not_use_up_guesses(
    onboarding_app, db_engine, monkeypatch
):
    with client_for(onboarding_app) as owner, client_for(onboarding_app) as partner:
        code = owner_code(owner, start(owner))
        busy_password_work(monkeypatch)
        payload = {**INPUT, "display_name": "합성 배우자", "code": code}
        response = partner.post("/api/v1/auth/web/connect", json=payload, headers=WEB)
        assert response.status_code == 429 and response.json()["error"]["code"] == "AUTH_BUSY"
    with Session(db_engine) as session:
        key = service.token_hash("throttle", "connection-global")
        assert session.get(LoginThrottle, key).attempts == 0
        assert session.scalar(select(func.count()).select_from(User)) == 1
