"""Synthetic identity tests. Database tests require the disposable migrated schema fixture."""

import json
import secrets
import stat
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from argon2.low_level import Type
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sallimbook.config import Settings
from sallimbook.core.audit import AuditEvent
from sallimbook.core.authorization import scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.http import install_http_contract
from sallimbook.identity import cli, service
from sallimbook.identity.auth_models import (
    AuthSession,
    HouseholdMember,
    Invitation,
    LoginThrottle,
    RefreshToken,
    RegisteredDevice,
    User,
)
from sallimbook.identity.dependencies import NATIVE_HEADER, SESSION_COOKIE
from sallimbook.identity.models import Household
from sallimbook.identity.router import router
from sallimbook.identity.schemas import (
    InvitationAcceptance,
    LoginRequest,
    PasswordChangeRequest,
)

ORIGIN = "https://sallimbook-test.invalid"
NATIVE = {NATIVE_HEADER: "1"}


@dataclass(frozen=True)
class Account:
    login_name: str
    user_id: UUID
    member_id: UUID
    household_id: UUID
    password: str = field(repr=False)


@pytest.fixture
def identity_app(db_engine):
    # Use the real router, session dependency, and safe HTTP errors without a production DB URL.
    app = FastAPI()
    app.state.settings = Settings(environment="test", allowed_origins=[ORIGIN])
    app.state.engine = db_engine
    install_http_contract(app)
    app.include_router(router)
    return app


@pytest.fixture
def account(db_engine):
    password = secrets.token_urlsafe(24)
    with Session(db_engine) as session:
        invitation = service.create_bootstrap_invitation(session, "합성 가계 H1", "synthetic_owner")
        session.commit()
        member = service.accept_invitation(
            session,
            InvitationAcceptance(
                token=invitation.token,
                password=password,
                display_name="합성 구성원 A",
            ),
            "synthetic-operator",
        )
    return Account(
        "synthetic_owner", member.user_id, member.member_id, member.household_id, password
    )


def web_login(client, account):
    response = client.post(
        "/api/v1/auth/web/login",
        headers={"Origin": ORIGIN},
        json={
            "login_name": account.login_name,
            "password": account.password,
            "device_label": "합성 PC",
        },
    )
    assert response.status_code == 200
    return response


def native_login(client, account):
    response = client.post(
        "/api/v1/auth/native/login",
        headers=NATIVE,
        json={
            "login_name": account.login_name,
            "password": account.password,
            "device_label": "합성 Android",
        },
    )
    assert response.status_code == 200
    return response.json()


def bearer(tokens):
    return {"Authorization": "Bearer " + tokens["access_token"]}


def csrf(response):
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def test_password_policy_and_input_schema_are_not_client_authorization():
    assert service.PASSWORD_HASHER.type is Type.ID
    assert service.PASSWORD_HASHER.memory_cost == 65536
    assert service.PASSWORD_HASHER.time_cost == 3
    parsed = LoginRequest(
        login_name=" Synthetic_Owner ",
        password=secrets.token_urlsafe(24),
        device_label="PC",
    )
    assert parsed.login_name == "synthetic_owner"
    with pytest.raises(ValidationError):
        LoginRequest(
            login_name="synthetic_owner",
            password="unused",
            device_label="PC",
            household_id=str(UUID(int=1)),
        )
    with pytest.raises(ValidationError):
        InvitationAcceptance(
            token=secrets.token_urlsafe(32), password="too-short", display_name="A"
        )


def test_bootstrap_cli_writes_only_private_file_and_rolls_back_failed_commit(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    target = directory / "registration.json"
    generated = secrets.token_urlsafe(32)
    engine = MagicMock()
    session = MagicMock()
    monkeypatch.setattr(cli, "make_engine", lambda _: engine)
    monkeypatch.setattr(cli, "Session", lambda _: session)
    monkeypatch.setattr(
        cli,
        "create_bootstrap_invitation",
        lambda *args: MagicMock(
            token=generated,
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        ),
    )
    settings = Settings(
        database_url=SecretStr("postgresql+psycopg://synthetic.invalid/example_test")
    )
    cli.bootstrap_to_file(settings, "합성 가계", "synthetic_owner", target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    stored = json.loads(target.read_text())
    assert service.token_hash("invite", stored["invitation_token"]) == service.token_hash(
        "invite",
        generated,
    )
    session.__enter__.return_value.commit.assert_called_once()
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        cli.bootstrap_to_file(settings, "합성 가계", "synthetic_owner", target)
    assert target.read_bytes() == original
    failed_target = directory / "failed.json"
    session.__enter__.return_value.commit.side_effect = RuntimeError("synthetic commit failure")
    with pytest.raises(RuntimeError):
        cli.bootstrap_to_file(settings, "합성 가계", "synthetic_owner", failed_target)
    assert not failed_target.exists()


def test_bootstrap_cli_rejects_public_directory_and_symlink_destination(tmp_path, monkeypatch):
    directory = tmp_path / "public"
    directory.mkdir(mode=0o755)
    # mkdir's mode is filtered by umask; explicitly create the rejected fixture.
    directory.chmod(0o755)
    settings = Settings(
        database_url=SecretStr("postgresql+psycopg://synthetic.invalid/example_test")
    )
    engine_factory = MagicMock()
    monkeypatch.setattr(cli, "make_engine", engine_factory)
    with pytest.raises(ValueError):
        cli.bootstrap_to_file(settings, "합성 가계", "synthetic_owner", directory / "token.json")
    directory.chmod(0o700)
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("synthetic sentinel")
    link = directory / "token.json"
    link.symlink_to(sentinel)
    with pytest.raises(FileExistsError):
        cli.bootstrap_to_file(settings, "합성 가계", "synthetic_owner", link)
    assert sentinel.read_text() == "synthetic sentinel"
    engine_factory.assert_not_called()


class BlockingHasher:
    """Synthetic stand-in that holds a work slot; never receives real credentials."""

    def __init__(self):
        self.entered = threading.Semaphore(0)
        self.release = threading.Event()

    def verify(self, encoded, password):
        self.entered.release()
        self.release.wait(5)
        return True

    def hash(self, password):
        self.entered.release()
        self.release.wait(5)
        return "synthetic-hash"

    def check_needs_rehash(self, encoded):
        return True


def test_password_work_allows_two_concurrent_operations_then_fails_fast(monkeypatch):
    fake = BlockingHasher()
    monkeypatch.setattr(service, "PASSWORD_HASHER", fake)
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = [
            pool.submit(service._verify_password, "synthetic", "synthetic"),
            pool.submit(service.hash_password, "synthetic"),
        ]
        assert fake.entered.acquire(timeout=5) and fake.entered.acquire(timeout=5)
        with pytest.raises(DomainError) as busy:
            service._verify_password("synthetic", "synthetic")
        assert (busy.value.code, busy.value.status, busy.value.safe_message) == (
            "AUTH_BUSY",
            429,
            "로그인 확인 요청이 몰려 있어요. 잠시 후 다시 시도해 주세요.",
        )
        fake.release.set()
        assert [f.result(timeout=5) for f in running] == [True, "synthetic-hash"]
    assert service._verify_password("synthetic", "synthetic") is True  # slots returned


def test_rehash_is_skipped_not_failed_when_slots_are_busy(monkeypatch):
    monkeypatch.setattr(service, "PASSWORD_HASHER", BlockingHasher())
    monkeypatch.setattr(service, "_password_slots", threading.BoundedSemaphore(1))
    service._password_slots.acquire()
    user = SimpleNamespace(password_hash="synthetic-old")
    service._upgrade_hash(user, "synthetic")
    assert user.password_hash == "synthetic-old"


@pytest.mark.database
class TestIdentityDatabase:
    @pytest.mark.parametrize("replacement", ["changed", "rehashed"])
    def test_login_rechecks_password_hash_under_account_lock(
        self, db_engine, account, monkeypatch, replacement
    ):
        verify = service._verify_admitted

        def replace_after_verification(session, buckets, encoded, password):
            verified = verify(session, buckets, encoded, password)
            with Session(db_engine) as other:
                user = other.get(User, account.user_id)
                user.password_hash = service.hash_password(
                    secrets.token_urlsafe(24) if replacement == "changed" else account.password
                )
                other.commit()
            return verified

        monkeypatch.setattr(service, "_verify_admitted", replace_after_verification)
        request = LoginRequest(
            login_name=account.login_name,
            password=account.password,
            device_label="합성 경합 기기",
        )
        with Session(db_engine) as session:
            if replacement == "changed":
                with pytest.raises(DomainError) as error:
                    service.login(session, request, "synthetic-race", "native")
                assert (error.value.code, error.value.status) == ("UNAUTHENTICATED", 401)
            else:
                service.login(session, request, "synthetic-race", "native")
        with Session(db_engine) as session:
            devices = session.scalar(select(func.count()).select_from(RegisteredDevice))
        assert devices == (0 if replacement == "changed" else 1)

    @pytest.mark.parametrize("transport", ["web", "native"])
    def test_revoke_other_devices_keeps_this_device_and_requires_the_password(
        self, identity_app, db_engine, account, transport
    ):
        path = "/api/v1/devices/revoke-others"
        with (
            TestClient(identity_app, base_url="https://testserver") as client,
            TestClient(identity_app, base_url="https://testserver") as device,
        ):
            other = native_login(device, account)
            headers = (
                csrf(web_login(client, account))
                if transport == "web"
                else {**NATIVE, **bearer(native_login(client, account))}
            )
            if transport == "web":
                missing = client.post(
                    path, headers={"Origin": ORIGIN}, json={"password": account.password}
                )
                assert missing.json()["error"]["code"] == "CSRF_FAILED"
            wrong = client.post(path, headers=headers, json={"password": secrets.token_urlsafe(24)})
            assert wrong.status_code == 403
            assert wrong.json()["error"]["code"] == "REAUTHENTICATION_FAILED"
            assert device.get("/api/v1/me", headers=bearer(other)).status_code == 200
            stale = service.utcnow() - timedelta(minutes=6)
            with Session(db_engine) as session:
                for auth in session.scalars(select(AuthSession)):
                    auth.authenticated_at = stale
                session.commit()
            result = client.post(path, headers=headers, json={"password": account.password})
            assert result.status_code == 200 and result.json() == {"revoked_devices": 1}
            assert device.get("/api/v1/me", headers=bearer(other)).status_code == 401
            refreshed = device.post(
                "/api/v1/auth/native/refresh",
                headers=NATIVE,
                json={"refresh_token": other["refresh_token"]},
            )
            assert refreshed.status_code == 401
            again = client.post(path, headers=headers, json={"password": account.password})
            assert again.status_code == 200 and again.json() == {"revoked_devices": 0}
        with Session(db_engine) as session:
            rows = session.execute(
                select(
                    RegisteredDevice.id, RegisteredDevice.status, AuthSession.authenticated_at
                ).join(AuthSession, AuthSession.device_id == RegisteredDevice.id)
            ).all()
            events = session.execute(
                select(AuditEvent.entity_id, AuditEvent.safe_diff).where(
                    AuditEvent.entity_type == "registered_device", AuditEvent.action == "revoke"
                )
            ).all()
        assert sorted(status for _, status, _ in rows) == ["active", "revoked"]
        assert all((at > stale) == (status == "active") for _, status, at in rows)
        revoked = next(identifier for identifier, status, _ in rows if status == "revoked")
        assert [(entity, diff["changed_fields"]) for entity, diff in events] == [
            (revoked, ["revoked_at", "status"])
        ]

    def test_revoke_others_shares_the_reauthentication_limit(self, identity_app, account):
        with TestClient(identity_app, base_url="https://testserver") as client:
            tokens = native_login(client, account)
            headers = {**NATIVE, **bearer(tokens)}
            paths = ["/api/v1/auth/native/reauthenticate"] * 3
            paths += ["/api/v1/devices/revoke-others"] * 2
            for path in paths:
                wrong = client.post(
                    path, headers=headers, json={"password": secrets.token_urlsafe(24)}
                )
                assert wrong.status_code == 403
            limited = client.post(
                "/api/v1/devices/revoke-others",
                headers=headers,
                json={"password": account.password},
            )
            assert limited.status_code == 429
            assert limited.json()["error"]["code"] == "RATE_LIMITED"
            assert client.get("/api/v1/me", headers=bearer(tokens)).status_code == 200

    def test_revoke_others_relocks_when_a_login_finishes_before_the_account_lock(
        self, identity_app, db_engine, account, monkeypatch
    ):
        lock = service.lock_session_devices
        concurrent = []

        def login_after_first_lock(session, principal, *, additional_device_ids=()):
            locked = lock(session, principal, additional_device_ids=additional_device_ids)
            if not concurrent:
                with Session(db_engine) as other:
                    concurrent.append(
                        service.login(
                            other,
                            LoginRequest(
                                login_name=account.login_name,
                                password=account.password,
                                device_label="합성 동시 기기",
                            ),
                            "synthetic-concurrent",
                            "native",
                        )
                    )
            return locked

        with TestClient(identity_app, base_url="https://testserver") as client:
            other = native_login(client, account)
            tokens = native_login(client, account)
            monkeypatch.setattr(service, "lock_session_devices", login_after_first_lock)
            result = client.post(
                "/api/v1/devices/revoke-others",
                headers={**NATIVE, **bearer(tokens)},
                json={"password": account.password},
            )
            assert result.status_code == 200 and result.json() == {"revoked_devices": 2}
            late = {"Authorization": "Bearer " + concurrent[0].token}
            assert client.get("/api/v1/me", headers=late).status_code == 401
            assert client.get("/api/v1/me", headers=bearer(other)).status_code == 401
            assert client.get("/api/v1/me", headers=bearer(tokens)).status_code == 200

    @pytest.mark.parametrize("transport", ["web", "native"])
    def test_password_change_replaces_login_and_signs_out_other_devices(
        self, identity_app, db_engine, account, transport
    ):
        replacement = secrets.token_urlsafe(24)
        body = {"current_password": account.password, "new_password": replacement}
        with (
            TestClient(identity_app, base_url="https://testserver") as client,
            TestClient(identity_app, base_url="https://testserver") as device,
        ):
            other = native_login(device, account)
            tokens = None if transport == "web" else native_login(client, account)
            headers = (
                csrf(web_login(client, account)) if tokens is None else {**NATIVE, **bearer(tokens)}
            )
            if transport == "web":
                missing = client.post(
                    "/api/v1/auth/password", headers={"Origin": ORIGIN}, json=body
                )
                assert missing.json()["error"]["code"] == "CSRF_FAILED"
            result = client.post("/api/v1/auth/password", headers=headers, json=body)
            assert result.status_code == 200 and result.json() == {"revoked_devices": 1}
            assert device.get("/api/v1/me", headers=bearer(other)).status_code == 401
            me = {} if tokens is None else bearer(tokens)
            assert client.get("/api/v1/me", headers=me).status_code == 200

            def login(password):
                return device.post(
                    "/api/v1/auth/native/login",
                    headers=NATIVE,
                    json={
                        "login_name": account.login_name,
                        "password": password,
                        "device_label": "합성 Android",
                    },
                )

            assert login(account.password).status_code == 401
            assert login(replacement).status_code == 200
        with Session(db_engine) as session:
            stored = session.get(User, account.user_id).password_hash
            rows = session.execute(
                select(
                    AuditEvent.entity_type,
                    AuditEvent.action,
                    AuditEvent.entity_id,
                    AuditEvent.safe_diff,
                ).where(AuditEvent.action.not_in(("login", "accept")))  # fixture accept
            ).all()
        events = Counter((kind, action, tuple(d["changed_fields"])) for kind, action, _, d in rows)
        assert events == Counter(
            [
                ("registered_device", "revoke", ("revoked_at", "status")),
                ("user", "update", ("password_hash",)),
            ]
        )
        assert next(entity for kind, _, entity, _ in rows if kind == "user") == account.user_id
        dumped = json.dumps([d for *_, d in rows], ensure_ascii=False)
        for secret in (account.password, replacement, stored):
            assert secret not in dumped

    def test_password_change_rejects_wrong_same_or_short_passwords_without_side_effects(
        self, identity_app, db_engine, account
    ):
        with (
            TestClient(identity_app, base_url="https://testserver") as client,
            TestClient(identity_app, base_url="https://testserver") as device,
        ):
            other = native_login(device, account)
            headers = {**NATIVE, **bearer(native_login(client, account))}
            cases = [
                (
                    {
                        "current_password": secrets.token_urlsafe(24),
                        "new_password": secrets.token_urlsafe(24),
                    },
                    403,
                    "REAUTHENTICATION_FAILED",
                ),
                (
                    {"current_password": account.password, "new_password": account.password},
                    422,
                    "VALIDATION_ERROR",
                ),
                (
                    {
                        "current_password": account.password,
                        "new_password": secrets.token_urlsafe(24)[:14],
                    },
                    422,
                    "VALIDATION_ERROR",
                ),
                ({"current_password": account.password}, 422, "VALIDATION_ERROR"),
            ]
            for body, status, code in cases:
                response = client.post("/api/v1/auth/password", headers=headers, json=body)
                assert (response.status_code, response.json()["error"]["code"]) == (status, code)
            assert device.get("/api/v1/me", headers=bearer(other)).status_code == 200
        with Session(db_engine) as session:
            stored = session.get(User, account.user_id).password_hash
            changed = session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action.not_in(("login", "accept")))  # fixture accept
            )
        assert service._verify_password(stored, account.password)
        assert changed == 0

    def test_concurrent_password_changes_from_two_devices_leave_one_winner(
        self, db_engine, account
    ):
        logins = []
        with Session(db_engine) as session:
            for label in ("합성 첫 기기", "합성 둘째 기기"):
                logins.append(
                    service.login(
                        session,
                        LoginRequest(
                            login_name=account.login_name,
                            password=account.password,
                            device_label=label,
                        ),
                        "synthetic-native",
                        "native",
                    )
                )
        barrier = Barrier(2)

        def change(login):
            with Session(db_engine) as session:
                principal = service.authenticate(session, login.token, "native")
                barrier.wait(timeout=10)
                request = PasswordChangeRequest(
                    current_password=account.password,
                    new_password=secrets.token_urlsafe(24),
                )
                try:
                    return service.change_password(
                        session, principal, request, "synthetic-concurrency"
                    ).revoked_devices
                except DomainError as exc:
                    return exc.status

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(change, login) for login in logins]
            outcomes = [future.result(timeout=30) for future in futures]
        assert sorted(outcomes) == [1, 401]
        with Session(db_engine) as session:
            statuses = sorted(session.scalars(select(RegisteredDevice.status)))
        assert statuses == ["active", "revoked"]

    def test_security_events_keep_metadata_only(self, identity_app, db_engine, account):
        with Session(db_engine) as session:
            fixture_events = set(session.scalars(select(AuditEvent.id)))  # bootstrap acceptance
        with TestClient(identity_app, base_url="https://testserver") as client:
            tokens = native_login(client, account)
            device = client.get("/api/v1/devices", headers=bearer(tokens)).json()["items"][0]
            assert (
                client.delete(
                    "/api/v1/devices/" + device["id"],
                    headers={**bearer(tokens), "If-Match": f'"{device["version"]}"'},
                ).status_code
                == 204
            )
            login = web_login(client, account)
            invited = client.post(
                "/api/v1/household/invitations",
                headers=csrf(login),
                json={"intended_login": "synthetic_partner"},
            )
            assert invited.is_success
            secret = secrets.token_urlsafe(24)
            assert client.post(
                "/api/v1/auth/invitations/accept",
                headers={"Origin": ORIGIN},
                json={
                    "token": invited.json()["token"],
                    "password": secret,
                    "display_name": "합성 B",
                },
            ).is_success
            assert client.post("/api/v1/auth/web/logout", headers=csrf(login)).is_success
        with Session(db_engine) as session:
            rows = session.execute(
                select(AuditEvent.entity_type, AuditEvent.action, AuditEvent.safe_diff).where(
                    AuditEvent.id.not_in(fixture_events)
                )
            ).all()
        assert Counter((t, a, tuple(d["changed_fields"])) for t, a, d in rows) == Counter(
            [
                ("registered_device", "login", ()),
                ("registered_device", "revoke", ("revoked_at", "status")),
                ("registered_device", "login", ()),
                ("invitation", "create", ()),
                ("invitation", "accept", ("used_at",)),
                ("registered_device", "revoke", ("revoked_at", "status")),
            ]
        )
        dumped = json.dumps([d for *_, d in rows], ensure_ascii=False)
        for raw in (invited.json()["token"], secret, "synthetic_partner", account.login_name):
            assert raw not in dumped

    def test_busy_password_work_does_not_consume_login_attempts(
        self, identity_app, account, db_engine, monkeypatch
    ):
        monkeypatch.setattr(service, "_password_slots", threading.BoundedSemaphore(1))
        service._password_slots.acquire()
        with TestClient(identity_app, base_url="https://testserver") as client:
            response = client.post(
                "/api/v1/auth/web/login",
                headers={"Origin": ORIGIN},
                json={
                    "login_name": account.login_name,
                    "password": account.password,
                    "device_label": "PC",
                },
            )
        assert response.status_code == 429 and response.json()["error"]["code"] == "AUTH_BUSY"
        with Session(db_engine) as session:
            key = service.token_hash("throttle", f"login-account:{account.login_name}")
            assert session.get(LoginThrottle, key).attempts == 0
            assert session.scalar(select(func.count()).select_from(AuthSession)) == 0

    def test_a_rate_limited_attempt_is_not_added_to_other_buckets(self, db_engine):
        now = service.utcnow()
        with Session(db_engine) as session:
            service._admit_attempt(session, [("narrow", 1), ("wide", 30)], now)
            for _ in range(3):
                with pytest.raises(DomainError) as failure:
                    service._admit_attempt(session, [("narrow", 1), ("wide", 30)], now)
                assert failure.value.code == "RATE_LIMITED"
            assert session.get(LoginThrottle, service.token_hash("throttle", "wide")).attempts == 1

    def test_one_device_using_up_its_refreshes_does_not_block_another(self, identity_app, account):
        # Every device refreshes through the same proxy peer, so the source bucket is shared.
        with (
            TestClient(identity_app, base_url="https://testserver") as first,
            TestClient(identity_app, base_url="https://testserver") as second,
        ):
            tokens = native_login(first, account)
            other = native_login(second, account)
            refresh = tokens["refresh_token"]
            limited = 0
            for _ in range(31):
                response = first.post(
                    "/api/v1/auth/native/refresh", headers=NATIVE, json={"refresh_token": refresh}
                )
                if response.status_code == 200:
                    refresh = response.json()["refresh_token"]
                else:
                    assert response.json()["error"]["code"] == "RATE_LIMITED"
                    limited += 1
            assert limited > 0
            response = second.post(
                "/api/v1/auth/native/refresh",
                headers=NATIVE,
                json={"refresh_token": other["refresh_token"]},
            )
            assert response.status_code == 200, response.text

    def test_successful_logins_do_not_consume_account_limit(self, identity_app, account, db_engine):
        with TestClient(identity_app, base_url="https://testserver") as client:
            for _ in range(6):
                web_login(client, account)  # helper asserts 200
        with Session(db_engine) as session:
            for key in (f"login-account:{account.login_name}", "login-source:testclient"):
                row = session.get(LoginThrottle, service.token_hash("throttle", key))
                assert row is None or row.attempts == 0

    def test_five_failures_lock_even_with_success_between_and_messages_differ(
        self, identity_app, account
    ):
        wrong = {
            "login_name": account.login_name,
            "password": secrets.token_urlsafe(24),
            "device_label": "PC",
        }
        right = {**wrong, "password": account.password}
        with TestClient(identity_app, base_url="https://testserver") as client:

            def post(body):
                return client.post("/api/v1/auth/web/login", headers={"Origin": ORIGIN}, json=body)

            failures = [post(wrong) for _ in range(4)]
            assert post(right).status_code == 200  # success is not a failure
            failures.append(post(wrong))
            assert [r.status_code for r in failures] == [401] * 5
            assert {
                (r.json()["error"]["code"], r.json()["error"]["message"]) for r in failures
            } == {("UNAUTHENTICATED", "로그인 정보를 확인해 주세요.")}
            locked = post(right)
            assert locked.status_code == 429
            assert (locked.json()["error"]["code"], locked.json()["error"]["message"]) == (
                "RATE_LIMITED",
                "잠시 후 다시 시도해 주세요.",
            )

    def test_successful_reauthentication_does_not_consume_limit(self, identity_app, account):
        with TestClient(identity_app, base_url="https://testserver") as client:
            headers = {**NATIVE, **bearer(native_login(client, account))}
            for _ in range(6):
                assert (
                    client.post(
                        "/api/v1/auth/native/reauthenticate",
                        headers=headers,
                        json={"password": account.password},
                    ).status_code
                    == 200
                )

    def test_refund_never_goes_negative_or_touches_expired_windows(self, db_engine):
        now = service.utcnow()
        rows = {
            "current": (now, 1),
            "zero": (now, 0),
            "expired": (now - service.THROTTLE_WINDOW, 3),
        }
        with Session(db_engine) as session:
            session.add_all(
                LoginThrottle(
                    key_hash=service.token_hash("throttle", k), window_started_at=t, attempts=a
                )
                for k, (t, a) in rows.items()
            )
            session.commit()
            service._refund_attempts(session, ["zero", "expired", "current", "missing"])
            session.commit()
            assert [
                session.get(LoginThrottle, service.token_hash("throttle", k)).attempts
                for k in ("current", "zero", "expired")
            ] == [0, 0, 3]

    @pytest.mark.parametrize("transport", ["web", "native"])
    def test_password_reauthentication_preserves_device_session_and_expiry(
        self, identity_app, account, db_engine, transport
    ):
        with TestClient(identity_app, base_url="https://testserver") as client:
            headers = (
                csrf(web_login(client, account))
                if transport == "web"
                else {**NATIVE, **bearer(native_login(client, account))}
            )
            old_authentication = service.utcnow() - timedelta(minutes=6)
            with Session(db_engine) as session:
                auth = session.scalar(select(AuthSession))
                identity, device_id, expires_at = auth.id, auth.device_id, auth.expires_at
                old_session_hash = auth.session_hash
                auth.authenticated_at = old_authentication
                session.commit()
            path = f"/api/v1/auth/{transport}/reauthenticate"
            failed = client.post(
                path, headers=headers, json={"password": secrets.token_urlsafe(24)}
            )
            assert failed.status_code == 403
            assert failed.json()["error"]["code"] == "REAUTHENTICATION_FAILED"
            assert client.get("/api/v1/me", headers=headers).status_code == 200
            with Session(db_engine) as session:
                assert session.get(AuthSession, identity).authenticated_at == old_authentication
            accepted = client.post(path, headers=headers, json={"password": account.password})
            assert accepted.status_code == 200
            assert set(accepted.json()) == {
                "user_id",
                "member_id",
                "household_id",
                "display_name",
                "role",
            }
            assert "set-cookie" not in accepted.headers
            with Session(db_engine) as session:
                auth = session.get(AuthSession, identity)
                assert auth.authenticated_at > old_authentication
                assert auth.expires_at == expires_at
                assert auth.device_id == device_id and auth.session_hash == old_session_hash
                assert session.scalar(select(func.count()).select_from(AuthSession)) == 1
                assert session.scalar(select(func.count()).select_from(RegisteredDevice)) == 1
                assert session.scalar(select(func.count()).select_from(RefreshToken)) == (
                    1 if transport == "native" else 0
                )

    def test_web_reauthentication_requires_csrf_and_a_live_session(self, identity_app, account):
        with TestClient(identity_app, base_url="https://testserver") as client:
            login = web_login(client, account)
            missing = client.post(
                "/api/v1/auth/web/reauthenticate",
                headers={"Origin": ORIGIN},
                json={"password": account.password},
            )
            assert missing.status_code == 403
            assert missing.json()["error"]["code"] == "CSRF_FAILED"
            client.post("/api/v1/auth/web/logout", headers=csrf(login))
            assert (
                client.post(
                    "/api/v1/auth/web/reauthenticate",
                    headers=csrf(login),
                    json={"password": account.password},
                ).status_code
                == 401
            )

    @pytest.mark.parametrize("changed", ["device", "session"])
    def test_reauthentication_rechecks_revocation_after_admission_commit(
        self, identity_app, account, db_engine, monkeypatch, changed
    ):
        with TestClient(identity_app, base_url="https://testserver") as client:
            tokens = native_login(client, account)
            admission = service._admit_attempt

            def revoke_after_admission(session, buckets, now):
                admission(session, buckets, now)
                with Session(db_engine) as other:
                    if changed == "device":
                        device = other.scalar(select(RegisteredDevice))
                        device.status = "revoked"
                        device.revoked_at = now
                    else:
                        other.scalar(select(AuthSession)).revoked_at = now
                    other.commit()

            monkeypatch.setattr(service, "_admit_attempt", revoke_after_admission)
            result = client.post(
                "/api/v1/auth/native/reauthenticate",
                headers={**NATIVE, **bearer(tokens)},
                json={"password": account.password},
            )
            assert result.status_code == 401
            assert client.get("/api/v1/me", headers=bearer(tokens)).status_code == 401

    def test_reauthentication_rate_limit_preserves_existing_session(self, identity_app, account):
        with TestClient(identity_app, base_url="https://testserver") as client:
            tokens = native_login(client, account)
            headers = {**NATIVE, **bearer(tokens)}
            for _ in range(5):
                assert (
                    client.post(
                        "/api/v1/auth/native/reauthenticate",
                        headers=headers,
                        json={"password": secrets.token_urlsafe(24)},
                    ).status_code
                    == 403
                )
            assert (
                client.post(
                    "/api/v1/auth/native/reauthenticate",
                    headers=headers,
                    json={"password": account.password},
                ).status_code
                == 429
            )
            assert client.get("/api/v1/me", headers=bearer(tokens)).status_code == 200

    def test_shared_session_issuance_keeps_commit_with_verified_caller(self, db_engine, account):
        pending_device = uuid4()
        with Session(db_engine) as session:
            result = service.issue_session(
                session,
                session.get(User, account.user_id),
                session.get(HouseholdMember, account.member_id),
                "합성 인증 기기",
                "native",
                device_id=pending_device,
            )
            assert result.native_tokens is not None
            assert session.get(RegisteredDevice, pending_device) is not None
            assert session.scalar(select(func.count()).select_from(AuthSession)) == 1
            assert session.scalar(select(func.count()).select_from(RefreshToken)) == 1
            session.rollback()
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(RegisteredDevice)) == 0
            assert session.scalar(select(func.count()).select_from(AuthSession)) == 0
            assert session.scalar(select(func.count()).select_from(RefreshToken)) == 0

    @pytest.mark.parametrize("disabled", ["user", "member"])
    def test_shared_session_issuance_rechecks_active_account(self, db_engine, account, disabled):
        with Session(db_engine) as session:
            user = session.get(User, account.user_id)
            member = session.get(HouseholdMember, account.member_id)
            if disabled == "user":
                user.disabled_at = service.utcnow()
            else:
                member.status = "revoked"
            session.commit()
            with pytest.raises(DomainError) as rejected:
                service.issue_session(session, user, member, "합성 기기", "web")
            assert rejected.value.status == 401
            assert session.scalar(select(func.count()).select_from(AuthSession)) == 0

    def test_operator_renewal_replaces_expired_code_without_new_household(self, db_engine):
        password = secrets.token_urlsafe(24)
        with Session(db_engine) as session:
            original = service.create_bootstrap_invitation(session, "합성 가계 H1", "synthetic_a")
            session.commit()
            session.get(Invitation, original.id).expires_at = service.utcnow() - timedelta(
                minutes=1
            )
            session.commit()
            renewed = service.renew_bootstrap_invitation(session, "synthetic_a")
            session.commit()
            assert session.scalar(select(func.count()).select_from(Household)) == 1
            assert session.get(Invitation, original.id).revoked_at is not None
            with pytest.raises(DomainError) as old_code:
                service.accept_invitation(
                    session,
                    InvitationAcceptance(
                        token=original.token,
                        password=password,
                        display_name="합성 A",
                    ),
                    "synthetic-source",
                )
            assert old_code.value.code == "INVALID_INVITATION"
            session.rollback()
            member = service.accept_invitation(
                session,
                InvitationAcceptance(
                    token=renewed.token,
                    password=password,
                    display_name="합성 A",
                ),
                "synthetic-source",
            )
            # Even a revoked historical membership means bootstrap must never reset an account.
            session.get(HouseholdMember, member.member_id).status = "revoked"
            session.commit()
            with pytest.raises(DomainError) as enrolled:
                service.renew_bootstrap_invitation(session, "synthetic_other")
            assert enrolled.value.code == "BOOTSTRAP_RENEWAL_UNAVAILABLE"

    def test_bootstrap_is_one_use_hashed_and_refuses_second_household(self, db_engine):
        password = secrets.token_urlsafe(24)
        with Session(db_engine) as session:
            invitation = service.create_bootstrap_invitation(session, "합성 가계 H1", "synthetic_a")
            session.commit()
            stored = session.get(Invitation, invitation.id)
            assert stored.token_hash == service.token_hash("invite", invitation.token)
            assert 0 < (stored.expires_at - service.utcnow()).total_seconds() <= 900
            request = InvitationAcceptance(
                token=invitation.token,
                password=password,
                display_name="합성 A",
            )
            member = service.accept_invitation(session, request, "synthetic-source")
            user = session.get(User, member.user_id)
            assert user.password_hash.startswith("$argon2id$")
            assert service.PASSWORD_HASHER.verify(user.password_hash, password)
            with pytest.raises(DomainError) as reused:
                service.accept_invitation(session, request, "synthetic-source")
            assert reused.value.code == "INVALID_INVITATION"
            session.rollback()
            with pytest.raises(DomainError) as second:
                service.create_bootstrap_invitation(session, "합성 가계 H2", "synthetic_b")
            assert second.value.code == "HOUSEHOLD_EXISTS"

    def test_web_cookie_csrf_and_logout(self, identity_app, db_engine, account):
        with TestClient(identity_app, base_url="https://testserver") as client:
            missing_origin = client.post(
                "/api/v1/auth/web/login",
                json={
                    "login_name": account.login_name,
                    "password": account.password,
                    "device_label": "PC",
                },
            )
            assert missing_origin.status_code == 403
            response = web_login(client, account)
            cookie_header = response.headers["set-cookie"]
            assert "HttpOnly" in cookie_header and "Secure" in cookie_header
            assert "SameSite=strict" in cookie_header and "Path=/" in cookie_header
            assert set(response.json()) == {"member", "csrf_token", "expires_at"}
            raw_cookie = client.cookies[SESSION_COOKIE]
            with Session(db_engine) as session:
                auth = session.scalar(select(AuthSession))
                assert auth.session_hash == service.token_hash("session", raw_cookie)
                assert auth.csrf_hash == service.token_hash("csrf", response.json()["csrf_token"])
            me = client.get("/api/v1/me")
            assert me.status_code == 200
            assert me.json()["household_id"] == str(account.household_id)
            assert me.headers["cache-control"] == "no-store"
            invitation = {"intended_login": "synthetic_partner"}
            assert (
                client.post(
                    "/api/v1/household/invitations", json=invitation, headers={"Origin": ORIGIN}
                ).status_code
                == 403
            )
            assert (
                client.post(
                    "/api/v1/household/invitations",
                    json=invitation,
                    headers={
                        "Origin": "https://untrusted.invalid",
                        "X-CSRF-Token": response.json()["csrf_token"],
                    },
                ).status_code
                == 403
            )
            assert (
                client.post(
                    "/api/v1/household/invitations", json=invitation, headers=csrf(response)
                ).status_code
                == 201
            )
            assert (
                client.post("/api/v1/auth/web/logout", headers={"Origin": ORIGIN}).status_code
                == 403
            )
            assert client.post("/api/v1/auth/web/logout", headers=csrf(response)).status_code == 204
            assert client.get("/api/v1/me").status_code == 401
        with Session(db_engine) as session:
            assert session.scalar(select(AuthSession.revoked_at)) is not None

    def test_csrf_is_bound_to_session_and_can_be_renewed(self, identity_app, account):
        with (
            TestClient(identity_app, base_url="https://testserver") as first,
            TestClient(identity_app, base_url="https://testserver") as second,
        ):
            first_login = web_login(first, account)
            second_login = web_login(second, account)
            invitation = {"intended_login": "synthetic_partner"}
            assert (
                second.post(
                    "/api/v1/household/invitations", json=invitation, headers=csrf(first_login)
                ).status_code
                == 403
            )
            renewed = second.get("/api/v1/auth/web/csrf")
            assert renewed.status_code == 200
            assert (
                second.post(
                    "/api/v1/household/invitations", json=invitation, headers=csrf(second_login)
                ).status_code
                == 403
            )
            assert (
                second.post(
                    "/api/v1/household/invitations", json=invitation, headers=csrf(renewed)
                ).status_code
                == 201
            )

    @pytest.mark.parametrize(
        "browser_headers",
        [
            {},
            {NATIVE_HEADER: "1", "Origin": ORIGIN},
            {NATIVE_HEADER: "1", "Cookie": "unrelated=synthetic"},
        ],
    )
    def test_native_token_endpoint_excludes_browser_transport(
        self, identity_app, account, browser_headers
    ):
        with TestClient(identity_app, base_url="https://testserver") as client:
            response = client.post(
                "/api/v1/auth/native/login",
                headers=browser_headers,
                json={
                    "login_name": account.login_name,
                    "password": account.password,
                    "device_label": "PC",
                },
            )
            assert response.status_code == 403
            assert "access_token" not in response.json() and "refresh_token" not in response.json()

    def test_refresh_rotation_reuse_revokes_entire_session(self, identity_app, db_engine, account):
        with TestClient(identity_app, base_url="https://testserver") as client:
            original = native_login(client, account)
            assert original["expires_in"] == 600
            refreshed = client.post(
                "/api/v1/auth/native/refresh",
                headers=NATIVE,
                json={"refresh_token": original["refresh_token"]},
            )
            assert refreshed.status_code == 200
            current = refreshed.json()
            assert client.get("/api/v1/me", headers=bearer(original)).status_code == 401
            assert client.get("/api/v1/me", headers=bearer(current)).status_code == 200
            replay = client.post(
                "/api/v1/auth/native/refresh",
                headers=NATIVE,
                json={"refresh_token": original["refresh_token"]},
            )
            assert replay.status_code == 401
            assert client.get("/api/v1/me", headers=bearer(current)).status_code == 401
            assert (
                client.post(
                    "/api/v1/auth/native/refresh",
                    headers=NATIVE,
                    json={"refresh_token": current["refresh_token"]},
                ).status_code
                == 401
            )
        with Session(db_engine) as session:
            assert session.scalar(select(AuthSession.revoked_at)) is not None
            rows = list(session.scalars(select(RefreshToken)))
            assert len(rows) == 2
            assert sum(row.consumed_at is not None for row in rows) == 1
            expected_hashes = {
                service.token_hash("refresh", tokens["refresh_token"])
                for tokens in (original, current)
            }
            assert {row.token_hash for row in rows} == expected_hashes

    @pytest.mark.parametrize("hours, idle_minutes", [(0, 31), (13, 0)])
    def test_web_idle_and_absolute_expiration(
        self, identity_app, db_engine, account, hours, idle_minutes
    ):
        with TestClient(identity_app, base_url="https://testserver") as client:
            web_login(client, account)
            with Session(db_engine) as session:
                auth = session.scalar(select(AuthSession))
                if hours:
                    auth.expires_at = service.utcnow() - timedelta(hours=hours)
                else:
                    auth.last_seen_at = service.utcnow() - timedelta(minutes=idle_minutes)
                session.commit()
            assert client.get("/api/v1/me").status_code == 401

    def test_native_access_expiry_and_absolute_refresh_expiry(
        self, identity_app, account, monkeypatch
    ):
        now = service.utcnow()
        with TestClient(identity_app, base_url="https://testserver") as client:
            original = native_login(client, account)
            monkeypatch.setattr(service, "utcnow", lambda: now + timedelta(minutes=11))
            assert client.get("/api/v1/me", headers=bearer(original)).status_code == 401
            refreshed = client.post(
                "/api/v1/auth/native/refresh",
                headers=NATIVE,
                json={"refresh_token": original["refresh_token"]},
            )
            assert refreshed.status_code == 200
            assert refreshed.json()["refresh_expires_at"] == original["refresh_expires_at"]
            monkeypatch.setattr(service, "utcnow", lambda: now + timedelta(days=31))
            assert (
                client.post(
                    "/api/v1/auth/native/refresh",
                    headers=NATIVE,
                    json={"refresh_token": refreshed.json()["refresh_token"]},
                ).status_code
                == 401
            )

    @pytest.mark.parametrize("revocation", ["user", "member", "device", "session"])
    def test_each_request_checks_active_identity(
        self, identity_app, db_engine, account, revocation
    ):
        with TestClient(identity_app, base_url="https://testserver") as client:
            tokens = native_login(client, account)
            with Session(db_engine) as session:
                if revocation == "user":
                    session.get(User, account.user_id).disabled_at = service.utcnow()
                elif revocation == "member":
                    session.get(HouseholdMember, account.member_id).status = "revoked"
                elif revocation == "device":
                    session.scalar(select(RegisteredDevice)).status = "revoked"
                else:
                    session.scalar(select(AuthSession)).revoked_at = service.utcnow()
                session.commit()
            assert client.get("/api/v1/me", headers=bearer(tokens)).status_code == 401
            assert (
                client.post(
                    "/api/v1/auth/native/refresh",
                    headers=NATIVE,
                    json={"refresh_token": tokens["refresh_token"]},
                ).status_code
                == 401
            )

    def test_recent_login_required_and_refresh_cannot_reset_it(
        self, identity_app, account, monkeypatch
    ):
        now = service.utcnow()
        with TestClient(identity_app, base_url="https://testserver") as client:
            tokens = native_login(client, account)
            monkeypatch.setattr(service, "utcnow", lambda: now + timedelta(minutes=6))
            refreshed = client.post(
                "/api/v1/auth/native/refresh",
                headers=NATIVE,
                json={"refresh_token": tokens["refresh_token"]},
            )
            assert refreshed.status_code == 200
            current = refreshed.json()
            assert client.get("/api/v1/me", headers=bearer(current)).status_code == 200
            assert (
                client.post(
                    "/api/v1/household/invitations",
                    headers=bearer(current),
                    json={"intended_login": "synthetic_partner"},
                ).status_code
                == 403
            )
            devices = client.get("/api/v1/devices", headers=bearer(current)).json()["items"]
            assert (
                client.delete(
                    "/api/v1/devices/" + devices[0]["id"],
                    headers={
                        **bearer(current),
                        "If-Match": f'"{devices[0]["version"]}"',
                    },
                ).status_code
                == 403
            )

    def test_device_version_conflict_and_current_device_revocation(self, identity_app, account):
        with TestClient(identity_app, base_url="https://testserver") as client:
            tokens = native_login(client, account)
            device = client.get("/api/v1/devices", headers=bearer(tokens)).json()["items"][0]
            stale = client.delete(
                "/api/v1/devices/" + device["id"],
                headers={
                    **bearer(tokens),
                    "If-Match": '"999"',
                },
            )
            assert stale.status_code == 409
            assert stale.json()["error"]["current_version"] == device["version"]
            assert (
                client.delete(
                    "/api/v1/devices/" + device["id"],
                    headers={
                        **bearer(tokens),
                        "If-Match": f'"{device["version"]}"',
                    },
                ).status_code
                == 204
            )
            assert client.get("/api/v1/me", headers=bearer(tokens)).status_code == 401

    def test_revoking_a_revoked_device_keeps_the_first_revocation(
        self, identity_app, db_engine, account, monkeypatch
    ):
        with (
            TestClient(identity_app, base_url="https://testserver") as first,
            TestClient(identity_app, base_url="https://testserver") as second,
        ):
            native_login(first, account)
            tokens = native_login(second, account)
            devices = second.get("/api/v1/devices", headers=bearer(tokens))
            assert devices.status_code == 200
            other = next(row for row in devices.json()["items"] if not row["current"])
            revoke = {**bearer(tokens), "If-Match": f'"{other["version"]}"'}
            assert (
                second.delete("/api/v1/devices/" + other["id"], headers=revoke).status_code == 204
            )
            with Session(db_engine) as session:
                revoked = session.get(RegisteredDevice, UUID(other["id"]))
                first_revoked_at, version = revoked.revoked_at, revoked.version
            later = service.utcnow() + timedelta(minutes=1)
            monkeypatch.setattr(service, "utcnow", lambda: later)
            again = {**bearer(tokens), "If-Match": f'"{version}"'}
            assert second.delete("/api/v1/devices/" + other["id"], headers=again).status_code == 204
        with Session(db_engine) as session:
            assert session.get(RegisteredDevice, UUID(other["id"])).revoked_at == first_revoked_at

    def test_rate_limit_persists_failed_logins_without_logging_secrets(
        self, identity_app, account, caplog
    ):
        wrong = secrets.token_urlsafe(24)
        with TestClient(identity_app, base_url="https://testserver") as client:
            for _ in range(5):
                response = client.post(
                    "/api/v1/auth/web/login",
                    headers={"Origin": ORIGIN},
                    json={
                        "login_name": account.login_name,
                        "password": wrong,
                        "device_label": "PC",
                    },
                )
                assert response.status_code == 401
            limited = client.post(
                "/api/v1/auth/web/login",
                headers={"Origin": ORIGIN},
                json={
                    "login_name": account.login_name,
                    "password": account.password,
                    "device_label": "PC",
                },
            )
            assert limited.status_code == 429
        assert all(value not in caplog.text for value in (wrong, account.password))

    def test_expired_throttle_buckets_are_reclaimed_without_resetting_active_limits(
        self, db_engine
    ):
        now = service.utcnow()
        active_key = service.token_hash("throttle", "active")
        with Session(db_engine) as session:
            session.add_all(
                [
                    LoginThrottle(
                        key_hash=service.token_hash("throttle", f"expired-{index}"),
                        window_started_at=now - service.THROTTLE_WINDOW,
                        attempts=30,
                    )
                    for index in range(service.THROTTLE_CLEANUP_BATCH * 2)
                ]
            )
            session.add(LoginThrottle(key_hash=active_key, window_started_at=now, attempts=1))
            session.commit()
            for remaining in (service.THROTTLE_CLEANUP_BATCH + 1, 1):
                with pytest.raises(DomainError) as failure:
                    service._admit_attempt(session, [("active", 1)], now)
                assert failure.value.code == "RATE_LIMITED"
                assert session.scalar(select(func.count()).select_from(LoginThrottle)) == remaining
                assert session.get(LoginThrottle, active_key).attempts == 1

    def test_concurrent_expiry_cleanup_keeps_one_shared_admission_limit(self, db_engine):
        now = service.utcnow()
        key = "shared-expiring-key"
        digest = service.token_hash("throttle", key)
        with Session(db_engine) as session:
            session.add(
                LoginThrottle(
                    key_hash=digest, window_started_at=now - service.THROTTLE_WINDOW, attempts=8
                )
            )
            session.commit()
        start = Barrier(8)

        def attempt():
            start.wait(timeout=10)
            with Session(db_engine) as session:
                try:
                    service._admit_attempt(session, [(key, 4)], now)
                    return True
                except DomainError as failure:
                    assert failure.code == "RATE_LIMITED"
                    return False

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(attempt) for _ in range(8)]
            admitted = [future.result(timeout=15) for future in futures]
        assert admitted.count(True) == 4
        with Session(db_engine) as session:
            assert session.get(LoginThrottle, digest).attempts == 4

    def test_invite_reissue_expiry_reuse_and_two_member_limit(
        self, identity_app, account, monkeypatch
    ):
        with TestClient(identity_app, base_url="https://testserver") as client:
            login = web_login(client, account)
            first = client.post(
                "/api/v1/household/invitations",
                headers=csrf(login),
                json={"intended_login": "synthetic_partner"},
            ).json()
            second = client.post(
                "/api/v1/household/invitations",
                headers=csrf(login),
                json={"intended_login": "synthetic_partner"},
            ).json()
            acceptance = {
                "token": first["token"],
                "password": secrets.token_urlsafe(24),
                "display_name": "합성 B",
            }
            assert (
                client.post(
                    "/api/v1/auth/invitations/accept", headers={"Origin": ORIGIN}, json=acceptance
                ).status_code
                == 400
            )
            acceptance["token"] = second["token"]
            now = service.utcnow()
            monkeypatch.setattr(service, "utcnow", lambda: now + timedelta(minutes=16))
            assert (
                client.post(
                    "/api/v1/auth/invitations/accept", headers={"Origin": ORIGIN}, json=acceptance
                ).status_code
                == 400
            )
            monkeypatch.setattr(service, "utcnow", lambda: now)
            assert (
                client.post(
                    "/api/v1/auth/invitations/accept", headers={"Origin": ORIGIN}, json=acceptance
                ).status_code
                == 201
            )
            assert (
                client.post(
                    "/api/v1/auth/invitations/accept", headers={"Origin": ORIGIN}, json=acceptance
                ).status_code
                == 400
            )
            assert (
                client.post(
                    "/api/v1/household/invitations",
                    headers=csrf(login),
                    json={"intended_login": "synthetic_third"},
                ).status_code
                == 409
            )
            assert len(client.get("/api/v1/household/members").json()) == 2

    def test_concurrent_acceptance_allows_only_one_remaining_slot(self, db_engine, account):
        tokens = [secrets.token_urlsafe(32), secrets.token_urlsafe(32)]
        with Session(db_engine) as session:
            session.add_all(
                [
                    Invitation(
                        household_id=account.household_id,
                        intended_login=f"synthetic_partner_{index}",
                        token_hash=service.token_hash("invite", token),
                        kind="partner",
                        created_by_member_id=account.member_id,
                        expires_at=service.utcnow() + timedelta(minutes=15),
                    )
                    for index, token in enumerate(tokens)
                ]
            )
            session.commit()
        barrier = Barrier(2)

        def accept(token):
            with Session(db_engine) as session:
                barrier.wait(timeout=10)
                try:
                    service.accept_invitation(
                        session,
                        InvitationAcceptance(
                            token=token,
                            password=secrets.token_urlsafe(24),
                            display_name="합성 B",
                        ),
                        "synthetic-concurrency",
                    )
                    return 201
                except DomainError as exc:
                    return exc.status

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(accept, token) for token in tokens]
            outcomes = [future.result(timeout=20) for future in futures]
        assert sorted(outcomes) == [201, 409]
        with Session(db_engine) as session:
            count = session.scalar(
                select(func.count())
                .select_from(HouseholdMember)
                .where(
                    HouseholdMember.household_id == account.household_id,
                    HouseholdMember.status == "active",
                )
            )
            assert count == 2

    def test_concurrent_refresh_detects_reuse(self, db_engine, account):
        with Session(db_engine) as session:
            original = service.login(
                session,
                LoginRequest(
                    login_name=account.login_name,
                    password=account.password,
                    device_label="합성 Android",
                ),
                "synthetic-native",
                "native",
            ).native_tokens
        barrier = Barrier(2)

        def rotate():
            with Session(db_engine) as session:
                barrier.wait(timeout=10)
                try:
                    service.rotate_refresh(session, original.refresh_token, "synthetic-concurrency")
                    return 200
                except DomainError as exc:
                    return exc.status

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(rotate) for _ in range(2)]
            outcomes = [future.result(timeout=20) for future in futures]
        assert sorted(outcomes) == [200, 401]
        with Session(db_engine) as session:
            assert session.scalar(select(AuthSession.revoked_at)) is not None

    def test_parallel_reads_share_one_session_without_spurious_version_conflicts(
        self,
        db_engine,
        account,
    ):
        with Session(db_engine) as session:
            authenticated = service.login(
                session,
                LoginRequest(
                    login_name=account.login_name,
                    password=account.password,
                    device_label="합성 Android",
                ),
                "synthetic-native",
                "native",
            )
        barrier = Barrier(2)

        def read():
            with Session(db_engine) as session:
                barrier.wait(timeout=10)
                principal = service.authenticate(session, authenticated.token, "native")
                session.commit()
                return principal.user_id

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(read) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        assert results == [account.user_id, account.user_id]

    def test_request_and_device_revocation_do_not_invert_locks(self, db_engine, account):
        with Session(db_engine) as session:
            actor = service.login(
                session,
                LoginRequest(
                    login_name=account.login_name,
                    password=account.password,
                    device_label="합성 관리 기기",
                ),
                "synthetic-manager",
                "native",
            )
            target = service.login(
                session,
                LoginRequest(
                    login_name=account.login_name,
                    password=account.password,
                    device_label="합성 대상 기기",
                ),
                "synthetic-target",
                "native",
            )
            target_principal = service.authenticate(session, target.token, "native")
            session.commit()
        device_locked = Event()
        request_authorized = Event()
        revoked = Event()

        def revoke():
            with Session(db_engine) as session:
                principal = service.authenticate(session, actor.token, "native")
                device = scoped_entity(
                    session,
                    RegisteredDevice,
                    target_principal.device_id,
                    principal,
                    for_update=True,
                )
                device_locked.set()
                assert request_authorized.wait(10), (
                    "Authentication waited for the target device lock"
                )
                service.revoke_device(session, principal, device)
                revoked.set()

        def request():
            assert device_locked.wait(10), "Revocation did not acquire the target device lock"
            with Session(db_engine) as session:
                principal = service.authenticate(session, target.token, "native")
                request_authorized.set()
                assert revoked.wait(10), "Revocation waited for the target request's session lock"
                session.commit()
                return principal.user_id

        with ThreadPoolExecutor(max_workers=2) as pool:
            revocation = pool.submit(revoke)
            pending_request = pool.submit(request)
            revocation.result(timeout=20)
            assert pending_request.result(timeout=20) == account.user_id
        with Session(db_engine) as session:
            with pytest.raises(DomainError) as access:
                service.authenticate(session, target.token, "native")
            assert access.value.status == 401
            session.rollback()
            with pytest.raises(DomainError) as refresh:
                service.rotate_refresh(
                    session, target.native_tokens.refresh_token, "synthetic-target"
                )
            assert refresh.value.status == 401

    def _age_device(self, db_engine, device_id, age):
        # Moves every session of a synthetic device into the past, as if it was last used then.
        then = service.utcnow() - age
        with Session(db_engine) as session:
            device = session.get(RegisteredDevice, device_id)
            device.last_seen_at = then
            for row in session.scalars(
                select(AuthSession).where(AuthSession.device_id == device_id)
            ):
                row.last_seen_at = then
                row.authenticated_at = then
                row.expires_at = min(row.expires_at, then + timedelta(hours=12))
            session.commit()

    def _devices(self, client, tokens):
        response = client.get("/api/v1/devices", headers=bearer(tokens))
        assert response.status_code == 200, response.text
        return {row["label"]: row for row in response.json()["items"]}

    def test_device_login_state_is_active_expired_or_revoked(
        self, identity_app, db_engine, account
    ):
        with TestClient(identity_app, base_url="https://testserver") as browser:
            web_login(browser, account)
        with TestClient(identity_app, base_url="https://testserver") as client:
            tokens = native_login(client, account)
            devices = self._devices(client, tokens)
            assert devices["합성 Android"]["login_state"] == "active"
            assert devices["합성 PC"]["login_state"] == "active"
            # A web session ends after the idle limit even before its absolute expiry.
            self._age_device(db_engine, UUID(devices["합성 PC"]["id"]), timedelta(hours=1))
            assert self._devices(client, tokens)["합성 PC"]["login_state"] == "expired"
            pc = self._devices(client, tokens)["합성 PC"]
            assert (
                client.delete(
                    "/api/v1/devices/" + pc["id"],
                    headers={**bearer(tokens), "If-Match": f'"{pc["version"]}"'},
                ).status_code
                == 204
            )
            assert self._devices(client, tokens)["합성 PC"]["login_state"] == "revoked"

    @pytest.mark.parametrize(("days", "listed"), [(89, True), (91, False)])
    def test_devices_unused_for_90_days_are_left_out_of_the_list(
        self, identity_app, db_engine, account, days, listed
    ):
        with TestClient(identity_app, base_url="https://testserver") as browser:
            web_login(browser, account)
        with TestClient(identity_app, base_url="https://testserver") as client:
            tokens = native_login(client, account)
            pc = self._devices(client, tokens)["합성 PC"]
            self._age_device(db_engine, UUID(pc["id"]), timedelta(days=days))
            devices = self._devices(client, tokens)
            assert ("합성 PC" in devices) is listed
            assert devices["합성 Android"]["login_state"] == "active"
            if listed:
                assert devices["합성 PC"]["login_state"] == "expired"
        with Session(db_engine) as session:
            # Hidden, not deleted: sessions and audit history keep referring to the row.
            assert session.get(RegisteredDevice, UUID(pc["id"])) is not None

    def test_device_activity_comes_from_session_without_advancing_edit_version(
        self,
        identity_app,
        db_engine,
        account,
        monkeypatch,
    ):
        now = service.utcnow()
        with TestClient(identity_app, base_url="https://testserver") as client:
            tokens = native_login(client, account)
            later = now + timedelta(minutes=1)
            monkeypatch.setattr(service, "utcnow", lambda: later)
            assert client.get("/api/v1/me", headers=bearer(tokens)).status_code == 200
            device = client.get("/api/v1/devices", headers=bearer(tokens)).json()["items"][0]
            assert datetime.fromisoformat(device["last_seen_at"]) == later
            assert device["version"] == 1
        with Session(db_engine) as session:
            stored = session.get(RegisteredDevice, UUID(device["id"]))
            assert stored.last_seen_at < later
            assert stored.version == 1
