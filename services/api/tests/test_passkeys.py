"""Real WebAuthn verification using synthetic ES256 keys; no physical-device attestation claim."""

import hashlib
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import UUID, uuid4

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from sallimbook.config import Settings
from sallimbook.core.authorization import Principal, require_recent_login, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.http import install_http_contract
from sallimbook.identity import service as identity
from sallimbook.identity.auth_models import (
    AuthSession,
    HouseholdMember,
    Invitation,
    RegisteredDevice,
    User,
)
from sallimbook.identity.dependencies import NATIVE_HEADER, SESSION_COOKIE
from sallimbook.identity.models import Household
from sallimbook.identity.passkeys import service
from sallimbook.identity.passkeys.models import (
    AuthChallenge,
    AuthCredential,
    StepUpGrant,
    StepUpPurpose,
)
from sallimbook.identity.passkeys.router import BINDING_COOKIE, router
from sallimbook.identity.passkeys.schemas import (
    AssertionVerification,
    AuthenticationCredential,
    LoginOptionsRequest,
    RegisterOptionsRequest,
    RegisterVerification,
    RegistrationCredential,
    StepUpOptionsRequest,
)
from sallimbook.identity.router import revoke_device as revoke_device_route
from sallimbook.identity.router import router as identity_router
from sallimbook.identity.schemas import InvitationAcceptance, InvitationRequest, LoginRequest

RP_ID = "sallimbook-passkeys.invalid"
WEB_ORIGIN = "https://sallimbook-passkeys.invalid:8443"
NATIVE_ORIGIN = "android:apk-key-hash:" + bytes_to_base64url(bytes(range(32)))
NATIVE_HEADERS = {NATIVE_HEADER: "1"}
WEB_POLICY = service.VerificationPolicy(RP_ID, (WEB_ORIGIN,), "web")
NATIVE_POLICY = service.VerificationPolicy(RP_ID, (NATIVE_ORIGIN,), "native")


@dataclass
class SyntheticAuthenticator:
    """Test-only protocol messages, signed by cryptography's standard ES256 implementation."""

    key: ec.EllipticCurvePrivateKey = field(repr=False)
    credential_id: bytes = field(repr=False)
    counter: int = 0
    multi_device: bool = False

    @classmethod
    def create(cls, *, multi_device=False):
        return cls(
            ec.generate_private_key(ec.SECP256R1()),
            secrets.token_bytes(32),
            multi_device=multi_device,
        )

    @property
    def public_key(self):
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps(
            {
                1: 2,
                3: -7,
                -1: 1,
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    @property
    def device_type(self):
        return "multi_device" if self.multi_device else "single_device"

    def _client_data(self, kind, challenge, origin, cross_origin=False, top_origin=None):
        value = {
            "type": kind,
            "challenge": bytes_to_base64url(challenge),
            "origin": origin,
            "crossOrigin": cross_origin,
        }
        if top_origin is not None:
            value["topOrigin"] = top_origin
        return json.dumps(value, separators=(",", ":")).encode()

    def registration(
        self,
        challenge,
        *,
        origin=WEB_ORIGIN,
        rp_id=RP_ID,
        uv=True,
        up=True,
        cross_origin=False,
        top_origin=None,
    ):
        flags = (1 if up else 0) | (4 if uv else 0) | 64 | (24 if self.multi_device else 0)
        auth_data = (
            hashlib.sha256(rp_id.encode()).digest()
            + bytes([flags])
            + self.counter.to_bytes(4, "big")
            + bytes(16)
            + len(self.credential_id).to_bytes(2, "big")
            + self.credential_id
            + self.public_key
        )
        # "none" is the requested WebAuthn attestation format; it conveys no hardware trust.
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        client_data = self._client_data(
            "webauthn.create", challenge, origin, cross_origin, top_origin
        )
        return RegistrationCredential.model_validate(
            {
                "id": bytes_to_base64url(self.credential_id),
                "rawId": bytes_to_base64url(self.credential_id),
                "type": "public-key",
                "response": {
                    "clientDataJSON": bytes_to_base64url(client_data),
                    "attestationObject": bytes_to_base64url(attestation),
                    "transports": ["internal"],
                },
                "clientExtensionResults": {},
            }
        )

    def assertion(
        self,
        challenge,
        user_id,
        *,
        origin=WEB_ORIGIN,
        rp_id=RP_ID,
        uv=True,
        up=True,
        cross_origin=False,
        top_origin=None,
        counter=None,
        user_handle=True,
        corrupt_signature=False,
        multi_device=None,
    ):
        if counter is None:
            self.counter += 1
            counter = self.counter
        multi = self.multi_device if multi_device is None else multi_device
        flags = (1 if up else 0) | (4 if uv else 0) | (24 if multi else 0)
        auth_data = (
            hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + counter.to_bytes(4, "big")
        )
        client_data = self._client_data("webauthn.get", challenge, origin, cross_origin, top_origin)
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        if corrupt_signature:
            signature = signature[:-1] + bytes([signature[-1] ^ 1])
        return AuthenticationCredential.model_validate(
            {
                "id": bytes_to_base64url(self.credential_id),
                "rawId": bytes_to_base64url(self.credential_id),
                "type": "public-key",
                "response": {
                    "clientDataJSON": bytes_to_base64url(client_data),
                    "authenticatorData": bytes_to_base64url(auth_data),
                    "signature": bytes_to_base64url(signature),
                    "userHandle": bytes_to_base64url(user_id.bytes) if user_handle else None,
                },
                "clientExtensionResults": {},
            }
        )


def configured_settings(**overrides):
    values = dict(
        allowed_origins=[WEB_ORIGIN],
        webauthn_rp_id=RP_ID,
        webauthn_web_origins=[WEB_ORIGIN],
        webauthn_native_origins=[NATIVE_ORIGIN],
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_passkeys_are_disabled_without_explicit_configuration():
    with pytest.raises(DomainError) as disabled:
        service.policy_from_settings(Settings(), "web", WEB_ORIGIN)
    assert disabled.value.status == 503
    assert disabled.value.code == "PASSKEYS_DISABLED"


@pytest.mark.parametrize(
    "origin",
    [
        "http://sallimbook-passkeys.invalid:8443",
        "https://wrong.invalid:8443",
        "https://sallimbook-passkeys.invalid:8443/",
        "https://sallimbook-passkeys.invalid:8443?x=1",
        "https://user@sallimbook-passkeys.invalid:8443",
        "https://sallimbook-passkeys.invalid:8443#fragment",
    ],
)
def test_web_origin_configuration_must_be_exact_https_rp_host(origin):
    with pytest.raises(DomainError) as invalid:
        service.policy_from_settings(
            configured_settings(webauthn_web_origins=[origin]), "web", origin
        )
    assert invalid.value.code == "PASSKEY_CONFIGURATION_INVALID"


@pytest.mark.parametrize(
    "rp_id",
    [
        "https://example.invalid",
        "example.invalid:8443",
        "*.invalid",
        "EXAMPLE.invalid",
        "example.invalid.",
    ],
)
def test_rp_id_has_no_scheme_port_wildcard_or_implicit_normalization(rp_id):
    with pytest.raises(DomainError):
        service.policy_from_settings(configured_settings(webauthn_rp_id=rp_id), "web", WEB_ORIGIN)


def test_origin_policies_keep_ports_and_native_certificate_digests_separate():
    web = service.policy_from_settings(configured_settings(), "web", WEB_ORIGIN)
    native = service.policy_from_settings(configured_settings(), "native", None)
    assert web.origins == (WEB_ORIGIN,)
    assert native.origins == (NATIVE_ORIGIN,)
    assert web.digest != native.digest
    with pytest.raises(DomainError):
        service.policy_from_settings(configured_settings(), "web", "https://" + RP_ID)
    for invalid in (NATIVE_ORIGIN + "=", "android:apk-key-hash:short", WEB_ORIGIN):
        with pytest.raises(DomainError) as failure:
            service.policy_from_settings(
                configured_settings(webauthn_native_origins=[invalid]), "native", None
            )
        assert failure.value.code == "PASSKEY_CONFIGURATION_INVALID"


def test_real_library_accepts_synthetic_registration_and_signed_assertion():
    authenticator = SyntheticAuthenticator.create()
    registration_challenge = secrets.token_bytes(32)
    registration = service.verify_registration_proof(
        authenticator.registration(registration_challenge),
        service.challenge_digest(registration_challenge),
        WEB_POLICY,
    )
    assert registration.credential_public_key == authenticator.public_key
    assert registration.user_verified is True
    nonce, user_id = secrets.token_bytes(32), uuid4()
    proof = authenticator.assertion(nonce, user_id)
    result = service.verify_assertion_proof(
        proof,
        service.challenge_digest(nonce),
        WEB_POLICY,
        public_key=registration.credential_public_key,
        sign_count=registration.sign_count,
        user_id=user_id,
        device_type="single_device",
        require_user_handle=True,
    )
    assert result.new_sign_count == 1 and result.user_verified is True


@pytest.mark.parametrize(
    "mutation",
    [
        {"origin": "https://wrong.invalid"},
        {"rp_id": "wrong.invalid"},
        {"uv": False},
        {"up": False},
        {"cross_origin": True},
        {"top_origin": "https://embedding.invalid"},
    ],
)
def test_registration_rejects_wrong_origin_rp_uv_up_and_embedding(mutation):
    authenticator = SyntheticAuthenticator.create()
    nonce = secrets.token_bytes(32)
    proof = authenticator.registration(nonce, **mutation)
    with pytest.raises(service.PasskeyProofError):
        service.verify_registration_proof(proof, service.challenge_digest(nonce), WEB_POLICY)


@pytest.mark.parametrize(
    "mutation",
    [
        {"origin": "https://wrong.invalid"},
        {"rp_id": "wrong.invalid"},
        {"uv": False},
        {"up": False},
        {"cross_origin": True},
        {"top_origin": "https://embedding.invalid"},
        {"corrupt_signature": True},
        {"user_handle": False},
        {"multi_device": True},
    ],
)
def test_signed_assertion_still_rejects_wrong_protocol_or_identity_fields(mutation):
    authenticator = SyntheticAuthenticator.create()
    nonce, user_id = secrets.token_bytes(32), uuid4()
    proof = authenticator.assertion(nonce, user_id, **mutation)
    with pytest.raises(service.PasskeyProofError):
        service.verify_assertion_proof(
            proof,
            service.challenge_digest(nonce),
            WEB_POLICY,
            public_key=authenticator.public_key,
            sign_count=0,
            user_id=user_id,
            device_type="single_device",
            require_user_handle=True,
        )


def test_nonce_user_handle_public_key_and_sign_count_are_all_verified():
    authenticator, different_key = SyntheticAuthenticator.create(), SyntheticAuthenticator.create()
    nonce, user_id = secrets.token_bytes(32), uuid4()
    proof = authenticator.assertion(nonce, user_id)
    defaults = dict(
        expected_hash=service.challenge_digest(nonce),
        policy=WEB_POLICY,
        public_key=authenticator.public_key,
        sign_count=0,
        user_id=user_id,
        device_type="single_device",
        require_user_handle=True,
    )
    for changed in (
        {"expected_hash": service.challenge_digest(secrets.token_bytes(32))},
        {"user_id": uuid4()},
        {"public_key": different_key.public_key},
        {"sign_count": 1},
    ):
        with pytest.raises(service.PasskeyProofError):
            service.verify_assertion_proof(proof, **{**defaults, **changed})


def test_attested_id_must_match_outer_raw_id_and_private_extensions_are_rejected():
    authenticator = SyntheticAuthenticator.create()
    nonce = secrets.token_bytes(32)
    payload = authenticator.registration(nonce).model_dump(mode="json", exclude_none=True)
    payload["id"] = payload["rawId"] = bytes_to_base64url(secrets.token_bytes(32))
    with pytest.raises(service.PasskeyProofError):
        service.verify_registration_proof(
            RegistrationCredential.model_validate(payload),
            service.challenge_digest(nonce),
            WEB_POLICY,
        )
    payload["clientExtensionResults"] = {
        "prf": {"results": {"first": "synthetic-forbidden-output"}}
    }
    with pytest.raises(ValidationError):
        RegistrationCredential.model_validate(payload)


def test_zero_counter_synced_passkeys_still_use_challenge_and_uv_verification():
    authenticator = SyntheticAuthenticator.create(multi_device=True)
    nonce, user_id = secrets.token_bytes(32), uuid4()
    result = service.verify_assertion_proof(
        authenticator.assertion(nonce, user_id, counter=0),
        service.challenge_digest(nonce),
        WEB_POLICY,
        public_key=authenticator.public_key,
        sign_count=0,
        user_id=user_id,
        device_type="multi_device",
        require_user_handle=True,
    )
    assert result.new_sign_count == 0
    assert result.credential_backed_up is True


@dataclass(frozen=True)
class TestAccount:
    __test__ = False
    user_id: UUID
    member_id: UUID
    household_id: UUID
    login_name: str
    password: str = field(repr=False)
    token: str = field(repr=False)
    principal: Principal

    @property
    def headers(self):
        return {**NATIVE_HEADERS, "Authorization": "Bearer " + self.token}


@pytest.fixture
def passkey_app(db_engine):
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(
        environment="test",
        allowed_origins=[WEB_ORIGIN],
        webauthn_rp_id=RP_ID,
        webauthn_web_origins=[WEB_ORIGIN],
        webauthn_native_origins=[NATIVE_ORIGIN],
    )
    install_http_contract(app)
    app.include_router(identity_router)
    app.include_router(router)
    return app


@pytest.fixture
def passkey_account(db_engine):
    password = secrets.token_urlsafe(24)
    with Session(db_engine) as session:
        invitation = identity.create_bootstrap_invitation(
            session, "합성 패스키 가계", "synthetic_owner"
        )
        session.commit()
        member = identity.accept_invitation(
            session,
            InvitationAcceptance(
                token=invitation.token,
                password=password,
                display_name="합성 A",
            ),
            "synthetic-bootstrap",
        )
        authenticated = identity.login(
            session,
            LoginRequest(
                login_name="synthetic_owner",
                password=password,
                device_label="합성 초기 기기",
            ),
            "synthetic-owner",
            "native",
        )
        principal = identity.authenticate(session, authenticated.token, "native")
        session.commit()
    return TestAccount(
        member.user_id,
        member.member_id,
        member.household_id,
        "synthetic_owner",
        password,
        authenticated.token,
        principal,
    )


@pytest.fixture
def enrolled(db_engine, passkey_account):
    authenticator = SyntheticAuthenticator.create()
    with Session(db_engine) as session:
        options = service.registration_options(
            session,
            passkey_account.principal,
            RegisterOptionsRequest(label="합성 패스키"),
            NATIVE_POLICY,
        )
        proof = authenticator.registration(
            base64url_to_bytes(options.public_key["challenge"]), origin=NATIVE_ORIGIN
        )
        stored = service.register_credential(
            session,
            passkey_account.principal,
            RegisterVerification(challenge_id=options.challenge_id, credential=proof),
            NATIVE_POLICY,
        )
    return authenticator, stored.id


def native_options(client, account):
    response = client.post(
        "/api/v1/auth/native/passkeys/options",
        headers=NATIVE_HEADERS,
        json={
            "login_name": account.login_name,
            "device_label": "합성 패스키 로그인 기기",
        },
    )
    assert response.status_code == 200
    return response.json()


def native_verification(options, authenticator, account, **assertion_options):
    proof = authenticator.assertion(
        base64url_to_bytes(options["public_key"]["challenge"]),
        account.user_id,
        origin=assertion_options.pop("origin", NATIVE_ORIGIN),
        **assertion_options,
    )
    return {
        "challenge_id": options["challenge_id"],
        "device_binding": options["device_binding"],
        "credential": proof.model_dump(mode="json", exclude_none=True),
    }


def another_account(db_engine, household_id=None):
    password = secrets.token_urlsafe(24)
    with Session(db_engine) as session:
        if household_id is None:
            household = Household(name="합성 검증용 H2")
            session.add(household)
            session.flush()
            household_id = household.id
            slot = 1
        else:
            slot = 2
        user = User(
            login_name="synthetic_other",
            display_name="합성 B",
            password_hash=identity.PASSWORD_HASHER.hash(password),
        )
        session.add(user)
        session.flush()
        member = HouseholdMember(
            household_id=household_id, user_id=user.id, slot=slot, role="member", status="active"
        )
        session.add(member)
        session.commit()
        login = identity.login(
            session,
            LoginRequest(
                login_name=user.login_name, password=password, device_label="합성 다른 사용자 기기"
            ),
            "synthetic-other",
            "native",
        )
        principal = identity.authenticate(session, login.token, "native")
        session.commit()
        return TestAccount(
            user.id, member.id, household_id, user.login_name, password, login.token, principal
        )


def issue_grant(
    session, account, authenticator, *, target=None, purpose=StepUpPurpose.DEVICE_REVOKE
):
    options = service.step_up_options(
        session,
        account.principal,
        StepUpOptionsRequest(purpose=purpose, target_id=target or account.principal.device_id),
        NATIVE_POLICY,
    )
    proof = authenticator.assertion(
        base64url_to_bytes(options.public_key["challenge"]), account.user_id, origin=NATIVE_ORIGIN
    )
    return service.verify_step_up(
        session,
        account.principal,
        AssertionVerification(challenge_id=options.challenge_id, credential=proof),
        NATIVE_POLICY,
    )


def seed_expired_ceremonies(session, account, credential_id, count):
    now = identity.utcnow()
    challenge_ids, grant_ids = [], []
    for index in range(count):
        challenge_id, grant_id = uuid4(), uuid4()
        challenge_ids.append(challenge_id)
        grant_ids.append(grant_id)
        session.add(
            AuthChallenge(
                id=challenge_id,
                pending_device_id=uuid4(),
                kind="login",
                transport="native",
                label="합성 만료 요청",
                challenge_hash=secrets.token_hex(32),
                binding_hash=secrets.token_hex(32),
                policy_hash=NATIVE_POLICY.digest,
                expires_at=now - timedelta(minutes=1),
                consumed_at=now - timedelta(minutes=2) if index % 2 else None,
            )
        )
        session.add(
            StepUpGrant(
                id=grant_id,
                household_id=account.household_id,
                user_id=account.user_id,
                session_id=account.principal.session_id,
                device_id=account.principal.device_id,
                credential_record_id=credential_id,
                grant_hash=secrets.token_hex(32),
                purpose=StepUpPurpose.DEVICE_REVOKE.value,
                target_id=account.principal.device_id,
                expires_at=now - timedelta(minutes=1),
                consumed_at=now - timedelta(minutes=2) if index % 2 else None,
            )
        )
    session.commit()
    return challenge_ids, grant_ids


@pytest.mark.database
class TestPasskeyDatabase:
    def test_registration_excludes_only_active_credentials(
        self, db_engine, passkey_account, enrolled
    ):
        authenticator, credential_id = enrolled

        def excluded():
            with Session(db_engine) as session:
                options = service.registration_options(
                    session,
                    passkey_account.principal,
                    RegisterOptionsRequest(label="합성 재등록 키"),
                    NATIVE_POLICY,
                )
            return [item["id"] for item in options.public_key.get("excludeCredentials", [])]

        assert excluded() == [bytes_to_base64url(authenticator.credential_id)]
        with Session(db_engine) as session:
            session.get(AuthCredential, credential_id).revoked_at = identity.utcnow()
            session.commit()
        assert excluded() == []

    def test_device_and_passkey_lists_are_newest_first_and_owner_scoped(
        self, passkey_app, passkey_account, db_engine
    ):
        # Imported here: test_pagination -> test_accounts -> test_passkeys would be circular.
        from test_pagination import api_pages, ids, pairs

        account = passkey_account
        spouse = another_account(db_engine, account.household_id)
        days = [3, 1, 4, 2, 5]
        with Session(db_engine) as session:
            devices = [
                RegisteredDevice(
                    id=uuid4(),
                    household_id=account.household_id,
                    user_id=account.user_id,
                    label=f"합성 기기 {n}",
                    platform="android",
                    status="active",
                    last_seen_at=datetime(2026, 1, day, tzinfo=UTC),
                    created_at=datetime(2026, 1, day, tzinfo=UTC),
                )
                for n, day in enumerate(days[:4])
            ]
            keys = [
                AuthCredential(
                    id=uuid4(),
                    household_id=account.household_id,
                    user_id=account.user_id,
                    created_device_id=account.principal.device_id,
                    credential_id=secrets.token_bytes(32),
                    public_key=b"synthetic-public-key",
                    rp_id=RP_ID,
                    label=f"합성 패스키 {n}",
                    sign_count=0,
                    aaguid=UUID(int=0),
                    transports=[],
                    device_type="single_device",
                    backed_up=False,
                    created_at=datetime(2026, 1, day, tzinfo=UTC),
                )
                for n, day in enumerate(days)
            ]
            session.add_all([*devices, *keys])
            session.commit()
            device_ids = [str(row.id) for row in devices]
            key_ids = [str(row.id) for row in keys]
        login_device = str(account.principal.device_id)  # created now, so newest
        with TestClient(passkey_app, base_url="https://testserver") as client:
            expected = [login_device, *(device_ids[i] for i in (2, 0, 3, 1))]
            assert ids(api_pages(client, account, "/api/v1/devices")) == pairs(expected)
            expected = [key_ids[i] for i in (4, 2, 0, 3, 1)]
            assert ids(api_pages(client, account, "/api/v1/auth/passkeys")) == pairs(expected)
            other = client.get(
                "/api/v1/devices",
                headers=account.headers,
                params={"cursor": str(spouse.principal.device_id)},
            )
            assert other.status_code == 404 and other.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.parametrize(
        "invalid_state",
        [
            "session_revoked",
            "session_expired",
            "access_expired",
            "device_revoked",
            "login_old",
        ],
    )
    def test_registration_revalidates_live_identity_instead_of_a_cached_principal(
        self, db_engine, passkey_account, invalid_state
    ):
        authenticator = SyntheticAuthenticator.create()
        with Session(db_engine) as session:
            options = service.registration_options(
                session,
                passkey_account.principal,
                RegisterOptionsRequest(label="합성 대기 등록"),
                NATIVE_POLICY,
            )
            payload = RegisterVerification(
                challenge_id=options.challenge_id,
                credential=authenticator.registration(
                    base64url_to_bytes(options.public_key["challenge"]), origin=NATIVE_ORIGIN
                ),
            )
            auth = session.get(AuthSession, passkey_account.principal.session_id)
            now = identity.utcnow()
            if invalid_state == "session_revoked":
                auth.revoked_at = now
            elif invalid_state == "session_expired":
                auth.expires_at = now - timedelta(seconds=1)
                auth.access_expires_at = auth.expires_at
            elif invalid_state == "access_expired":
                auth.access_expires_at = now - timedelta(seconds=1)
            elif invalid_state == "device_revoked":
                device = session.get(RegisteredDevice, passkey_account.principal.device_id)
                device.status = "revoked"
                device.revoked_at = now
            else:
                auth.authenticated_at = now - timedelta(minutes=6)
            session.commit()
            with pytest.raises(DomainError) as failure:
                service.register_credential(
                    session, passkey_account.principal, payload, NATIVE_POLICY
                )
            assert failure.value.code == (
                "REAUTHENTICATION_REQUIRED" if invalid_state == "login_old" else "UNAUTHENTICATED"
            )
            session.rollback()
            assert session.scalar(select(func.count()).select_from(AuthCredential)) == 0

    def test_registration_waits_for_device_revocation_then_rejects_the_stale_principal(
        self, db_engine, passkey_account
    ):
        authenticator = SyntheticAuthenticator.create()
        with Session(db_engine) as session:
            options = service.registration_options(
                session,
                passkey_account.principal,
                RegisterOptionsRequest(label="합성 경합 등록"),
                NATIVE_POLICY,
            )
            payload = RegisterVerification(
                challenge_id=options.challenge_id,
                credential=authenticator.registration(
                    base64url_to_bytes(options.public_key["challenge"]), origin=NATIVE_ORIGIN
                ),
            )
            other_login = identity.login(
                session,
                LoginRequest(
                    login_name=passkey_account.login_name,
                    password=passkey_account.password,
                    device_label="합성 폐기 요청 기기",
                ),
                "synthetic-device-revoker",
                "native",
            )

        authenticated, begin_registration = Event(), Event()
        backend = []

        def enroll():
            with Session(db_engine) as session:
                principal = identity.authenticate(session, passkey_account.token, "native")
                backend.append(session.scalar(select(func.pg_backend_pid())))
                authenticated.set()
                assert begin_registration.wait(timeout=10)
                try:
                    service.register_credential(session, principal, payload, NATIVE_POLICY)
                    return "registered"
                except DomainError as failure:
                    return failure.code

        with ThreadPoolExecutor(max_workers=1) as pool:
            enrollment = pool.submit(enroll)
            try:
                assert authenticated.wait(timeout=10)
                with Session(db_engine) as revocation:
                    revoker = identity.authenticate(revocation, other_login.token, "native")
                    device = scoped_entity(
                        revocation,
                        RegisteredDevice,
                        passkey_account.principal.device_id,
                        revoker,
                        for_update=True,
                    )
                    device.status = "revoked"
                    device.revoked_at = identity.utcnow()
                    revocation.flush()
                    revoker_pid = revocation.scalar(select(func.pg_backend_pid()))
                    begin_registration.set()
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        blockers = revocation.scalar(select(func.pg_blocking_pids(backend[0])))
                        if revoker_pid in blockers or enrollment.done():
                            break
                        time.sleep(0.01)
                    assert revoker_pid in blockers, (
                        "Enrollment must serialize on the revoking device row"
                    )
                    identity.revoke_device(revocation, revoker, device)
                assert enrollment.result(timeout=10) == "UNAUTHENTICATED"
            finally:
                begin_registration.set()
        with Session(db_engine) as session:
            assert (
                session.get(RegisteredDevice, passkey_account.principal.device_id).status
                == "revoked"
            )
            assert session.scalar(select(func.count()).select_from(AuthCredential)) == 0
            assert session.get(AuthChallenge, options.challenge_id).consumed_at is None

    @pytest.mark.parametrize(
        "blocked_on,change,with_grant,expected",
        [
            ("credential", "revoke", True, "STEP_UP_REQUIRED"),
            ("device", "revoke", True, "UNAUTHENTICATED"),
            ("device", "revoke", False, "UNAUTHENTICATED"),
            ("grant", "expire_grant", True, "STEP_UP_REQUIRED"),
            ("credential", "expire_access", True, "UNAUTHENTICATED"),
            ("household", "expire_recent", False, "REAUTHENTICATION_REQUIRED"),
        ],
    )
    def test_invitation_rechecks_after_real_lock_wait(
        self,
        db_engine,
        passkey_account,
        enrolled,
        monkeypatch,
        blocked_on,
        change,
        with_grant,
        expected,
    ):
        authenticator, credential_id = enrolled
        with Session(db_engine) as session:
            grant = issue_grant(
                session,
                passkey_account,
                authenticator,
                purpose=StepUpPurpose.HOUSEHOLD_INVITE,
                target=passkey_account.household_id,
            )
            grant_id = session.scalar(select(StepUpGrant.id))
            auth = session.get(AuthSession, passkey_account.principal.session_id)
            access_expiry, authenticated_at = auth.access_expires_at, auth.authenticated_at
        ready, proceed = Event(), Event()
        backend = []

        def invite():
            with Session(db_engine) as session:
                principal = identity.authenticate(session, passkey_account.token, "native")
                cached = [
                    session.get(AuthCredential, credential_id),
                    session.get(RegisteredDevice, principal.device_id),
                    session.get(StepUpGrant, grant_id),
                ]
                backend.append(session.scalar(select(func.pg_backend_pid())))
                ready.set()
                assert proceed.wait(timeout=10)
                try:
                    identity.create_partner_invitation(
                        session,
                        principal,
                        InvitationRequest(intended_login="synthetic_partner"),
                        step_up_token=grant.grant_token if with_grant else None,
                    )
                    return "created"
                except DomainError as failure:
                    assert len(cached) == 3
                    return failure.code

        targets = {
            "credential": (AuthCredential, credential_id),
            "device": (RegisteredDevice, passkey_account.principal.device_id),
            "grant": (StepUpGrant, grant_id),
            "household": (Household, passkey_account.household_id),
        }
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(invite)
            try:
                assert ready.wait(timeout=10)
                with Session(db_engine) as blocker:
                    model, target = targets[blocked_on]
                    row = blocker.scalar(select(model).where(model.id == target).with_for_update())
                    blocker_pid = blocker.scalar(select(func.pg_backend_pid()))
                    proceed.set()
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        blockers = blocker.scalar(select(func.pg_blocking_pids(backend[0])))
                        if blocker_pid in blockers or future.done():
                            break
                        time.sleep(0.01)
                    assert blocker_pid in blockers, "Protected operation must wait on its barrier"
                    if change == "revoke":
                        row.revoked_at = identity.utcnow()
                        if blocked_on == "device":
                            row.status = "revoked"
                    else:
                        after = {
                            "expire_grant": grant.expires_at,
                            "expire_access": access_expiry,
                            "expire_recent": authenticated_at + timedelta(minutes=5),
                        }[change] + timedelta(seconds=1)
                        monkeypatch.setattr(identity, "utcnow", lambda: after)
                    blocker.commit()
                assert future.result(timeout=10) == expected
            finally:
                proceed.set()
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(Invitation).where(Invitation.kind == "partner")
                )
                == 0
            )
            assert session.get(StepUpGrant, grant_id).consumed_at is None

    @pytest.mark.parametrize("reverse_submission", [False, True])
    def test_opposite_device_revocations_lock_sorted_complete_set(
        self,
        db_engine,
        passkey_account,
        reverse_submission,
    ):
        with Session(db_engine) as session:
            other_login = identity.login(
                session,
                LoginRequest(
                    login_name=passkey_account.login_name,
                    password=passkey_account.password,
                    device_label="합성 두 번째 기기",
                ),
                "synthetic-opposite",
                "native",
            )
            other = identity.authenticate(session, other_login.token, "native")
            session.commit()
        actors = sorted(
            [
                (passkey_account.token, passkey_account.principal.device_id),
                (other_login.token, other.device_id),
            ],
            key=lambda actor: actor[1],
            reverse=reverse_submission,
        )
        ready = Barrier(2)

        def revoke(actor, target):
            with Session(db_engine) as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                principal = identity.authenticate(session, actor[0], "native")
                ready.wait(timeout=10)
                try:
                    return revoke_device_route(
                        target[1], principal, session, '"1"', None
                    ).status_code
                except DomainError as failure:
                    return failure.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(revoke, actors[0], actors[1])
            second = pool.submit(revoke, actors[1], actors[0])
            results = [first.result(timeout=15), second.result(timeout=15)]
        assert sorted(map(str, results)) == ["204", "UNAUTHENTICATED"]
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(RegisteredDevice)
                    .where(RegisteredDevice.status == "revoked")
                )
                == 1
            )

    def test_step_up_issuance_device_fk_does_not_invert_concurrent_device_revocation(
        self,
        db_engine,
        passkey_account,
        enrolled,
    ):
        authenticator, credential_id = enrolled
        with Session(db_engine) as session:
            options = service.step_up_options(
                session,
                passkey_account.principal,
                StepUpOptionsRequest(
                    purpose=StepUpPurpose.HOUSEHOLD_INVITE, target_id=passkey_account.household_id
                ),
                NATIVE_POLICY,
            )
            proof = authenticator.assertion(
                base64url_to_bytes(options.public_key["challenge"]),
                passkey_account.user_id,
                origin=NATIVE_ORIGIN,
            )
            payload = AssertionVerification(challenge_id=options.challenge_id, credential=proof)
            other_login = identity.login(
                session,
                LoginRequest(
                    login_name=passkey_account.login_name,
                    password=passkey_account.password,
                    device_label="합성 폐기 기기",
                ),
                "synthetic-fk-lock-order",
                "native",
            )
        verifier_ready, revoker_ready = Event(), Event()
        pids = {}

        def verify():
            with Session(db_engine) as session:
                session.execute(text("SET LOCAL lock_timeout = '8s'"))
                principal = identity.authenticate(session, passkey_account.token, "native")
                pids["verify"] = session.scalar(select(func.pg_backend_pid()))
                verifier_ready.set()
                return service.verify_step_up(session, principal, payload, NATIVE_POLICY)

        def revoke():
            with Session(db_engine) as session:
                session.execute(text("SET LOCAL lock_timeout = '8s'"))
                principal = identity.authenticate(session, other_login.token, "native")
                pids["revoke"] = session.scalar(select(func.pg_backend_pid()))
                revoker_ready.set()
                return revoke_device_route(
                    passkey_account.principal.device_id, principal, session, '"1"', None
                ).status_code

        def wait_blocked(observer, waiter, blocker, future):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                blockers = observer.scalar(select(func.pg_blocking_pids(waiter)))
                if blocker in blockers or future.done():
                    break
                time.sleep(0.01)
            assert blocker in blockers

        with ThreadPoolExecutor(max_workers=2) as pool:
            with Session(db_engine) as blocker:
                blocker.scalar(
                    select(AuthCredential)
                    .where(AuthCredential.id == credential_id)
                    .with_for_update()
                )
                blocker_pid = blocker.scalar(select(func.pg_backend_pid()))
                verification = pool.submit(verify)
                assert verifier_ready.wait(timeout=10)
                wait_blocked(blocker, pids["verify"], blocker_pid, verification)
                revocation = pool.submit(revoke)
                assert revoker_ready.wait(timeout=10)
                wait_blocked(blocker, pids["revoke"], pids["verify"], revocation)
                blocker.commit()
            grant = verification.result(timeout=15)
            assert revocation.result(timeout=15) == 204
        with Session(db_engine) as session:
            with pytest.raises(DomainError) as rejected:
                service.consume_step_up(
                    session,
                    passkey_account.principal,
                    grant.grant_token,
                    grant.purpose,
                    grant.target_id,
                )
            assert rejected.value.code == "UNAUTHENTICATED"

    def test_self_revocation_uses_single_device_barrier(self, db_engine, passkey_account):
        with Session(db_engine) as session:
            principal = identity.authenticate(session, passkey_account.token, "native")
            assert (
                revoke_device_route(
                    principal.device_id, principal, session, '"1"', None
                ).status_code
                == 204
            )
            assert session.get(RegisteredDevice, principal.device_id).status == "revoked"

    @pytest.mark.parametrize("ceremony", ["register", "login", "step_up"])
    def test_ceremony_creation_prunes_a_bounded_batch_and_preserves_active_rows(
        self, db_engine, passkey_account, enrolled, ceremony
    ):
        authenticator, credential_id = enrolled
        with Session(db_engine) as session:
            active_grant = issue_grant(session, passkey_account, authenticator)
            active_challenges = set(session.scalars(select(AuthChallenge.id)))
            challenge_ids, grant_ids = seed_expired_ceremonies(
                session, passkey_account, credential_id, service.EXPIRY_CLEANUP_BATCH + 3
            )
            if ceremony == "register":
                service.registration_options(
                    session,
                    passkey_account.principal,
                    RegisterOptionsRequest(label="합성 새 요청"),
                    NATIVE_POLICY,
                )
            elif ceremony == "login":
                service.login_options(
                    session,
                    LoginOptionsRequest(
                        login_name=passkey_account.login_name, device_label="합성 새 기기"
                    ),
                    NATIVE_POLICY,
                    "synthetic-retention",
                )
            else:
                service.step_up_options(
                    session,
                    passkey_account.principal,
                    StepUpOptionsRequest(
                        purpose=StepUpPurpose.DEVICE_REVOKE,
                        target_id=passkey_account.principal.device_id,
                    ),
                    NATIVE_POLICY,
                )
        with Session(db_engine) as session:
            remaining_challenges = set(session.scalars(select(AuthChallenge.id)))
            remaining_grants = set(session.scalars(select(StepUpGrant.id)))
            assert active_challenges <= remaining_challenges
            assert len(set(challenge_ids) & remaining_challenges) == 3
            assert len(set(grant_ids) & remaining_grants) == 3
            service.consume_step_up(
                session,
                passkey_account.principal,
                active_grant.grant_token,
                active_grant.purpose,
                active_grant.target_id,
            )
            session.commit()

    def test_expiry_cleanup_skips_locked_rows_and_preserves_transaction_locks_and_rollback(
        self, db_engine, passkey_account, enrolled
    ):
        _, credential_id = enrolled
        with Session(db_engine) as session:
            challenge_ids, grant_ids = seed_expired_ceremonies(
                session, passkey_account, credential_id, 2
            )
        with Session(db_engine) as held, Session(db_engine) as cleanup:
            held.scalar(
                select(AuthChallenge).where(AuthChallenge.id == challenge_ids[0]).with_for_update()
            )
            held.scalar(select(StepUpGrant).where(StepUpGrant.id == grant_ids[0]).with_for_update())
            cleanup.execute(text("SET LOCAL lock_timeout = '200ms'"))
            identity.authenticate(cleanup, passkey_account.token, "native")
            service._prune_expired_ceremonies(cleanup)
            assert (
                cleanup.scalar(
                    select(func.count())
                    .select_from(AuthChallenge)
                    .where(AuthChallenge.id.in_(challenge_ids))
                )
                == 1
            )
            assert (
                cleanup.scalar(
                    select(func.count())
                    .select_from(StepUpGrant)
                    .where(StepUpGrant.id.in_(grant_ids))
                )
                == 1
            )
            with Session(db_engine) as observer:
                with pytest.raises(OperationalError) as locked:
                    observer.scalar(
                        select(AuthSession)
                        .where(AuthSession.id == passkey_account.principal.session_id)
                        .with_for_update(nowait=True)
                    )
                assert locked.value.orig.sqlstate == "55P03"
            cleanup.rollback()
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuthChallenge)
                    .where(AuthChallenge.id.in_(challenge_ids))
                )
                == 2
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(StepUpGrant)
                    .where(StepUpGrant.id.in_(grant_ids))
                )
                == 2
            )

    def test_expiry_cleanup_never_restores_a_rejected_proofs_challenge(
        self, db_engine, passkey_account, enrolled
    ):
        authenticator, _ = enrolled
        with Session(db_engine) as session:
            options = service.login_options(
                session,
                LoginOptionsRequest(
                    login_name=passkey_account.login_name, device_label="합성 재전송 시험"
                ),
                NATIVE_POLICY,
                "synthetic-retention-replay",
            )
            challenge = base64url_to_bytes(options.response.public_key["challenge"])
            bad = AssertionVerification(
                challenge_id=options.response.challenge_id,
                credential=authenticator.assertion(
                    challenge, passkey_account.user_id, origin=NATIVE_ORIGIN, corrupt_signature=True
                ),
            )
            with pytest.raises(DomainError) as rejected:
                service.verify_login(
                    session,
                    bad,
                    NATIVE_POLICY,
                    options.device_binding,
                    "synthetic-retention-replay",
                )
            assert rejected.value.code == "PASSKEY_VERIFICATION_FAILED"
            valid = AssertionVerification(
                challenge_id=options.response.challenge_id,
                credential=authenticator.assertion(
                    challenge, passkey_account.user_id, origin=NATIVE_ORIGIN
                ),
            )
            for expire in (False, True):
                if expire:
                    session.get(AuthChallenge, options.response.challenge_id).expires_at = (
                        identity.utcnow() - timedelta(seconds=1)
                    )
                    session.commit()
                service.registration_options(
                    session,
                    passkey_account.principal,
                    RegisterOptionsRequest(label="합성 정리 요청"),
                    NATIVE_POLICY,
                )
                row = session.scalar(
                    select(AuthChallenge).where(AuthChallenge.id == options.response.challenge_id)
                )
                if expire:
                    assert row is None
                else:
                    assert row.consumed_at is not None
                with pytest.raises(DomainError) as replay:
                    service.verify_login(
                        session,
                        valid,
                        NATIVE_POLICY,
                        options.device_binding,
                        "synthetic-retention-replay",
                    )
                assert replay.value.code == "INVALID_AUTH_CHALLENGE"
                session.rollback()

    def test_invitation_grant_is_atomic_with_operation_and_does_not_refresh_login(
        self, db_engine, passkey_app, passkey_account, enrolled
    ):
        authenticator, _ = enrolled
        with Session(db_engine) as session:
            grant = issue_grant(
                session,
                passkey_account,
                authenticator,
                purpose=StepUpPurpose.HOUSEHOLD_INVITE,
                target=passkey_account.household_id,
            )
            auth = session.get(AuthSession, passkey_account.principal.session_id)
            old_login = auth.authenticated_at - timedelta(minutes=6)
            auth.authenticated_at = old_login
            session.commit()
        headers = {**passkey_account.headers, "X-Step-Up-Token": grant.grant_token}
        with TestClient(passkey_app) as client:
            missing = client.post(
                "/api/v1/household/invitations",
                headers=passkey_account.headers,
                json={"intended_login": "synthetic_partner"},
            )
            assert missing.status_code == 403
            assert missing.json()["error"]["code"] == "REAUTHENTICATION_REQUIRED"
            conflict = client.post(
                "/api/v1/household/invitations",
                headers=headers,
                json={"intended_login": passkey_account.login_name},
            )
            assert conflict.status_code == 409
            with Session(db_engine) as session:
                assert session.scalar(select(StepUpGrant.consumed_at)) is None
            created = client.post(
                "/api/v1/household/invitations",
                headers=headers,
                json={"intended_login": "synthetic_partner"},
            )
            assert created.status_code == 201
            replay = client.post(
                "/api/v1/household/invitations",
                headers=headers,
                json={"intended_login": "synthetic_other_partner"},
            )
            assert replay.status_code == 403
            assert replay.json()["error"]["code"] == "STEP_UP_REQUIRED"
        with Session(db_engine) as session:
            assert session.scalar(select(StepUpGrant.consumed_at)) is not None
            assert (
                session.get(AuthSession, passkey_account.principal.session_id).authenticated_at
                == old_login
            )

    def test_device_grant_survives_version_conflict_then_commits_once(
        self, db_engine, passkey_app, passkey_account, enrolled
    ):
        authenticator, _ = enrolled
        with Session(db_engine) as session:
            target_login = identity.login(
                session,
                LoginRequest(
                    login_name=passkey_account.login_name,
                    password=passkey_account.password,
                    device_label="합성 해제 대상",
                ),
                "synthetic-revoke-target",
                "native",
            )
            target = identity.authenticate(session, target_login.token, "native")
            session.commit()
            target_version = session.get(RegisteredDevice, target.device_id).version
            grant = issue_grant(session, passkey_account, authenticator, target=target.device_id)
            auth = session.get(AuthSession, passkey_account.principal.session_id)
            old_login = auth.authenticated_at - timedelta(minutes=6)
            auth.authenticated_at = old_login
            session.commit()
        path = f"/api/v1/devices/{target.device_id}"
        headers = {
            **passkey_account.headers,
            "X-Step-Up-Token": grant.grant_token,
            "If-Match": f'"{target_version}"',
        }
        with TestClient(passkey_app) as client:
            missing = client.delete(
                path, headers={**passkey_account.headers, "If-Match": f'"{target_version}"'}
            )
            assert missing.status_code == 403
            assert missing.json()["error"]["code"] == "REAUTHENTICATION_REQUIRED"
            conflict = client.delete(path, headers={**headers, "If-Match": '"999"'})
            assert conflict.status_code == 409
            with Session(db_engine) as session:
                assert session.scalar(select(StepUpGrant.consumed_at)) is None
                assert session.get(RegisteredDevice, target.device_id).status == "active"
            result = client.delete(path, headers=headers)
            assert result.status_code == 204
            with Session(db_engine) as session:
                device = session.get(RegisteredDevice, target.device_id)
                assert device.status == "revoked"
                assert session.scalar(select(StepUpGrant.consumed_at)) is not None
                headers["If-Match"] = f'"{device.version}"'
                assert (
                    session.get(AuthSession, passkey_account.principal.session_id).authenticated_at
                    == old_login
                )
            replay = client.delete(path, headers=headers)
            assert replay.status_code == 403
            assert replay.json()["error"]["code"] == "STEP_UP_REQUIRED"

    def test_explicit_invalid_grant_is_not_ignored_for_recent_password_login(
        self, db_engine, passkey_app, passkey_account
    ):
        with Session(db_engine) as session:
            device = session.get(RegisteredDevice, passkey_account.principal.device_id)
            version = device.version
        headers = {**passkey_account.headers, "X-Step-Up-Token": "invalid"}
        with TestClient(passkey_app) as client:
            invitation = client.post(
                "/api/v1/household/invitations",
                headers=headers,
                json={"intended_login": "synthetic_partner"},
            )
            assert invitation.status_code == 403
            assert invitation.json()["error"]["code"] == "STEP_UP_REQUIRED"
            revoke = client.delete(
                f"/api/v1/devices/{passkey_account.principal.device_id}",
                headers={**headers, "If-Match": f'"{version}"'},
            )
            assert revoke.status_code == 403
            assert revoke.json()["error"]["code"] == "STEP_UP_REQUIRED"

    def test_registration_is_authenticated_recent_and_stores_only_public_material(
        self,
        passkey_app,
        db_engine,
        passkey_account,
    ):
        authenticator = SyntheticAuthenticator.create()
        with TestClient(passkey_app, base_url="https://testserver") as client:
            assert (
                client.post(
                    "/api/v1/auth/passkeys/register/options",
                    headers=NATIVE_HEADERS,
                    json={"label": "합성 키"},
                ).status_code
                == 401
            )
            options = client.post(
                "/api/v1/auth/passkeys/register/options",
                headers=passkey_account.headers,
                json={"label": "합성 키"},
            )
            assert options.status_code == 200
            data = options.json()
            selection = data["public_key"]["authenticatorSelection"]
            assert selection["userVerification"] == "required"
            assert selection["residentKey"] == "required"
            nonce = base64url_to_bytes(data["public_key"]["challenge"])
            proof = authenticator.registration(nonce, origin=NATIVE_ORIGIN)
            result = client.post(
                "/api/v1/auth/passkeys/register/verify",
                headers=passkey_account.headers,
                json={
                    "challenge_id": data["challenge_id"],
                    "credential": proof.model_dump(mode="json", exclude_none=True),
                },
            )
            assert result.status_code == 201
            assert "public_key" not in result.json() and "credential_id" not in result.json()
        with Session(db_engine) as session:
            challenge = session.get(AuthChallenge, UUID(data["challenge_id"]))
            credential = session.get(AuthCredential, UUID(result.json()["id"]))
            assert challenge.challenge_hash == service.challenge_digest(nonce)
            assert challenge.consumed_at is not None
            assert credential.public_key == authenticator.public_key
            assert credential.user_id == passkey_account.user_id
            assert credential.created_device_id == passkey_account.principal.device_id
            assert not {"private_key", "assertion", "client_data_json"} & set(
                AuthCredential.__table__.c.keys()
            )

    def test_registration_needs_recent_login_at_verification_too(
        self,
        db_engine,
        passkey_account,
        monkeypatch,
    ):
        now = identity.utcnow()
        authenticator = SyntheticAuthenticator.create()
        with Session(db_engine) as session:
            monkeypatch.setattr(identity, "utcnow", lambda: now + timedelta(minutes=4))
            options = service.registration_options(
                session,
                passkey_account.principal,
                RegisterOptionsRequest(label="합성 키"),
                NATIVE_POLICY,
            )
            proof = authenticator.registration(
                base64url_to_bytes(options.public_key["challenge"]), origin=NATIVE_ORIGIN
            )
            monkeypatch.setattr(identity, "utcnow", lambda: now + timedelta(minutes=6))
            with pytest.raises(DomainError) as rejected:
                service.register_credential(
                    session,
                    passkey_account.principal,
                    RegisterVerification(challenge_id=options.challenge_id, credential=proof),
                    NATIVE_POLICY,
                )
            assert rejected.value.code == "REAUTHENTICATION_REQUIRED"
            assert session.scalar(select(func.count()).select_from(AuthCredential)) == 0

    def test_failed_proof_consumes_challenge_and_cannot_be_retried(
        self,
        db_engine,
        passkey_account,
    ):
        authenticator = SyntheticAuthenticator.create()
        with Session(db_engine) as session:
            options = service.registration_options(
                session,
                passkey_account.principal,
                RegisterOptionsRequest(label="합성 키"),
                NATIVE_POLICY,
            )
            nonce = base64url_to_bytes(options.public_key["challenge"])
            with pytest.raises(DomainError) as invalid:
                service.register_credential(
                    session,
                    passkey_account.principal,
                    RegisterVerification(
                        challenge_id=options.challenge_id,
                        credential=authenticator.registration(
                            nonce, origin=NATIVE_ORIGIN, uv=False
                        ),
                    ),
                    NATIVE_POLICY,
                )
            assert invalid.value.code == "PASSKEY_VERIFICATION_FAILED"
            assert session.get(AuthChallenge, options.challenge_id).consumed_at is not None
            with pytest.raises(DomainError) as replay:
                service.register_credential(
                    session,
                    passkey_account.principal,
                    RegisterVerification(
                        challenge_id=options.challenge_id,
                        credential=authenticator.registration(nonce, origin=NATIVE_ORIGIN),
                    ),
                    NATIVE_POLICY,
                )
            assert replay.value.code == "INVALID_AUTH_CHALLENGE"
            assert session.scalar(select(func.count()).select_from(AuthCredential)) == 0

    def test_registration_challenge_is_bound_to_session_device_and_transport(
        self,
        db_engine,
        passkey_account,
    ):
        authenticator = SyntheticAuthenticator.create()
        with Session(db_engine) as session:
            options = service.registration_options(
                session,
                passkey_account.principal,
                RegisterOptionsRequest(label="합성 키"),
                NATIVE_POLICY,
            )
            other_login = identity.login(
                session,
                LoginRequest(
                    login_name=passkey_account.login_name,
                    password=passkey_account.password,
                    device_label="합성 다른 기기",
                ),
                "synthetic-second",
                "native",
            )
            other = identity.authenticate(session, other_login.token, "native")
            session.commit()
            payload = RegisterVerification(
                challenge_id=options.challenge_id,
                credential=authenticator.registration(
                    base64url_to_bytes(options.public_key["challenge"]), origin=NATIVE_ORIGIN
                ),
            )
            for principal, policy in (
                (other, NATIVE_POLICY),
                (passkey_account.principal, WEB_POLICY),
            ):
                with pytest.raises(DomainError) as mismatch:
                    service.register_credential(session, principal, payload, policy)
                assert mismatch.value.code == "INVALID_AUTH_CHALLENGE"
                session.rollback()
            assert session.get(AuthChallenge, options.challenge_id).consumed_at is None
            service.register_credential(session, passkey_account.principal, payload, NATIVE_POLICY)

    def test_native_passkey_login_issues_shared_session_and_blocks_replay(
        self,
        passkey_app,
        db_engine,
        passkey_account,
        enrolled,
    ):
        authenticator, credential_id = enrolled
        with TestClient(passkey_app, base_url="https://testserver") as client:
            options = native_options(client, passkey_account)
            payload = native_verification(options, authenticator, passkey_account)
            result = client.post(
                "/api/v1/auth/native/passkeys/verify", headers=NATIVE_HEADERS, json=payload
            )
            assert result.status_code == 200
            tokens = result.json()
            assert tokens["expires_in"] == 600 and "refresh_token" in tokens
            me = client.get(
                "/api/v1/me", headers={"Authorization": "Bearer " + tokens["access_token"]}
            )
            assert me.status_code == 200 and me.json()["user_id"] == str(passkey_account.user_id)
            assert (
                client.post(
                    "/api/v1/auth/native/passkeys/verify", headers=NATIVE_HEADERS, json=payload
                ).status_code
                == 400
            )
        with Session(db_engine) as session:
            challenge = session.get(AuthChallenge, UUID(options["challenge_id"]))
            device = session.get(RegisteredDevice, challenge.pending_device_id)
            assert device.user_id == passkey_account.user_id
            assert session.get(AuthCredential, credential_id).sign_count == 1
            assert challenge.binding_hash == identity.token_hash(
                "passkey-device-binding", options["device_binding"]
            )

    def test_web_login_binding_cookie_cannot_be_replaced_by_client_boolean(
        self,
        passkey_app,
        db_engine,
        passkey_account,
        enrolled,
    ):
        authenticator, _ = enrolled
        with (
            TestClient(passkey_app, base_url="https://testserver") as client,
            TestClient(passkey_app, base_url="https://testserver") as stranger,
        ):
            response = client.post(
                "/api/v1/auth/web/passkeys/options",
                headers={"Origin": WEB_ORIGIN},
                json={"login_name": passkey_account.login_name, "device_label": "합성 PC"},
            )
            assert response.status_code == 200
            assert "device_binding" not in response.json()
            assert (
                "HttpOnly" in response.headers["set-cookie"]
                and "Secure" in response.headers["set-cookie"]
            )
            options = response.json()
            proof = authenticator.assertion(
                base64url_to_bytes(options["public_key"]["challenge"]), passkey_account.user_id
            )
            payload = {
                "challenge_id": options["challenge_id"],
                "credential": proof.model_dump(mode="json", exclude_none=True),
            }
            assert (
                stranger.post(
                    "/api/v1/auth/web/passkeys/verify", headers={"Origin": WEB_ORIGIN}, json=payload
                ).status_code
                == 400
            )
            result = client.post(
                "/api/v1/auth/web/passkeys/verify", headers={"Origin": WEB_ORIGIN}, json=payload
            )
            assert result.status_code == 200
            assert set(result.json()) == {"member", "csrf_token", "expires_at"}
            assert SESSION_COOKIE in client.cookies and BINDING_COOKIE not in client.cookies
            assert client.get("/api/v1/me").status_code == 200
        with Session(db_engine) as session:
            assert session.get(AuthChallenge, UUID(options["challenge_id"])).consumed_at is not None

    def test_unknown_and_disabled_accounts_have_same_options_shape(
        self,
        passkey_app,
        db_engine,
        passkey_account,
        enrolled,
    ):
        with TestClient(passkey_app, base_url="https://testserver") as client:
            known = native_options(client, passkey_account)
            unknown = client.post(
                "/api/v1/auth/native/passkeys/options",
                headers=NATIVE_HEADERS,
                json={"login_name": "synthetic_missing", "device_label": "합성 기기"},
            )
            assert unknown.status_code == 200
            with Session(db_engine) as session:
                session.get(User, passkey_account.user_id).disabled_at = identity.utcnow()
                session.commit()
            disabled = native_options(client, passkey_account)
        shapes = []
        for result in (known, unknown.json(), disabled):
            options = dict(result["public_key"])
            options.pop("challenge")
            shapes.append(options)
            assert options.get("allowCredentials", []) == []
        assert shapes[0] == shapes[1] == shapes[2]

    def test_login_rejects_uv_signature_and_old_counter_and_burns_challenge(
        self,
        passkey_app,
        passkey_account,
        enrolled,
    ):
        authenticator, _ = enrolled
        with TestClient(passkey_app, base_url="https://testserver") as client:
            good = native_options(client, passkey_account)
            assert (
                client.post(
                    "/api/v1/auth/native/passkeys/verify",
                    headers=NATIVE_HEADERS,
                    json=native_verification(good, authenticator, passkey_account),
                ).status_code
                == 200
            )
            for mutation in (
                {"uv": False},
                {"corrupt_signature": True},
                {"counter": 1},
                {"origin": WEB_ORIGIN},
            ):
                options = native_options(client, passkey_account)
                payload = native_verification(options, authenticator, passkey_account, **mutation)
                assert (
                    client.post(
                        "/api/v1/auth/native/passkeys/verify", headers=NATIVE_HEADERS, json=payload
                    ).status_code
                    == 401
                )
                assert (
                    client.post(
                        "/api/v1/auth/native/passkeys/verify", headers=NATIVE_HEADERS, json=payload
                    ).status_code
                    == 400
                )

    def test_challenge_expiration_and_policy_change_fail_closed(
        self,
        db_engine,
        passkey_account,
        enrolled,
        monkeypatch,
    ):
        authenticator, _ = enrolled
        with Session(db_engine) as session:
            options = service.login_options(
                session,
                LoginOptionsRequest(
                    login_name=passkey_account.login_name,
                    device_label="합성 기기",
                ),
                NATIVE_POLICY,
                "synthetic-native",
            )
            proof = authenticator.assertion(
                base64url_to_bytes(options.response.public_key["challenge"]),
                passkey_account.user_id,
                origin=NATIVE_ORIGIN,
            )
            payload = AssertionVerification(
                challenge_id=options.response.challenge_id, credential=proof
            )
            altered = service.VerificationPolicy(
                RP_ID,
                (
                    NATIVE_ORIGIN,
                    "android:apk-key-hash:" + bytes_to_base64url(bytes(reversed(range(32)))),
                ),
                "native",
            )
            with pytest.raises(DomainError) as policy_change:
                service.verify_login(
                    session, payload, altered, options.device_binding, "synthetic-native"
                )
            assert policy_change.value.code == "INVALID_AUTH_CHALLENGE"
            session.rollback()
            monkeypatch.setattr(
                identity, "utcnow", lambda: options.response.expires_at + timedelta(seconds=1)
            )
            with pytest.raises(DomainError) as expired:
                service.verify_login(
                    session, payload, NATIVE_POLICY, options.device_binding, "synthetic-native"
                )
            assert expired.value.code == "INVALID_AUTH_CHALLENGE"

    def test_grant_is_purpose_target_session_bound_one_use_and_not_global_reauthentication(
        self,
        db_engine,
        passkey_account,
        enrolled,
        monkeypatch,
    ):
        authenticator, _ = enrolled
        now = identity.utcnow()
        monkeypatch.setattr(identity, "utcnow", lambda: now + timedelta(minutes=6))
        with Session(db_engine) as session:
            original_auth_time = session.get(
                AuthSession, passkey_account.principal.session_id
            ).authenticated_at
            grant = issue_grant(session, passkey_account, authenticator)
            assert (
                session.get(AuthSession, passkey_account.principal.session_id).authenticated_at
                == original_auth_time
            )
            with pytest.raises(DomainError):
                require_recent_login(passkey_account.principal, now=identity.utcnow())
            for purpose, target in (
                (StepUpPurpose.DATA_EXPORT, grant.target_id),
                (grant.purpose, uuid4()),
            ):
                with pytest.raises(DomainError) as incorrect:
                    service.consume_step_up(
                        session, passkey_account.principal, grant.grant_token, purpose, target
                    )
                assert incorrect.value.code == "STEP_UP_REQUIRED"
                session.rollback()
            other_login = identity.login(
                session,
                LoginRequest(
                    login_name=passkey_account.login_name,
                    password=passkey_account.password,
                    device_label="합성 다른 인증 기기",
                ),
                "synthetic-other",
                "native",
            )
            other = identity.authenticate(session, other_login.token, "native")
            session.commit()
            with pytest.raises(DomainError):
                service.consume_step_up(
                    session, other, grant.grant_token, grant.purpose, grant.target_id
                )
            session.rollback()
            service.consume_step_up(
                session,
                passkey_account.principal,
                grant.grant_token,
                grant.purpose,
                grant.target_id,
            )
            session.commit()
            with pytest.raises(DomainError):
                service.consume_step_up(
                    session,
                    passkey_account.principal,
                    grant.grant_token,
                    grant.purpose,
                    grant.target_id,
                )

    def test_grant_rollback_expiry_and_credential_revocation(
        self,
        db_engine,
        passkey_account,
        enrolled,
        monkeypatch,
    ):
        authenticator, credential_id = enrolled
        with Session(db_engine) as session:
            grant = issue_grant(session, passkey_account, authenticator)
            service.consume_step_up(
                session,
                passkey_account.principal,
                grant.grant_token,
                grant.purpose,
                grant.target_id,
            )
            session.rollback()
            assert session.scalar(select(StepUpGrant.consumed_at)) is None
            now = identity.utcnow()
            monkeypatch.setattr(identity, "utcnow", lambda: grant.expires_at + timedelta(seconds=1))
            with pytest.raises(DomainError):
                service.consume_step_up(
                    session,
                    passkey_account.principal,
                    grant.grant_token,
                    grant.purpose,
                    grant.target_id,
                )
            session.rollback()
            monkeypatch.setattr(identity, "utcnow", lambda: now)
            session.get(AuthCredential, credential_id).revoked_at = now
            session.commit()
            with pytest.raises(DomainError):
                service.consume_step_up(
                    session,
                    passkey_account.principal,
                    grant.grant_token,
                    grant.purpose,
                    grant.target_id,
                )

    def test_step_up_challenge_cannot_be_used_for_login(self, db_engine, passkey_account, enrolled):
        authenticator, _ = enrolled
        with Session(db_engine) as session:
            options = service.step_up_options(
                session,
                passkey_account.principal,
                StepUpOptionsRequest(
                    purpose=StepUpPurpose.DEVICE_REVOKE,
                    target_id=passkey_account.principal.device_id,
                ),
                NATIVE_POLICY,
            )
            proof = authenticator.assertion(
                base64url_to_bytes(options.public_key["challenge"]),
                passkey_account.user_id,
                origin=NATIVE_ORIGIN,
            )
            with pytest.raises(DomainError) as confused:
                service.verify_login(
                    session,
                    AssertionVerification(challenge_id=options.challenge_id, credential=proof),
                    NATIVE_POLICY,
                    secrets.token_urlsafe(32),
                    "synthetic-native",
                )
            assert confused.value.code == "INVALID_AUTH_CHALLENGE"
            session.rollback()
            valid = AssertionVerification(challenge_id=options.challenge_id, credential=proof)
            service.verify_step_up(session, passkey_account.principal, valid, NATIVE_POLICY)
            with pytest.raises(DomainError) as replay:
                service.verify_step_up(session, passkey_account.principal, valid, NATIVE_POLICY)
            assert replay.value.code == "INVALID_AUTH_CHALLENGE"
            assert session.scalar(select(func.count()).select_from(StepUpGrant)) == 1

    @pytest.mark.parametrize("same_household", [True, False])
    def test_credential_cannot_authenticate_or_register_as_another_user(
        self,
        db_engine,
        passkey_account,
        enrolled,
        same_household,
    ):
        authenticator, credential_id = enrolled
        other = another_account(db_engine, passkey_account.household_id if same_household else None)
        with Session(db_engine) as session:
            login = service.login_options(
                session,
                LoginOptionsRequest(login_name=other.login_name, device_label="합성 기기"),
                NATIVE_POLICY,
                "synthetic-other",
            )
            proof = authenticator.assertion(
                base64url_to_bytes(login.response.public_key["challenge"]),
                other.user_id,
                origin=NATIVE_ORIGIN,
            )
            with pytest.raises(DomainError) as ownership:
                service.verify_login(
                    session,
                    AssertionVerification(
                        challenge_id=login.response.challenge_id, credential=proof
                    ),
                    NATIVE_POLICY,
                    login.device_binding,
                    "synthetic-other",
                )
            assert ownership.value.code == "PASSKEY_VERIFICATION_FAILED"
            assert session.get(AuthChallenge, login.response.challenge_id).consumed_at is not None
            registration = service.registration_options(
                session,
                other.principal,
                RegisterOptionsRequest(label="합성 중복 키"),
                NATIVE_POLICY,
            )
            duplicate = authenticator.registration(
                base64url_to_bytes(registration.public_key["challenge"]),
                origin=NATIVE_ORIGIN,
            )
            with pytest.raises(DomainError) as duplicate_id:
                service.register_credential(
                    session,
                    other.principal,
                    RegisterVerification(
                        challenge_id=registration.challenge_id, credential=duplicate
                    ),
                    NATIVE_POLICY,
                )
            assert duplicate_id.value.code == "CREDENTIAL_UNAVAILABLE"
            assert session.get(AuthChallenge, registration.challenge_id).consumed_at is not None
            assert session.scalar(select(func.count()).select_from(AuthCredential)) == 1
            assert session.get(AuthCredential, credential_id).user_id == passkey_account.user_id

    def test_grant_cannot_be_used_by_another_household(self, db_engine, passkey_account, enrolled):
        authenticator, _ = enrolled
        other = another_account(db_engine)
        with Session(db_engine) as session:
            grant = issue_grant(session, passkey_account, authenticator)
            with pytest.raises(DomainError) as forbidden:
                service.consume_step_up(
                    session, other.principal, grant.grant_token, grant.purpose, grant.target_id
                )
            assert forbidden.value.code == "STEP_UP_REQUIRED"
            session.rollback()
            assert session.scalar(select(StepUpGrant.consumed_at)) is None

    def test_concurrent_same_challenge_issues_one_session(
        self, db_engine, passkey_account, enrolled
    ):
        authenticator, _ = enrolled
        with Session(db_engine) as session:
            options = service.login_options(
                session,
                LoginOptionsRequest(
                    login_name=passkey_account.login_name,
                    device_label="합성 동시 로그인",
                ),
                NATIVE_POLICY,
                "synthetic-native",
            )
            proof = authenticator.assertion(
                base64url_to_bytes(options.response.public_key["challenge"]),
                passkey_account.user_id,
                origin=NATIVE_ORIGIN,
            )
            payload = AssertionVerification(
                challenge_id=options.response.challenge_id, credential=proof
            )
            previous_sessions = session.scalar(select(func.count()).select_from(AuthSession))
        barrier = Barrier(2)

        def verify():
            with Session(db_engine) as session:
                barrier.wait(timeout=10)
                try:
                    service.verify_login(
                        session,
                        payload,
                        NATIVE_POLICY,
                        options.device_binding,
                        "synthetic-concurrency",
                    )
                    return 200
                except DomainError as exc:
                    return exc.status

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(verify) for _ in range(2)]
            outcomes = [future.result(timeout=20) for future in futures]
        assert sorted(outcomes) == [200, 400]
        with Session(db_engine) as session:
            assert (
                session.scalar(select(func.count()).select_from(AuthSession))
                == previous_sessions + 1
            )
