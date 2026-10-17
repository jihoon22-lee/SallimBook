"""Server field encryption, separate from the client-owned card vault.

Uses cryptography 50.0.2 AESGCM, including its authenticated 128-bit tag:
https://cryptography.io/en/50.0.2/hazmat/primitives/aead/
Keys come only from an explicitly configured private keyring file. Never log that file,
decoded keys, ciphertext, or plaintext. Python memory erasure is not guaranteed.
"""

import base64
import json
import os
import re
import secrets
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from sallimbook.core.errors import DomainError

MAX_KEYRING_BYTES = 16_384


def _unavailable() -> DomainError:
    return DomainError("FIELD_ENCRYPTION_UNAVAILABLE", "계좌번호 보호 설정을 확인해 주세요.", 503)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate keyring field")
        result[key] = value
    return result


def _read_private_file(path: Path) -> bytes:
    if not path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
        raise ValueError("An absolute keyring path is required")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory = os.open(path.anchor, directory_flags)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=directory,
        )
    finally:
        os.close(directory)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) not in {0o400, 0o600}
            or metadata.st_size > MAX_KEYRING_BYTES
        ):
            raise ValueError("Keyring file must be private and owned by the service")
        contents = stream.read(MAX_KEYRING_BYTES + 1)
        if len(contents) > MAX_KEYRING_BYTES:
            raise ValueError("Keyring file is too large")
        return contents


@dataclass(frozen=True)
class KeyRing:
    active_key_version: int
    keys: Mapping[int, bytes] = field(repr=False)

    @classmethod
    def load(cls, path: Path | str | None) -> KeyRing:
        if path is None or not str(path):
            raise _unavailable()
        try:
            document = json.loads(_read_private_file(Path(path)), object_pairs_hook=_unique_object)
            if (
                not isinstance(document, dict)
                or set(document) != {"schema_version", "active_key_version", "keys"}
                or type(document["schema_version"]) is not int
                or document["schema_version"] != 1
            ):
                raise ValueError("Unsupported keyring schema")
            active = document["active_key_version"]
            encoded = document["keys"]
            if type(active) is not int or not 1 <= active <= 2_147_483_647:
                raise ValueError("Invalid active key version")
            if not isinstance(encoded, dict) or not 1 <= len(encoded) <= 32:
                raise ValueError("Invalid keyring size")
            keys = {}
            for version, key in encoded.items():
                if (
                    not re.fullmatch(r"[1-9][0-9]{0,9}", version)
                    or int(version) > 2_147_483_647
                    or not isinstance(key, str)
                    or len(key) != 44
                ):
                    raise ValueError("Invalid key entry")
                decoded = base64.b64decode(key, validate=True)
                if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != key:
                    raise ValueError("Keys must be canonical base64 AES-256 keys")
                keys[int(version)] = decoded
            if active not in keys:
                raise ValueError("Active key is absent")
            return cls(active, MappingProxyType(keys))
        except OSError, ValueError, TypeError, UnicodeError, RecursionError:
            raise _unavailable() from None


@dataclass(frozen=True)
class SealedNumber:
    key_version: int
    nonce: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)


def _aad(household_id: UUID, account_id: UUID, key_version: int) -> bytes:
    return json.dumps(
        [
            "SallimBook/server-field/v1",
            str(household_id),
            str(account_id),
            "account_number",
            key_version,
        ],
        separators=(",", ":"),
    ).encode("utf-8")


def encrypt_number(
    keyring: KeyRing, household_id: UUID, account_id: UUID, number: str
) -> SealedNumber:
    version = keyring.active_key_version
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(keyring.keys[version]).encrypt(
        nonce, number.encode("utf-8"), _aad(household_id, account_id, version)
    )
    return SealedNumber(version, nonce, ciphertext)


def decrypt_number(
    keyring: KeyRing, household_id: UUID, account_id: UUID, sealed: SealedNumber
) -> str:
    key = keyring.keys.get(sealed.key_version)
    if key is None:
        raise _unavailable()
    try:
        if len(sealed.nonce) != 12 or not 21 <= len(sealed.ciphertext) <= 80:
            raise ValueError("Invalid number envelope")
        return (
            AESGCM(key)
            .decrypt(
                sealed.nonce, sealed.ciphertext, _aad(household_id, account_id, sealed.key_version)
            )
            .decode("utf-8")
        )
    except InvalidTag, ValueError, UnicodeError:
        raise DomainError("ACCOUNT_NUMBER_UNAVAILABLE", "계좌번호를 열 수 없습니다.", 503) from None
