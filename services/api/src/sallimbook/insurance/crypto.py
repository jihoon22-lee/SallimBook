"""AES-GCM server protection for policy identifiers, separate from card-vault keys.

Pinned primitive: https://cryptography.io/en/50.0.2/hazmat/primitives/aead/#aesgcm
The existing private keyring loader is reused; AAD separates policy and account fields.
"""

import json
import secrets
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from sallimbook.accounts.crypto import KeyRing, SealedNumber
from sallimbook.core.errors import DomainError


def _aad(household_id: UUID, policy_id: UUID, version: int) -> bytes:
    return json.dumps(
        ["SallimBook/server-field/v1", str(household_id), str(policy_id), "policy_number", version],
        separators=(",", ":"),
    ).encode("utf-8")


def encrypt_number(
    keyring: KeyRing, household_id: UUID, policy_id: UUID, number: str
) -> SealedNumber:
    version = keyring.active_key_version
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(keyring.keys[version]).encrypt(
        nonce, number.encode("utf-8"), _aad(household_id, policy_id, version)
    )
    return SealedNumber(version, nonce, ciphertext)


def decrypt_number(
    keyring: KeyRing, household_id: UUID, policy_id: UUID, sealed: SealedNumber
) -> str:
    key = keyring.keys.get(sealed.key_version)
    if key is None:
        raise DomainError(
            "FIELD_ENCRYPTION_UNAVAILABLE", "증권번호 보호 설정을 확인해 주세요.", 503
        )
    try:
        if len(sealed.nonce) != 12 or not 21 <= len(sealed.ciphertext) <= 80:
            raise ValueError("Invalid envelope")
        return (
            AESGCM(key)
            .decrypt(
                sealed.nonce, sealed.ciphertext, _aad(household_id, policy_id, sealed.key_version)
            )
            .decode("utf-8")
        )
    except InvalidTag, ValueError, UnicodeError:
        raise DomainError("POLICY_NUMBER_UNAVAILABLE", "증권번호를 열 수 없습니다.", 503) from None
