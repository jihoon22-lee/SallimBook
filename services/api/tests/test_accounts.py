"""Only synthetic account identifiers/keys; actual AES-GCM and PostgreSQL API boundaries."""

import base64
import json
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_passkeys import NATIVE_ORIGIN, NATIVE_POLICY, SyntheticAuthenticator
from webauthn.helpers import base64url_to_bytes

from sallimbook.accounts import service
from sallimbook.accounts.crypto import KeyRing, decrypt_number, encrypt_number
from sallimbook.accounts.models import FinancialAccount
from sallimbook.accounts.router import router
from sallimbook.accounts.schemas import AccountCreate, AccountNumber, AccountPatch, AccountType
from sallimbook.assets import month_service
from sallimbook.assets import service as asset_service
from sallimbook.assets.models import Asset
from sallimbook.assets.month_schemas import MonthDraft
from sallimbook.assets.router import router as asset_router
from sallimbook.cards import service as card_service
from sallimbook.cards.schemas import CardCreate
from sallimbook.config import Settings
from sallimbook.core.audit import AuditEvent
from sallimbook.core.authorization import Principal
from sallimbook.core.errors import DomainError
from sallimbook.core.http import install_http_contract
from sallimbook.identity import service as identity
from sallimbook.identity.auth_models import AuthSession, HouseholdMember, RegisteredDevice, User
from sallimbook.identity.models import Household
from sallimbook.identity.passkeys import service as passkeys
from sallimbook.identity.passkeys.models import AuthCredential, StepUpGrant, StepUpPurpose
from sallimbook.identity.passkeys.schemas import (
    AssertionVerification,
    RegisterOptionsRequest,
    RegisterVerification,
    StepUpOptionsRequest,
)
from sallimbook.identity.router import router as identity_router
from sallimbook.identity.schemas import LoginRequest

SYNTHETIC_NUMBER = "000123-4567890"
ACCOUNT_TYPES = (
    "checking",
    "savings",
    "term_deposit",
    "brokerage",
    "pension_savings",
    "irp",
    "dc_pension",
    "isa",
    "cma",
    "other",
)


def key_document(keys, active=1):
    return {
        "schema_version": 1,
        "active_key_version": active,
        "keys": {
            str(version): base64.b64encode(key).decode("ascii") for version, key in keys.items()
        },
    }


def write_keyring(path, keys, active=1):
    path.write_text(json.dumps(key_document(keys, active)), encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.fixture
def key_file(tmp_path):
    return write_keyring(
        tmp_path / "synthetic-keyring.json", {1: AESGCM.generate_key(bit_length=256)}
    )


def asset_payload(**overrides):
    return {
        "name": "합성 금융 자산",
        "kind": "asset",
        "category": "financial",
        "ownership_kind": "joint",
        "household_share": "1",
        "amount_basis": "owned",
        "started_on": "2025-01-01",
        **overrides,
    }


def account_payload(**overrides):
    return {
        "asset": asset_payload(),
        "institution_name": "합성 은행",
        "account_type": "checking",
        "account_number": SYNTHETIC_NUMBER,
        "opened_on": "2025-01-01",
        **overrides,
    }


def test_all_account_types_and_single_asset_source_schema():
    for account_type in ACCOUNT_TYPES:
        assert TypeAdapter(AccountType).validate_python(account_type) == account_type
        assert (
            AccountCreate.model_validate(account_payload(account_type=account_type)).asset
            is not None
        )
    assert not {
        "balance",
        "balance_krw",
        "amount_krw",
        "owner_member_id",
        "closed_on",
        "status",
    } & set(FinancialAccount.__table__.columns.keys())
    request = AccountCreate.model_validate(account_payload())
    assert request.account_number.get_secret_value() == SYNTHETIC_NUMBER
    assert SYNTHETIC_NUMBER not in repr(request)
    assert SYNTHETIC_NUMBER not in request.model_dump_json()


def test_account_patch_openapi_nullability_matches_validation():
    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()["components"]["schemas"]["AccountPatch"]
    for name, prop in schema["properties"].items():
        assert name not in schema.get("required", [])
        nullable = any(item.get("type") == "null" for item in prop.get("anyOf", []))
        assert nullable == (name not in {"institution_name", "account_type"})
        if not nullable:
            assert "default" not in prop
            with pytest.raises(ValidationError):
                AccountPatch.model_validate({name: None})


def test_account_openapi_declares_versions_and_response_headers():
    app = FastAPI()
    app.include_router(router)
    paths = app.openapi()["paths"]
    patch = paths["/api/v1/accounts/{account_id}"]["patch"]
    header = next(item for item in patch["parameters"] if item["name"] == "If-Match")
    assert header["required"] is True
    assert header["schema"]["type"] == "string"
    assert set(patch["responses"]["200"]["headers"]) == {"ETag"}
    assert set(paths["/api/v1/accounts"]["post"]["responses"]["201"]["headers"]) == {
        "ETag",
        "Location",
    }
    delete = paths["/api/v1/accounts/{account_id}"]["delete"]
    assert delete["operationId"] == "deleteAccount"
    assert next(p for p in delete["parameters"] if p["name"] == "If-Match")["required"] is True
    assert set(delete["responses"]) >= {"204"}


@pytest.mark.parametrize(
    "change",
    [
        {"asset": None},
        {"asset_id": str(uuid4())},
        {"asset": asset_payload(category="real_estate")},
        {"asset": asset_payload(kind="liability")},
        {"account_type": "retirement"},
        {"balance_krw": "1000"},
        {"owner_member_id": str(uuid4())},
        {"closed_on": "2025-03-01"},
        {"institution_name": " "},
    ],
)
def test_invalid_account_contracts_rejected(change):
    with pytest.raises(ValidationError):
        AccountCreate.model_validate(account_payload(**change))


@pytest.mark.parametrize(
    "number",
    [123456, True, "1234", "1---234", "１２３４５６", "0000/12345", "x" * 65, " 12345", "12345\n"],
)
def test_invalid_number_inputs_rejected_without_coercion(number):
    with pytest.raises(ValidationError):
        TypeAdapter(AccountNumber).validate_python(number)


def test_account_patch_distinguishes_omitted_number_from_explicit_clear():
    assert AccountPatch(purpose=None).model_dump(exclude_unset=True) == {"purpose": None}
    assert AccountPatch(account_number=None).model_fields_set == {"account_number"}
    for invalid in (
        {},
        {"account_type": None},
        {"institution_name": None},
        {"asset_id": str(uuid4())},
    ):
        with pytest.raises(ValidationError):
            AccountPatch.model_validate(invalid)


def test_aes_gcm_nonce_aad_integrity_and_key_rotation(tmp_path):
    first, second = AESGCM.generate_key(bit_length=256), AESGCM.generate_key(bit_length=256)
    path = write_keyring(tmp_path / "synthetic-keyring.json", {1: first})
    old = KeyRing.load(path)
    household_id, account_id = uuid4(), uuid4()
    sealed = encrypt_number(old, household_id, account_id, SYNTHETIC_NUMBER)
    again = encrypt_number(old, household_id, account_id, SYNTHETIC_NUMBER)
    assert len(sealed.nonce) == 12 and sealed.nonce != again.nonce
    assert sealed.ciphertext != again.ciphertext
    assert SYNTHETIC_NUMBER.encode() not in sealed.ciphertext
    assert decrypt_number(old, household_id, account_id, sealed) == SYNTHETIC_NUMBER
    assert base64.b64encode(first).decode() not in repr(old)
    write_keyring(path, {1: first, 2: second}, active=2)
    current = KeyRing.load(path)
    assert decrypt_number(current, household_id, account_id, sealed) == SYNTHETIC_NUMBER
    fresh = encrypt_number(current, household_id, account_id, SYNTHETIC_NUMBER)
    assert fresh.key_version == 2
    for wrong_household, wrong_account, envelope in (
        (uuid4(), account_id, sealed),
        (household_id, uuid4(), sealed),
        (household_id, account_id, replace(sealed, key_version=2)),
        (household_id, account_id, replace(sealed, nonce=bytes(12))),
        (
            household_id,
            account_id,
            replace(sealed, ciphertext=sealed.ciphertext[:-1] + bytes([sealed.ciphertext[-1] ^ 1])),
        ),
    ):
        with pytest.raises(DomainError) as invalid:
            decrypt_number(current, wrong_household, wrong_account, envelope)
        assert invalid.value.code == "ACCOUNT_NUMBER_UNAVAILABLE"
    write_keyring(path, {2: second}, active=2)
    with pytest.raises(DomainError) as missing_old_key:
        decrypt_number(KeyRing.load(path), household_id, account_id, sealed)
    assert missing_old_key.value.code == "FIELD_ENCRYPTION_UNAVAILABLE"


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o666, 0o700])
def test_keyring_rejects_nonprivate_or_executable_files(key_file, mode):
    key_file.chmod(mode)
    with pytest.raises(DomainError) as unavailable:
        KeyRing.load(key_file)
    assert unavailable.value.code == "FIELD_ENCRYPTION_UNAVAILABLE"
    assert str(key_file) not in str(unavailable.value)


def test_keyring_rejects_missing_file_symlinks_parent_symlinks_and_nonregular_file(
    key_file, tmp_path
):
    link = tmp_path / "synthetic-link"
    link.symlink_to(key_file)
    parent = tmp_path / "synthetic-parent"
    parent.symlink_to(tmp_path, target_is_directory=True)
    fifo = tmp_path / "synthetic-fifo"
    os.mkfifo(fifo, 0o600)
    for path in (None, tmp_path / "absent", link, parent / key_file.name, fifo):
        with pytest.raises(DomainError) as unavailable:
            KeyRing.load(path)
        assert unavailable.value.status == 503


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"active_key_version": True},
        {"active_key_version": 2},
        {"keys": {}},
        {"keys": {"1": "bad"}},
        {"unexpected": "synthetic"},
    ],
)
def test_keyring_schema_fails_closed(key_file, change):
    document = json.loads(key_file.read_text())
    document.update(change)
    key_file.write_text(json.dumps(document))
    with pytest.raises(DomainError) as unavailable:
        KeyRing.load(key_file)
    assert unavailable.value.code == "FIELD_ENCRYPTION_UNAVAILABLE"


def test_keyring_rejects_duplicate_fields_and_oversize_input(key_file):
    key_file.write_text('{"schema_version":1,"schema_version":1,"active_key_version":1,"keys":{}}')
    with pytest.raises(DomainError):
        KeyRing.load(key_file)
    key_file.write_bytes(b" " * 16_385)
    with pytest.raises(DomainError):
        KeyRing.load(key_file)


@dataclass(frozen=True)
class AccountActor:
    user_id: UUID
    member_id: UUID
    household_id: UUID
    login_name: str
    password: str = field(repr=False)
    token: str = field(repr=False)
    principal: Principal

    @property
    def headers(self):
        return {
            "Authorization": "Bearer " + self.token,
            "X-SallimBook-Native": "1",
            "Content-Type": "application/json",
        }


def make_actor(engine, household_id=None):
    password = secrets.token_urlsafe(24)
    with Session(engine) as session:
        if household_id is None:
            household = Household(name="합성 계좌 가계")
            session.add(household)
            session.flush()
            household_id, slot, role = household.id, 1, "owner"
        else:
            slot, role = 2, "member"
        user = User(
            login_name="account_" + uuid4().hex[:12],
            display_name="합성 사용자",
            password_hash=identity.PASSWORD_HASHER.hash(password),
        )
        session.add(user)
        session.flush()
        member = HouseholdMember(
            household_id=household_id, user_id=user.id, slot=slot, role=role, status="active"
        )
        session.add(member)
        session.commit()
        result = identity.login(
            session,
            LoginRequest(
                login_name=user.login_name, password=password, device_label="합성 계좌 기기"
            ),
            "synthetic-account",
            "native",
        )
        principal = identity.authenticate(session, result.token, "native")
        session.commit()
        return AccountActor(
            user.id, member.id, household_id, user.login_name, password, result.token, principal
        )


@pytest.fixture
def account_actor(db_engine):
    return make_actor(db_engine)


@pytest.fixture
def accounts_app(db_engine, key_file):
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(
        environment="test", field_encryption_key_file=key_file, _env_file=None
    )
    install_http_contract(app)
    app.include_router(identity_router)
    app.include_router(asset_router)
    app.include_router(router)
    return app


def create_account(client, actor, **overrides):
    response = client.post(
        "/api/v1/accounts", json=account_payload(**overrides), headers=actor.headers
    )
    assert response.status_code == 201
    return response.json()


def account_grant(session, actor, target):
    authenticator = SyntheticAuthenticator.create()
    options = passkeys.registration_options(
        session, actor.principal, RegisterOptionsRequest(label="합성 계좌 패스키"), NATIVE_POLICY
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
        StepUpOptionsRequest(purpose=StepUpPurpose.ACCOUNT_REVEAL, target_id=target),
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


@pytest.mark.database
class TestAccountsDatabase:
    def test_account_delete_is_atomic_and_refuses_referenced_rows(
        self, accounts_app, account_actor, db_engine
    ):
        stranger = make_actor(db_engine)
        with TestClient(accounts_app) as client:

            def delete(account, actor=account_actor, version=None):
                return client.delete(
                    f"/api/v1/accounts/{account['id']}",
                    headers={**actor.headers, "If-Match": f'"{version or account["version"]}"'},
                )

            plain = create_account(client, account_actor)
            assert delete(plain, stranger).json()["error"]["code"] == "NOT_FOUND"
            stale = delete(plain, version=plain["version"] + 1)
            assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
            assert delete(plain).status_code == 204
            assert delete(plain).status_code == 404  # a resend deletes nothing else
            settled = create_account(
                client, account_actor, asset=asset_payload(name="합성 결제 자산")
            )
            recorded = create_account(
                client, account_actor, asset=asset_payload(name="합성 월 기록 자산")
            )
            with Session(db_engine) as session:
                card_service.create_card(
                    session,
                    account_actor.principal,
                    CardCreate(
                        owner_member_id=account_actor.member_id,
                        issuer_name="합성 카드사",
                        product_name="합성 카드",
                        card_type="credit",
                        settlement_account_id=UUID(settled["id"]),
                    ),
                )
            # The account row deletes, but the month value FK blocks the asset row.
            with Session(db_engine) as session:
                month_service.create_draft(
                    session,
                    account_actor.principal,
                    "2026-01",
                    MonthDraft(copy_previous=False),
                    uuid4().hex,
                )
            for account in (settled, recorded):
                refused = delete(account)
                assert (refused.status_code, refused.json()["error"]["code"]) == (
                    409,
                    "ACCOUNT_IN_USE",
                )
                assert (
                    client.get(
                        f"/api/v1/accounts/{account['id']}", headers=account_actor.headers
                    ).status_code
                    == 200
                )
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(FinancialAccount)) == 2
            assert session.scalar(select(func.count()).select_from(Asset)) == 2
            deleted = session.scalars(select(AuditEvent).where(AuditEvent.action == "delete")).all()
            assert sorted((e.entity_type, str(e.entity_id)) for e in deleted) == sorted(
                [("financial_account", plain["id"]), ("asset", plain["asset_id"])]
            )

    def test_nested_asset_future_end_creates_neither_account_nor_asset(
        self, accounts_app, account_actor, db_engine, monkeypatch
    ):
        monkeypatch.setattr(
            asset_service, "utcnow", lambda: datetime(2026, 3, 31, 14, 59, 59, tzinfo=UTC)
        )
        with TestClient(accounts_app) as client:
            response = client.post(
                "/api/v1/accounts",
                headers=account_actor.headers,
                json=account_payload(asset=asset_payload(ended_on="2026-04-01")),
            )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ASSET_END_IN_FUTURE"
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(FinancialAccount)) == 0
            assert session.scalar(select(func.count()).select_from(Asset)) == 0

    @pytest.mark.parametrize("change", [{"kind": "liability"}, {"category": "real_estate"}])
    def test_linked_asset_keeps_financial_kind(self, accounts_app, account_actor, change):
        with TestClient(accounts_app) as client:
            item = create_account(client, account_actor)
            path = f"/api/v1/assets/{item['asset_id']}"
            response = client.patch(
                path,
                json=change,
                headers={**account_actor.headers, "If-Match": f'"{item["asset"]["version"]}"'},
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "FINANCIAL_ASSET_REQUIRED"
            current = client.get(path, headers=account_actor.headers).json()
            assert current["kind"] == "asset" and current["category"] == "financial"
            assert current["version"] == item["asset"]["version"]

    def test_asset_closure_checks_linked_account_opening_date(self, accounts_app, account_actor):
        with TestClient(accounts_app) as client:
            item = create_account(client, account_actor, opened_on="2025-04-01")
            response = client.post(
                f"/api/v1/assets/{item['asset_id']}/archive",
                json={"ended_on": "2025-03-31"},
                headers={**account_actor.headers, "If-Match": f'"{item["asset"]["version"]}"'},
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "INVALID_ACCOUNT_DATES"
            current = client.get(
                f"/api/v1/accounts/{item['id']}", headers=account_actor.headers
            ).json()
            assert current["status"] == "active" and current["closed_on"] is None

    def test_number_update_uses_active_key_version_and_clear_needs_no_decryption(
        self, accounts_app, account_actor, db_engine, key_file
    ):
        old_key = json.loads(key_file.read_text())["keys"]["1"]
        with TestClient(accounts_app) as client:
            item = create_account(client, account_actor)
            path = f"/api/v1/accounts/{item['id']}"
            with Session(db_engine) as session:
                old_nonce = session.get(FinancialAccount, UUID(item["id"])).number_nonce
            write_keyring(
                key_file,
                {1: base64.b64decode(old_key), 2: AESGCM.generate_key(bit_length=256)},
                active=2,
            )
            assert (
                client.post(path + "/reveal", headers=account_actor.headers).json()[
                    "account_number"
                ]
                == SYNTHETIC_NUMBER
            )
            update = client.patch(
                path,
                json={"account_number": SYNTHETIC_NUMBER},
                headers={**account_actor.headers, "If-Match": f'"{item["version"]}"'},
            )
            assert update.status_code == 200
            with Session(db_engine) as session:
                account = session.get(FinancialAccount, UUID(item["id"]))
                assert account.number_key_version == 2 and account.number_nonce != old_nonce
            accounts_app.state.settings.field_encryption_key_file = None
            assert client.get(path, headers=account_actor.headers).json()["has_number"] is True
            assert client.post(path + "/reveal", headers=account_actor.headers).status_code == 503
            cleared = client.patch(
                path,
                json={"account_number": None},
                headers={**account_actor.headers, "If-Match": f'"{update.json()["version"]}"'},
            )
            assert cleared.status_code == 200
            assert cleared.json()["has_number"] is False and cleared.json()["masked_number"] is None
        with Session(db_engine) as session:
            account = session.get(FinancialAccount, UUID(item["id"]))
            assert (
                account.account_number_ciphertext
                is account.number_nonce
                is account.number_key_version
                is account.last_four
                is None
            )

    def test_all_types_share_one_asset_and_list_filters_paginate(
        self, accounts_app, account_actor, db_engine
    ):
        with TestClient(accounts_app) as client:
            accounts = [
                create_account(client, account_actor, account_type=kind) for kind in ACCOUNT_TYPES
            ]
            for item in accounts:
                assert item["asset_id"] == item["asset"]["id"]
                assert item["asset"]["category"] == "financial"
                assert item["masked_number"] == "**** 7890" and item["has_number"] is True
                assert "account_number" not in item and "account_number_ciphertext" not in item
                assert SYNTHETIC_NUMBER not in json.dumps(item)
                filtered = client.get(
                    "/api/v1/accounts",
                    params={"account_type": item["account_type"]},
                    headers=account_actor.headers,
                )
                assert [row["id"] for row in filtered.json()["items"]] == [item["id"]]
            received, cursor = [], None
            while True:
                params = {"limit": 3}
                if cursor is not None:
                    params["cursor"] = cursor
                page = client.get(
                    "/api/v1/accounts", params=params, headers=account_actor.headers
                ).json()
                received.extend(row["id"] for row in page["items"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            assert len(received) == len(set(received)) == 10
            assert set(received) == {row["id"] for row in accounts}
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(Asset)) == 10
            assert session.scalar(select(func.count()).select_from(FinancialAccount)) == 10

    @pytest.mark.parametrize("opened_on", [None, "2025-01-01"])
    def test_archived_existing_asset_cannot_receive_a_new_account(
        self, accounts_app, account_actor, db_engine, opened_on
    ):
        with TestClient(accounts_app) as client:
            asset = client.post(
                "/api/v1/assets",
                json=asset_payload(ended_on="2025-10-01"),
                headers=account_actor.headers,
            ).json()
            rejected = client.post(
                "/api/v1/accounts",
                headers=account_actor.headers,
                json=account_payload(asset=None, asset_id=asset["id"], opened_on=opened_on),
            )
            assert rejected.status_code == 422
            assert rejected.json()["error"]["code"] == "ASSET_UNAVAILABLE"
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(FinancialAccount)) == 0
            assert session.scalar(select(func.count()).select_from(Asset)) == 1

    def test_existing_asset_link_is_unique_and_restricts_deletion(
        self, accounts_app, account_actor, db_engine
    ):
        with TestClient(accounts_app) as client:
            asset = client.post(
                "/api/v1/assets", json=asset_payload(), headers=account_actor.headers
            ).json()
            payload = account_payload(asset=None, asset_id=asset["id"])
            first = client.post("/api/v1/accounts", json=payload, headers=account_actor.headers)
            assert first.status_code == 201
            second = client.post("/api/v1/accounts", json=payload, headers=account_actor.headers)
            assert (
                second.status_code == 409
                and second.json()["error"]["code"] == "ASSET_ALREADY_LINKED"
            )
            removed = client.delete(
                f"/api/v1/assets/{asset['id']}",
                headers={**account_actor.headers, "If-Match": f'"{asset["version"]}"'},
            )
            assert removed.status_code == 409
            assert (
                client.get(
                    f"/api/v1/accounts/{first.json()['id']}", headers=account_actor.headers
                ).status_code
                == 200
            )
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(Asset)) == 1

    def test_failed_encryption_rolls_back_nested_asset_and_audit_but_numberless_metadata_works(
        self, accounts_app, account_actor, db_engine
    ):
        accounts_app.state.settings.field_encryption_key_file = None
        with TestClient(accounts_app) as client:
            failed = client.post(
                "/api/v1/accounts", json=account_payload(), headers=account_actor.headers
            )
            assert failed.status_code == 503
            with Session(db_engine) as session:
                assert session.scalar(select(func.count()).select_from(Asset)) == 0
                assert session.scalar(select(func.count()).select_from(FinancialAccount)) == 0
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.entity_type != "registered_device")  # fixture sign-ins
                    )
                    == 0
                )
            item = create_account(client, account_actor, account_number=None)
            assert item["masked_number"] is None and item["has_number"] is False
            assert (
                client.get(
                    f"/api/v1/accounts/{item['id']}", headers=account_actor.headers
                ).status_code
                == 200
            )

    def test_other_household_ids_and_owner_are_hidden_while_partner_can_share(
        self, accounts_app, account_actor, db_engine
    ):
        foreign, partner = make_actor(db_engine), make_actor(db_engine, account_actor.household_id)
        with TestClient(accounts_app) as client:
            item = create_account(
                client,
                account_actor,
                asset=asset_payload(
                    ownership_kind="individual", owner_member_id=str(account_actor.member_id)
                ),
            )
            path = f"/api/v1/accounts/{item['id']}"
            assert client.get(path, headers=partner.headers).status_code == 200
            for response in (
                client.get(path, headers=foreign.headers),
                client.patch(
                    path,
                    json={"purpose": "합성 변경"},
                    headers={**foreign.headers, "If-Match": '"1"'},
                ),
                client.post(path + "/reveal", headers=foreign.headers),
                client.post(
                    "/api/v1/accounts",
                    json=account_payload(asset=None, asset_id=item["asset_id"]),
                    headers=foreign.headers,
                ),
                client.post(
                    "/api/v1/accounts",
                    json=account_payload(
                        asset=asset_payload(
                            ownership_kind="individual", owner_member_id=str(foreign.member_id)
                        )
                    ),
                    headers=account_actor.headers,
                ),
                client.get(
                    "/api/v1/accounts",
                    params={"owner_member_id": str(foreign.member_id)},
                    headers=account_actor.headers,
                ),
            ):
                assert response.status_code == 404
                assert SYNTHETIC_NUMBER not in response.text

    def test_metadata_version_conflict_and_asset_closure_preserve_history(
        self, accounts_app, account_actor
    ):
        with TestClient(accounts_app) as client:
            item = create_account(client, account_actor)
            path = f"/api/v1/accounts/{item['id']}"
            update = client.patch(
                path,
                json={"purpose": "합성 비상금"},
                headers={**account_actor.headers, "If-Match": f'"{item["version"]}"'},
            )
            assert update.status_code == 200
            conflict = client.patch(
                path,
                json={"purpose": "합성 옛 편집"},
                headers={**account_actor.headers, "If-Match": f'"{item["version"]}"'},
            )
            assert conflict.status_code == 409
            closed = client.post(
                f"/api/v1/assets/{item['asset_id']}/archive",
                json={"ended_on": "2025-10-01"},
                headers={**account_actor.headers, "If-Match": f'"{item["asset"]["version"]}"'},
            )
            assert closed.status_code == 200
            current = client.get(path, headers=account_actor.headers).json()
            assert current["closed_on"] == "2025-10-01" and current["status"] == "closed"
            assert current["purpose"] == "합성 비상금" and current["masked_number"] == "**** 7890"
            assert (
                client.get("/api/v1/accounts", headers=account_actor.headers).json()["items"] == []
            )
            assert (
                len(
                    client.get(
                        "/api/v1/accounts",
                        params={"status": "closed"},
                        headers=account_actor.headers,
                    ).json()["items"]
                )
                == 1
            )
            invalid_date = client.patch(
                path,
                json={"opened_on": "2026-01-01"},
                headers={**account_actor.headers, "If-Match": f'"{current["version"]}"'},
            )
            assert invalid_date.status_code == 422

    def test_number_reveal_is_explicit_no_store_and_audited_without_number(
        self, accounts_app, account_actor, db_engine, caplog
    ):
        with TestClient(accounts_app) as client:
            item = create_account(client, account_actor)
            path = f"/api/v1/accounts/{item['id']}"
            for response in (
                client.get(path, headers=account_actor.headers),
                client.get("/api/v1/accounts", headers=account_actor.headers),
            ):
                assert SYNTHETIC_NUMBER not in response.text
                assert response.headers["cache-control"] == "no-store"
            revealed = client.post(path + "/reveal", headers=account_actor.headers)
            assert revealed.status_code == 200
            assert revealed.json()["account_number"] == SYNTHETIC_NUMBER
            assert revealed.json()["display_for_seconds"] == 30
            assert revealed.headers["cache-control"] == "no-store"
            explicit_bad = client.post(
                path + "/reveal", headers={**account_actor.headers, "X-Step-Up-Token": "invalid"}
            )
            assert explicit_bad.status_code == 403
            invalid_input = client.patch(
                path,
                json={"account_number": SYNTHETIC_NUMBER + "/invalid"},
                headers={**account_actor.headers, "If-Match": f'"{item["version"]}"'},
            )
            assert invalid_input.status_code == 422
            assert SYNTHETIC_NUMBER not in invalid_input.text
        with Session(db_engine) as session:
            account = session.get(FinancialAccount, UUID(item["id"]))
            assert SYNTHETIC_NUMBER.encode() not in account.account_number_ciphertext
            events = list(session.scalars(select(AuditEvent)))
            reveal = [event for event in events if event.action == "reveal"]
            assert len(reveal) == 1 and reveal[0].entity_id == account.id
            assert reveal[0].safe_diff == {"changed_fields": []}
            assert SYNTHETIC_NUMBER not in json.dumps([event.safe_diff for event in events])
        assert SYNTHETIC_NUMBER not in caplog.text

    def test_scoped_reveal_grant_survives_key_failure_then_consumes_once(
        self, accounts_app, account_actor, db_engine, key_file
    ):
        with TestClient(accounts_app) as client:
            item = create_account(client, account_actor)
            with Session(db_engine) as session:
                grant = account_grant(session, account_actor, UUID(item["id"]))
                auth = session.get(AuthSession, account_actor.principal.session_id)
                old_login = auth.authenticated_at - timedelta(minutes=6)
                auth.authenticated_at = old_login
                session.commit()
            path = f"/api/v1/accounts/{item['id']}/reveal"
            assert client.post(path, headers=account_actor.headers).status_code == 403
            headers = {**account_actor.headers, "X-Step-Up-Token": grant.grant_token}
            accounts_app.state.settings.field_encryption_key_file = None
            assert client.post(path, headers=headers).status_code == 503
            with Session(db_engine) as session:
                assert session.scalar(select(StepUpGrant.consumed_at)) is None
            accounts_app.state.settings.field_encryption_key_file = key_file
            success = client.post(path, headers=headers)
            assert (
                success.status_code == 200 and success.json()["account_number"] == SYNTHETIC_NUMBER
            )
            assert client.post(path, headers=headers).status_code == 403
        with Session(db_engine) as session:
            assert session.scalar(select(StepUpGrant.consumed_at)) is not None
            assert (
                session.get(AuthSession, account_actor.principal.session_id).authenticated_at
                == old_login
            )

    @pytest.mark.parametrize("with_grant", [False, True])
    @pytest.mark.parametrize("invalid_state", ["session", "device"])
    def test_stale_principal_cannot_reveal_number(
        self,
        db_engine,
        account_actor,
        key_file,
        with_grant,
        invalid_state,
        monkeypatch,
    ):
        with Session(db_engine) as session:
            item = service.create_account(
                session, account_actor.principal, AccountCreate(**account_payload()), key_file
            )
            grant = account_grant(session, account_actor, item.id) if with_grant else None
            if invalid_state == "session":
                session.get(
                    AuthSession, account_actor.principal.session_id
                ).revoked_at = identity.utcnow()
            else:
                device = session.get(RegisteredDevice, account_actor.principal.device_id)
                device.status, device.revoked_at = "revoked", identity.utcnow()
            session.commit()

            def forbidden_decryption(*args):
                pytest.fail("A revoked source must fail before decryption")

            monkeypatch.setattr(service, "decrypt_number", forbidden_decryption)
            with pytest.raises(DomainError) as rejected:
                service.reveal_number(
                    session,
                    account_actor.principal,
                    item.id,
                    key_file,
                    step_up_token=grant.grant_token if grant else None,
                )
            assert rejected.value.code == "UNAUTHENTICATED"
            session.rollback()
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "reveal")
                )
                == 0
            )
            if grant:
                assert session.scalar(select(StepUpGrant.consumed_at)) is None

    @pytest.mark.parametrize(
        "blocked_on,change,with_grant,expected",
        [
            ("device", "revoke", False, "UNAUTHENTICATED"),
            ("device", "revoke", True, "UNAUTHENTICATED"),
            ("credential", "revoke", True, "STEP_UP_REQUIRED"),
            ("asset", "expire_recent", False, "REAUTHENTICATION_REQUIRED"),
            ("account", "expire_recent", False, "REAUTHENTICATION_REQUIRED"),
            ("asset", "expire_grant", True, "STEP_UP_REQUIRED"),
            ("account", "expire_access", True, "UNAUTHENTICATED"),
            ("grant", "expire_grant", True, "STEP_UP_REQUIRED"),
        ],
    )
    def test_reveal_revalidates_after_real_lock_wait_without_plaintext(
        self,
        db_engine,
        account_actor,
        key_file,
        monkeypatch,
        caplog,
        blocked_on,
        change,
        with_grant,
        expected,
    ):
        with Session(db_engine) as session:
            item = service.create_account(
                session, account_actor.principal, AccountCreate(**account_payload()), key_file
            )
            grant = account_grant(session, account_actor, item.id)
            grant_id = session.scalar(select(StepUpGrant.id))
            credential_id = session.scalar(select(AuthCredential.id))
            auth = session.get(AuthSession, account_actor.principal.session_id)
            access_expiry, authenticated_at = auth.access_expires_at, auth.authenticated_at

        def forbidden_decryption(*args):
            pytest.fail("Rejected requests must not decrypt")

        monkeypatch.setattr(service, "decrypt_number", forbidden_decryption)
        ready, proceed = Event(), Event()
        pids = []

        def reveal():
            with Session(db_engine) as session:
                principal = identity.authenticate(session, account_actor.token, "native")
                cached = [
                    session.get(RegisteredDevice, principal.device_id),
                    session.get(AuthCredential, credential_id),
                    session.get(StepUpGrant, grant_id),
                ]
                pids.append(session.scalar(select(func.pg_backend_pid())))
                ready.set()
                assert proceed.wait(timeout=10)
                try:
                    result = service.reveal_number(
                        session,
                        principal,
                        item.id,
                        key_file,
                        step_up_token=grant.grant_token if with_grant else None,
                    )
                    return result.model_dump_json()
                except DomainError as failure:
                    assert len(cached) == 3
                    return failure.code

        targets = {
            "device": (RegisteredDevice, account_actor.principal.device_id),
            "credential": (AuthCredential, credential_id),
            "grant": (StepUpGrant, grant_id),
            "asset": (Asset, item.asset_id),
            "account": (FinancialAccount, item.id),
        }
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(reveal)
            try:
                assert ready.wait(timeout=10)
                with Session(db_engine) as blocker:
                    model, target = targets[blocked_on]
                    row = blocker.scalar(select(model).where(model.id == target).with_for_update())
                    blocker_pid = blocker.scalar(select(func.pg_backend_pid()))
                    proceed.set()
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        blockers = blocker.scalar(select(func.pg_blocking_pids(pids[0])))
                        if blocker_pid in blockers or future.done():
                            break
                        time.sleep(0.01)
                    assert blocker_pid in blockers
                    if change == "revoke":
                        row.revoked_at = identity.utcnow()
                        if blocked_on == "device":
                            row.status = "revoked"
                    else:
                        after = {
                            "expire_recent": authenticated_at + timedelta(minutes=5),
                            "expire_access": access_expiry,
                            "expire_grant": grant.expires_at,
                        }[change] + timedelta(seconds=1)
                        monkeypatch.setattr(identity, "utcnow", lambda: after)
                    blocker.commit()
                result = future.result(timeout=10)
                assert result == expected and SYNTHETIC_NUMBER not in result
            finally:
                proceed.set()
        assert SYNTHETIC_NUMBER not in caplog.text
        with Session(db_engine) as session:
            assert session.get(StepUpGrant, grant_id).consumed_at is None
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "reveal")
                )
                == 0
            )

    @pytest.mark.parametrize("phase", ["decryption", "audit"])
    @pytest.mark.parametrize("expiry", ["recent", "grant", "access"])
    def test_expiry_before_response_rolls_back_grant_and_audit_without_plaintext(
        self,
        accounts_app,
        account_actor,
        db_engine,
        monkeypatch,
        caplog,
        phase,
        expiry,
    ):
        with TestClient(accounts_app) as client:
            item = create_account(client, account_actor)
            with Session(db_engine) as session:
                grant = account_grant(session, account_actor, UUID(item["id"]))
                auth = session.get(AuthSession, account_actor.principal.session_id)
                after = {
                    "recent": auth.authenticated_at + timedelta(minutes=5),
                    "grant": grant.expires_at,
                    "access": auth.access_expires_at,
                }[expiry] + timedelta(seconds=1)
            function = "decrypt_number" if phase == "decryption" else "record_event"
            original = getattr(service, function)

            def advance_after_work(*args, **kwargs):
                result = original(*args, **kwargs)
                monkeypatch.setattr(identity, "utcnow", lambda: after)
                return result

            monkeypatch.setattr(service, function, advance_after_work)
            headers = account_actor.headers
            if expiry != "recent":
                headers = {**headers, "X-Step-Up-Token": grant.grant_token}
            response = client.post(f"/api/v1/accounts/{item['id']}/reveal", headers=headers)
            assert response.status_code == (401 if expiry == "access" else 403)
            assert SYNTHETIC_NUMBER not in response.text and SYNTHETIC_NUMBER not in caplog.text
        with Session(db_engine) as session:
            assert session.scalar(select(StepUpGrant.consumed_at)) is None
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "reveal")
                )
                == 0
            )

    def test_audit_failure_never_returns_plaintext(
        self, accounts_app, account_actor, db_engine, monkeypatch, caplog
    ):
        with TestClient(accounts_app) as client:
            item = create_account(client, account_actor)

            def unavailable_audit(*args, **kwargs):
                raise RuntimeError("Synthetic audit failure")

            monkeypatch.setattr(service, "record_event", unavailable_audit)
            response = client.post(
                f"/api/v1/accounts/{item['id']}/reveal", headers=account_actor.headers
            )
            assert response.status_code == 500
            assert SYNTHETIC_NUMBER not in response.text and SYNTHETIC_NUMBER not in caplog.text
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "reveal")
                )
                == 0
            )

    def test_ciphertext_cannot_be_transplanted_to_another_account(
        self, accounts_app, account_actor, db_engine
    ):
        with TestClient(accounts_app) as client:
            first, second = (
                create_account(client, account_actor),
                create_account(client, account_actor),
            )
            with Session(db_engine) as session:
                source, target = (
                    session.get(FinancialAccount, UUID(first["id"])),
                    session.get(FinancialAccount, UUID(second["id"])),
                )
                target.account_number_ciphertext = source.account_number_ciphertext
                target.number_nonce = source.number_nonce
                target.number_key_version = source.number_key_version
                session.commit()
            response = client.post(
                f"/api/v1/accounts/{second['id']}/reveal", headers=account_actor.headers
            )
            assert response.status_code == 503
            assert SYNTHETIC_NUMBER not in response.text

    def test_composite_foreign_key_rejects_cross_household_asset(
        self, accounts_app, account_actor, db_engine
    ):
        foreign = make_actor(db_engine)
        with TestClient(accounts_app) as client:
            foreign_asset = client.post(
                "/api/v1/assets", json=asset_payload(), headers=foreign.headers
            ).json()
        with Session(db_engine) as session:
            session.add(
                FinancialAccount(
                    household_id=account_actor.household_id,
                    asset_id=UUID(foreign_asset["id"]),
                    institution_name="합성 은행",
                    account_type="checking",
                    created_by_member_id=account_actor.member_id,
                    updated_by_member_id=account_actor.member_id,
                )
            )
            with pytest.raises(IntegrityError) as failure:
                session.flush()
            assert failure.value.orig.sqlstate == "23503"
