"""Bounded opaque persistence, with no cryptographic key or plaintext handling."""

import base64

from sqlalchemy import func, select

from sallimbook.core.errors import DomainError
from sallimbook.identity import service as identity
from sallimbook.vault.formats import MAX_SAFE_INTEGER
from sallimbook.vault.models import (
    CardSecretEnvelope,
    VaultKeyCheck,
    VaultMemberWrapping,
    VaultNonceReservation,
    VaultRecoveryWrapping,
)
from sallimbook.vault.schemas import (
    CardSecretResponse,
    KeyCheckResponse,
    MemberWrappingResponse,
    RecoveryWrappingResponse,
    decode_opaque,
)


def actor_fields(principal):
    return {
        "household_id": principal.household_id,
        "created_by_member_id": principal.member_id,
        "updated_by_member_id": principal.member_id,
    }


def touch(row, principal):
    if row.version >= MAX_SAFE_INTEGER:
        raise DomainError("VAULT_VERSION_EXHAUSTED", "보관함 버전을 확인해 주세요.", 409)
    row.version += 1
    row.updated_by_member_id = principal.member_id
    row.updated_at = identity.utcnow()


def encode_opaque(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def key_check_response(row):
    return KeyCheckResponse(
        household_id=row.household_id,
        key_version=row.key_version,
        format_version=row.format_version,
        nonce=encode_opaque(row.nonce),
        ciphertext=encode_opaque(row.ciphertext),
    )


def member_wrapping_response(row):
    return MemberWrappingResponse(
        id=row.id,
        household_id=row.household_id,
        member_id=row.member_id,
        key_version=row.key_version,
        format_version=row.format_version,
        generation=row.generation,
        kdf=row.kdf,
        iterations=row.iterations,
        salt=encode_opaque(row.salt),
        nonce=encode_opaque(row.nonce),
        wrapped_hvk=encode_opaque(row.wrapped_hvk),
        version=row.version,
    )


def recovery_wrapping_response(row):
    return RecoveryWrappingResponse(
        id=row.id,
        household_id=row.household_id,
        key_version=row.key_version,
        format_version=row.format_version,
        generation=row.generation,
        kdf=row.kdf,
        salt=encode_opaque(row.salt),
        nonce=encode_opaque(row.nonce),
        wrapped_hvk=encode_opaque(row.wrapped_hvk),
        version=row.version,
    )


def card_secret_response(row, card):
    if row.ciphertext is None or row.purged_at is not None:
        raise DomainError("VAULT_SECRET_NOT_SET", "등록된 카드 비밀이 없습니다.", 404)
    return CardSecretResponse(
        id=row.id,
        household_id=row.household_id,
        card_id=row.card_id,
        key_version=row.key_version,
        format_version=row.format_version,
        payload_schema_version=row.payload_schema_version,
        last_four=row.last_four,
        nonce=encode_opaque(row.nonce),
        ciphertext=encode_opaque(row.ciphertext),
        revision=row.revision,
        version=row.version,
        card_version=card.version,
    )


def _nonce(session, principal, payload, purpose):
    nonce = decode_opaque(payload.nonce)
    if (
        session.get(VaultNonceReservation, (principal.household_id, payload.key_version, nonce))
        is not None
    ):
        raise DomainError("VAULT_NONCE_REUSED", "새 암호화 nonce로 다시 준비해 주세요.", 409)
    reservation = VaultNonceReservation(
        household_id=principal.household_id,
        key_version=payload.key_version,
        nonce=nonce,
        purpose=purpose,
    )
    session.add(reservation)
    # FK ordering has no ORM relationships; materialize the reservation before its child.
    session.flush()
    return nonce


def _fresh_salt(session, principal, model, salt):
    raw = decode_opaque(salt)
    if (
        session.scalar(
            select(model.id).where(model.household_id == principal.household_id, model.salt == raw)
        )
        is not None
    ):
        raise DomainError("VAULT_SALT_REUSED", "새 salt로 wrapping을 다시 준비해 주세요.", 409)
    return raw


def member_generation(session, principal, member_id, key_version):
    previous = (
        session.scalar(
            select(func.max(VaultMemberWrapping.generation)).where(
                VaultMemberWrapping.household_id == principal.household_id,
                VaultMemberWrapping.member_id == member_id,
                VaultMemberWrapping.key_version == key_version,
            )
        )
        or 0
    )
    if previous >= MAX_SAFE_INTEGER:
        raise DomainError("VAULT_VERSION_EXHAUSTED", "보관함 버전을 확인해 주세요.", 409)
    return previous + 1


def recovery_generation(session, principal, key_version):
    previous = (
        session.scalar(
            select(func.max(VaultRecoveryWrapping.generation)).where(
                VaultRecoveryWrapping.household_id == principal.household_id,
                VaultRecoveryWrapping.key_version == key_version,
            )
        )
        or 0
    )
    if previous >= MAX_SAFE_INTEGER:
        raise DomainError("VAULT_VERSION_EXHAUSTED", "보관함 버전을 확인해 주세요.", 409)
    return previous + 1


def store_key_check(session, principal, payload):
    row = VaultKeyCheck(
        **actor_fields(principal),
        key_version=payload.key_version,
        format_version=payload.format_version,
        purpose="key_check",
        nonce=_nonce(session, principal, payload, "key_check"),
        ciphertext=decode_opaque(payload.ciphertext),
    )
    session.add(row)
    session.flush()
    return row


def store_member_wrapping(session, principal, payload, *, state):
    expected = member_generation(session, principal, payload.member_id, payload.key_version)
    if payload.generation != expected:
        raise DomainError("VAULT_GENERATION_CONFLICT", "최신 wrapping 버전을 확인해 주세요.", 409)
    salt = _fresh_salt(session, principal, VaultMemberWrapping, payload.salt)
    row = VaultMemberWrapping(
        **actor_fields(principal),
        member_id=payload.member_id,
        key_version=payload.key_version,
        format_version=payload.format_version,
        purpose="member",
        generation=payload.generation,
        state=state,
        kdf=payload.kdf,
        iterations=payload.iterations,
        salt=salt,
        nonce=_nonce(session, principal, payload, "member"),
        wrapped_hvk=decode_opaque(payload.wrapped_hvk),
    )
    session.add(row)
    session.flush()
    return row


def store_recovery_wrapping(session, principal, payload):
    if payload.generation != recovery_generation(session, principal, payload.key_version):
        raise DomainError("VAULT_GENERATION_CONFLICT", "최신 복구 버전을 확인해 주세요.", 409)
    salt = _fresh_salt(session, principal, VaultRecoveryWrapping, payload.salt)
    row = VaultRecoveryWrapping(
        **actor_fields(principal),
        key_version=payload.key_version,
        format_version=payload.format_version,
        purpose="recovery",
        generation=payload.generation,
        kdf=payload.kdf,
        salt=salt,
        nonce=_nonce(session, principal, payload, "recovery"),
        wrapped_hvk=decode_opaque(payload.wrapped_hvk),
        is_current=True,
    )
    session.add(row)
    session.flush()
    return row


def store_card_envelope(session, principal, card, payload):
    previous = (
        session.scalar(
            select(func.max(CardSecretEnvelope.revision)).where(
                CardSecretEnvelope.household_id == principal.household_id,
                CardSecretEnvelope.card_id == card.id,
                CardSecretEnvelope.key_version == payload.key_version,
            )
        )
        or 0
    )
    if previous >= MAX_SAFE_INTEGER:
        raise DomainError("VAULT_VERSION_EXHAUSTED", "보관함 버전을 확인해 주세요.", 409)
    row = CardSecretEnvelope(
        **actor_fields(principal),
        card_id=card.id,
        key_version=payload.key_version,
        format_version=payload.format_version,
        purpose="card",
        revision=previous + 1,
        payload_schema_version=payload.payload_schema_version,
        last_four=payload.last_four,
        nonce=_nonce(session, principal, payload, "card"),
        ciphertext=decode_opaque(payload.ciphertext),
        is_current=True,
    )
    session.add(row)
    session.flush()
    return row
