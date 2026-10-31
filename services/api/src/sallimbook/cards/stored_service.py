"""Direct-entry card storage: authenticated household session, no additional password."""

from datetime import UTC, datetime

from sallimbook.accounts.crypto import KeyRing, SealedNumber
from sallimbook.assets.locking import lock_asset_scope
from sallimbook.cards.models import Card, CardStoredDetails
from sallimbook.cards.schemas import CardStoredDetailsResponse
from sallimbook.cards.service import card_response, has_current_secret
from sallimbook.cards.stored_crypto import checksum_valid, decrypt_details, encrypt_details
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.identity import service as identity


def _lock(session, principal, card_id):
    auth, devices = identity.lock_session_devices(session, principal)
    lock_asset_scope(session, principal)
    card = scoped_entity(session, Card, card_id, principal, for_update=True)

    def recheck():
        return identity.validate_locked_session(principal, auth, devices[principal.device_id])

    recheck()
    return card, recheck


def _stored(session, card):
    return session.get(CardStoredDetails, (card.household_id, card.id))


def _touch(card, principal):
    before = card.version
    card.version += 1
    card.updated_by_member_id = principal.member_id
    card.updated_at = datetime.now(UTC)
    return before


def _audit(session, principal, card, action, before, request_id):
    record_event(
        session,
        principal,
        entity_type="card",
        entity_id=card.id,
        action=action,
        before_version=before,
        after_version=card.version,
        changed_fields=("stored_details",),
        request_id=request_id,
    )


def put_details(session, principal, card_id, payload, if_match, key_file, request_id=None):
    card, recheck = _lock(session, principal, card_id)
    require_version(card, if_match)
    if has_current_secret(session, card):
        raise DomainError(
            "CARD_SECRET_PROTECTED", "기존 보관함의 카드 정보를 먼저 삭제해 주세요.", 409
        )
    recheck()
    sealed = encrypt_details(KeyRing.load(key_file), card.household_id, card.id, payload)
    recheck()
    row = _stored(session, card)
    if row is None:
        row = CardStoredDetails(household_id=card.household_id, card_id=card.id)
        session.add(row)
    row.key_version, row.nonce, row.ciphertext = sealed.key_version, sealed.nonce, sealed.ciphertext
    before = _touch(card, principal)
    card.last_four = payload.pan.get_secret_value()[-4:]
    _audit(session, principal, card, "update", before, request_id)
    session.flush()
    result = card_response(session, card)
    recheck()
    session.commit()
    return result


def reveal_details(session, principal, card_id, key_file, request_id=None):
    card, recheck = _lock(session, principal, card_id)
    row = _stored(session, card)
    if row is None:
        raise DomainError("CARD_DETAILS_NOT_SET", "등록된 카드 정보가 없습니다.", 404)
    recheck()
    payload = decrypt_details(
        KeyRing.load(key_file),
        card.household_id,
        card.id,
        SealedNumber(row.key_version, row.nonce, row.ciphertext),
    )
    recheck()
    result = CardStoredDetailsResponse(
        card_id=card.id,
        household_id=card.household_id,
        pan=payload.pan.get_secret_value(),
        expiry_year=payload.expiry_year,
        expiry_month=payload.expiry_month,
        cvc=payload.cvc.get_secret_value() if payload.cvc is not None else None,
        checksum_valid=checksum_valid(payload.pan.get_secret_value()),
        version=card.version,
    )
    _audit(session, principal, card, "reveal", card.version, request_id)
    session.flush()
    recheck()
    session.commit()
    return result


def delete_details(session, principal, card_id, if_match, request_id=None):
    card, recheck = _lock(session, principal, card_id)
    require_version(card, if_match)
    row = _stored(session, card)
    if row is None:
        raise DomainError("CARD_DETAILS_NOT_SET", "등록된 카드 정보가 없습니다.", 404)
    session.delete(row)
    before = _touch(card, principal)
    _audit(session, principal, card, "update", before, request_id)
    session.flush()
    recheck()
    session.commit()
