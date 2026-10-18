"""Authenticated private bytes; disk contains only ciphertext under opaque random names.

HKDF/AESGCM use cryptography 50.0.2. The document subkey is purpose-separated from
account/policy numbers and is never derived from a login credential or vault key.
"""

import hashlib
import json
import os
import re
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from sallimbook.accounts.crypto import KeyRing
from sallimbook.core.errors import DomainError
from sallimbook.documents.models import MAX_DOCUMENT_BYTES

STORAGE_NAME = re.compile(r"[0-9a-f]{32}\.sbdoc")


def unavailable():
    return DomainError("DOCUMENT_STORAGE_UNAVAILABLE", "첨부파일 저장소를 확인해 주세요.", 503)


def load_keys(path):
    try:
        return KeyRing.load(path)
    except DomainError:
        raise unavailable() from None


def _key(keyring, version):
    key = keyring.keys.get(version)
    if key is None:
        raise unavailable()
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"SallimBook/server-document/v1",
        info=b"AES-256-GCM/content",
    ).derive(key)


def _aad(row, version):
    return json.dumps(
        [
            "SallimBook/server-document/v1",
            str(row.household_id),
            str(row.id),
            version,
            row.mime_type,
            row.size_bytes,
            row.checksum_sha256,
        ],
        separators=(",", ":"),
    ).encode("ascii")


@dataclass(frozen=True)
class DocumentEnvelope:
    storage_key: str
    key_version: int
    nonce: bytes = field(repr=False)


class PrivateStore:
    def __init__(self, path):
        self.path = Path(path) if path is not None else None

    @contextmanager
    def directory(self):
        path = self.path
        repository = Path(__file__).absolute().parents[5]
        if (
            path is None
            or not path.is_absolute()
            or ".." in path.parts
            or len(path.parts) < 3
            or path.is_relative_to(repository)
        ):
            raise unavailable()
        directory = None
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            directory = os.open(path.anchor, flags)
            for index, part in enumerate(path.parts[1:], start=1):
                if index == len(path.parts) - 1:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=directory)
                    except FileExistsError:
                        pass
                child = os.open(part, flags, dir_fd=directory)
                os.close(directory)
                directory = child
            metadata = os.fstat(directory)
            if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
                raise unavailable()
            yield directory
        except OSError:
            raise unavailable() from None
        finally:
            if directory is not None:
                os.close(directory)

    def put(self, row, content, keyring, *, storage_key=None):
        if (
            not 1 <= len(content) <= MAX_DOCUMENT_BYTES
            or len(content) != row.size_bytes
            or hashlib.sha256(content).hexdigest() != row.checksum_sha256
        ):
            raise DomainError(
                "DOCUMENT_CONTENT_MISMATCH", "첨부파일 크기와 해시를 확인해 주세요.", 422
            )
        version = keyring.active_key_version
        nonce = secrets.token_bytes(12)
        encrypted = AESGCM(_key(keyring, version)).encrypt(nonce, content, _aad(row, version))
        name = storage_key if storage_key is not None else uuid4().hex + ".sbdoc"
        if not isinstance(name, str) or not STORAGE_NAME.fullmatch(name):
            raise unavailable()
        with self.directory() as directory:
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory,
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(encrypted)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fsync(directory)
            except BaseException:
                os.unlink(name, dir_fd=directory)
                raise
        return DocumentEnvelope(name, version, nonce)

    def read(self, row, keyring):
        name = row.storage_key
        if not isinstance(name, str) or not STORAGE_NAME.fullmatch(name):
            raise unavailable()
        with self.directory() as directory:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=directory,
            )
            with os.fdopen(descriptor, "rb") as stream:
                metadata = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o600
                    or metadata.st_nlink != 1
                    or metadata.st_size != row.size_bytes + 16
                    or not 1 <= row.size_bytes <= MAX_DOCUMENT_BYTES
                ):
                    raise unavailable()
                encrypted = stream.read(MAX_DOCUMENT_BYTES + 17)
        try:
            if row.nonce is None or len(row.nonce) != 12:
                raise ValueError("Invalid envelope")
            content = AESGCM(_key(keyring, row.encryption_key_version)).decrypt(
                row.nonce, encrypted, _aad(row, row.encryption_key_version)
            )
            if (
                len(content) != row.size_bytes
                or hashlib.sha256(content).hexdigest() != row.checksum_sha256
            ):
                raise ValueError("Invalid content")
            return content
        except InvalidTag, ValueError, TypeError:
            raise unavailable() from None

    def remove(self, name):
        if not isinstance(name, str) or not STORAGE_NAME.fullmatch(name):
            raise unavailable()
        with self.directory() as directory:
            try:
                metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                return
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1
            ):
                raise unavailable()
            os.unlink(name, dir_fd=directory)
            os.fsync(directory)
