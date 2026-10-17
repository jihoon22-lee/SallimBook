"""Authorized opaque vault lifecycle; cryptographic operations remain on clients."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sallimbook.assets.locking import lock_asset_scope
from sallimbook.cards.models import Card
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import Principal, require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.idempotency import IdempotentResult, run_idempotent
from sallimbook.identity import service as identity
from sallimbook.identity.auth_models import AuthSession, HouseholdMember, RegisteredDevice, User
from sallimbook.identity.passkeys.models import StepUpGrant, StepUpPurpose
from sallimbook.identity.passkeys.service import consume_step_up
from sallimbook.vault.formats import MAX_SAFE_INTEGER
from sallimbook.vault.models import (
    CardSecretEnvelope,
    VaultKeyCheck,
    VaultMembership,
    VaultMemberWrapping,
    VaultRecoveryWrapping,
    VaultRotationCard,
    VaultRotationMember,
    VaultShareOffer,
    VaultState,
    VaultVersion,
)
from sallimbook.vault.schemas import (
    VaultMemberSummary,
    VaultMutationReference,
    VaultOwnWrappingResponse,
    VaultRecoveryResponse,
    VaultRotationCardResponse,
    VaultRotationMemberResponse,
    VaultRotationResponse,
    VaultShareListResponse,
    VaultShareResponse,
    VaultShareWrappingResponse,
    VaultStatusResponse,
)
from sallimbook.vault.storage import (
    actor_fields,
    card_secret_response,
    key_check_response,
    member_generation,
    member_wrapping_response,
    recovery_wrapping_response,
    store_card_envelope,
    store_key_check,
    store_member_wrapping,
    store_recovery_wrapping,
    touch,
)

SHARE_LIFETIME = timedelta(minutes=15)


@dataclass
class _Context:
    session: Session
    principal: Principal
    auth: AuthSession
    device: RegisteredDevice
    recent_required: bool = False
    grant: StepUpGrant | None = None

    def recheck(self):
        now = identity.validate_locked_session(
            self.principal, self.auth, self.device, recent_login=self.recent_required
        )
        if self.grant is not None and self.grant.expires_at <= now:
            raise DomainError("STEP_UP_REQUIRED", "이 작업을 다시 인증해 주세요.", 403)
        return now

    def management(self, purpose, target_id, token):
        if token is None:
            self.recent_required = True
        else:
            self.grant = consume_step_up(self.session, self.principal, token, purpose, target_id)
        self.recheck()


def _lock(session, principal):
    # Every vault read and write holds the same identity barriers through commit.
    auth, devices = identity.lock_session_devices(session, principal)
    lock_asset_scope(session, principal)
    member = scoped_entity(session, HouseholdMember, principal.member_id, principal)
    if member.status != "active" or member.user_id != principal.user_id:
        raise DomainError("UNAUTHENTICATED", "로그인이 필요합니다.", 401)
    context = _Context(session, principal, auth, devices[principal.device_id])
    context.recheck()
    return context


def _state(context, *, required=True):
    row = context.session.scalar(
        select(VaultState)
        .where(VaultState.household_id == context.principal.household_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None and required:
        raise DomainError("VAULT_NOT_INITIALIZED", "보관함을 먼저 설정해 주세요.", 409)
    return row


def _membership(context, member_id):
    return context.session.scalar(
        select(VaultMembership).where(
            VaultMembership.household_id == context.principal.household_id,
            VaultMembership.member_id == member_id,
        )
    )


def _enrolled(context):
    row = _membership(context, context.principal.member_id)
    if row is None or row.status != "active":
        raise DomainError("VAULT_ACCESS_DENIED", "보관함 공유 권한을 확인해 주세요.", 403)
    return row


def _staging_version(context):
    return context.session.scalar(
        select(VaultVersion).where(
            VaultVersion.household_id == context.principal.household_id,
            VaultVersion.state == "staging",
        )
    )


def _unfrozen(context, state, *, requires_rotated_key=False):
    if _staging_version(context) is not None:
        raise DomainError("VAULT_ROTATION_IN_PROGRESS", "키 회전을 먼저 마쳐 주세요.", 409)
    if requires_rotated_key and state.rotation_required:
        raise DomainError("VAULT_ROTATION_REQUIRED", "새 보관함 키로 회전해 주세요.", 409)


def _current_key(state, key_version):
    if key_version != state.current_key_version:
        raise DomainError("VAULT_KEY_VERSION_CONFLICT", "현재 보관함 키를 확인해 주세요.", 409)


def _check_row(context, key_version):
    row = context.session.scalar(
        select(VaultKeyCheck).where(
            VaultKeyCheck.household_id == context.principal.household_id,
            VaultKeyCheck.key_version == key_version,
        )
    )
    if row is None:
        raise DomainError("VAULT_NOT_PREPARED", "보관함 키 준비를 확인해 주세요.", 409)
    return row


def _member_wrap(context, key_version, member_id):
    row = context.session.scalar(
        select(VaultMemberWrapping).where(
            VaultMemberWrapping.household_id == context.principal.household_id,
            VaultMemberWrapping.key_version == key_version,
            VaultMemberWrapping.member_id == member_id,
            VaultMemberWrapping.state == "current",
        )
    )
    if row is None:
        raise DomainError("VAULT_NOT_PREPARED", "본인 wrapping을 확인해 주세요.", 409)
    return row


def _recovery_wrap(context, key_version):
    row = context.session.scalar(
        select(VaultRecoveryWrapping).where(
            VaultRecoveryWrapping.household_id == context.principal.household_id,
            VaultRecoveryWrapping.key_version == key_version,
            VaultRecoveryWrapping.is_current.is_(True),
        )
    )
    if row is None:
        raise DomainError("VAULT_NOT_PREPARED", "복구 wrapping을 확인해 주세요.", 409)
    return row


def _envelope(context, key_version, card_id):
    return context.session.scalar(
        select(CardSecretEnvelope).where(
            CardSecretEnvelope.household_id == context.principal.household_id,
            CardSecretEnvelope.key_version == key_version,
            CardSecretEnvelope.card_id == card_id,
            CardSecretEnvelope.is_current.is_(True),
        )
    )


def _audit(context, row, entity_type, action, fields=(), before=None):
    record_event(
        context.session,
        context.principal,
        entity_type=entity_type,
        entity_id=row.id,
        action=action,
        before_version=before,
        after_version=row.version,
        changed_fields=fields,
    )


def _read(context, result):
    context.session.flush()
    context.recheck()
    context.session.commit()
    return result


def _reference(row, kind, *, status_code=200):
    return IdempotentResult(
        resource_id=row.id,
        resource_type=kind,
        resource_version=row.version,
        status_code=status_code,
    )


def _run(context, operation, key, payload, execute):
    # Callers authorize the actor and target before this lookup. Tokens never enter
    # the fingerprint, and completed retries only return immutable safe references.
    context.recheck()
    try:
        result = run_idempotent(
            context.session, context.principal, operation, key, payload, execute
        )
        context.session.flush()
        context.recheck()
        response = VaultMutationReference(id=result.resource_id, version=result.resource_version)
        context.session.commit()
        return response
    except IntegrityError as error:
        context.session.rollback()
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        if constraint == "pk_vault_nonce_reservations":
            code = "VAULT_NONCE_REUSED"
        elif constraint in {"uq_vault_member_wrappings_salt", "uq_vault_recovery_wrappings_salt"}:
            code = "VAULT_SALT_REUSED"
        else:
            code = "VAULT_STATE_CONFLICT"
        raise DomainError(code, "보관함 상태가 변경됐습니다. 다시 확인해 주세요.", 409) from None


def get_status(session, principal):
    context = _lock(session, principal)
    state = _state(context, required=False)
    if state is None:
        return _read(
            context,
            VaultStatusResponse(
                household_id=principal.household_id,
                initialized=False,
                id=None,
                version=None,
                current_key_version=None,
                own_membership="not_enrolled",
                rotation_required=False,
                pending_rotation_id=None,
                members=[],
            ),
        )
    members = []
    for member in session.scalars(
        select(HouseholdMember)
        .where(
            HouseholdMember.household_id == principal.household_id,
            HouseholdMember.status == "active",
        )
        .order_by(HouseholdMember.id)
    ):
        membership = _membership(context, member.id)
        members.append(
            VaultMemberSummary(
                member_id=member.id,
                status=membership.status if membership is not None else "not_enrolled",
                version=membership.version if membership is not None else None,
                next_wrapping_generation=member_generation(
                    session, principal, member.id, state.current_key_version
                ),
            )
        )
    own = _membership(context, principal.member_id)
    staging = _staging_version(context)
    return _read(
        context,
        VaultStatusResponse(
            household_id=principal.household_id,
            initialized=True,
            id=state.id,
            version=state.version,
            current_key_version=state.current_key_version,
            own_membership=own.status if own is not None else "not_enrolled",
            rotation_required=state.rotation_required,
            pending_rotation_id=staging.id if staging is not None else None,
            members=members,
        ),
    )


def initialize(session, principal, payload, idempotency_key, *, step_up_token=None):
    context = _lock(session, principal)
    state = _state(context, required=False)
    if payload.member_wrapping.member_id != principal.member_id:
        raise DomainError("VAULT_ACCESS_DENIED", "본인 wrapping으로 설정해 주세요.", 403)

    def execute():
        if state is not None:
            raise DomainError("VAULT_ALREADY_INITIALIZED", "이미 설정된 보관함입니다.", 409)
        context.management(StepUpPurpose.VAULT_KEY_ROTATION, principal.household_id, step_up_token)
        version = VaultVersion(
            **actor_fields(principal),
            key_version=1,
            source_key_version=None,
            state="current",
            expected_card_count=0,
            expected_member_count=1,
            activated_at=identity.utcnow(),
        )
        session.add(version)
        session.flush([version])
        membership = VaultMembership(
            **actor_fields(principal),
            member_id=principal.member_id,
            joined_key_version=1,
            status="active",
        )
        session.add(membership)
        session.flush([membership])
        store_key_check(session, principal, payload.key_check)
        store_member_wrapping(session, principal, payload.member_wrapping, state="current")
        store_recovery_wrapping(session, principal, payload.recovery_wrapping)
        created = VaultState(
            **actor_fields(principal),
            current_key_version=1,
            next_key_version=2,
            rotation_required=False,
        )
        session.add(created)
        session.flush([created])
        _audit(context, created, "vault", "create", ("current_key_version",))
        return _reference(created, "vault", status_code=201)

    return _run(
        context, "vault.initialize", idempotency_key, payload.model_dump(mode="json"), execute
    )


def get_own_wrapping(session, principal):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    wrapping = _member_wrap(context, state.current_key_version, principal.member_id)
    check = _check_row(context, state.current_key_version)
    _audit(context, wrapping, "vault_member_wrapping", "reveal")
    return _read(
        context,
        VaultOwnWrappingResponse(
            wrapping=member_wrapping_response(wrapping),
            key_check=key_check_response(check),
        ),
    )


def rewrap_member(session, principal, payload, if_match, idempotency_key, *, step_up_token=None):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    if payload.wrapping.member_id != principal.member_id:
        raise DomainError("VAULT_ACCESS_DENIED", "본인 wrapping만 변경할 수 있습니다.", 403)

    def execute():
        _unfrozen(context, state)
        _current_key(state, payload.wrapping.key_version)
        previous = _member_wrap(context, state.current_key_version, principal.member_id)
        require_version(previous, if_match)
        context.management(StepUpPurpose.VAULT_MEMBERSHIP, principal.member_id, step_up_token)
        previous.state = "replaced"
        touch(previous, principal)
        session.flush([previous])
        wrapping = store_member_wrapping(session, principal, payload.wrapping, state="current")
        touch(state, principal)
        _audit(context, wrapping, "vault_member_wrapping", "update", ("generation",))
        return _reference(wrapping, "vault_member_wrapping")

    return _run(
        context,
        "vault.member.rewrap",
        idempotency_key,
        {"body": payload.model_dump(mode="json"), "if_match": if_match},
        execute,
    )


def get_recovery_wrapping(session, principal, *, step_up_token=None):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    context.management(StepUpPurpose.VAULT_KEY_ROTATION, principal.household_id, step_up_token)
    wrapping = _recovery_wrap(context, state.current_key_version)
    check = _check_row(context, state.current_key_version)
    _audit(context, wrapping, "vault_recovery_wrapping", "reveal")
    return _read(
        context,
        VaultRecoveryResponse(
            wrapping=recovery_wrapping_response(wrapping),
            key_check=key_check_response(check),
        ),
    )


def recover(session, principal, payload, if_match, idempotency_key, *, step_up_token=None):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    if payload.member_wrapping.member_id != principal.member_id:
        raise DomainError("VAULT_ACCESS_DENIED", "본인 wrapping만 복구할 수 있습니다.", 403)

    def execute():
        _unfrozen(context, state)
        require_version(state, if_match)
        _current_key(state, payload.member_wrapping.key_version)
        context.management(StepUpPurpose.VAULT_KEY_ROTATION, principal.household_id, step_up_token)
        previous_member = _member_wrap(context, state.current_key_version, principal.member_id)
        previous_recovery = _recovery_wrap(context, state.current_key_version)
        previous_member.state = "replaced"
        previous_recovery.is_current = False
        touch(previous_member, principal)
        touch(previous_recovery, principal)
        session.flush([previous_member, previous_recovery])
        member = store_member_wrapping(session, principal, payload.member_wrapping, state="current")
        recovery = store_recovery_wrapping(session, principal, payload.recovery_wrapping)
        old_version = state.version
        touch(state, principal)
        session.flush([state])
        _audit(context, member, "vault_member_wrapping", "update", ("generation",))
        _audit(context, recovery, "vault_recovery_wrapping", "update", ("generation",))
        _audit(
            context, state, "vault", "update", ("member_wrapping", "recovery_wrapping"), old_version
        )
        return _reference(state, "vault")

    return _run(
        context,
        "vault.recover",
        idempotency_key,
        {"body": payload.model_dump(mode="json"), "if_match": if_match},
        execute,
    )


def get_card_secret(session, principal, card_id):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    card = scoped_entity(session, Card, card_id, principal)
    envelope = _envelope(context, state.current_key_version, card.id)
    if envelope is None:
        raise DomainError("VAULT_SECRET_NOT_SET", "등록된 카드 비밀이 없습니다.", 404)
    _audit(context, envelope, "card_secret_envelope", "reveal")
    return _read(context, card_secret_response(envelope, card))


def write_card_secret(session, principal, card_id, payload, if_match, idempotency_key):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    card = scoped_entity(session, Card, card_id, principal, for_update=True)

    def execute():
        _unfrozen(context, state, requires_rotated_key=True)
        _current_key(state, payload.key_version)
        require_version(card, if_match)
        previous = _envelope(context, state.current_key_version, card.id)
        if previous is not None:
            previous.is_current = False
            touch(previous, principal)
            session.flush([previous])
        envelope = store_card_envelope(session, principal, card, payload)
        old_version = card.version
        card.last_four = payload.last_four
        touch(card, principal)
        session.flush([card])
        _audit(context, envelope, "card_secret_envelope", "create", ("ciphertext", "last_four"))
        _audit(context, card, "card", "update", ("last_four", "secret_envelope"), old_version)
        return _reference(card, "card")

    return _run(
        context,
        "vault.card.write",
        idempotency_key,
        {"card_id": str(card_id), "body": payload.model_dump(mode="json"), "if_match": if_match},
        execute,
    )


def delete_card_secret(session, principal, card_id, if_match, idempotency_key):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    card = scoped_entity(session, Card, card_id, principal, for_update=True)

    def execute():
        _unfrozen(context, state)
        require_version(card, if_match)
        envelopes = list(
            session.scalars(
                select(CardSecretEnvelope)
                .where(
                    CardSecretEnvelope.household_id == principal.household_id,
                    CardSecretEnvelope.card_id == card_id,
                    CardSecretEnvelope.ciphertext.is_not(None),
                )
                .order_by(CardSecretEnvelope.key_version, CardSecretEnvelope.revision)
                .with_for_update()
            )
        )
        if not envelopes:
            raise DomainError("VAULT_SECRET_NOT_SET", "등록된 카드 비밀이 없습니다.", 404)
        now = context.recheck()
        for envelope in envelopes:
            before = envelope.version
            envelope.ciphertext, envelope.purged_at, envelope.is_current = None, now, False
            touch(envelope, principal)
            _audit(context, envelope, "card_secret_envelope", "delete", ("ciphertext",), before)
        before = card.version
        touch(card, principal)
        session.flush()
        _audit(context, card, "card", "update", ("secret_envelope",), before)
        return _reference(card, "card")

    return _run(
        context,
        "vault.card.delete",
        idempotency_key,
        {"card_id": str(card_id), "if_match": if_match},
        execute,
    )


def _available_member(context, member_id):
    member = scoped_entity(context.session, HouseholdMember, member_id, context.principal)
    user = context.session.get(User, member.user_id)
    if member.status != "active" or user is None or user.disabled_at is not None:
        raise DomainError("VAULT_MEMBER_UNAVAILABLE", "현재 가계 구성원을 확인해 주세요.", 409)
    return member


def _active_members(context):
    return list(
        context.session.scalars(
            select(VaultMembership)
            .where(
                VaultMembership.household_id == context.principal.household_id,
                VaultMembership.status == "active",
            )
            .order_by(VaultMembership.member_id)
        )
    )


def _share_response(row):
    return VaultShareResponse(
        **{name: getattr(row, name) for name in VaultShareResponse.model_fields}
    )


def _offer(context, offer_id):
    offer = scoped_entity(
        context.session, VaultShareOffer, offer_id, context.principal, for_update=True
    )
    if context.principal.member_id not in {offer.source_member_id, offer.target_member_id}:
        raise DomainError("NOT_FOUND", "요청한 항목을 찾을 수 없습니다.", 404)
    return offer


def _pending_offer(context, state, offer):
    _current_key(state, offer.key_version)
    source = _membership(context, offer.source_member_id)
    _available_member(context, offer.source_member_id)
    _available_member(context, offer.target_member_id)
    if (
        offer.state != "pending"
        or offer.expires_at <= context.recheck()
        or source is None
        or source.status != "active"
    ):
        raise DomainError(
            "VAULT_SHARE_UNAVAILABLE", "유효한 보관함 공유 요청을 확인해 주세요.", 409
        )


def create_share(session, principal, payload, if_match, idempotency_key, *, step_up_token=None):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    target_id = payload.wrapping.member_id
    _available_member(context, target_id)
    if target_id == principal.member_id:
        raise DomainError("VAULT_SHARE_TARGET", "다른 가계 구성원을 선택해 주세요.", 422)

    def execute():
        _unfrozen(context, state, requires_rotated_key=True)
        require_version(state, if_match)
        _current_key(state, payload.wrapping.key_version)
        target_membership = _membership(context, target_id)
        if target_membership is not None and target_membership.status == "active":
            raise DomainError("VAULT_ALREADY_ENROLLED", "이미 보관함을 공유한 구성원입니다.", 409)
        context.management(StepUpPurpose.VAULT_MEMBERSHIP, target_id, step_up_token)
        now = context.recheck()
        for old in session.scalars(
            select(VaultShareOffer).where(
                VaultShareOffer.household_id == principal.household_id,
                VaultShareOffer.target_member_id == target_id,
                VaultShareOffer.state == "pending",
            )
        ):
            if old.expires_at > now:
                raise DomainError(
                    "VAULT_SHARE_PENDING", "진행 중인 공유 요청을 확인해 주세요.", 409
                )
            before = old.version
            old.state, old.closed_at = "expired", now
            touch(old, principal)
            _audit(context, old, "vault_share", "archive", ("state",), before)
        session.flush()
        wrapping = store_member_wrapping(session, principal, payload.wrapping, state="offered")
        offer = VaultShareOffer(
            **actor_fields(principal),
            source_member_id=principal.member_id,
            target_member_id=target_id,
            key_version=state.current_key_version,
            wrapping_id=wrapping.id,
            state="pending",
            expires_at=now + SHARE_LIFETIME,
        )
        session.add(offer)
        touch(state, principal)
        session.flush([offer, state])
        _audit(context, offer, "vault_share", "create", ("target_member_id", "key_version"))
        return _reference(offer, "vault_share", status_code=201)

    return _run(
        context,
        "vault.share.create",
        idempotency_key,
        {"body": payload.model_dump(mode="json"), "if_match": if_match},
        execute,
    )


def list_shares(session, principal, *, cursor=None, limit=50):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise DomainError("INVALID_PAGE_SIZE", "조회 건수를 확인해 주세요.", 422)
    context = _lock(session, principal)
    query = select(VaultShareOffer).where(
        VaultShareOffer.household_id == principal.household_id,
        or_(
            VaultShareOffer.source_member_id == principal.member_id,
            VaultShareOffer.target_member_id == principal.member_id,
        ),
    )
    if cursor is not None:
        query = query.where(VaultShareOffer.id < cursor)
    rows = list(session.scalars(query.order_by(VaultShareOffer.id.desc()).limit(limit + 1)))
    items = rows[:limit]
    return _read(
        context,
        VaultShareListResponse(
            items=[_share_response(row) for row in items],
            next_cursor=items[-1].id if len(rows) > limit else None,
        ),
    )


def get_share_wrapping(session, principal, offer_id, *, step_up_token=None):
    context = _lock(session, principal)
    state = _state(context)
    offer = _offer(context, offer_id)
    if offer.target_member_id != principal.member_id:
        raise DomainError("VAULT_ACCESS_DENIED", "본인 공유 wrapping만 조회할 수 있습니다.", 403)
    _pending_offer(context, state, offer)
    context.management(StepUpPurpose.VAULT_MEMBERSHIP, principal.member_id, step_up_token)
    wrapping = scoped_entity(session, VaultMemberWrapping, offer.wrapping_id, principal)
    if wrapping.state != "offered":
        raise DomainError("VAULT_SHARE_UNAVAILABLE", "공유 wrapping을 확인해 주세요.", 409)
    check = _check_row(context, state.current_key_version)
    _audit(context, offer, "vault_share", "reveal")
    return _read(
        context,
        VaultShareWrappingResponse(
            offer=_share_response(offer),
            wrapping=member_wrapping_response(wrapping),
            key_check=key_check_response(check),
        ),
    )


def accept_share(
    session,
    principal,
    offer_id,
    payload,
    if_match,
    idempotency_key,
    *,
    step_up_token=None,
):
    context = _lock(session, principal)
    state = _state(context)
    offer = _offer(context, offer_id)
    if offer.target_member_id != principal.member_id:
        raise DomainError("VAULT_ACCESS_DENIED", "본인 공유 요청만 수락할 수 있습니다.", 403)

    def execute():
        _unfrozen(context, state, requires_rotated_key=True)
        require_version(offer, if_match)
        _pending_offer(context, state, offer)
        _current_key(state, payload.key_version)
        context.management(StepUpPurpose.VAULT_MEMBERSHIP, principal.member_id, step_up_token)
        membership = _membership(context, principal.member_id)
        if membership is not None and membership.status == "active":
            raise DomainError("VAULT_ALREADY_ENROLLED", "이미 보관함을 공유한 구성원입니다.", 409)
        if membership is None:
            membership = VaultMembership(
                **actor_fields(principal),
                member_id=principal.member_id,
                status="active",
                joined_key_version=state.current_key_version,
            )
            session.add(membership)
        else:
            membership.status, membership.revoked_at = "active", None
            membership.joined_key_version = state.current_key_version
            touch(membership, principal)
        wrapping = scoped_entity(
            session, VaultMemberWrapping, offer.wrapping_id, principal, for_update=True
        )
        if wrapping.state != "offered":
            raise DomainError("VAULT_SHARE_UNAVAILABLE", "공유 wrapping을 확인해 주세요.", 409)
        wrapping.state = "current"
        touch(wrapping, principal)
        before = offer.version
        offer.state, offer.closed_at = "accepted", context.recheck()
        touch(offer, principal)
        touch(state, principal)
        session.flush()
        _audit(context, offer, "vault_share", "confirm", ("state",), before)
        _audit(context, membership, "vault_membership", "confirm", ("status",))
        return _reference(offer, "vault_share")

    return _run(
        context,
        "vault.share.accept",
        idempotency_key,
        {"offer_id": str(offer_id), "body": payload.model_dump(mode="json"), "if_match": if_match},
        execute,
    )


def cancel_share(session, principal, offer_id, if_match, idempotency_key, *, step_up_token=None):
    context = _lock(session, principal)
    state = _state(context)
    offer = _offer(context, offer_id)
    if offer.source_member_id == principal.member_id:
        _enrolled(context)

    def execute():
        _unfrozen(context, state)
        require_version(offer, if_match)
        if offer.state != "pending":
            raise DomainError(
                "VAULT_SHARE_UNAVAILABLE", "진행 중인 공유 요청을 확인해 주세요.", 409
            )
        context.management(StepUpPurpose.VAULT_MEMBERSHIP, offer.target_member_id, step_up_token)
        before = offer.version
        offer.state, offer.closed_at = "cancelled", context.recheck()
        touch(offer, principal)
        touch(state, principal)
        session.flush()
        _audit(context, offer, "vault_share", "archive", ("state",), before)
        return _reference(offer, "vault_share")

    return _run(
        context,
        "vault.share.cancel",
        idempotency_key,
        {"offer_id": str(offer_id), "if_match": if_match},
        execute,
    )


def revoke_member(session, principal, member_id, if_match, idempotency_key, *, step_up_token=None):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    scoped_entity(session, HouseholdMember, member_id, principal)
    membership = _membership(context, member_id)
    if membership is None:
        raise DomainError("NOT_FOUND", "요청한 항목을 찾을 수 없습니다.", 404)

    def execute():
        _unfrozen(context, state)
        require_version(membership, if_match)
        if membership.status != "active":
            raise DomainError("VAULT_MEMBER_UNAVAILABLE", "이미 철회된 공유 권한입니다.", 409)
        remaining = [row for row in _active_members(context) if row.member_id != member_id]
        if not remaining:
            raise DomainError(
                "VAULT_LAST_MEMBER", "마지막 보관함 구성원은 철회할 수 없습니다.", 409
            )
        for row in remaining:
            _available_member(context, row.member_id)
        context.management(StepUpPurpose.VAULT_MEMBERSHIP, member_id, step_up_token)
        before = membership.version
        membership.status, membership.revoked_at = "revoked", context.recheck()
        touch(membership, principal)
        state.rotation_required = True
        touch(state, principal)
        session.flush()
        _audit(context, membership, "vault_membership", "archive", ("status",), before)
        _audit(context, state, "vault", "update", ("rotation_required",))
        return _reference(membership, "vault_membership")

    return _run(
        context,
        "vault.member.revoke",
        idempotency_key,
        {"member_id": str(member_id), "if_match": if_match},
        execute,
    )


def _rotation(context, rotation_id):
    row = scoped_entity(
        context.session, VaultVersion, rotation_id, context.principal, for_update=True
    )
    if row.source_key_version is None:
        raise DomainError("NOT_FOUND", "요청한 항목을 찾을 수 없습니다.", 404)
    return row


def _require_staging(context, state, rotation):
    if rotation.state != "staging" or rotation.source_key_version != state.current_key_version:
        raise DomainError("VAULT_ROTATION_UNAVAILABLE", "진행 중인 키 회전을 확인해 주세요.", 409)


def _rotation_cards(context, rotation):
    return list(
        context.session.scalars(
            select(VaultRotationCard)
            .where(
                VaultRotationCard.household_id == context.principal.household_id,
                VaultRotationCard.key_version == rotation.key_version,
            )
            .order_by(VaultRotationCard.card_id)
        )
    )


def _rotation_members(context, rotation):
    return list(
        context.session.scalars(
            select(VaultRotationMember)
            .where(
                VaultRotationMember.household_id == context.principal.household_id,
                VaultRotationMember.key_version == rotation.key_version,
            )
            .order_by(VaultRotationMember.member_id)
        )
    )


def _current_envelopes(context, key_version):
    return list(
        context.session.scalars(
            select(CardSecretEnvelope)
            .where(
                CardSecretEnvelope.household_id == context.principal.household_id,
                CardSecretEnvelope.key_version == key_version,
                CardSecretEnvelope.is_current.is_(True),
            )
            .order_by(CardSecretEnvelope.card_id)
        )
    )


def start_rotation(session, principal, payload, if_match, idempotency_key, *, step_up_token=None):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)

    def execute():
        _unfrozen(context, state)
        require_version(state, if_match)
        context.management(StepUpPurpose.VAULT_KEY_ROTATION, principal.household_id, step_up_token)
        if state.next_key_version >= MAX_SAFE_INTEGER:
            raise DomainError("VAULT_VERSION_EXHAUSTED", "보관함 버전을 확인해 주세요.", 409)
        members = _active_members(context)
        if not 1 <= len(members) <= 2:
            raise DomainError("VAULT_MEMBER_UNAVAILABLE", "보관함 구성원을 확인해 주세요.", 409)
        for member in members:
            _available_member(context, member.member_id)
        envelopes = _current_envelopes(context, state.current_key_version)
        rotation = VaultVersion(
            **actor_fields(principal),
            key_version=state.next_key_version,
            source_key_version=state.current_key_version,
            state="staging",
            expected_card_count=len(envelopes),
            expected_member_count=len(members),
        )
        session.add(rotation)
        session.flush([rotation])
        for envelope in envelopes:
            session.add(
                VaultRotationCard(
                    **actor_fields(principal),
                    key_version=rotation.key_version,
                    card_id=envelope.card_id,
                    source_envelope_id=envelope.id,
                    source_key_version=envelope.key_version,
                    source_revision=envelope.revision,
                )
            )
        for member in members:
            session.add(
                VaultRotationMember(
                    **actor_fields(principal),
                    key_version=rotation.key_version,
                    member_id=member.member_id,
                    source_membership_version=member.version,
                )
            )
        state.next_key_version += 1
        touch(state, principal)
        session.flush()
        _audit(context, rotation, "vault_rotation", "create", ("key_version", "source_key_version"))
        return _reference(rotation, "vault_rotation", status_code=201)

    return _run(
        context,
        "vault.rotation.start",
        idempotency_key,
        {"body": payload.model_dump(mode="json"), "if_match": if_match},
        execute,
    )


def get_rotation(session, principal, rotation_id):
    context = _lock(session, principal)
    _state(context)
    _enrolled(context)
    rotation = _rotation(context, rotation_id)
    cards = []
    for target in _rotation_cards(context, rotation):
        source = scoped_entity(session, CardSecretEnvelope, target.source_envelope_id, principal)
        cards.append(
            VaultRotationCardResponse(
                card_id=target.card_id,
                source_envelope_id=source.id,
                source_revision=source.revision,
                last_four=source.last_four,
                prepared=_envelope(context, rotation.key_version, target.card_id) is not None,
            )
        )
    prepared_members = set(
        session.scalars(
            select(VaultMemberWrapping.member_id).where(
                VaultMemberWrapping.household_id == principal.household_id,
                VaultMemberWrapping.key_version == rotation.key_version,
                VaultMemberWrapping.state == "current",
            )
        )
    )
    check_exists = (
        session.scalar(
            select(VaultKeyCheck.id).where(
                VaultKeyCheck.household_id == principal.household_id,
                VaultKeyCheck.key_version == rotation.key_version,
            )
        )
        is not None
    )
    recovery_exists = (
        session.scalar(
            select(VaultRecoveryWrapping.id).where(
                VaultRecoveryWrapping.household_id == principal.household_id,
                VaultRecoveryWrapping.key_version == rotation.key_version,
                VaultRecoveryWrapping.is_current.is_(True),
            )
        )
        is not None
    )
    return _read(
        context,
        VaultRotationResponse(
            id=rotation.id,
            household_id=rotation.household_id,
            key_version=rotation.key_version,
            source_key_version=rotation.source_key_version,
            state=rotation.state,
            version=rotation.version,
            key_check_prepared=check_exists,
            recovery_prepared=recovery_exists,
            cards=cards,
            members=[
                VaultRotationMemberResponse(
                    member_id=member.member_id,
                    source_membership_version=member.source_membership_version,
                    prepared=member.member_id in prepared_members,
                )
                for member in _rotation_members(context, rotation)
            ],
        ),
    )


def prepare_rotation(
    session,
    principal,
    rotation_id,
    payload,
    if_match,
    idempotency_key,
    *,
    step_up_token=None,
):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    rotation = _rotation(context, rotation_id)

    def execute():
        _require_staging(context, state, rotation)
        require_version(rotation, if_match)
        if payload.key_check.key_version != rotation.key_version:
            raise DomainError(
                "VAULT_KEY_VERSION_CONFLICT", "회전할 새 키 버전을 확인해 주세요.", 409
            )
        targets = _rotation_members(context, rotation)
        expected = {row.member_id for row in targets}
        if (
            len(expected) != rotation.expected_member_count
            or {row.member_id for row in payload.member_wrappings} != expected
        ):
            raise DomainError(
                "VAULT_ROTATION_INCOMPLETE", "모든 구성원의 새 wrapping이 필요합니다.", 409
            )
        if (
            session.scalar(
                select(VaultKeyCheck.id).where(
                    VaultKeyCheck.household_id == principal.household_id,
                    VaultKeyCheck.key_version == rotation.key_version,
                )
            )
            is not None
        ):
            raise DomainError("VAULT_ALREADY_PREPARED", "이미 준비된 키 회전입니다.", 409)
        context.management(StepUpPurpose.VAULT_KEY_ROTATION, principal.household_id, step_up_token)
        store_key_check(session, principal, payload.key_check)
        for wrapping in payload.member_wrappings:
            _available_member(context, wrapping.member_id)
            store_member_wrapping(session, principal, wrapping, state="current")
        store_recovery_wrapping(session, principal, payload.recovery_wrapping)
        before = rotation.version
        touch(rotation, principal)
        session.flush([rotation])
        _audit(context, rotation, "vault_rotation", "update", ("wrappings", "key_check"), before)
        return _reference(rotation, "vault_rotation")

    return _run(
        context,
        "vault.rotation.prepare",
        idempotency_key,
        {
            "rotation_id": str(rotation_id),
            "body": payload.model_dump(mode="json"),
            "if_match": if_match,
        },
        execute,
    )


def _rotation_card(context, rotation, card_id):
    target = context.session.scalar(
        select(VaultRotationCard).where(
            VaultRotationCard.household_id == context.principal.household_id,
            VaultRotationCard.key_version == rotation.key_version,
            VaultRotationCard.card_id == card_id,
        )
    )
    if target is None:
        raise DomainError("NOT_FOUND", "회전 대상 카드를 찾을 수 없습니다.", 404)
    return target


def stage_card(
    session,
    principal,
    rotation_id,
    card_id,
    payload,
    if_match,
    idempotency_key,
    *,
    step_up_token=None,
):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    rotation = _rotation(context, rotation_id)
    card = scoped_entity(session, Card, card_id, principal, for_update=True)
    target = _rotation_card(context, rotation, card_id)

    def execute():
        _require_staging(context, state, rotation)
        require_version(rotation, if_match)
        _check_row(context, rotation.key_version)
        if (
            payload.source_envelope_id != target.source_envelope_id
            or payload.source_revision != target.source_revision
            or payload.envelope.key_version != rotation.key_version
        ):
            raise DomainError(
                "VAULT_ROTATION_SNAPSHOT_CONFLICT", "원본 카드 버전을 확인해 주세요.", 409
            )
        source = scoped_entity(session, CardSecretEnvelope, target.source_envelope_id, principal)
        if payload.envelope.last_four != source.last_four or card.last_four != source.last_four:
            raise DomainError(
                "VAULT_ROTATION_SNAPSHOT_CONFLICT", "카드 표시 정보가 변경됐습니다.", 409
            )
        if _envelope(context, rotation.key_version, card_id) is not None:
            raise DomainError("VAULT_ALREADY_PREPARED", "이미 준비된 카드입니다.", 409)
        context.management(StepUpPurpose.VAULT_KEY_ROTATION, principal.household_id, step_up_token)
        envelope = store_card_envelope(session, principal, card, payload.envelope)
        before = rotation.version
        touch(rotation, principal)
        session.flush([rotation])
        _audit(context, envelope, "card_secret_envelope", "create", ("key_version", "ciphertext"))
        _audit(context, rotation, "vault_rotation", "update", ("cards",), before)
        return _reference(rotation, "vault_rotation")

    return _run(
        context,
        "vault.rotation.card",
        idempotency_key,
        {
            "rotation_id": str(rotation_id),
            "card_id": str(card_id),
            "body": payload.model_dump(mode="json"),
            "if_match": if_match,
        },
        execute,
    )


def get_staged_card(session, principal, rotation_id, card_id):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    rotation = _rotation(context, rotation_id)
    _require_staging(context, state, rotation)
    _rotation_card(context, rotation, card_id)
    card = scoped_entity(session, Card, card_id, principal)
    envelope = _envelope(context, rotation.key_version, card_id)
    if envelope is None:
        raise DomainError("VAULT_NOT_PREPARED", "카드 암호문이 아직 준비되지 않았습니다.", 409)
    _audit(context, envelope, "card_secret_envelope", "reveal")
    return _read(context, card_secret_response(envelope, card))


def get_staged_wrapping(session, principal, rotation_id):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    rotation = _rotation(context, rotation_id)
    _require_staging(context, state, rotation)
    wrapping = _member_wrap(context, rotation.key_version, principal.member_id)
    check = _check_row(context, rotation.key_version)
    _audit(context, wrapping, "vault_member_wrapping", "reveal")
    return _read(
        context,
        VaultOwnWrappingResponse(
            wrapping=member_wrapping_response(wrapping),
            key_check=key_check_response(check),
        ),
    )


def _complete_snapshot(context, rotation):
    targets = _rotation_cards(context, rotation)
    current = _current_envelopes(context, rotation.source_key_version)
    staged = _current_envelopes(context, rotation.key_version)
    if (
        len(targets) != rotation.expected_card_count
        or {(row.card_id, row.source_envelope_id, row.source_revision) for row in targets}
        != {(row.card_id, row.id, row.revision) for row in current}
        or {row.card_id for row in targets} != {row.card_id for row in staged}
    ):
        raise DomainError(
            "VAULT_ROTATION_INCOMPLETE", "모든 원본 카드의 새 암호문이 필요합니다.", 409
        )
    current_by_id = {row.card_id: row for row in current}
    for row in staged:
        card = scoped_entity(context.session, Card, row.card_id, context.principal)
        if row.last_four != current_by_id[row.card_id].last_four or row.last_four != card.last_four:
            raise DomainError(
                "VAULT_ROTATION_SNAPSHOT_CONFLICT", "카드 표시 정보가 변경됐습니다.", 409
            )
    members = _rotation_members(context, rotation)
    active = _active_members(context)
    prepared = list(
        context.session.scalars(
            select(VaultMemberWrapping).where(
                VaultMemberWrapping.household_id == context.principal.household_id,
                VaultMemberWrapping.key_version == rotation.key_version,
                VaultMemberWrapping.state == "current",
            )
        )
    )
    if (
        len(members) != rotation.expected_member_count
        or {(row.member_id, row.source_membership_version) for row in members}
        != {(row.member_id, row.version) for row in active}
        or {row.member_id for row in members} != {row.member_id for row in prepared}
    ):
        raise DomainError(
            "VAULT_ROTATION_INCOMPLETE", "모든 구성원의 새 wrapping이 필요합니다.", 409
        )
    for member in active:
        _available_member(context, member.member_id)
    _check_row(context, rotation.key_version)
    _recovery_wrap(context, rotation.key_version)


def finalize_rotation(
    session,
    principal,
    rotation_id,
    payload,
    if_match,
    idempotency_key,
    *,
    step_up_token=None,
):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    rotation = _rotation(context, rotation_id)

    def execute():
        _require_staging(context, state, rotation)
        require_version(rotation, if_match)
        if payload.key_version != rotation.key_version:
            raise DomainError(
                "VAULT_KEY_VERSION_CONFLICT", "회전할 새 키 버전을 확인해 주세요.", 409
            )
        context.management(StepUpPurpose.VAULT_KEY_ROTATION, principal.household_id, step_up_token)
        _complete_snapshot(context, rotation)
        previous = session.scalar(
            select(VaultVersion)
            .where(
                VaultVersion.household_id == principal.household_id,
                VaultVersion.key_version == state.current_key_version,
            )
            .with_for_update()
        )
        if previous is None or previous.state != "current":
            raise DomainError("VAULT_STATE_CONFLICT", "현재 보관함 버전을 확인해 주세요.", 409)
        now = context.recheck()
        previous.state, previous.retired_at = "retired", now
        touch(previous, principal)
        # Release the partial-unique current slot before activating its successor.
        # Deferred lifecycle constraints verify the whole atomic switch at commit.
        session.flush([previous])
        before = rotation.version
        rotation.state, rotation.activated_at = "current", now
        touch(rotation, principal)
        state.current_key_version = rotation.key_version
        state.rotation_required = False
        touch(state, principal)
        session.flush()
        _audit(context, rotation, "vault_rotation", "confirm", ("state",), before)
        _audit(context, state, "vault", "update", ("current_key_version", "rotation_required"))
        return _reference(rotation, "vault_rotation")

    return _run(
        context,
        "vault.rotation.finalize",
        idempotency_key,
        {
            "rotation_id": str(rotation_id),
            "body": payload.model_dump(mode="json"),
            "if_match": if_match,
        },
        execute,
    )


def abort_rotation(
    session,
    principal,
    rotation_id,
    if_match,
    idempotency_key,
    *,
    step_up_token=None,
):
    context = _lock(session, principal)
    state = _state(context)
    _enrolled(context)
    rotation = _rotation(context, rotation_id)

    def execute():
        _require_staging(context, state, rotation)
        require_version(rotation, if_match)
        context.management(StepUpPurpose.VAULT_KEY_ROTATION, principal.household_id, step_up_token)
        before = rotation.version
        rotation.state, rotation.aborted_at = "aborted", context.recheck()
        touch(rotation, principal)
        touch(state, principal)
        session.flush()
        _audit(context, rotation, "vault_rotation", "archive", ("state",), before)
        return _reference(rotation, "vault_rotation")

    return _run(
        context,
        "vault.rotation.abort",
        idempotency_key,
        {"rotation_id": str(rotation_id), "if_match": if_match},
        execute,
    )
