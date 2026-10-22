"""Step-up paths take household and credential locks in one order, so they cannot deadlock."""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from psycopg import errors as pg_errors
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_accounts import make_actor
from test_passkeys import NATIVE_ORIGIN, NATIVE_POLICY, SyntheticAuthenticator
from test_vault import initialize, vault_app  # noqa: F401 -- fixture
from webauthn.helpers import base64url_to_bytes

from sallimbook.exports import service as export_service
from sallimbook.exports.archive import Budget
from sallimbook.identity import service as identity
from sallimbook.identity.passkeys import service as passkeys
from sallimbook.identity.passkeys.models import StepUpPurpose
from sallimbook.identity.passkeys.schemas import (
    AssertionVerification,
    RegisterOptionsRequest,
    RegisterVerification,
    StepUpOptionsRequest,
)
from sallimbook.identity.schemas import LoginRequest
from sallimbook.vault import service as vault_service

pytestmark = pytest.mark.database


class LockProbe:
    """Hold each thread between its first and second lock kind until both threads got there.

    With opposite orders both threads then wait on each other's first lock; with one order the
    second thread is blocked on the first lock and the barrier simply times out.
    """

    def __init__(self):
        self.barrier = threading.Barrier(2, timeout=2)
        self.local = threading.local()

    def reset(self):
        self.local.kinds = []

    def wrap(self, kind, function):
        def probed(*args, **kwargs):
            if self.local.kinds and kind not in self.local.kinds:
                try:
                    self.barrier.wait()
                except threading.BrokenBarrierError:
                    pass
            result = function(*args, **kwargs)
            self.local.kinds.append(kind)
            return result

        return probed


def second_session(engine, actor):
    """The same user signed in on another device: another session and device row."""
    with Session(engine) as session:
        result = identity.login(
            session,
            LoginRequest(
                login_name=actor.login_name,
                password=actor.password,
                device_label="합성 두 번째 기기",
            ),
            "synthetic-second-device",
            "native",
        )
        principal = identity.authenticate(session, result.token, "native")
        session.commit()
    return replace(actor, token=result.token, principal=principal)


def test_export_and_vault_step_up_use_one_lock_order(vault_app, db_engine, monkeypatch):  # noqa: F811
    first = make_actor(db_engine)
    second = second_session(db_engine, first)
    with TestClient(vault_app) as client:
        initialize(client, first)
    authenticator = SyntheticAuthenticator.create()
    with Session(db_engine) as session:
        options = passkeys.registration_options(
            session, first.principal, RegisterOptionsRequest(label="합성 잠금 순서"), NATIVE_POLICY
        )
        passkeys.register_credential(
            session,
            first.principal,
            RegisterVerification(
                challenge_id=options.challenge_id,
                credential=authenticator.registration(
                    base64url_to_bytes(options.public_key["challenge"]), origin=NATIVE_ORIGIN
                ),
            ),
            NATIVE_POLICY,
        )

        def grant(actor, purpose):
            # Both grants rest on the user's one credential row, the row both paths lock.
            options = passkeys.step_up_options(
                session,
                actor.principal,
                StepUpOptionsRequest(purpose=purpose, target_id=actor.household_id),
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
            ).grant_token

        export_token = grant(first, StepUpPurpose.DATA_EXPORT)
        vault_token = grant(second, StepUpPurpose.VAULT_KEY_ROTATION)

    probe = LockProbe()
    monkeypatch.setattr(
        export_service,
        "lock_asset_scope",
        probe.wrap("household", export_service.lock_asset_scope),
    )
    monkeypatch.setattr(
        vault_service,
        "lock_asset_scope",
        probe.wrap("household", vault_service.lock_asset_scope),
    )
    monkeypatch.setattr(
        passkeys,
        "_validated_step_up",
        probe.wrap("credential", passkeys._validated_step_up),
    )

    def run(work):
        probe.reset()
        with Session(db_engine) as session:
            session.execute(text("SET LOCAL lock_timeout = '8000ms'"))
            work(session)
            session.commit()

    def export_authorize(session):
        export_service._authorize(session, first.principal, export_token, Budget())

    def vault_step_up(session):
        vault_service.get_recovery_wrapping(session, second.principal, step_up_token=vault_token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, export_authorize), pool.submit(run, vault_step_up)]
        failures = []
        for future in futures:
            try:
                future.result(timeout=60)
            except DBAPIError as error:
                failures.append(error.orig)
    assert not [
        error
        for error in failures
        if isinstance(error, (pg_errors.DeadlockDetected, pg_errors.LockNotAvailable))
    ], failures
    assert failures == []
