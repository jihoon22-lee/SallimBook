"""Password-backed sessions and invitations; no passkey or biometric claims are inferred."""

import hashlib
import hmac
import re
import secrets
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sallimbook.core.audit import append_event, record_event
from sallimbook.core.authorization import Principal, require_owner, require_recent_login
from sallimbook.core.errors import DomainError
from sallimbook.identity.auth_models import (
    AuthSession,
    HouseholdMember,
    Invitation,
    LoginThrottle,
    RefreshToken,
    RegisteredDevice,
    User,
)
from sallimbook.identity.models import Household
from sallimbook.identity.schemas import (
    ConnectionCodeResponse,
    ConnectionRequest,
    InstallClaim,
    InstallDevice,
    InvitationAcceptance,
    InvitationRequest,
    InvitationResponse,
    LoginRequest,
    MemberResponse,
    NativeLoginRequest,
    NativeTokenResponse,
    PasswordChangeRequest,
    ReauthenticationRequest,
    RevokedDevicesResponse,
    SetupRequest,
)

WEB_IDLE = timedelta(minutes=30)
WEB_ABSOLUTE = timedelta(hours=12)
ACCESS_LIFETIME = timedelta(minutes=10)
REFRESH_LIFETIME = timedelta(days=30)
# A device that nobody has used for this long is left out of the device list. Its row stays,
# since sessions, passkeys and audit history refer to it; it can no longer sign in anyway.
DEVICE_LIST_IDLE = timedelta(days=90)
INVITATION_LIFETIME = timedelta(minutes=15)
INSTALL_KEY = "install-device"
THROTTLE_WINDOW = timedelta(minutes=15)
THROTTLE_CLEANUP_BATCH = 64
# Refreshes per device per THROTTLE_WINDOW; a 10-minute access token needs about two.
REFRESH_DEVICE_LIMIT = 10
PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
# Unknown logins do the same expensive verification without any usable default account.
_DUMMY_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))
# Each Argon2 call needs about 64 MiB; the single API worker runs at most two at once.
PASSWORD_WORK_SLOTS = 2
_password_slots = threading.BoundedSemaphore(PASSWORD_WORK_SLOTS)


def utcnow() -> datetime:
    return datetime.now(UTC)


def token_hash(kind: str, token: str) -> str:
    return hashlib.sha256(f"{kind}\0{token}".encode()).hexdigest()


def _valid_token(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token))


def _unauthenticated() -> DomainError:
    return DomainError("UNAUTHENTICATED", "로그인 정보를 확인해 주세요.", 401)


def _admit_attempt(session: Session, buckets: list[tuple[str, int]], now: datetime) -> None:
    """Commit admission counters before credential work so failed requests cannot roll them back."""
    # Expired windows carry no remaining restriction. Reclaim a bounded batch on every
    # admission, including rejected attempts, so arbitrary names/peers do not persist forever.
    # Release cleanup locks before touching admission keys: disjoint cleanup batches must
    # not deadlock when their following requests contend for each other's expired keys.
    expired = session.scalars(
        select(LoginThrottle.key_hash)
        .where(LoginThrottle.window_started_at <= now - THROTTLE_WINDOW)
        .order_by(LoginThrottle.window_started_at, LoginThrottle.key_hash)
        .limit(THROTTLE_CLEANUP_BATCH)
        .with_for_update(skip_locked=True)
    ).all()
    if expired:
        session.execute(delete(LoginThrottle).where(LoginThrottle.key_hash.in_(expired)))
    session.commit()
    counters = []
    for key, limit in sorted(buckets):
        digest = token_hash("throttle", key)
        session.execute(
            insert(LoginThrottle)
            .values(
                key_hash=digest,
                window_started_at=now,
                attempts=0,
            )
            # Acquire the existing row lock during upsert, before concurrent cleanup can
            # delete an expired row between the insert and the locked read below.
            .on_conflict_do_update(index_elements=["key_hash"], set_={"key_hash": digest})
        )
        counter = session.scalar(
            select(LoginThrottle)
            .where(
                LoginThrottle.key_hash == digest,
            )
            .with_for_update()
        )
        if now - counter.window_started_at >= THROTTLE_WINDOW:
            counter.window_started_at = now
            counter.attempts = 0
        counters.append((counter, limit))
    # A refused attempt counts nowhere, so one exhausted bucket cannot drain the others.
    blocked = any(counter.attempts >= limit for counter, limit in counters)
    if not blocked:
        for counter, _ in counters:
            counter.attempts += 1
    session.commit()
    if blocked:
        raise DomainError("RATE_LIMITED", "잠시 후 다시 시도해 주세요.", 429)


@contextmanager
def _password_work() -> Iterator[None]:
    """Hold one password work slot, failing fast instead of queueing more Argon2 memory."""
    slots = _password_slots
    if not slots.acquire(blocking=False):
        raise DomainError(
            "AUTH_BUSY", "로그인 확인 요청이 몰려 있어요. 잠시 후 다시 시도해 주세요.", 429
        )
    try:
        yield
    finally:
        slots.release()


def hash_password(password: str) -> str:
    with _password_work():
        return PASSWORD_HASHER.hash(password)


def _verify_password(encoded: str, password: str) -> bool:
    with _password_work():
        try:
            return PASSWORD_HASHER.verify(encoded, password)
        except InvalidHashError, VerificationError:
            return False


def _upgrade_hash(user: User, password: str) -> None:
    """Rehash with current parameters when a slot is free; a busy server keeps the old hash."""
    if not PASSWORD_HASHER.check_needs_rehash(user.password_hash):
        return
    try:
        user.password_hash = hash_password(password)
    except DomainError as error:
        if error.code != "AUTH_BUSY":
            raise


def _login_buckets(login_name: str, source: str) -> list[tuple[str, int]]:
    return [(f"login-account:{login_name}", 5), (f"login-source:{source}", 30)]


def _reauth_buckets(user_id: UUID, source: str) -> list[tuple[str, int]]:
    return [(f"reauth-account:{user_id}", 5), (f"reauth-source:{source}", 30)]


def _refund_attempts(session: Session, keys: Iterable[str]) -> None:
    """Return one admitted attempt per key after a verified password; the caller commits.

    Keys are updated one at a time in the admission lock order. A success right after a
    window reset may refund nothing, so it can count at most once.
    """
    window_start = utcnow() - THROTTLE_WINDOW
    for key in sorted(set(keys)):
        session.execute(
            update(LoginThrottle)
            .where(
                LoginThrottle.key_hash == token_hash("throttle", key),
                LoginThrottle.attempts > 0,
                LoginThrottle.window_started_at > window_start,
            )
            .values(attempts=LoginThrottle.attempts - 1)
        )


def _verify_admitted(
    session: Session, buckets: list[tuple[str, int]], encoded: str, password: str
) -> bool:
    """Verify after admission; only failed verifications keep counting toward the limits."""
    keys = [key for key, _ in buckets]
    try:
        verified = _verify_password(encoded, password)
    except DomainError as error:
        if error.code == "AUTH_BUSY":
            # Nothing was verified, so the admitted attempt is returned before refusing.
            _refund_attempts(session, keys)
            session.commit()
        raise
    if not verified:
        return False
    _refund_attempts(session, keys)
    return True


def member_response(user: User, member: HouseholdMember) -> MemberResponse:
    return MemberResponse(
        user_id=user.id,
        member_id=member.id,
        household_id=member.household_id,
        display_name=user.display_name,
        role=member.role,
    )


def _active_identity(
    session: Session, auth: AuthSession
) -> tuple[User, HouseholdMember, RegisteredDevice]:
    row = session.execute(
        select(User, HouseholdMember, RegisteredDevice)
        .select_from(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .join(Household, Household.id == HouseholdMember.household_id)
        .join(
            RegisteredDevice,
            (RegisteredDevice.user_id == User.id)
            & (RegisteredDevice.household_id == HouseholdMember.household_id),
        )
        .where(
            User.id == auth.user_id,
            User.disabled_at.is_(None),
            HouseholdMember.household_id == auth.household_id,
            HouseholdMember.status == "active",
            RegisteredDevice.id == auth.device_id,
            RegisteredDevice.status == "active",
            RegisteredDevice.revoked_at.is_(None),
            # An install row admits only the session of its latest sign-in.
            or_(
                RegisteredDevice.install_session_id.is_(None),
                RegisteredDevice.install_session_id == auth.id,
            ),
        )
    ).one_or_none()
    if row is None:
        raise _unauthenticated()
    return row[0], row[1], row[2]


def authenticate(
    session: Session,
    token: str,
    transport: Literal["web", "native"],
    *,
    csrf_token: str | None = None,
    check_csrf: bool = False,
) -> Principal:
    if not _valid_token(token):
        raise _unauthenticated()
    auth = session.scalar(
        select(AuthSession)
        .where(
            AuthSession.session_hash == token_hash("session", token),
            AuthSession.kind == transport,
        )
        .with_for_update()
    )
    # Locks may have waited; expiration is checked against the time we actually authorize.
    now = utcnow()
    if (
        auth is None
        or auth.revoked_at is not None
        or auth.expires_at <= now
        or (transport == "web" and auth.last_seen_at <= now - WEB_IDLE)
        or (transport == "native" and auth.access_expires_at <= now)
    ):
        raise _unauthenticated()
    if check_csrf and (
        csrf_token is None
        or not _valid_token(csrf_token)
        or not hmac.compare_digest(auth.csrf_hash or "", token_hash("csrf", csrf_token))
    ):
        raise DomainError("CSRF_FAILED", "요청의 인증 상태를 다시 확인해 주세요.", 403)
    user, member, device = _active_identity(session, auth)
    auth.last_seen_at = now
    # Do not lock/write the device here: a concurrent revocation locks that device.
    # Device activity is derived from session timestamps when listing devices.
    session.flush()
    return Principal(
        user_id=user.id,
        member_id=member.id,
        household_id=member.household_id,
        session_id=auth.id,
        device_id=device.id,
        role=member.role,
        transport=transport,
        authenticated_at=auth.authenticated_at,
    )


def validate_locked_session(
    principal: Principal,
    auth: AuthSession,
    source_device: RegisteredDevice,
    *,
    recent_login: bool = False,
) -> datetime:
    """Recheck state/time after waits while the caller still holds both barrier rows."""
    now = utcnow()
    if (
        auth.id != principal.session_id
        or auth.user_id != principal.user_id
        or auth.household_id != principal.household_id
        or auth.device_id != principal.device_id
        or auth.kind != principal.transport
        or auth.revoked_at is not None
        or auth.expires_at <= now
        or source_device.id != principal.device_id
        or source_device.user_id != principal.user_id
        or source_device.household_id != principal.household_id
        or source_device.status != "active"
        or source_device.revoked_at is not None
        or (auth.kind == "web" and auth.last_seen_at <= now - WEB_IDLE)
        or (
            auth.kind == "native"
            and (auth.access_expires_at is None or auth.access_expires_at <= now)
        )
    ):
        raise _unauthenticated()
    if recent_login:
        age = now - auth.authenticated_at
        if age < timedelta(0) or age > timedelta(minutes=5):
            raise DomainError("REAUTHENTICATION_REQUIRED", "다시 로그인한 후 진행해 주세요.", 403)
    return now


def lock_session_devices(
    session: Session,
    principal: Principal,
    *,
    additional_device_ids: Iterable[UUID] = (),
) -> tuple[AuthSession, dict[UUID, RegisteredDevice]]:
    """Acquire Session -> complete Device set sorted by immutable UUID, without committing.

    Protected operations call this BEFORE household, credential, grant or domain locks.
    Device revocation must include its target in the first call; never lock its source
    separately first. Ordinary authenticate/read requests intentionally keep no device lock.
    """
    auth = session.scalar(
        select(AuthSession)
        .where(
            AuthSession.id == principal.session_id,
            AuthSession.user_id == principal.user_id,
            AuthSession.household_id == principal.household_id,
            AuthSession.device_id == principal.device_id,
            AuthSession.kind == principal.transport,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if auth is None:
        raise _unauthenticated()
    required = {principal.device_id, *additional_device_ids}
    devices = {
        device.id: device
        for device in session.scalars(
            select(RegisteredDevice)
            .where(
                RegisteredDevice.id.in_(required),
                RegisteredDevice.household_id == principal.household_id,
                RegisteredDevice.user_id == principal.user_id,
            )
            .order_by(RegisteredDevice.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    source = devices.get(principal.device_id)
    if source is None:
        raise _unauthenticated()
    validate_locked_session(principal, auth, source)
    _active_identity(session, auth)
    if required != devices.keys():
        raise DomainError("NOT_FOUND", "요청한 항목을 찾을 수 없습니다.", 404)
    return auth, devices


def _active_device_ids(session: Session, principal: Principal) -> set[UUID]:
    return set(
        session.scalars(
            select(RegisteredDevice.id).where(
                RegisteredDevice.household_id == principal.household_id,
                RegisteredDevice.user_id == principal.user_id,
                RegisteredDevice.status == "active",
            )
        )
    )


def _lock_account_devices(
    session: Session, principal: Principal
) -> tuple[AuthSession, dict[UUID, RegisteredDevice], User]:
    """Lock session -> every active device of this user (UUID order) -> the users row.

    `issue_session` takes the same users row lock, so devices read after it include every
    login that committed first; later logins wait and recheck the password hash. A device
    that appeared after the first read cannot be locked out of UUID order, so start over.
    """
    for _ in range(3):
        auth, devices = lock_session_devices(
            session, principal, additional_device_ids=_active_device_ids(session, principal)
        )
        user = session.scalar(
            select(User)
            .where(User.id == principal.user_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        if _active_device_ids(session, principal).issubset(devices):
            return auth, devices, user
        session.rollback()
    raise DomainError(
        "AUTH_BUSY", "로그인 확인 요청이 몰려 있어요. 잠시 후 다시 시도해 주세요.", 429
    )


def _refund_busy[T](session: Session, buckets: list[tuple[str, int]], action: Callable[[], T]) -> T:
    """AUTH_BUSY work never finished a password check, so it is not a counted attempt."""
    try:
        return action()
    except DomainError as error:
        if error.code == "AUTH_BUSY":
            session.rollback()
            _refund_attempts(session, [key for key, _ in buckets])
            session.commit()
        raise


def _revoke_other_devices(
    session: Session,
    principal: Principal,
    devices: dict[UUID, RegisteredDevice],
    now: datetime,
) -> int:
    """Revoke locked sibling devices; their sessions and refresh tokens fail on device status."""
    revoked = 0
    for device in devices.values():
        if device.id == principal.device_id or device.status != "active":
            continue
        before = device.version
        device.status = "revoked"
        device.revoked_at = now
        session.flush()
        record_event(
            session,
            principal,
            entity_type="registered_device",
            entity_id=device.id,
            action="revoke",
            before_version=before,
            after_version=device.version,
            changed_fields=("revoked_at", "status"),
        )
        revoked += 1
    return revoked


def revoke_other_devices(
    session: Session, principal: Principal, request: ReauthenticationRequest, source: str
) -> RevokedDevicesResponse:
    buckets = _reauth_buckets(principal.user_id, source)
    _admit_attempt(session, buckets, utcnow())
    auth, devices, user = _refund_busy(
        session, buckets, lambda: _lock_account_devices(session, principal)
    )
    if not _verify_admitted(
        session, buckets, user.password_hash, request.password.get_secret_value()
    ):
        raise DomainError("REAUTHENTICATION_FAILED", "비밀번호를 확인해 주세요.", 403)
    # Password work can take time; recheck the live session before counting it as recent.
    now = validate_locked_session(principal, auth, devices[principal.device_id])
    auth.authenticated_at = now
    auth.last_seen_at = now
    revoked = _revoke_other_devices(session, principal, devices, now)
    session.commit()
    return RevokedDevicesResponse(revoked_devices=revoked)


def change_password(
    session: Session, principal: Principal, request: PasswordChangeRequest, source: str
) -> RevokedDevicesResponse:
    """Replace the password and revoke every other device of this user in one transaction."""
    current = request.current_password.get_secret_value()
    replacement = request.new_password.get_secret_value()
    if hmac.compare_digest(current.encode(), replacement.encode()):
        raise DomainError(
            "VALIDATION_ERROR", "현재 비밀번호와 다른 새 비밀번호를 입력해 주세요.", 422
        )
    buckets = _reauth_buckets(principal.user_id, source)
    _admit_attempt(session, buckets, utcnow())
    auth, devices, user = _refund_busy(
        session, buckets, lambda: _lock_account_devices(session, principal)
    )
    if not _verify_admitted(session, buckets, user.password_hash, current):
        raise DomainError("REAUTHENTICATION_FAILED", "비밀번호를 확인해 주세요.", 403)
    encoded = _refund_busy(session, buckets, lambda: hash_password(replacement))
    now = validate_locked_session(principal, auth, devices[principal.device_id])
    before = user.version
    user.password_hash = encoded
    auth.authenticated_at = now
    auth.last_seen_at = now
    revoked = _revoke_other_devices(session, principal, devices, now)
    session.flush()
    record_event(
        session,
        principal,
        entity_type="user",
        entity_id=user.id,
        action="update",
        before_version=before,
        after_version=user.version,
        changed_fields=("password_hash",),
    )
    session.commit()
    return RevokedDevicesResponse(revoked_devices=revoked)


def create_bootstrap_invitation(
    session: Session, household_name: str, intended_login: str
) -> InvitationResponse:
    """Operator-only; caller writes the private token file and commits this transaction."""
    login = InvitationRequest(intended_login=intended_login).intended_login
    name = household_name.strip()
    if not 1 <= len(name) <= 120:
        raise DomainError("INVALID_HOUSEHOLD_NAME", "가계 이름을 확인해 주세요.", 422)
    # Installation-level serialization: only one real household can be bootstrapped.
    session.execute(select(func.pg_advisory_xact_lock(0x53414C4C494D)))
    if session.scalar(select(Household.id).limit(1)) is not None:
        raise DomainError("HOUSEHOLD_EXISTS", "이미 등록된 가계가 있습니다.", 409)
    household = Household(name=name)
    session.add(household)
    session.flush()
    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        household_id=household.id,
        intended_login=login,
        token_hash=token_hash("invite", token),
        kind="bootstrap",
        expires_at=utcnow() + INVITATION_LIFETIME,
    )
    session.add(invitation)
    session.flush()
    return InvitationResponse(id=invitation.id, token=token, expires_at=invitation.expires_at)


def create_partner_invitation(
    session: Session,
    principal: Principal,
    request: InvitationRequest,
    *,
    step_up_token: str | None = None,
    _connection_code: bool = False,
) -> InvitationResponse:
    now = utcnow()
    if step_up_token is None:
        require_recent_login(principal, now=now)
    require_owner(principal)
    # Step-up order: session -> devices -> household -> credential -> grant (consume_step_up).
    auth, devices = lock_session_devices(session, principal)
    session.execute(
        select(Household).where(Household.id == principal.household_id).with_for_update()
    ).scalar_one()
    validate_locked_session(
        principal, auth, devices[principal.device_id], recent_login=step_up_token is None
    )
    count = session.scalar(
        select(func.count())
        .select_from(HouseholdMember)
        .where(
            HouseholdMember.household_id == principal.household_id,
            HouseholdMember.status == "active",
        )
    )
    if count >= 2:
        raise DomainError("HOUSEHOLD_FULL", "가계에는 두 계정까지만 등록할 수 있습니다.", 409)
    if session.scalar(select(User.id).where(User.login_name == request.intended_login)) is not None:
        raise DomainError("LOGIN_UNAVAILABLE", "다른 로그인 이름을 사용해 주세요.", 409)
    if step_up_token is not None:
        # Import at the operation boundary: passkey verification reuses identity sessions.
        from sallimbook.identity.passkeys.models import StepUpPurpose
        from sallimbook.identity.passkeys.service import consume_step_up

        consume_step_up(
            session,
            principal,
            step_up_token,
            StepUpPurpose.HOUSEHOLD_INVITE,
            principal.household_id,
        )
    now = validate_locked_session(
        principal, auth, devices[principal.device_id], recent_login=step_up_token is None
    )
    # Reissuing an invite invalidates all unconsumed codes for this household.
    session.execute(
        update(Invitation)
        .where(
            Invitation.household_id == principal.household_id,
            Invitation.used_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=now, version=Invitation.version + 1)
    )
    token = _fresh_connection_code(session) if _connection_code else secrets.token_urlsafe(32)
    invitation = Invitation(
        household_id=principal.household_id,
        intended_login=request.intended_login,
        token_hash=token_hash("invite", token),
        kind="partner",
        created_by_member_id=principal.member_id,
        expires_at=now + INVITATION_LIFETIME,
    )
    session.add(invitation)
    session.flush()
    record_event(
        session,
        principal,
        entity_type="invitation",
        entity_id=invitation.id,
        action="create",
        before_version=None,
        after_version=invitation.version,
    )
    result = InvitationResponse(id=invitation.id, token=token, expires_at=invitation.expires_at)
    session.commit()
    return result


def _fresh_connection_code(session: Session) -> str:
    # Reissuing never recycles a previous code, including consumed/revoked ones.
    for _ in range(32):
        code = f"{secrets.randbelow(100_000_000):08d}"
        if (
            session.scalar(
                select(Invitation.id).where(Invitation.token_hash == token_hash("invite", code))
            )
            is None
        ):
            return code
    raise DomainError("DATABASE_UNAVAILABLE", "연결 코드를 만들지 못했습니다.", 503)


def create_connection_code(
    session: Session, principal: Principal, *, step_up_token: str | None = None
) -> ConnectionCodeResponse:
    invitation = create_partner_invitation(
        session,
        principal,
        InvitationRequest(intended_login="partner"),
        step_up_token=step_up_token,
        _connection_code=True,
    )
    return ConnectionCodeResponse(code=invitation.token, expires_at=invitation.expires_at)


def renew_bootstrap_invitation(session: Session, intended_login: str) -> InvitationResponse:
    """Operator-only renewal for the existing, never-enrolled household; caller commits."""
    login_name = InvitationRequest(intended_login=intended_login).intended_login
    now = utcnow()
    session.execute(select(func.pg_advisory_xact_lock(0x53414C4C494D)))
    households = list(session.scalars(select(Household).with_for_update()))
    if len(households) != 1:
        raise DomainError("BOOTSTRAP_RENEWAL_UNAVAILABLE", "초기 등록 상태를 확인해 주세요.", 409)
    household = households[0]
    if (
        session.scalar(
            select(HouseholdMember.id).where(HouseholdMember.household_id == household.id).limit(1)
        )
        is not None
    ):
        raise DomainError("BOOTSTRAP_RENEWAL_UNAVAILABLE", "이미 구성원이 등록된 가계입니다.", 409)
    session.execute(
        update(Invitation)
        .where(
            Invitation.household_id == household.id,
        )
        .values(revoked_at=now, version=Invitation.version + 1)
    )
    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        household_id=household.id,
        intended_login=login_name,
        token_hash=token_hash("invite", token),
        kind="bootstrap",
        expires_at=now + INVITATION_LIFETIME,
    )
    session.add(invitation)
    session.flush()
    return InvitationResponse(id=invitation.id, token=token, expires_at=invitation.expires_at)


def accept_invitation(
    session: Session, request: InvitationAcceptance, source: str
) -> MemberResponse:
    now = utcnow()
    buckets = [(f"invite-source:{source}", 30)]
    _admit_attempt(session, buckets, now)
    user, member = _refund_busy(
        session, buckets, lambda: _accept_invitation_locked(session, request, connection=False)
    )
    result = member_response(user, member)
    session.commit()
    return result


def _accept_invitation_locked(
    session: Session, request: InvitationAcceptance | ConnectionRequest, *, connection: bool
) -> tuple[User, HouseholdMember]:
    token = request.code.get_secret_value() if connection else request.token.get_secret_value()
    invalid_code = "INVALID_CONNECTION_CODE" if connection else "INVALID_INVITATION"
    valid = bool(re.fullmatch(r"[0-9]{8}", token)) if connection else _valid_token(token)
    if not valid:
        raise DomainError(invalid_code, "초대를 다시 확인해 주세요.", 400)
    invitation_id = session.execute(
        select(Invitation.id, Invitation.household_id).where(
            Invitation.token_hash == token_hash("invite", token),
        )
    ).one_or_none()
    if invitation_id is None:
        raise DomainError(invalid_code, "초대를 다시 확인해 주세요.", 400)
    # Always lock household before invitation, matching invitation issuance's lock order.
    session.execute(
        select(Household).where(Household.id == invitation_id.household_id).with_for_update()
    ).scalar_one()
    invitation = session.scalar(
        select(Invitation).where(Invitation.id == invitation_id.id).with_for_update()
    )
    now = utcnow()
    if (
        invitation.used_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= now
        or (connection and (invitation.kind != "partner" or invitation.intended_login != "partner"))
    ):
        raise DomainError(invalid_code, "초대를 다시 확인해 주세요.", 400)
    slots = set(
        session.scalars(
            select(HouseholdMember.slot).where(
                HouseholdMember.household_id == invitation.household_id,
                HouseholdMember.status == "active",
            )
        )
    )
    if len(slots) >= 2 or (invitation.kind == "bootstrap" and slots):
        raise DomainError("HOUSEHOLD_FULL", "가계에는 두 계정까지만 등록할 수 있습니다.", 409)
    if invitation.kind == "partner":
        issuer = session.scalar(
            select(HouseholdMember)
            .join(User)
            .where(
                HouseholdMember.id == invitation.created_by_member_id,
                HouseholdMember.household_id == invitation.household_id,
                HouseholdMember.status == "active",
                HouseholdMember.role == "owner",
                User.disabled_at.is_(None),
            )
        )
        if issuer is None:
            raise DomainError(invalid_code, "초대를 다시 확인해 주세요.", 400)
    user = User(
        login_name=invitation.intended_login,
        display_name=request.display_name,
        password_hash=hash_password(request.password.get_secret_value()),
    )
    session.add(user)
    try:
        session.flush()
        member = HouseholdMember(
            household_id=invitation.household_id,
            user_id=user.id,
            slot=min({1, 2} - slots),
            role="owner" if invitation.kind == "bootstrap" else "member",
            status="active",
        )
        session.add(member)
        before = invitation.version
        invitation.used_at = now
        session.flush()
        from sallimbook.identity.people_models import add_member_person

        add_member_person(session, member)
        # The new member is the actor; acceptance does not sign anyone in.
        append_event(
            session,
            household_id=invitation.household_id,
            actor_id=user.id,
            entity_type="invitation",
            entity_id=invitation.id,
            action="accept",
            before_version=before,
            after_version=invitation.version,
            changed_fields=("used_at",),
        )
    except IntegrityError:
        session.rollback()
        raise DomainError("REGISTRATION_CONFLICT", "등록 상태를 다시 확인해 주세요.", 409) from None
    return user, member


@dataclass(frozen=True)
class LoginResult:
    member: MemberResponse
    expires_at: datetime
    token: str = field(repr=False)
    csrf_token: str | None = field(default=None, repr=False)
    native_tokens: NativeTokenResponse | None = field(default=None, repr=False)
    install: InstallDevice | None = field(default=None, repr=False)


def login(
    session: Session, request: LoginRequest, source: str, transport: Literal["web", "native"]
) -> LoginResult:
    now = utcnow()
    buckets = _login_buckets(request.login_name, source)
    _admit_attempt(session, buckets, now)
    user = session.scalar(select(User).where(User.login_name == request.login_name))
    password = request.password.get_secret_value()
    encoded = user.password_hash if user else _DUMMY_HASH
    verified = _verify_admitted(session, buckets, encoded, password)
    member = (
        None
        if user is None
        else session.scalar(
            select(HouseholdMember).where(
                HouseholdMember.user_id == user.id,
                HouseholdMember.status == "active",
            )
        )
    )
    if not verified or user is None or user.disabled_at is not None or member is None:
        raise _unauthenticated()
    # Creating a device is backed by this actual password verification, never a client flag.
    result = issue_session(
        session,
        user,
        member,
        request.device_label,
        transport,
        install=request.install if isinstance(request, NativeLoginRequest) else None,
    )
    # issue_session locked and reloaded the users row. A hash that changed after our
    # verification is rechecked: a same-password rehash passes, an old password does not.
    if user.password_hash != encoded and not _verify_password(user.password_hash, password):
        raise _unauthenticated()
    _upgrade_hash(user, password)
    session.commit()
    return result


def setup_available(session: Session) -> bool:
    # Revoked members and disabled/orphaned users also permanently close setup.
    # A server recovery must never turn into a fresh account takeover endpoint.
    return (
        session.scalar(select(User.id).limit(1)) is None
        and session.scalar(select(HouseholdMember.id).limit(1)) is None
        and len(session.scalars(select(Household.id).limit(2)).all()) <= 1
    )


def setup_household(
    session: Session, request: SetupRequest, source: str, transport: Literal["web", "native"]
) -> LoginResult:
    """Enroll once after the route verifies the private proxy's owner identity."""
    buckets = [(f"setup-source:{source}", 5)]
    _admit_attempt(session, buckets, utcnow())
    # Same installation lock as both operator CLI paths; household lock also
    # serializes acceptance of a previously issued operator invitation.
    session.execute(select(func.pg_advisory_xact_lock(0x53414C4C494D)))
    households = list(session.scalars(select(Household).order_by(Household.id).with_for_update()))
    if not setup_available(session):
        raise DomainError("SETUP_COMPLETE", "이미 시작한 가계입니다. 로그인해 주세요.", 409)
    household = households[0] if households else Household(name="우리 가계")
    if not households:
        session.add(household)
        session.flush()
    now = utcnow()
    session.execute(
        update(Invitation)
        .where(
            Invitation.household_id == household.id,
            Invitation.used_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=now, version=Invitation.version + 1)
    )
    # A busy server never checked anything, so the attempt is returned (as for login).
    encoded = _refund_busy(
        session, buckets, lambda: hash_password(request.password.get_secret_value())
    )
    user = User(login_name="owner", display_name=request.display_name, password_hash=encoded)
    session.add(user)
    try:
        session.flush()
        member = HouseholdMember(
            household_id=household.id, user_id=user.id, slot=1, role="owner", status="active"
        )
        session.add(member)
        session.flush()
        from sallimbook.identity.people_models import add_member_person

        add_member_person(session, member)
        result = issue_session(session, user, member, request.device_label, transport)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise DomainError("REGISTRATION_CONFLICT", "등록 상태를 다시 확인해 주세요.", 409) from None
    return result


def connect_household(
    session: Session, request: ConnectionRequest, source: str, transport: Literal["web", "native"]
) -> LoginResult:
    # Five guesses per installation/15 minutes, regardless of claimed or actual
    # source address. Reissuing a code does not reset the guessing budget.
    buckets = [("connection-global", 5), (f"connection-source:{source}", 5)]
    _admit_attempt(session, buckets, utcnow())
    # Password hashing starts only after the code was found valid, so a refund never helps
    # a guesser.
    user, member = _refund_busy(
        session, buckets, lambda: _accept_invitation_locked(session, request, connection=True)
    )
    result = issue_session(session, user, member, request.device_label, transport)
    session.commit()
    return result


def reauthenticate(
    session: Session, principal: Principal, request: ReauthenticationRequest, source: str
) -> MemberResponse:
    """Verify the current account again without creating a device or extending session expiry."""
    buckets = _reauth_buckets(principal.user_id, source)
    _admit_attempt(session, buckets, utcnow())
    # Admission intentionally commits failures. Reacquire session -> device in this
    # order and recheck live state before elevating the existing session's recency.
    auth, devices = lock_session_devices(session, principal)
    user, member, _ = _active_identity(session, auth)
    if not _verify_admitted(
        session, buckets, user.password_hash, request.password.get_secret_value()
    ):
        raise DomainError("REAUTHENTICATION_FAILED", "비밀번호를 확인해 주세요.", 403)
    # Password verification can take time; no previously expired access/session is revived.
    now = validate_locked_session(principal, auth, devices[principal.device_id])
    auth.authenticated_at = now
    auth.last_seen_at = now
    _upgrade_hash(user, request.password.get_secret_value())
    result = member_response(user, member)
    session.commit()
    return result


def live_session(now: datetime):
    """The SQL form of the session checks that depend on time or on a later install sign-in."""
    superseded = (
        select(RegisteredDevice.id)
        .where(
            RegisteredDevice.id == AuthSession.device_id,
            RegisteredDevice.install_session_id != AuthSession.id,
        )
        .exists()
    )
    return (
        AuthSession.revoked_at.is_(None)
        & (AuthSession.expires_at > now)
        & ((AuthSession.kind == "native") | (AuthSession.last_seen_at > now - WEB_IDLE))
        & ~superseded
    )


def lock_install_device(
    session: Session,
    install: InstallClaim | None,
    user_id: UUID | None,
    household_id: UUID | None,
    *,
    skip_locked: bool = False,
) -> RegisteredDevice | None:
    """Lock the device row an install claim names, only if it is this user's Android row.

    Devices come before the users row and before credentials, the order password change,
    revocation and step-up use. After a password check the user is known, so another member's
    row is never locked. Before a passkey proof the user is only claimed: `skip_locked` takes
    the row only when free, so a claim never waits on it or learns whether it is busy.
    """
    if install is None or install.device_id is None or user_id is None or household_id is None:
        return None
    return session.scalar(
        select(RegisteredDevice)
        .where(
            RegisteredDevice.id == install.device_id,
            RegisteredDevice.user_id == user_id,
            RegisteredDevice.household_id == household_id,
            RegisteredDevice.platform == "android",
        )
        .with_for_update(skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    )


def issue_session(
    session: Session,
    user: User,
    member: HouseholdMember,
    device_label: str,
    transport: Literal["web", "native"],
    *,
    device_id: UUID | None = None,
    install: InstallClaim | None = None,
) -> LoginResult:
    """Issue credentials after server verification; caller owns the atomic commit.

    This is an internal service, not an authentication bypass endpoint. The optional device
    ID must come from server ceremony state. A client's device id counts only inside an
    install claim whose key matches the stored hash for the same user and household; any
    other claim gets a new row, so a claim reveals nothing about other devices.
    Locks the users row so password changes and sign-out of other devices serialize with
    new sessions.
    """
    if transport not in {"web", "native"}:
        raise ValueError("Unsupported authentication transport")
    if install is not None and transport != "native":
        raise ValueError("Only native sign-in presents an install claim")
    claimed = lock_install_device(session, install, user.id, member.household_id)
    active = session.execute(
        select(User, HouseholdMember)
        .select_from(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .where(
            User.id == user.id,
            User.disabled_at.is_(None),
            HouseholdMember.id == member.id,
            HouseholdMember.household_id == member.household_id,
            HouseholdMember.status == "active",
        )
        .with_for_update(of=User, key_share=True)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if active is None:
        raise _unauthenticated()
    user, member = active
    now = utcnow()
    install_key = None
    session_id = uuid4()
    if claimed is not None and _install_matches(claimed, install, user, member):
        device = claimed
        before_version = device.version
        device.label = device_label
        device.last_seen_at = now
        device.version += 1
        # One session per install: what this install signed in with before ends here, at the
        # device row. Writing those session rows would invert the session -> device lock order.
        device.install_session_id = session_id
    else:
        before_version = None
        device = RegisteredDevice(
            household_id=member.household_id,
            user_id=user.id,
            label=device_label,
            platform="web" if transport == "web" else "android",
            status="active",
            last_seen_at=now,
        )
        if device_id is not None:
            device.id = device_id
        if install is not None:
            install_key = secrets.token_urlsafe(32)
            device.install_key_hash = token_hash(INSTALL_KEY, install_key)
            device.install_session_id = session_id
        session.add(device)
    session.flush()
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32) if transport == "web" else None
    auth = AuthSession(
        id=session_id,
        household_id=member.household_id,
        user_id=user.id,
        device_id=device.id,
        kind=transport,
        session_hash=token_hash("session", token),
        csrf_hash=token_hash("csrf", csrf) if csrf else None,
        access_expires_at=now + ACCESS_LIFETIME if transport == "native" else None,
        expires_at=now + (WEB_ABSOLUTE if transport == "web" else REFRESH_LIFETIME),
        authenticated_at=now,
        last_seen_at=now,
    )
    session.add(auth)
    session.flush()
    native_tokens = None
    if transport == "native":
        refresh = secrets.token_urlsafe(32)
        session.add(
            RefreshToken(
                household_id=member.household_id,
                session_id=auth.id,
                token_hash=token_hash("refresh", refresh),
                expires_at=auth.expires_at,
            )
        )
        native_tokens = NativeTokenResponse(
            access_token=token,
            refresh_token=refresh,
            refresh_expires_at=auth.expires_at,
        )
    session.flush()
    record_event(
        session,
        Principal(
            user_id=user.id,
            member_id=member.id,
            household_id=member.household_id,
            session_id=auth.id,
            device_id=device.id,
            role=member.role,
            transport=transport,
            authenticated_at=now,
        ),
        entity_type="registered_device",
        entity_id=device.id,
        action="login",
        before_version=before_version,
        after_version=device.version,
    )
    return LoginResult(
        member=member_response(user, member),
        expires_at=auth.expires_at,
        token=token,
        csrf_token=csrf,
        native_tokens=native_tokens,
        install=None if install is None else InstallDevice(device_id=device.id, key=install_key),
    )


def _install_matches(
    device: RegisteredDevice, install: InstallClaim, user: User, member: HouseholdMember
) -> bool:
    key = install.key.get_secret_value() if install.key else ""
    return (
        device.install_key_hash is not None
        and hmac.compare_digest(device.install_key_hash, token_hash(INSTALL_KEY, key))
        and device.user_id == user.id
        and device.household_id == member.household_id
        and device.platform == "android"
        and device.status == "active"
        and device.revoked_at is None
    )


def rotate_refresh(session: Session, token: str, source: str) -> NativeTokenResponse:
    now = utcnow()
    # Every device reaches the API through the same proxy peer, so the source bucket is shared
    # by the whole installation. A device over its own limit is refused before it can use it up.
    buckets = [(f"refresh-source:{source}", 30)]
    if _valid_token(token):
        device_id = session.scalar(
            select(AuthSession.device_id).where(
                AuthSession.id == RefreshToken.session_id,
                AuthSession.household_id == RefreshToken.household_id,
                RefreshToken.token_hash == token_hash("refresh", token),
            )
        )
        if device_id is not None:
            buckets.append((f"refresh-device:{device_id}", REFRESH_DEVICE_LIMIT))
    _admit_attempt(session, buckets, now)
    if not _valid_token(token):
        raise _unauthenticated()
    # Look up family before locking; every rotation locks session then token in that order.
    family_id = session.scalar(
        select(RefreshToken.session_id).where(
            RefreshToken.token_hash == token_hash("refresh", token),
        )
    )
    if family_id is None:
        raise _unauthenticated()
    auth = session.scalar(select(AuthSession).where(AuthSession.id == family_id).with_for_update())
    previous = session.scalar(
        select(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash("refresh", token),
            RefreshToken.session_id == auth.id,
            RefreshToken.household_id == auth.household_id,
        )
        .with_for_update()
    )
    now = utcnow()
    if (
        auth.kind != "native"
        or auth.revoked_at is not None
        or auth.expires_at <= now
        or previous is None
        or previous.expires_at <= now
    ):
        raise _unauthenticated()
    if previous.consumed_at is not None:
        auth.revoked_at = now
        session.commit()  # Revocation must survive the subsequent authentication error.
        raise _unauthenticated()
    _active_identity(session, auth)
    previous.consumed_at = now
    access = secrets.token_urlsafe(32)
    refresh = secrets.token_urlsafe(32)
    auth.session_hash = token_hash("session", access)
    auth.access_expires_at = min(now + ACCESS_LIFETIME, auth.expires_at)
    auth.last_seen_at = now
    session.add(
        RefreshToken(
            household_id=auth.household_id,
            session_id=auth.id,
            token_hash=token_hash("refresh", refresh),
            expires_at=auth.expires_at,
        )
    )
    result = NativeTokenResponse(
        access_token=access,
        refresh_token=refresh,
        refresh_expires_at=auth.expires_at,
        expires_in=max(1, int((auth.access_expires_at - now).total_seconds())),
    )
    session.commit()
    return result


def renew_csrf(session: Session, principal: Principal) -> str:
    if principal.transport != "web":
        raise DomainError("WRONG_AUTH_TRANSPORT", "인증 경로를 확인해 주세요.", 403)
    auth = session.get(AuthSession, principal.session_id)
    token = secrets.token_urlsafe(32)
    auth.csrf_hash = token_hash("csrf", token)
    session.commit()
    return token


def revoke_device(session: Session, principal: Principal, device: RegisteredDevice) -> None:
    """Mutate after the route's sorted source/target barrier and operation authorization.

    Do not acquire target session locks: ordinary reads can already hold those sessions.
    """
    if device.household_id != principal.household_id or device.user_id != principal.user_id:
        raise DomainError("NOT_FOUND", "요청한 항목을 찾을 수 없습니다.", 404)
    now = utcnow()
    before = device.version
    device.status = "revoked"
    # Revoking again keeps the time of the first revocation.
    device.revoked_at = device.revoked_at or now
    session.flush()
    record_event(
        session,
        principal,
        entity_type="registered_device",
        entity_id=device.id,
        action="revoke",
        before_version=before,
        after_version=device.version,
        changed_fields=("revoked_at", "status"),
    )
    # This is the authoritative barrier for ALL sessions/refresh tokens on this device.
    # Updating target session rows here would invert the request's session->device lock order.
    session.commit()


def logout(session: Session, principal: Principal) -> None:
    now = utcnow()
    auth = session.get(AuthSession, principal.session_id)
    auth.revoked_at = now
    revoked = session.execute(
        update(RegisteredDevice)
        .where(
            RegisteredDevice.id == principal.device_id,
            RegisteredDevice.household_id == principal.household_id,
            RegisteredDevice.user_id == principal.user_id,
            RegisteredDevice.status == "active",
        )
        .values(status="revoked", revoked_at=now, version=RegisteredDevice.version + 1)
        .execution_options(synchronize_session=False)
    )
    if revoked.rowcount:
        # A bulk UPDATE has no loaded row, so the versions are not recorded.
        record_event(
            session,
            principal,
            entity_type="registered_device",
            entity_id=principal.device_id,
            action="revoke",
            before_version=None,
            after_version=None,
            changed_fields=("revoked_at", "status"),
        )
    session.commit()
