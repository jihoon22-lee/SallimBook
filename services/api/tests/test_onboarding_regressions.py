"""HTTP and transaction regressions using only disposable synthetic households."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_onboarding import (
    INPUT,
    NATIVE,
    ORIGIN,
    PASSWORD,
    WEB,
    client_for,
    owner_code,
    start,
)
from test_onboarding import onboarding_app as onboarding_app
from test_onboarding import trusted_dns as trusted_dns

from sallimbook.core.errors import DomainError
from sallimbook.identity import service
from sallimbook.identity.auth_models import (
    AuthSession,
    HouseholdMember,
    Invitation,
    RefreshToken,
    RegisteredDevice,
    User,
)

pytestmark = pytest.mark.database


def csrf(response):
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def enrollment_counts(engine):
    with Session(engine) as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (User, HouseholdMember, RegisteredDevice, AuthSession, RefreshToken)
        )


def assert_unused_code(engine, code):
    with Session(engine) as session:
        invitation = session.scalar(
            select(Invitation).where(Invitation.token_hash == service.token_hash("invite", code))
        )
        assert invitation is not None
        assert invitation.used_at is None and invitation.revoked_at is None


def accept_legacy(client, token, *, transport="web"):
    return client.post(
        "/api/v1/auth/invitations/accept",
        json={"token": token, "password": PASSWORD, "display_name": "합성 기존 경로 사용자"},
        headers=WEB if transport == "web" else NATIVE,
    )


def legacy_login(client, login_name):
    response = client.post(
        "/api/v1/auth/web/login",
        json={"login_name": login_name, "password": PASSWORD, "device_label": "합성 기존 기기"},
        headers=WEB,
    )
    assert response.status_code == 200
    return response


@pytest.mark.parametrize("transport", ["web", "native"])
def test_connection_session_failure_rolls_back_code_and_all_enrollment_rows(
    onboarding_app, db_engine, monkeypatch, transport
):
    with client_for(onboarding_app) as owner, client_for(onboarding_app) as partner:
        code = owner_code(owner, start(owner))
        baseline = enrollment_counts(db_engine)
        original = service.issue_session

        def fail_after_session_flush(*args, **kwargs):
            original(*args, **kwargs)
            raise DomainError("DATABASE_UNAVAILABLE", "합성 세션 저장 실패", 503)

        payload = {**INPUT, "code": code}
        headers = WEB if transport == "web" else NATIVE
        with monkeypatch.context() as failure:
            failure.setattr(service, "issue_session", fail_after_session_flush)
            response = partner.post(
                f"/api/v1/auth/{transport}/connect", json=payload, headers=headers
            )
        assert response.status_code == 503
        assert "set-cookie" not in response.headers
        assert enrollment_counts(db_engine) == baseline
        assert_unused_code(db_engine, code)

        retried = partner.post(
            f"/api/v1/auth/{transport}/connect", json=payload, headers=headers
        )
        assert retried.status_code == 201
        me_headers = (
            {} if transport == "web"
            else {"Authorization": "Bearer " + retried.json()["access_token"]}
        )
        me = partner.get("/api/v1/me", headers=me_headers)
        assert me.status_code == 200 and me.json()["role"] == "member"
        assert enrollment_counts(db_engine) == (2, 2, 2, 2, int(transport == "native"))


def test_concurrent_web_native_redemption_creates_only_one_partner_and_session(
    onboarding_app, db_engine
):
    with client_for(onboarding_app) as owner:
        code = owner_code(owner, start(owner))
    barrier = Barrier(2)

    def connect(transport):
        with client_for(onboarding_app) as client:
            barrier.wait(timeout=10)
            response = client.post(
                f"/api/v1/auth/{transport}/connect",
                json={**INPUT, "code": code},
                headers=WEB if transport == "web" else NATIVE,
            )
            if response.status_code == 201:
                headers = (
                    {} if transport == "web"
                    else {"Authorization": "Bearer " + response.json()["access_token"]}
                )
                assert client.get("/api/v1/me", headers=headers).json()["role"] == "member"
            else:
                assert response.json()["error"]["code"] == "INVALID_CONNECTION_CODE"
            return transport, response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(connect, ("web", "native")))
    assert sorted(status for _, status in results) == [201, 400]
    native_won = ("native", 201) in results
    assert enrollment_counts(db_engine) == (2, 2, 2, 2, int(native_won))
    with Session(db_engine) as session:
        assert session.scalar(select(Invitation.used_at)) is not None


def test_alternating_transports_and_reissue_keep_the_same_five_guess_budget(
    onboarding_app, db_engine
):
    with client_for(onboarding_app) as owner, client_for(onboarding_app) as partner:
        started = start(owner)
        code = owner_code(owner, started)
        for attempt in range(5):
            if attempt == 2:
                previous = code
                code = owner_code(owner, started)
                assert code != previous
            # The guess is guaranteed different from the currently valid code.
            wrong = f"{(int(code) + 1) % 100_000_000:08d}"
            transport = "web" if attempt % 2 == 0 else "native"
            response = partner.post(
                f"/api/v1/auth/{transport}/connect",
                json={**INPUT, "code": wrong},
                headers=WEB if transport == "web" else NATIVE,
            )
            assert response.status_code == 400
            assert response.json()["error"]["code"] == "INVALID_CONNECTION_CODE"
        for transport in ("native", "web"):
            blocked = partner.post(
                f"/api/v1/auth/{transport}/connect",
                json={**INPUT, "code": code},
                headers=WEB if transport == "web" else NATIVE,
            )
            assert blocked.status_code == 429
            assert blocked.json()["error"]["code"] == "RATE_LIMITED"
        assert_unused_code(db_engine, code)
        assert enrollment_counts(db_engine) == (1, 1, 1, 1, 0)


def test_eight_digit_code_cannot_use_legacy_acceptance_but_legacy_invites_still_work(
    onboarding_app, db_engine
):
    with client_for(onboarding_app) as owner, client_for(onboarding_app) as partner:
        started = start(owner)
        code = owner_code(owner, started)
        for transport in ("web", "native"):
            rejected = accept_legacy(partner, code, transport=transport)
            assert rejected.status_code == 422
            assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"
        assert_unused_code(db_engine, code)
        assert enrollment_counts(db_engine) == (1, 1, 1, 1, 0)
        issued = owner.post(
            "/api/v1/household/invitations",
            json={"intended_login": "synthetic_legacy_spouse"},
            headers=csrf(started),
        )
        assert issued.status_code == 201
        assert len(issued.json()["token"]) >= 32
        accepted = accept_legacy(partner, issued.json()["token"], transport="native")
        assert accepted.status_code == 201 and accepted.json()["role"] == "member"
        # Legacy acceptance intentionally does not establish a new session.
        assert enrollment_counts(db_engine) == (2, 2, 1, 1, 0)
        legacy_login(partner, "synthetic_legacy_spouse")
        assert partner.get("/api/v1/me").json()["role"] == "member"


@pytest.mark.parametrize("revocation", ["disabled_user", "revoked_member"])
def test_connection_rejects_a_code_whose_owner_is_no_longer_active(
    onboarding_app, db_engine, revocation
):
    with client_for(onboarding_app) as owner, client_for(onboarding_app) as partner:
        code = owner_code(owner, start(owner))
        with Session(db_engine) as session:
            if revocation == "disabled_user":
                session.scalar(select(User)).disabled_at = service.utcnow()
            else:
                session.scalar(select(HouseholdMember)).status = "revoked"
            session.commit()
        response = partner.post(
            "/api/v1/auth/native/connect", json={**INPUT, "code": code}, headers=NATIVE
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_CONNECTION_CODE"
        assert_unused_code(db_engine, code)
        assert enrollment_counts(db_engine) == (1, 1, 1, 1, 0)


def test_code_creation_requires_authentication_valid_csrf_and_owner_role(
    onboarding_app, db_engine
):
    with client_for(onboarding_app) as owner, client_for(onboarding_app) as partner:
        anonymous = owner.post("/api/v1/household/connection-code", headers=WEB)
        assert anonymous.status_code == 401
        started = start(owner)
        for headers, error in (
            ({"Origin": ORIGIN}, "CSRF_FAILED"),
            ({"Origin": ORIGIN, "X-CSRF-Token": "invalid"}, "CSRF_FAILED"),
            ({**csrf(started), "Origin": "https://untrusted.invalid"}, "ORIGIN_REJECTED"),
        ):
            rejected = owner.post("/api/v1/household/connection-code", headers=headers)
            assert rejected.status_code == 403
            assert rejected.json()["error"]["code"] == error
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(Invitation)) == 0
        code = owner_code(owner, started)
        connected = partner.post(
            "/api/v1/auth/web/connect", json={**INPUT, "code": code}, headers=WEB
        )
        assert connected.status_code == 201
        denied = partner.post("/api/v1/household/connection-code", headers=csrf(connected))
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "FORBIDDEN"
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(Invitation)) == 1


def test_code_creation_requires_recent_authentication(onboarding_app, db_engine):
    with client_for(onboarding_app) as owner:
        started = start(owner)
        with Session(db_engine) as session:
            session.scalar(select(AuthSession)).authenticated_at = (
                service.utcnow() - timedelta(minutes=6)
            )
            session.commit()
        assert owner.get("/api/v1/me").status_code == 200
        rejected = owner.post("/api/v1/household/connection-code", headers=csrf(started))
        assert rejected.status_code == 403
        assert rejected.json()["error"]["code"] == "REAUTHENTICATION_REQUIRED"
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(Invitation)) == 0


def test_legacy_owner_named_partner_can_use_existing_invitation_flow(
    onboarding_app, db_engine
):
    with Session(db_engine) as session:
        bootstrap = service.create_bootstrap_invitation(session, "합성 기존 가계", "partner")
        session.commit()
    with client_for(onboarding_app) as owner, client_for(onboarding_app) as spouse:
        assert accept_legacy(owner, bootstrap.token).status_code == 201
        logged_in = legacy_login(owner, "partner")
        rejected = owner.post("/api/v1/household/connection-code", headers=csrf(logged_in))
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "LOGIN_UNAVAILABLE"
        issued = owner.post(
            "/api/v1/household/invitations",
            json={"intended_login": "synthetic_legacy_spouse"},
            headers=csrf(logged_in),
        )
        assert issued.status_code == 201
        accepted = accept_legacy(spouse, issued.json()["token"])
        assert accepted.status_code == 201
        assert accepted.json()["household_id"] == logged_in.json()["member"]["household_id"]
        legacy_login(spouse, "synthetic_legacy_spouse")
        assert spouse.get("/api/v1/me").json()["role"] == "member"
        assert enrollment_counts(db_engine) == (2, 2, 2, 2, 0)
