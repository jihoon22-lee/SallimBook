"""UID 10001 worker mounted from a separate, verified operator source archive.

The deployed image's ops.backup/recovery remain the app-source versions. Only
this operator helper and restore_check are loaded from the read-only mount.
"""

import importlib.util
import json
import os
import re
import secrets
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from ops import backup


def read_json(path, limit=65536, *, private=True):
    path = backup.private_file(path) if private else Path(path)
    if path.stat().st_size > limit:
        raise backup.OperationError("Worker input too large")
    result = json.loads(path.read_text())
    if not isinstance(result, dict):
        raise backup.OperationError("Worker input must be an object")
    return result


def verify_operator_bundle(root, expected_revision):
    root = Path(root)
    value = read_json(root / "operator-source.json", private=False)
    if value.get("source_commit") != expected_revision or set(value) != {"source_commit", "files"}:
        raise backup.OperationError("Operator source identity differs")
    if set(value["files"]) != {"automation_worker.py", "restore_check.py"}:
        raise backup.OperationError("Unexpected operator helpers")
    for name, digest in value["files"].items():
        if backup.digest(root / name) != digest:
            raise backup.OperationError("Operator helper checksum differs")


def verify_image_source(expected_revision):
    actual = read_json("/usr/share/sallimbook/source-revision.json", private=False)
    if actual != {"image_role": "api", "source_commit": expected_revision}:
        raise backup.OperationError("Actual image source identity differs")


def verify_candidate_deployment(job, path=Path("/run/candidate-deployment.json")):
    # Use the deployed image's policy, just as its ops.backup will. An older app
    # that cannot back up a local-ID manifest must fail before service promotion.
    from ops.deploy import validate

    candidate = validate(read_json(path, private=False))
    if candidate["source_commit"] != job["app_source_commit"]:
        raise backup.OperationError("Candidate deployment source differs")
    return {"status": "image-source-verified", "source_commit": job["app_source_commit"]}


def validate_service_file(path, database="sallimbook_prod"):
    """Both ConfigParser and libpq must accept the same exact key=value file."""
    path = backup.private_file(path)
    if path.stat().st_size > 16384:
        raise backup.OperationError("Backup service file too large")
    lines = path.read_text().splitlines()
    values = {}
    if not lines or lines[0] != "[sallimbook]":
        raise backup.OperationError("One dedicated backup service section required")
    for line in lines[1:]:
        if not line:
            continue
        key, separator, value = line.partition("=")
        if (
            not separator
            or key != key.strip()
            or value != value.strip()
            or key in values
            or not value
            or any(ord(char) < 32 for char in value)
        ):
            raise backup.OperationError("Service fields require exact key=value serialization")
        values[key] = value
    required = {"host", "port", "dbname", "user", "password", "sslmode"}
    if (
        not required.issubset(values)
        or set(values) - required - {"sslmode"}
        or values["host"] != "db"
        or values["port"] != "5432"
        or values["dbname"] != database
        or values["user"] != "sallimbook_app"
        or values.get("sslmode", "disable") != "disable"
    ):
        raise backup.OperationError("Dedicated runtime backup service required")
    return path


def verify_backup_receipt(directory, value, *, check_hash=True):
    directory = backup.private_directory(directory)
    keys = {"format", "id", "file", "sha256", "bytes", "completed_at"}
    try:
        identifier = str(UUID(value["id"]))
        completed = datetime.fromisoformat(value["completed_at"])
        valid = (
            set(value) == keys
            and value["format"] == 1
            and identifier == value["id"]
            and value["file"] == identifier + ".tar.age"
            and re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
            and type(value["bytes"]) is int
            and 1 <= value["bytes"] <= backup.MAX_ARCHIVE
            and completed.tzinfo is not None
            and completed <= datetime.now(UTC) + timedelta(minutes=5)
        )
    except ValueError, TypeError, KeyError:
        valid = False
    if not valid:
        raise backup.OperationError("Invalid completed backup evidence")
    receipt = read_json(directory / (identifier + ".complete.json"))
    archive = backup.private_file(directory / value["file"])
    if receipt != value or archive.stat().st_size != value["bytes"]:
        raise backup.OperationError("Backup completion record does not match its archive")
    if check_hash and backup.digest(archive) != value["sha256"]:
        raise backup.OperationError("Backup archive checksum differs")
    return dict(value)


def make_backup(job):
    validate_service_file("/run/private/backup-service.conf")
    recipient_path = backup.private_file("/run/private/backup-recipient.txt")
    recipient = recipient_path.read_text().removesuffix("\n")
    if not re.fullmatch(r"age1[0-9a-z]{58}", recipient):
        raise backup.OperationError("One private-file recipient required")
    documents, destination = Path("/srv/documents"), Path("/srv/backups")
    for path in (documents, destination):
        backup.private_directory(path)
    if (documents.stat().st_dev, documents.stat().st_ino) == (
        destination.stat().st_dev,
        destination.stat().st_ino,
    ):
        raise backup.OperationError("Document and backup storage must differ")
    result = backup.backup(
        Path("/run/private/backup-service.conf"),
        documents,
        destination,
        recipient,
        job["app_source_commit"],
        Path("/run/deployment.json"),
    )
    result = verify_backup_receipt(destination, result)
    backup.publish_json(destination / (".automation-" + job["run_id"] + ".json"), result)
    return {"status": "backup-verified", "backup": result}


def check_backup(job, directory=Path("/srv/backups")):
    directory = backup.private_directory(directory)
    expected = job.get("backup")
    marker = directory / (".automation-" + job["run_id"] + ".json")
    if expected is None:
        if not marker.exists() and not marker.is_symlink():
            return {"status": "backup-result-absent"}
        expected = read_json(marker)
    value = verify_backup_receipt(directory, expected, check_hash=job["action"] != "backup-stat")
    return {
        "status": "backup-verified" if job["action"] != "backup-stat" else "backup-present",
        "backup": value,
        "disk_free_bytes": shutil.disk_usage(directory).free,
    }


def data_storage(directory=Path("/srv/backups"), documents=Path("/srv/documents")):
    """Free space of the backup and attachment filesystems; needs no backup receipt."""
    directory = backup.private_directory(directory)
    documents = backup.private_directory(documents)
    return {
        "status": "data-storage-checked",
        "disk_free_bytes": shutil.disk_usage(directory).free,
        "documents_disk_free_bytes": shutil.disk_usage(documents).free,
    }


def acknowledge_backup(job, directory=Path("/srv/backups")):
    directory = backup.private_directory(directory)
    marker = directory / (".automation-" + job["run_id"] + ".json")
    value = verify_backup_receipt(directory, job["backup"], check_hash=False)
    if read_json(marker) != value:
        raise backup.OperationError("Backup run evidence differs")
    marker.unlink()
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {"status": "backup-acknowledged"}


def scanner_report():
    from sallimbook.documents.validation import _scanner_command

    path = "/run/scanner/clamd.sock"
    if _scanner_command(path, b"zPING\0") != b"PONG":
        raise backup.OperationError("Scanner unavailable")
    version = _scanner_command(path, b"zVERSIONCOMMANDS\0")
    prefix, separator, commands = version.partition(b"| COMMANDS:")
    matched = re.fullmatch(rb"ClamAV (1\.4\.6)/([1-9][0-9]{0,9})/([^|\r\n]+)", prefix.strip())
    if not matched or not separator or b"INSTREAM" not in commands.split():
        raise backup.OperationError("Scanner protocol differs")
    built = datetime.strptime(matched[3].strip().decode("ascii"), "%a %b %d %H:%M:%S %Y").replace(
        tzinfo=UTC
    )
    age = (datetime.now(UTC) - built).total_seconds()
    return {
        "status": "scanner-checked",
        "built_at": built.isoformat(),
        "age_seconds": int(age),
        "fresh": -300 <= age <= 7 * 86400,
        "refresh_due": age >= 4 * 86400,
    }


def prepare_restore(job, root=Path("/srv/restores")):
    root = backup.private_directory(root)
    directory = root / job["run_id"]
    directory.mkdir(mode=0o700)
    database = "sallimbook_" + job["run_id"].replace("-", "") + "_restorecheck"
    password = secrets.token_urlsafe(36)
    for name, content in {
        "db-password": password,
        "service.conf": "[sallimbook]\nhost=restore-db\nport=5432\nuser=sallimbook_restore\n"
        "dbname=" + database + "\npassword=" + password + "\nsslmode=disable\n",
    }.items():
        with (directory / name).open("x") as stream:
            stream.write(content)
        (directory / name).chmod(0o600)
    return {"status": "restore-prepared"}


def create_restore_database(service):
    from psycopg import sql

    env, database = backup.service_environment(service, restore=True)
    # The stock entrypoint creates its default DB from template1. Create the
    # actual quarantine target explicitly from pristine template0 instead.
    admin = service.parent / "admin-service.conf"
    with admin.open("x") as stream:
        stream.write(service.read_text().replace("dbname=" + database + "\n", "dbname=postgres\n"))
    admin.chmod(0o600)
    try:
        with backup.connect({**env, "PGSERVICEFILE": str(admin)}) as connection:
            connection.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database))
            )
    finally:
        admin.unlink(missing_ok=True)


def restore_check(job):
    value = verify_backup_receipt("/srv/backups", job["backup"])
    root = backup.private_directory("/srv/restores")
    identity = backup.private_file("/run/private/restore-identity.txt")
    backup.private_file("/run/private/field-keyring.json")
    prepared = backup.private_directory(root / job["run_id"])
    service = backup.private_file(prepared / "service.conf")
    create_restore_database(service)
    directory = prepared / "check"
    backup.restore(
        Path("/srv/backups") / value["file"], identity, service, directory, value["sha256"]
    )
    spec = importlib.util.spec_from_file_location(
        "sallimbook_operator_restore_check", Path(__file__).with_name("restore_check.py")
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    result = helper.verify_restored_integrity(
        service, directory, Path("/run/private/field-keyring.json"), value["sha256"]
    )
    return {"status": "restored-integrity-verified", "integrity": result}


def run(job):
    if os.geteuid() != 10001:
        raise backup.OperationError("Backup worker must run as UID 10001")
    if str(UUID(job["run_id"])) != job["run_id"]:
        raise backup.OperationError("Invalid automation run identity")
    verify_operator_bundle(Path(__file__).parent, job["operator_source_commit"])
    verify_image_source(job["app_source_commit"])
    action = job["action"]
    if action == "storage":
        # The image root is backed by the daemon image filesystem, even when
        # Docker Desktop keeps that filesystem outside the host mount namespace.
        return {"status": "storage-checked", "disk_free_bytes": shutil.disk_usage("/").free}
    if action == "data-storage":
        return data_storage()
    if action == "image-check":
        return verify_candidate_deployment(job)
    if action == "backup":
        return make_backup(job)
    if action in {"backup-stat", "backup-result", "backup-verify"}:
        return check_backup(job)
    if action == "backup-ack":
        return acknowledge_backup(job)
    if action == "scanner":
        return scanner_report()
    if action == "restore-prepare":
        return prepare_restore(job)
    if action == "restore-check":
        return restore_check(job)
    raise backup.OperationError("Unknown worker action")


def main():
    os.umask(0o077)
    try:
        # The mounted job has no credentials; the host keeps its containing dir
        # private while this exact read-only file is readable by container UID.
        result = run(read_json("/run/job.json", private=False))
    except Exception:
        print(json.dumps({"status": "failed", "code": "WORKER_FAILED"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
