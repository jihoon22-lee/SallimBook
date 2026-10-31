"""Server-owned AES-GCM card bundle, distinct from client vault envelopes.

Fixed-size padding avoids exposing CVC presence or PAN length through storage size.
Only the existing server keyring loads keys; AAD binds household, card, field and version.
"""

import json
import secrets
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import ValidationError

from sallimbook.accounts.crypto import KeyRing, SealedNumber
from sallimbook.cards.schemas import CardStoredDetailsInput
from sallimbook.core.errors import DomainError


def _aad(household_id: UUID, card_id: UUID, version: int) -> bytes:
    return json.dumps(
        [
            "SallimBook/server-field/v1",
            str(household_id),
            str(card_id),
            "card_stored_details",
            version,
        ],
        separators=(",", ":"),
    ).encode("ascii")


def checksum_valid(pan: str) -> bool:
    digits = [int(value) for value in reversed(pan)]
    return (
        sum(
            value if i % 2 == 0 else value * 2 - (9 if value > 4 else 0)
            for i, value in enumerate(digits)
        )
        % 10
        == 0
    )


def encrypt_details(
    keyring: KeyRing, household_id: UUID, card_id: UUID, payload: CardStoredDetailsInput
) -> SealedNumber:
    raw = (
        json.dumps(
            {
                "pan": payload.pan.get_secret_value(),
                "expiry_year": payload.expiry_year,
                "expiry_month": payload.expiry_month,
                "cvc": payload.cvc.get_secret_value() if payload.cvc is not None else None,
            },
            separators=(",", ":"),
        )
        .encode("ascii")
        .ljust(128, b" ")
    )
    version = keyring.active_key_version
    nonce = secrets.token_bytes(12)
    return SealedNumber(
        version,
        nonce,
        AESGCM(keyring.keys[version]).encrypt(nonce, raw, _aad(household_id, card_id, version)),
    )


def decrypt_details(
    keyring: KeyRing, household_id: UUID, card_id: UUID, sealed: SealedNumber
) -> CardStoredDetailsInput:
    try:
        if len(sealed.nonce) != 12 or len(sealed.ciphertext) != 144:
            raise ValueError("Invalid envelope")
        raw = AESGCM(keyring.keys[sealed.key_version]).decrypt(
            sealed.nonce, sealed.ciphertext, _aad(household_id, card_id, sealed.key_version)
        )
        return CardStoredDetailsInput.model_validate_json(raw)
    except InvalidTag, ValueError, KeyError, ValidationError:
        raise DomainError("CARD_DETAILS_UNAVAILABLE", "카드 정보를 열 수 없습니다.", 503) from None
