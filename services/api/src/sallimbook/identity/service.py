"""Password-backed sessions and invitations; no passkey or biometric claims are inferred."""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
    InvitationAcceptance,
    InvitationRequest,
    InvitationResponse,
    LoginRequest,
    MemberResponse,
    NativeTokenResponse,
)

WEB_IDLE = timedelta(minutes=30)
WEB_ABSOLUTE = timedelta(hours=12)
ACCESS_LIFETIME = timedelta(minutes=10)
REFRESH_LIFETIME = timedelta(days=30)
INVITATION_LIFETIME = timedelta(minutes=15)
THROTTLE_WINDOW = timedelta(minutes=15)
THROTTLE_CLEANUP_BATCH = 64
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
    blocked = False
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
        if counter.attempts >= limit:
            blocked = True
        else:
            counter.attempts += 1
    session.commit()
    if blocked:
        raise DomainError("RATE_LIMITED", "잠시 후 다시 시도해 주세요.", 429)


def _verify_password(encoded: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(encoded, password)
    except InvalidHashError, VerificationError:
        return False


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
) -> InvitationResponse:
    now = utcnow()
    if step_up_token is None:
        require_recent_login(principal, now=now)
    require_owner(principal)
    session.execute(
        select(Household).where(Household.id == principal.household_id).with_for_update()
    ).scalar_one()
    now = utcnow()
    if step_up_token is None:
        require_recent_login(principal, now=now)
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
    token = secrets.token_urlsafe(32)
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
    result = InvitationResponse(id=invitation.id, token=token, expires_at=invitation.expires_at)
    session.commit()
    return result


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
    _admit_attempt(session, [(f"invite-source:{source}", 30)], now)
    token = request.token.get_secret_value()
    if not _valid_token(token):
        raise DomainError("INVALID_INVITATION", "초대를 다시 확인해 주세요.", 400)
    invitation_id = session.execute(
        select(Invitation.id, Invitation.household_id).where(
            Invitation.token_hash == token_hash("invite", token),
        )
    ).one_or_none()
    if invitation_id is None:
        raise DomainError("INVALID_INVITATION", "초대를 다시 확인해 주세요.", 400)
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
    ):
        raise DomainError("INVALID_INVITATION", "초대를 다시 확인해 주세요.", 400)
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
            raise DomainError("INVALID_INVITATION", "초대를 다시 확인해 주세요.", 400)
    user = User(
        login_name=invitation.intended_login,
        display_name=request.display_name,
        password_hash=PASSWORD_HASHER.hash(request.password.get_secret_value()),
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
        invitation.used_at = now
        session.flush()
        result = member_response(user, member)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise DomainError("REGISTRATION_CONFLICT", "등록 상태를 다시 확인해 주세요.", 409) from None
    return result


@dataclass(frozen=True)
class LoginResult:
    member: MemberResponse
    expires_at: datetime
    token: str = field(repr=False)
    csrf_token: str | None = field(default=None, repr=False)
    native_tokens: NativeTokenResponse | None = field(default=None, repr=False)


def login(
    session: Session, request: LoginRequest, source: str, transport: Literal["web", "native"]
) -> LoginResult:
    now = utcnow()
    _admit_attempt(
        session,
        [
            (f"login-account:{request.login_name}", 5),
            (f"login-source:{source}", 30),
        ],
        now,
    )
    user = session.scalar(select(User).where(User.login_name == request.login_name))
    verified = _verify_password(
        user.password_hash if user else _DUMMY_HASH, request.password.get_secret_value()
    )
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
    if PASSWORD_HASHER.check_needs_rehash(user.password_hash):
        user.password_hash = PASSWORD_HASHER.hash(request.password.get_secret_value())
    # Creating a device is backed by this actual password verification, never a client flag.
    result = issue_session(session, user, member, request.device_label, transport)
    session.commit()
    return result


def issue_session(
    session: Session,
    user: User,
    member: HouseholdMember,
    device_label: str,
    transport: Literal["web", "native"],
    *,
    device_id: UUID | None = None,
) -> LoginResult:
    """Issue credentials after server verification; caller owns the atomic commit.

    This is an internal service, not an authentication bypass endpoint. The optional device
    ID must come from server ceremony state, never from a client's device identifier.
    """
    if transport not in {"web", "native"}:
        raise ValueError("Unsupported authentication transport")
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
        .execution_options(populate_existing=True)
    ).one_or_none()
    if active is None:
        raise _unauthenticated()
    user, member = active
    now = utcnow()
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
    session.add(device)
    session.flush()
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32) if transport == "web" else None
    auth = AuthSession(
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
    return LoginResult(
        member=member_response(user, member),
        expires_at=auth.expires_at,
        token=token,
        csrf_token=csrf,
        native_tokens=native_tokens,
    )


def rotate_refresh(session: Session, token: str, source: str) -> NativeTokenResponse:
    now = utcnow()
    _admit_attempt(session, [(f"refresh-source:{source}", 30)], now)
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
    if device.household_id != principal.household_id or device.user_id != principal.user_id:
        raise DomainError("NOT_FOUND", "요청한 항목을 찾을 수 없습니다.", 404)
    now = utcnow()
    device.status = "revoked"
    device.revoked_at = now
    # This is the authoritative barrier for ALL sessions/refresh tokens on this device.
    # Updating target session rows here would invert the request's session->device lock order.
    session.commit()


def logout(session: Session, principal: Principal) -> None:
    now = utcnow()
    auth = session.get(AuthSession, principal.session_id)
    auth.revoked_at = now
    session.execute(
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
    session.commit()
