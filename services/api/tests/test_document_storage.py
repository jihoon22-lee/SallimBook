"""Synthetic bytes and ephemeral keys only; actual AEAD/filesystem failure boundaries."""

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import ValidationError

from sallimbook.accounts.crypto import KeyRing
from sallimbook.core.errors import DomainError
from sallimbook.documents.schemas import DocumentCreate
from sallimbook.documents.storage import PrivateStore

CONTENT = b"Synthetic document fixture; no personal data."


def example(**changes):
    return SimpleNamespace(
        id=uuid4(),
        household_id=uuid4(),
        mime_type="application/pdf",
        size_bytes=len(CONTENT),
        checksum_sha256=hashlib.sha256(CONTENT).hexdigest(),
        **changes,
    )


def request(**changes):
    return (
        dict(
            original_name="합성.pdf",
            mime_type="application/pdf",
            size_bytes=100,
            checksum_sha256="0" * 64,
            target={"kind": "asset", "id": str(uuid4())},
            contains_no_card_data=True,
        )
        | changes
    )


@pytest.fixture
def keys():
    return KeyRing(1, {1: AESGCM.generate_key(bit_length=256)})


def saved(tmp_path, keys):
    row = example()
    store = PrivateStore(tmp_path / "private")
    envelope = store.put(row, CONTENT, keys)
    row.storage_key, row.encryption_key_version, row.nonce = (
        envelope.storage_key,
        envelope.key_version,
        envelope.nonce,
    )
    return store, row


def test_encrypted_private_roundtrip_and_randomization(tmp_path, keys):
    store, row = saved(tmp_path, keys)
    assert store.read(row, keys) == CONTENT
    path = store.path / row.storage_key
    assert CONTENT not in path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    assert store.path.stat().st_mode & 0o777 == 0o700
    other = store.put(row, CONTENT, keys)
    assert other.nonce != row.nonce and other.storage_key != row.storage_key
    store.remove(row.storage_key)
    store.remove(row.storage_key)
    with pytest.raises(DomainError):
        store.read(row, keys)


@pytest.mark.parametrize(
    "field,value",
    [
        ("household_id", uuid4()),
        ("id", uuid4()),
        ("mime_type", "image/png"),
        ("checksum_sha256", "1" * 64),
        ("size_bytes", len(CONTENT) + 1),
        ("encryption_key_version", 2),
        ("nonce", b"0" * 12),
    ],
)
def test_tampered_authenticated_metadata_fails(tmp_path, keys, field, value):
    store, row = saved(tmp_path, keys)
    setattr(row, field, value)
    with pytest.raises(DomainError) as exc:
        store.read(row, keys)
    assert exc.value.code == "DOCUMENT_STORAGE_UNAVAILABLE"


def test_wrong_key_and_ciphertext_corruption_fail(tmp_path, keys):
    store, row = saved(tmp_path, keys)
    wrong = KeyRing(1, {1: AESGCM.generate_key(bit_length=256)})
    with pytest.raises(DomainError):
        store.read(row, wrong)
    file = store.path / row.storage_key
    data = bytearray(file.read_bytes())
    data[-1] ^= 1
    file.write_bytes(data)
    with pytest.raises(DomainError):
        store.read(row, keys)


@pytest.mark.parametrize("case", ["root_symlink", "parent_symlink", "world_readable", "relative"])
def test_store_rejects_unsafe_directory(tmp_path, keys, case):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    if case == "root_symlink":
        path = tmp_path / "alias"
        path.symlink_to(private)
    elif case == "parent_symlink":
        path = tmp_path / "alias"
        path.symlink_to(private)
        path = path / "child"
    elif case == "world_readable":
        private.chmod(0o755)
        path = private
    else:
        path = Path("relative")
    with pytest.raises(DomainError):
        PrivateStore(path).put(example(), CONTENT, keys)


@pytest.mark.parametrize("case", ["symlink", "hardlink", "public", "fifo", "path"])
def test_file_type_permission_and_traversal_checks(tmp_path, keys, case):
    store, row = saved(tmp_path, keys)
    file = store.path / row.storage_key
    if case == "symlink":
        other = tmp_path / "original"
        file.rename(other)
        file.symlink_to(other)
    elif case == "hardlink":
        os.link(file, tmp_path / "other")
    elif case == "public":
        file.chmod(0o644)
    elif case == "fifo":
        file.unlink()
        os.mkfifo(file, mode=0o600)
    else:
        row.storage_key = "../private/" + row.storage_key
    with pytest.raises(DomainError):
        store.read(row, keys)


@pytest.mark.parametrize(
    "changes",
    [
        {"original_name": "../name.pdf"},
        {"original_name": "x\\name.pdf"},
        {"original_name": "x\n.pdf"},
        {"original_name": "x\u202e.pdf"},
        {"original_name": "x.html"},
        {"mime_type": "image/svg+xml"},
        {"contains_no_card_data": False},
        {"contains_no_card_data": 1},
        {"contains_no_card_data": "true"},
        {"size_bytes": True},
        {"target": {"kind": "card", "id": str(uuid4())}},
    ],
)
def test_metadata_rejects_unsafe_names_card_targets_and_coercion(changes):
    with pytest.raises(ValidationError):
        DocumentCreate.model_validate(request(**changes))


def test_filename_allows_korean_and_declared_extension():
    assert DocumentCreate.model_validate(request()).original_name == "합성.pdf"
