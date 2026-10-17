"""Cross-household access, optimistic edits, and durable exactly-once reservations."""

import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Header, Response
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sallimbook.config import Settings
from sallimbook.core.authorization import (
    Principal,
    require_recent_login,
    require_version,
    scoped_entity,
)
from sallimbook.core.errors import DomainError
from sallimbook.core.http import install_http_contract
from sallimbook.core.idempotency import (
    IdempotencyRecord,
    IdempotentResult,
    payload_hash,
    run_idempotent,
)
from sallimbook.identity import service
from sallimbook.identity.auth_models import AuthSession, HouseholdMember, RegisteredDevice, User
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency
from sallimbook.identity.models import Household
from sallimbook.identity.router import router
from sallimbook.identity.schemas import LoginRequest


def test_idempotency_hash_normalizes_key_order_but_preserves_null_zero_and_strings():
    assert payload_hash({"b": ["1000", None], "a": 0}) == payload_hash(
        {"a": 0, "b": ["1000", None]}
    )
    assert len({payload_hash({"amount": value}) for value in (None, "0", "1000", 0)}) == 4
    with pytest.raises(DomainError) as invalid:
        payload_hash({"amount": 1.25})
    assert invalid.value.status == 422


@pytest.mark.parametrize("header", [None, "7", 'W/"7"', '"0"', "*", '"-1"'])
def test_version_requires_an_explicit_positive_strong_tag(header):
    with pytest.raises(DomainError) as invalid:
        require_version(RegisteredDevice(version=7), header)
    assert invalid.value.status == 400


def test_stale_version_returns_current_version():
    with pytest.raises(DomainError) as stale:
        require_version(RegisteredDevice(version=8), '"7"')
    assert stale.value.status == 409
    assert stale.value.current_version == 8
    require_version(RegisteredDevice(version=8), '"8"')


def test_recent_login_uses_server_timestamp_and_rejects_future_values():
    now = datetime.now(UTC)
    principal = Principal(
        user_id=uuid4(),
        member_id=uuid4(),
        household_id=uuid4(),
        session_id=uuid4(),
        device_id=uuid4(),
        role="owner",
        transport="web",
        authenticated_at=now,
    )
    require_recent_login(principal, now=now)
    for timestamp in (now - timedelta(minutes=6), now + timedelta(minutes=1)):
        with pytest.raises(DomainError) as rejected:
            require_recent_login(replace(principal, authenticated_at=timestamp), now=now)
        assert rejected.value.code == "REAUTHENTICATION_REQUIRED"


@dataclass(frozen=True)
class Scope:
    principal: Principal
    resource_id: UUID
    access_token: str = field(repr=False)

    @property
    def headers(self):
        return {"Authorization": "Bearer " + self.access_token}


@pytest.fixture
def scopes(db_engine):
    result = []
    with Session(db_engine) as session:
        for suffix in ("a", "b"):
            password = secrets.token_urlsafe(24)
            household = Household(name="합성 가계 " + suffix)
            user = User(
                login_name="synthetic_" + suffix,
                display_name="합성 " + suffix,
                password_hash=service.PASSWORD_HASHER.hash(password),
            )
            session.add_all([household, user])
            session.flush()
            member = HouseholdMember(
                household_id=household.id, user_id=user.id, slot=1, role="owner", status="active"
            )
            session.add(member)
            session.commit()
            login = service.login(
                session,
                LoginRequest(
                    login_name=user.login_name,
                    password=password,
                    device_label="합성 인증 기기",
                ),
                "synthetic-" + suffix,
                "native",
            )
            principal = service.authenticate(session, login.token, "native")
            resource = RegisteredDevice(
                household_id=household.id,
                user_id=user.id,
                label="합성 권한 시험 자원",
                platform="android",
                status="active",
                last_seen_at=service.utcnow(),
            )
            session.add(resource)
            session.flush()
            result.append(Scope(principal, resource.id, login.token))
            session.commit()
    return result


class LabelInput(BaseModel):
    label: str


@pytest.fixture
def authorization_app(db_engine):
    app = FastAPI()
    app.state.settings = Settings(environment="test", allowed_origins=[])
    app.state.engine = db_engine
    install_http_contract(app)
    app.include_router(router)

    # These probes exercise the shared guards with real auth; they are never registered in main.
    @app.get("/test-only/resources/{resource_id}")
    def read_resource(resource_id: UUID, actor: PrincipalDependency, session: SessionDependency):
        resource = scoped_entity(session, RegisteredDevice, resource_id, actor)
        result = {"id": str(resource.id), "label": resource.label, "version": resource.version}
        session.commit()
        return result

    @app.patch("/test-only/resources/{resource_id}")
    def edit_resource(
        resource_id: UUID,
        payload: LabelInput,
        actor: PrincipalDependency,
        session: SessionDependency,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ):
        resource = scoped_entity(session, RegisteredDevice, resource_id, actor, for_update=True)
        require_version(resource, if_match)
        resource.label = payload.label
        session.commit()
        return {"version": resource.version}

    @app.delete("/test-only/resources/{resource_id}")
    def delete_resource(resource_id: UUID, actor: PrincipalDependency, session: SessionDependency):
        resource = scoped_entity(session, RegisteredDevice, resource_id, actor, for_update=True)
        session.delete(resource)
        session.commit()
        return Response(status_code=204)

    return app


def create_effect(session, actor):
    resource = RegisteredDevice(
        household_id=actor.household_id,
        user_id=actor.user_id,
        label="합성 멱등 효과",
        platform="web",
        status="active",
        last_seen_at=service.utcnow(),
    )
    session.add(resource)
    session.flush()
    return IdempotentResult(resource.id, "synthetic_effect", resource.version)


@pytest.mark.database
class TestAccessAndIdempotencyDatabase:
    @pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
    def test_h1_cannot_read_edit_or_delete_h2(self, authorization_app, db_engine, scopes, method):
        first, second = scopes
        with TestClient(authorization_app, base_url="https://testserver") as client:
            response = client.request(
                method,
                f"/test-only/resources/{second.resource_id}",
                headers={**first.headers, "If-Match": '"1"'},
                json={"label": "허용되지 않은 합성 변경"} if method == "PATCH" else None,
            )
            assert response.status_code == 404
        with Session(db_engine) as session:
            assert session.get(RegisteredDevice, second.resource_id).label == "합성 권한 시험 자원"

    def test_real_identity_lists_and_device_revocation_do_not_accept_foreign_household(
        self,
        authorization_app,
        scopes,
    ):
        first, second = scopes
        with TestClient(authorization_app, base_url="https://testserver") as client:
            members = client.get(
                "/api/v1/household/members",
                headers=first.headers,
                params={"household_id": str(second.principal.household_id)},
            )
            assert members.status_code == 200
            assert {row["household_id"] for row in members.json()} == {
                str(first.principal.household_id),
            }
            device_ids = {
                row["id"]
                for row in client.get(
                    "/api/v1/devices",
                    headers=first.headers,
                ).json()["items"]
            }
            assert str(second.resource_id) not in device_ids
            assert (
                client.delete(
                    f"/api/v1/devices/{second.resource_id}",
                    headers={
                        **first.headers,
                        "If-Match": '"1"',
                    },
                ).status_code
                == 404
            )

    def test_stale_api_edit_does_not_overwrite_partner_change(self, authorization_app, scopes):
        first = scopes[0]
        with TestClient(authorization_app, base_url="https://testserver") as client:
            url = f"/test-only/resources/{first.resource_id}"
            saved = client.patch(
                url, headers={**first.headers, "If-Match": '"1"'}, json={"label": "합성 최신 수정"}
            )
            assert saved.status_code == 200
            assert saved.json()["version"] == 2
            stale = client.patch(
                url,
                headers={**first.headers, "If-Match": '"1"'},
                json={"label": "합성 오래된 수정"},
            )
            assert stale.status_code == 409
            assert stale.json()["error"]["current_version"] == 2
            assert client.get(url, headers=first.headers).json()["label"] == "합성 최신 수정"

    def test_composite_session_fk_rejects_foreign_household_device(self, db_engine, scopes):
        first, second = scopes
        now = service.utcnow()
        with Session(db_engine) as session:
            session.add(
                AuthSession(
                    household_id=first.principal.household_id,
                    user_id=first.principal.user_id,
                    device_id=second.principal.device_id,
                    kind="web",
                    session_hash=service.token_hash("session", secrets.token_urlsafe(32)),
                    csrf_hash=service.token_hash("csrf", secrets.token_urlsafe(32)),
                    expires_at=now + timedelta(hours=12),
                    authenticated_at=now,
                    last_seen_at=now,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()

    def test_database_member_slots_reject_third_active_member(self, db_engine, scopes):
        household_id = scopes[0].principal.household_id
        with Session(db_engine) as session:
            for index in range(2):
                user = User(
                    login_name=f"synthetic_extra_{index}",
                    display_name="합성 추가 구성원",
                    password_hash=service.PASSWORD_HASHER.hash(secrets.token_urlsafe(24)),
                )
                session.add(user)
                session.flush()
                session.add(
                    HouseholdMember(
                        household_id=household_id,
                        user_id=user.id,
                        slot=2,
                        role="member",
                        status="active",
                    )
                )
                if index == 0:
                    session.commit()
                else:
                    with pytest.raises(IntegrityError):
                        session.commit()

    def test_idempotency_returns_original_reference_and_rejects_changed_payload(
        self, db_engine, scopes
    ):
        actor = scopes[0].principal
        key = str(uuid4())
        with Session(db_engine) as session:
            first = run_idempotent(
                session,
                actor,
                "synthetic.record",
                key,
                {"amount": "1000"},
                lambda: create_effect(session, actor),
            )
            session.commit()
        with Session(db_engine) as session:
            repeated = run_idempotent(
                session,
                actor,
                "synthetic.record",
                key,
                {"amount": "1000"},
                lambda: pytest.fail("Repeated operation executed twice"),
            )
            session.commit()
            assert repeated == first
            with pytest.raises(DomainError) as conflict:
                run_idempotent(
                    session,
                    actor,
                    "synthetic.record",
                    key,
                    {"amount": "1001"},
                    lambda: pytest.fail("Conflicting payload executed"),
                )
            assert conflict.value.status == 409
            session.rollback()
            assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(RegisteredDevice)
                    .where(
                        RegisteredDevice.label == "합성 멱등 효과",
                    )
                )
                == 1
            )

    def test_idempotency_key_is_scoped_to_actor_and_operation(self, db_engine, scopes):
        key = str(uuid4())
        results = []
        with Session(db_engine) as session:
            for actor, operation in (
                (scopes[0].principal, "synthetic.first"),
                (scopes[1].principal, "synthetic.first"),
                (scopes[0].principal, "synthetic.second"),
            ):
                results.append(
                    run_idempotent(
                        session,
                        actor,
                        operation,
                        key,
                        {"amount": "1000"},
                        lambda actor=actor: create_effect(session, actor),
                    )
                )
                session.commit()
            assert len({result.resource_id for result in results}) == 3
            assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 3

    def test_failed_operation_rolls_back_reservation_and_domain_effect(self, db_engine, scopes):
        actor = scopes[0].principal
        key = str(uuid4())
        with Session(db_engine) as session:

            def fail_after_write():
                create_effect(session, actor)
                raise DomainError("SYNTHETIC_FAILURE", "합성 실패", 422)

            with pytest.raises(DomainError):
                run_idempotent(session, actor, "synthetic.record", key, {}, fail_after_write)
            session.rollback()
            assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(RegisteredDevice)
                    .where(
                        RegisteredDevice.label == "합성 멱등 효과",
                    )
                )
                == 0
            )
            run_idempotent(
                session, actor, "synthetic.record", key, {}, lambda: create_effect(session, actor)
            )
            session.commit()
            assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1

    def test_concurrent_duplicate_requests_commit_one_effect(self, db_engine, scopes):
        actor = scopes[0].principal
        key = str(uuid4())
        barrier = Barrier(2)

        def execute():
            with Session(db_engine) as session:
                barrier.wait(timeout=10)
                result = run_idempotent(
                    session,
                    actor,
                    "synthetic.concurrent",
                    key,
                    {"amount": "1000"},
                    lambda: create_effect(session, actor),
                )
                session.commit()
                return result

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(execute) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        assert results[0] == results[1]
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(RegisteredDevice)
                    .where(
                        RegisteredDevice.label == "합성 멱등 효과",
                    )
                )
                == 1
            )
