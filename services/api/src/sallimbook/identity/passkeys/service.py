"""WebAuthn library verification with server-owned ceremony and operation bindings."""

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, NoReturn
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.authentication.verify_authentication_response import VerifiedAuthentication
from webauthn.helpers import (
    base64url_to_bytes,
    bytes_to_base64url,
    parse_authentication_credential_json,
    parse_client_data_json,
    parse_registration_credential_json,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)
from webauthn.registration.verify_registration_response import VerifiedRegistration

from sallimbook.config import Settings
from sallimbook.core.authorization import Principal, require_recent_login
from sallimbook.core.errors import DomainError
from sallimbook.identity import service as identity
from sallimbook.identity.auth_models import AuthSession, HouseholdMember, RegisteredDevice, User
from sallimbook.identity.passkeys.models import (
    AuthChallenge,
    AuthCredential,
    StepUpGrant,
    StepUpPurpose,
)
from sallimbook.identity.passkeys.schemas import (
    AssertionVerification,
    AuthenticationCredential,
    CredentialResponse,
    LoginOptionsRequest,
    OptionsResponse,
    RegisterOptionsRequest,
    RegisterVerification,
    RegistrationCredential,
    StepUpOptionsRequest,
    StepUpResponse,
)

CHALLENGE_LIFETIME = timedelta(minutes=5)
GRANT_LIFETIME = timedelta(minutes=2)
EXPIRY_CLEANUP_BATCH = 100


def _prune_expired_ceremonies(session: Session) -> None:
    """Bound retention work without committing or waiting on verification/operation locks."""
    now = identity.utcnow()
    for model in (AuthChallenge, StepUpGrant):
        expired = list(
            session.scalars(
                select(model.id)
                .where(model.expires_at <= now)
                .order_by(model.expires_at, model.id)
                .limit(EXPIRY_CLEANUP_BATCH)
                .with_for_update(skip_locked=True)
            )
        )
        if expired:
            session.execute(
                delete(model)
                .where(model.id.in_(expired))
                .execution_options(synchronize_session=False)
            )


class PasskeyProofError(Exception):
    """No library detail or client credential data crosses this verification boundary."""


@dataclass(frozen=True)
class VerificationPolicy:
    rp_id: str
    origins: tuple[str, ...]
    transport: Literal["web", "native"]

    @property
    def digest(self) -> str:
        payload = json.dumps(
            [self.rp_id, sorted(self.origins), self.transport], separators=(",", ":")
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def policy_from_settings(
    settings: Settings, transport: Literal["web", "native"], http_origin: str | None
) -> VerificationPolicy:
    rp_id = getattr(settings, "webauthn_rp_id", None)
    configured = getattr(settings, f"webauthn_{transport}_origins", [])
    if not rp_id or not configured:
        raise DomainError("PASSKEYS_DISABLED", "패스키 연결 설정이 아직 준비되지 않았습니다.", 503)
    labels = rp_id.split(".")
    if (
        len(rp_id) > 253
        or len(labels) < 2
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
    ):
        raise DomainError("PASSKEY_CONFIGURATION_INVALID", "패스키 연결 설정을 확인해 주세요.", 503)
    try:
        for origin in configured:
            if transport == "web":
                parsed = urlsplit(origin)
                if (
                    parsed.scheme != "https"
                    or parsed.hostname != rp_id
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.path
                    or parsed.query
                    or parsed.fragment
                    or origin != f"https://{rp_id}" + (f":{parsed.port}" if parsed.port else "")
                ):
                    raise ValueError("Non-canonical web origin")
            else:
                prefix = "android:apk-key-hash:"
                if not origin.startswith(prefix):
                    raise ValueError("Not an Android signing-certificate origin")
                digest = base64url_to_bytes(origin[len(prefix) :])
                if len(digest) != 32 or bytes_to_base64url(digest) != origin[len(prefix) :]:
                    raise ValueError("Non-canonical certificate digest")
    except ValueError, TypeError, WebAuthnException:
        raise DomainError(
            "PASSKEY_CONFIGURATION_INVALID", "패스키 연결 설정을 확인해 주세요.", 503
        ) from None
    if transport == "web":
        if http_origin not in configured or http_origin not in settings.allowed_origins:
            raise DomainError("ORIGIN_REJECTED", "허용되지 않은 요청 출처입니다.", 403)
        # Bind this ceremony to the exact origin, including its configured HTTPS port.
        origins = (http_origin,)
    else:
        if http_origin is not None:
            raise DomainError("WRONG_AUTH_TRANSPORT", "네이티브 인증 경로를 확인해 주세요.", 403)
        origins = tuple(sorted(set(configured)))
    return VerificationPolicy(rp_id, origins, transport)


def challenge_digest(challenge: bytes) -> str:
    return identity.token_hash("webauthn-challenge", bytes_to_base64url(challenge))


def _client_challenge(client_data_json: bytes, expected_hash: str) -> bytes:
    data = parse_client_data_json(client_data_json)
    raw = json.loads(client_data_json)
    cross_origin = raw.get("crossOrigin")
    if (cross_origin is not None and cross_origin is not False) or "topOrigin" in raw:
        raise PasskeyProofError()
    if len(data.challenge) != 32 or not hmac.compare_digest(
        challenge_digest(data.challenge),
        expected_hash,
    ):
        raise PasskeyProofError()
    return data.challenge


def verify_registration_proof(
    payload: RegistrationCredential, expected_hash: str, policy: VerificationPolicy
) -> VerifiedRegistration:
    try:
        parsed = parse_registration_credential_json(
            payload.model_dump(mode="json", exclude_none=True)
        )
        challenge = _client_challenge(parsed.response.client_data_json, expected_hash)
        verified = verify_registration_response(
            credential=parsed,
            expected_challenge=challenge,
            expected_rp_id=policy.rp_id,
            expected_origin=list(policy.origins),
            require_user_presence=True,
            require_user_verification=True,
        )
        if (
            verified.credential_id != parsed.raw_id
            or not 1 <= len(verified.credential_id) <= 1023
            or not 1 <= len(verified.credential_public_key) <= 8192
        ):
            raise PasskeyProofError()
        return verified
    except WebAuthnException, ValueError, TypeError, KeyError, OverflowError, PasskeyProofError:
        raise PasskeyProofError() from None


def verify_assertion_proof(
    payload: AuthenticationCredential,
    expected_hash: str,
    policy: VerificationPolicy,
    *,
    public_key: bytes,
    sign_count: int,
    user_id: UUID,
    device_type: str,
    require_user_handle: bool,
) -> VerifiedAuthentication:
    try:
        parsed = parse_authentication_credential_json(
            payload.model_dump(mode="json", exclude_none=True)
        )
        challenge = _client_challenge(parsed.response.client_data_json, expected_hash)
        handle = parsed.response.user_handle
        if (require_user_handle and handle is None) or (
            handle is not None and handle != user_id.bytes
        ):
            raise PasskeyProofError()
        verified = verify_authentication_response(
            credential=parsed,
            expected_challenge=challenge,
            expected_rp_id=policy.rp_id,
            expected_origin=list(policy.origins),
            credential_public_key=public_key,
            credential_current_sign_count=sign_count,
            require_user_verification=True,
        )
        if verified.credential_device_type.value != device_type:
            raise PasskeyProofError()
        return verified
    except WebAuthnException, ValueError, TypeError, KeyError, OverflowError, PasskeyProofError:
        raise PasskeyProofError() from None


def credential_response(credential: AuthCredential) -> CredentialResponse:
    return CredentialResponse(
        id=credential.id,
        label=credential.label,
        created_at=credential.created_at,
        last_used_at=credential.last_used_at,
        backed_up=credential.backed_up,
        device_type=credential.device_type,
        version=credential.version,
    )


def _active_account(
    session: Session, user_id: UUID | None, household_id: UUID | None
) -> tuple[User, HouseholdMember]:
    if user_id is None or household_id is None:
        raise DomainError("PASSKEY_VERIFICATION_FAILED", "패스키 인증 정보를 확인해 주세요.", 401)
    row = session.execute(
        select(User, HouseholdMember)
        .select_from(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .where(
            User.id == user_id,
            User.disabled_at.is_(None),
            HouseholdMember.household_id == household_id,
            HouseholdMember.status == "active",
        )
        .execution_options(populate_existing=True)
    ).one_or_none()
    if row is None:
        raise DomainError("PASSKEY_VERIFICATION_FAILED", "패스키 인증 정보를 확인해 주세요.", 401)
    return row[0], row[1]


def _descriptors(
    session: Session, principal: Principal, rp_id: str
) -> list[PublicKeyCredentialDescriptor]:
    # Revoked credentials stay out so the same authenticator can register again.
    query = select(AuthCredential).where(
        AuthCredential.household_id == principal.household_id,
        AuthCredential.user_id == principal.user_id,
        AuthCredential.rp_id == rp_id,
        AuthCredential.revoked_at.is_(None),
    )
    return [
        PublicKeyCredentialDescriptor(
            id=credential.credential_id,
            transports=[AuthenticatorTransport(value) for value in credential.transports],
        )
        for credential in session.scalars(query.order_by(AuthCredential.id))
    ]


def _lock_registration_identity(
    session: Session, principal: Principal
) -> tuple[AuthSession, dict[UUID, RegisteredDevice]]:
    auth, devices = identity.lock_session_devices(session, principal)
    identity.validate_locked_session(
        principal, auth, devices[principal.device_id], recent_login=True
    )
    return auth, devices


def registration_options(
    session: Session,
    principal: Principal,
    payload: RegisterOptionsRequest,
    policy: VerificationPolicy,
) -> OptionsResponse:
    require_recent_login(principal, now=identity.utcnow())
    _lock_registration_identity(session, principal)
    user, _ = _active_account(session, principal.user_id, principal.household_id)
    _prune_expired_ceremonies(session)
    raw = secrets.token_bytes(32)
    challenge = AuthChallenge(
        household_id=principal.household_id,
        user_id=principal.user_id,
        session_id=principal.session_id,
        device_id=principal.device_id,
        kind="register",
        transport=principal.transport,
        label=payload.label,
        challenge_hash=challenge_digest(raw),
        policy_hash=policy.digest,
        expires_at=identity.utcnow() + CHALLENGE_LIFETIME,
    )
    options = generate_registration_options(
        rp_id=policy.rp_id,
        rp_name="SallimBook",
        user_name=user.login_name,
        user_display_name=user.display_name,
        user_id=user.id.bytes,
        challenge=raw,
        timeout=int(CHALLENGE_LIFETIME.total_seconds() * 1000),
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=_descriptors(session, principal, policy.rp_id),
    )
    session.add(challenge)
    session.flush()
    result = OptionsResponse(
        challenge_id=challenge.id,
        public_key=json.loads(options_to_json(options)),
        expires_at=challenge.expires_at,
    )
    session.commit()
    return result


@dataclass(frozen=True)
class LoginOptionsResult:
    response: OptionsResponse
    device_binding: str = field(repr=False)


def login_options(
    session: Session, payload: LoginOptionsRequest, policy: VerificationPolicy, source: str
) -> LoginOptionsResult:
    identity._admit_attempt(
        session,
        [
            (f"passkey-options-account:{payload.login_name}", 10),
            (f"passkey-options-source:{source}", 30),
        ],
        identity.utcnow(),
    )
    _prune_expired_ceremonies(session)
    row = session.execute(
        select(User, HouseholdMember)
        .select_from(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .where(
            User.login_name == payload.login_name,
            User.disabled_at.is_(None),
            HouseholdMember.status == "active",
        )
    ).one_or_none()
    raw = secrets.token_bytes(32)
    binding = secrets.token_urlsafe(32)
    challenge = AuthChallenge(
        user_id=row[0].id if row else None,
        household_id=row[1].household_id if row else None,
        pending_device_id=uuid4(),
        kind="login",
        transport=policy.transport,
        label=payload.device_label,
        challenge_hash=challenge_digest(raw),
        binding_hash=identity.token_hash("passkey-device-binding", binding),
        policy_hash=policy.digest,
        expires_at=identity.utcnow() + CHALLENGE_LIFETIME,
    )
    # All accounts get the same discoverable-credential shape, including unknown/disabled users.
    options = generate_authentication_options(
        rp_id=policy.rp_id,
        challenge=raw,
        timeout=int(CHALLENGE_LIFETIME.total_seconds() * 1000),
        allow_credentials=[],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    session.add(challenge)
    session.flush()
    response = OptionsResponse(
        challenge_id=challenge.id,
        public_key=json.loads(options_to_json(options)),
        expires_at=challenge.expires_at,
    )
    session.commit()
    return LoginOptionsResult(response, binding)


def step_up_options(
    session: Session,
    principal: Principal,
    payload: StepUpOptionsRequest,
    policy: VerificationPolicy,
) -> OptionsResponse:
    identity.lock_session_devices(session, principal)
    _active_account(session, principal.user_id, principal.household_id)
    credentials = _descriptors(session, principal, policy.rp_id)
    if not credentials:
        raise DomainError("PASSKEY_REQUIRED", "먼저 패스키를 등록해 주세요.", 409)
    _prune_expired_ceremonies(session)
    raw = secrets.token_bytes(32)
    challenge = AuthChallenge(
        household_id=principal.household_id,
        user_id=principal.user_id,
        session_id=principal.session_id,
        device_id=principal.device_id,
        kind="step_up",
        transport=principal.transport,
        action=payload.purpose.value,
        target_id=payload.target_id,
        challenge_hash=challenge_digest(raw),
        policy_hash=policy.digest,
        expires_at=identity.utcnow() + CHALLENGE_LIFETIME,
    )
    options = generate_authentication_options(
        rp_id=policy.rp_id,
        challenge=raw,
        timeout=int(CHALLENGE_LIFETIME.total_seconds() * 1000),
        allow_credentials=credentials,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    session.add(challenge)
    session.flush()
    result = OptionsResponse(
        challenge_id=challenge.id,
        public_key=json.loads(options_to_json(options)),
        expires_at=challenge.expires_at,
    )
    session.commit()
    return result


def _consume_challenge(
    session: Session,
    challenge_id: UUID,
    kind: str,
    policy: VerificationPolicy,
    *,
    principal: Principal | None = None,
    device_binding: str | None = None,
) -> AuthChallenge:
    challenge = session.scalar(
        select(AuthChallenge)
        .where(AuthChallenge.id == challenge_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = identity.utcnow()
    if (
        challenge is None
        or challenge.kind != kind
        or challenge.transport != policy.transport
        or challenge.consumed_at is not None
        or challenge.expires_at <= now
        or not hmac.compare_digest(challenge.policy_hash, policy.digest)
    ):
        raise DomainError("INVALID_AUTH_CHALLENGE", "인증 요청을 새로 시작해 주세요.", 400)
    if kind == "login":
        if (
            device_binding is None
            or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", device_binding)
            or not hmac.compare_digest(
                challenge.binding_hash or "",
                identity.token_hash(
                    "passkey-device-binding",
                    device_binding,
                ),
            )
        ):
            raise DomainError("INVALID_AUTH_CHALLENGE", "인증 요청을 새로 시작해 주세요.", 400)
    elif (
        principal is None
        or challenge.user_id != principal.user_id
        or challenge.household_id != principal.household_id
        or challenge.session_id != principal.session_id
        or challenge.device_id != principal.device_id
    ):
        raise DomainError("INVALID_AUTH_CHALLENGE", "인증 요청을 새로 시작해 주세요.", 400)
    challenge.consumed_at = now
    session.flush()
    return challenge


def _failed_proof(session: Session) -> NoReturn:
    session.commit()  # A bound verification attempt consumes its challenge even when proof fails.
    raise DomainError(
        "PASSKEY_VERIFICATION_FAILED", "패스키 인증 정보를 확인해 주세요.", 401
    ) from None


def register_credential(
    session: Session,
    principal: Principal,
    payload: RegisterVerification,
    policy: VerificationPolicy,
) -> CredentialResponse:
    require_recent_login(principal, now=identity.utcnow())
    auth, devices = _lock_registration_identity(session, principal)
    challenge = _consume_challenge(
        session, payload.challenge_id, "register", policy, principal=principal
    )
    try:
        _active_account(session, principal.user_id, principal.household_id)
        identity.validate_locked_session(
            principal, auth, devices[principal.device_id], recent_login=True
        )
        verified = verify_registration_proof(payload.credential, challenge.challenge_hash, policy)
        identity.validate_locked_session(
            principal, auth, devices[principal.device_id], recent_login=True
        )
    except PasskeyProofError, DomainError:
        _failed_proof(session)
    credential = AuthCredential(
        household_id=principal.household_id,
        user_id=principal.user_id,
        created_device_id=principal.device_id,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        rp_id=policy.rp_id,
        label=challenge.label,
        sign_count=verified.sign_count,
        aaguid=UUID(verified.aaguid),
        transports=sorted(set(payload.credential.response.transports)),
        device_type=verified.credential_device_type.value,
        backed_up=verified.credential_backed_up,
    )
    try:
        with session.begin_nested():
            session.add(credential)
            session.flush()
            identity.validate_locked_session(
                principal, auth, devices[principal.device_id], recent_login=True
            )
    except IntegrityError:
        # Keep consumption while rolling back only the duplicate credential insert.
        session.commit()
        raise DomainError("CREDENTIAL_UNAVAILABLE", "다른 패스키를 등록해 주세요.", 409) from None
    except DomainError:
        _failed_proof(session)
    result = credential_response(credential)
    session.commit()
    return result


def _verify_owned_assertion(
    session: Session,
    challenge: AuthChallenge,
    payload: AuthenticationCredential,
    policy: VerificationPolicy,
    *,
    discoverable: bool,
) -> tuple[AuthCredential, User, HouseholdMember]:
    try:
        user, member = _active_account(session, challenge.user_id, challenge.household_id)
        parsed = parse_authentication_credential_json(
            payload.model_dump(mode="json", exclude_none=True)
        )
        credential = session.scalar(
            select(AuthCredential)
            .where(
                AuthCredential.credential_id == parsed.raw_id,
                AuthCredential.user_id == user.id,
                AuthCredential.household_id == member.household_id,
                AuthCredential.rp_id == policy.rp_id,
                AuthCredential.revoked_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if credential is None or challenge.expires_at <= identity.utcnow():
            raise PasskeyProofError()
        verified = verify_assertion_proof(
            payload,
            challenge.challenge_hash,
            policy,
            public_key=credential.public_key,
            sign_count=credential.sign_count,
            user_id=user.id,
            device_type=credential.device_type,
            require_user_handle=discoverable,
        )
    except WebAuthnException, ValueError, TypeError, KeyError, PasskeyProofError, DomainError:
        _failed_proof(session)
    credential.sign_count = verified.new_sign_count
    credential.backed_up = verified.credential_backed_up
    credential.last_used_at = identity.utcnow()
    session.flush()
    return credential, user, member


def verify_login(
    session: Session,
    payload: AssertionVerification,
    policy: VerificationPolicy,
    device_binding: str | None,
    source: str,
) -> identity.LoginResult:
    identity._admit_attempt(session, [(f"passkey-verify-source:{source}", 60)], identity.utcnow())
    challenge = _consume_challenge(
        session, payload.challenge_id, "login", policy, device_binding=device_binding
    )
    _, user, member = _verify_owned_assertion(
        session, challenge, payload.credential, policy, discoverable=True
    )
    result = identity.issue_session(
        session,
        user,
        member,
        challenge.label,
        policy.transport,
        device_id=challenge.pending_device_id,
    )
    session.commit()
    return result


def verify_step_up(
    session: Session,
    principal: Principal,
    payload: AssertionVerification,
    policy: VerificationPolicy,
) -> StepUpResponse:
    auth, devices = identity.lock_session_devices(session, principal)
    challenge = _consume_challenge(
        session, payload.challenge_id, "step_up", policy, principal=principal
    )
    credential, _, _ = _verify_owned_assertion(
        session, challenge, payload.credential, policy, discoverable=False
    )
    identity.validate_locked_session(principal, auth, devices[principal.device_id])
    token = secrets.token_urlsafe(32)
    grant = StepUpGrant(
        household_id=principal.household_id,
        user_id=principal.user_id,
        session_id=principal.session_id,
        device_id=principal.device_id,
        credential_record_id=credential.id,
        grant_hash=identity.token_hash("step-up-grant", token),
        purpose=challenge.action,
        target_id=challenge.target_id,
        expires_at=identity.utcnow() + GRANT_LIFETIME,
    )
    session.add(grant)
    session.flush()
    result = StepUpResponse(
        grant_token=token,
        purpose=StepUpPurpose(grant.purpose),
        target_id=grant.target_id,
        expires_at=grant.expires_at,
    )
    # Do NOT refresh AuthSession.authenticated_at: the proof is bound to its operation target.
    session.commit()
    return result


def _validated_step_up(
    session: Session,
    principal: Principal,
    token: str | None,
    purpose: StepUpPurpose,
    target_id: UUID,
) -> tuple[StepUpGrant, datetime]:
    """Validate without consuming: Device -> Credential -> Grant.

    Operations must acquire their complete device barrier BEFORE other resource locks.
    In particular device DELETE locks source+target together in sorted order beforehand.
    Reacquiring its already-held source row here is harmless; direct callers acquire their
    source barrier here before any credential/grant lock. No commit releases these locks.
    Return the locked row so a caller can recheck its deadline after subsequent work.
    """
    if token is None or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        raise DomainError("STEP_UP_REQUIRED", "이 작업을 다시 인증해 주세요.", 403)
    auth, devices = identity.lock_session_devices(session, principal)
    binding = (
        StepUpGrant.grant_hash == identity.token_hash("step-up-grant", token),
        StepUpGrant.household_id == principal.household_id,
        StepUpGrant.user_id == principal.user_id,
        StepUpGrant.session_id == principal.session_id,
        StepUpGrant.device_id == principal.device_id,
        StepUpGrant.purpose == purpose.value,
        StepUpGrant.target_id == target_id,
    )
    # Discovery is not authorization. Revalidate the complete binding under the final lock.
    candidate = session.execute(
        select(StepUpGrant.id, StepUpGrant.credential_record_id).where(*binding)
    ).one_or_none()
    if candidate is None:
        raise DomainError("STEP_UP_REQUIRED", "이 작업을 다시 인증해 주세요.", 403)
    credential = session.scalar(
        select(AuthCredential)
        .where(
            AuthCredential.id == candidate.credential_record_id,
            AuthCredential.household_id == principal.household_id,
            AuthCredential.user_id == principal.user_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    grant = session.scalar(
        select(StepUpGrant)
        .where(
            *binding,
            StepUpGrant.id == candidate.id,
            StepUpGrant.credential_record_id == candidate.credential_record_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = identity.validate_locked_session(principal, auth, devices[principal.device_id])
    if (
        credential is None
        or credential.revoked_at is not None
        or grant is None
        or grant.consumed_at is not None
        or grant.expires_at <= now
    ):
        raise DomainError("STEP_UP_REQUIRED", "이 작업을 다시 인증해 주세요.", 403)
    _active_account(session, principal.user_id, principal.household_id)
    return grant, now


def check_step_up(
    session: Session,
    principal: Principal,
    token: str | None,
    purpose: StepUpPurpose,
    target_id: UUID,
) -> StepUpGrant:
    """Check the complete locked binding without consuming or committing the grant."""
    grant, _ = _validated_step_up(session, principal, token, purpose, target_id)
    return grant


def consume_step_up(
    session: Session,
    principal: Principal,
    token: str | None,
    purpose: StepUpPurpose,
    target_id: UUID,
) -> StepUpGrant:
    """Consume the validated grant in the caller's transaction; never commits."""
    grant, now = _validated_step_up(session, principal, token, purpose, target_id)
    grant.consumed_at = now
    session.flush()
    return grant
