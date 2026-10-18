"""Integrity evidence for an isolated restore, never permission to activate it."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from ops.backup import (
    OperationError,
    connect,
    digest,
    private_directory,
    private_file,
    publish_json,
    service_environment,
    table_counts,
)
from ops.recovery import check_ciphertexts

RECEIPT_NAME = "restore-integrity.json"
CHECKS = {"schema", "table_counts", "objects", "field_ciphertexts"}


def read_private_json(path, limit=2 * 1024 * 1024):
    path = private_file(path)
    if path.stat().st_size > limit:
        raise OperationError("Private evidence exceeds its size limit")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise OperationError("Private evidence must be an object")
    return value


def verify_restored_integrity(service_file, directory, keyring_file, expected_archive_sha256):
    """Read actual restored rows and authenticated ciphertexts before publishing evidence.

    Restored auth rows are never enabled, reset or used for a login here. No API
    or tailnet node may be attached to this isolated PostgreSQL network.
    """
    directory = private_directory(directory)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_archive_sha256):
        raise OperationError("An independently recorded archive digest is required")
    private_file(directory / "QUARANTINE")
    private_file(keyring_file)
    receipt_path = directory / "restore.json"
    manifest_path = directory / "backup-manifest.json"
    restored = read_private_json(receipt_path, 16384)
    manifest = read_private_json(manifest_path)
    original_hashes = (digest(receipt_path), digest(manifest_path))
    env, database = service_environment(service_file, restore=True)
    try:
        restored_at = datetime.fromisoformat(restored["restored_at"])
        valid_time = restored_at.tzinfo is not None and restored_at <= datetime.now(UTC)
    except KeyError, TypeError, ValueError:
        valid_time = False
    if (
        restored.get("status") != "quarantined"
        or restored.get("database") != database
        or restored.get("backup_id") != manifest.get("id")
        or restored.get("archive_sha256") != expected_archive_sha256
        or manifest.get("format") != 1
        or not valid_time
    ):
        raise OperationError("Restore identity or time does not match its evidence")
    destination = directory / RECEIPT_NAME
    if destination.exists() or destination.is_symlink():
        raise OperationError("Restore integrity evidence already exists")
    objects = private_directory(directory / "objects")
    inventory = manifest.get("objects")
    if not isinstance(inventory, dict):
        raise OperationError("Restored object inventory is missing")
    actual = {path.name for path in objects.iterdir()}
    if actual != set(inventory):
        raise OperationError("Restored object inventory differs")
    for name, expected in inventory.items():
        if not re.fullmatch(r"[0-9a-f]{32}\.sbdoc", name):
            raise OperationError("Restored object identity is invalid")
        path = private_file(objects / name)
        if path.stat().st_size != expected["bytes"] or digest(path) != expected["sha256"]:
            raise OperationError("Restored object checksum differs")
    with connect(env) as connection:
        connection.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        connection.execute("SET LOCAL statement_timeout = '120s'")
        if connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] != (
            manifest.get("schema_revision")
        ):
            raise OperationError("Restored schema differs")
        if table_counts(connection) != manifest.get("table_counts"):
            raise OperationError("Restored table inventory differs")
        # Authenticated decryptions happen in this process only; discard counts
        # and plaintext. A success result contains no customer identifiers/data.
        check_ciphertexts(connection, objects, Path(keyring_file))
        connection.execute("COMMIT")
    if original_hashes != (digest(receipt_path), digest(manifest_path)):
        raise OperationError("Restore evidence changed during verification")
    result = {
        "format": 1,
        "status": "restored-integrity-verified",
        "backup_id": restored["backup_id"],
        "archive_sha256": expected_archive_sha256,
        "restored_at": restored["restored_at"],
        "verified_at": datetime.now(UTC).isoformat(),
        "restore_manifest_sha256": original_hashes[1],
        "restore_receipt_sha256": original_hashes[0],
        "checks": dict.fromkeys(sorted(CHECKS), True),
    }
    publish_json(destination, result)
    return result
