"""Consistent encrypted backups and quarantine-only restores; no service startup."""

import argparse
import configparser
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

STORAGE_BARRIER = 91544042505043
OBJECT_NAME = re.compile(r"[0-9a-f]{32}\.sbdoc")
MAX_OBJECT = 20 * 1024 * 1024 + 16
MAX_ARCHIVE = 8 * 1024 * 1024 * 1024
MAX_ENTRIES = 10000
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
TOOLS = {
    "age": "v1.3.2",
    "pg_dump": "pg_dump (PostgreSQL) 18.6 (Debian 18.6-1.pgdg12+2)",
    "pg_restore": "pg_restore (PostgreSQL) 18.6 (Debian 18.6-1.pgdg12+2)",
}


class OperationError(Exception):
    """Only fixed, non-sensitive messages are printed by the CLI."""


def private_file(path):
    path = Path(path).absolute()
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise OperationError("Symlink paths are forbidden")
    info = path.stat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) not in {0o400, 0o600}
        or info.st_nlink != 1
    ):
        raise OperationError("Private owner-only regular file required")
    return path


def private_directory(path):
    path = Path(path).absolute()
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise OperationError("Symlink paths are forbidden")
    info = path.stat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise OperationError("Private owner-only directory required")
    return path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def publish_json(path, value):
    """Publish a complete new receipt without replacing an existing one."""
    temporary = path.with_name("." + path.name + "." + uuid4().hex + ".partial")
    try:
        with temporary.open("x") as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def table_counts(conn):
    from psycopg import sql

    names = [
        row[0]
        for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
    ]
    return {
        name: conn.execute(
            sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(name))
        ).fetchone()[0]
        for name in names
    }


def encode_manifest(manifest):
    content = json.dumps(manifest, sort_keys=True).encode("utf-8")
    if len(content) > MAX_MANIFEST_BYTES:
        raise OperationError("Backup manifest exceeds the restorable bound")
    return content


def service_environment(path, *, restore=False):
    path = private_file(path)
    config = configparser.ConfigParser(interpolation=None)
    config.read(path)
    if config.sections() != ["sallimbook"] or config.defaults():
        raise OperationError("One dedicated libpq service section required")
    allowed = {"host", "port", "dbname", "user", "password", "sslmode", "sslrootcert"}
    if set(config["sallimbook"]) - allowed:
        raise OperationError("Unexpected libpq service option")
    dbname = config["sallimbook"].get("dbname", "")
    pattern = (
        r"sallimbook_[a-z0-9_]+_restorecheck" if restore else r"sallimbook_[a-z0-9_]+"
    )
    if not re.fullmatch(pattern, dbname):
        raise OperationError("Dedicated database name required")
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env.update(
        PGSERVICEFILE=str(path),
        PGSERVICE="sallimbook",
        PGCONNECT_TIMEOUT="5",
        PGAPPNAME="sallimbook-restore" if restore else "sallimbook-backup",
    )
    return env, dbname


def connect(env):
    import psycopg

    config = configparser.ConfigParser(interpolation=None)
    config.read(private_file(env["PGSERVICEFILE"]))
    parameters = dict(config["sallimbook"])
    if not {"host", "port", "dbname", "user", "password", "sslmode"}.issubset(
        parameters
    ):
        raise OperationError("Explicit database connection settings required")
    if any(key.startswith("PG") and value for key, value in os.environ.items()):
        raise OperationError(
            "Unset inherited PG variables; use the dedicated service file"
        )
    # No pool: session-level advisory lock must die with this physical connection.
    return psycopg.connect(
        **parameters,
        hostaddr="",
        passfile="/dev/null",
        options="-c timezone=UTC -c search_path=public",
        connect_timeout=5,
        application_name=env["PGAPPNAME"],
        autocommit=True,
    )


def verify_tools(*names):
    for name in names:
        result = subprocess.run(
            [name, "--version"], capture_output=True, timeout=10, check=True
        )
        if result.stdout.decode().strip() != TOOLS[name]:
            raise OperationError("Unverified backup tool version")


@contextmanager
def process(command, *, env=None, stdin=None, stdout=None):
    proc = subprocess.Popen(
        command,
        env=env,
        stdin=stdin,
        stdout=stdout,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    def stop():
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    timer = threading.Timer(900, stop)
    timer.daemon = True
    timer.start()
    try:
        yield proc
        if proc.wait(timeout=900) != 0:
            raise OperationError("Backup subprocess failed; no completed backup issued")
    finally:
        timer.cancel()
        stop()
        proc.wait()
        for stream in (proc.stdin, proc.stdout):
            if stream is not None:
                stream.close()


def encrypt_stream(source_command, target, recipient, env):
    with target.open("xb") as out:
        os.chmod(target, 0o600)
        with process(
            ["age", "-r", recipient], stdin=subprocess.PIPE, stdout=out
        ) as encoder:
            with process(source_command, env=env, stdout=encoder.stdin):
                pass
            encoder.stdin.close()
        out.flush()
        os.fsync(out.fileno())


def copy_objects(source, target):
    source = private_directory(source)
    target.mkdir(mode=0o700)
    objects = {}
    total = 0
    for path in sorted(source.iterdir()):
        if not OBJECT_NAME.fullmatch(path.name):
            raise OperationError("Unexpected entry in document store")
        private_file(path)
        size = path.stat().st_size
        total += size
        if (
            not 17 <= size <= MAX_OBJECT
            or len(objects) >= MAX_ENTRIES
            or total > MAX_ARCHIVE
        ):
            raise OperationError("Document backup bounds exceeded")
        with path.open("rb") as src, (target / path.name).open("xb") as dst:
            os.chmod(target / path.name, 0o600)
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        objects[path.name] = {"bytes": size, "sha256": digest(target / path.name)}
    return objects


def pack_encrypted(work, target, recipient):
    with target.open("xb") as output:
        os.chmod(target, 0o600)
        with process(
            ["age", "-r", recipient], stdin=subprocess.PIPE, stdout=output
        ) as proc:
            with tarfile.open(fileobj=proc.stdin, mode="w|") as archive:
                for path in sorted(work.rglob("*")):
                    if path.is_file():
                        info = archive.gettarinfo(
                            str(path), arcname=path.relative_to(work).as_posix()
                        )
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        info.mode = 0o600
                        with path.open("rb") as stream:
                            archive.addfile(info, stream)
            proc.stdin.close()
        output.flush()
        os.fsync(output.fileno())


def backup(
    service_file, documents, destination, recipient, source_commit, deployment_manifest
):
    from ops.deploy import validate

    if not re.fullmatch(r"age1[0-9a-z]{58}", recipient):
        raise OperationError("One standard age X25519 public recipient required")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise OperationError("Exact source commit required")
    deployment_path = Path(deployment_manifest)
    if deployment_path.stat().st_size > 64 * 1024:
        raise OperationError("Public deployment manifest is too large")
    deployment = validate(json.loads(deployment_path.read_text()))
    if deployment["source_commit"] != source_commit:
        raise OperationError("Backup source/deployment commit mismatch")
    verify_tools("age", "pg_dump")
    destination = private_directory(destination)
    documents = private_directory(documents)
    if destination == documents or destination.is_relative_to(documents):
        raise OperationError(
            "Backup destination must be separate from document storage"
        )
    env, dbname = service_environment(service_file)
    backup_id = str(uuid4())
    completed = destination / (backup_id + ".tar.age")
    partial = destination / (backup_id + ".partial")
    # Work contains encrypted pg_dump, existing encrypted objects, and non-plaintext
    # inventory. Neither raw SQL nor decrypted documents are written to disk.
    with tempfile.TemporaryDirectory(
        prefix=".sallimbook-backup-", dir=destination
    ) as temporary:
        work = Path(temporary)
        with connect(env) as conn:
            conn.execute("SET statement_timeout = '120s'")
            conn.execute("SELECT pg_advisory_lock(%s)", (STORAGE_BARRIER,))
            try:
                # Crucial ordering: no RR transaction/snapshot exists while waiting
                # for an upload/cleanup transaction to release the barrier.
                conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
                actual, revision, snapshot, taken_at = conn.execute(
                    "SELECT current_database(), (SELECT version_num FROM alembic_version), "
                    "pg_export_snapshot(), clock_timestamp()"
                ).fetchone()
                if actual != dbname or conn.info.server_version // 10000 != 18:
                    raise OperationError(
                        "Unexpected database identity or major version"
                    )
                versions = {
                    str(row[0]): row[1]
                    for row in conn.execute(
                        "SELECT household_id, max(key_version) FROM vault_versions GROUP BY household_id"
                    )
                }
                encrypt_stream(
                    [
                        "pg_dump",
                        "--format=custom",
                        "--no-owner",
                        "--no-acl",
                        "--snapshot=" + snapshot,
                        "--lock-wait-timeout=30s",
                    ],
                    work / "database.dump.age",
                    recipient,
                    env,
                )
                objects = copy_objects(documents, work / "objects")
                database_bytes = (work / "database.dump.age").stat().st_size
                if (
                    database_bytes + sum(item["bytes"] for item in objects.values())
                    > MAX_ARCHIVE - 16 * 1024 * 1024
                ):
                    raise OperationError(
                        "Complete backup exceeds the restorable archive bound"
                    )
                # All nondeleted rows with bytes must be covered. Deleted rows may
                # have been physically purged already; their audit metadata remains.
                required = dict(
                    conn.execute(
                        "SELECT storage_key, size_bytes + 16 FROM documents "
                        "WHERE storage_key IS NOT NULL AND state <> 'deleted'"
                    )
                )
                if any(
                    name not in objects or objects[name]["bytes"] != size
                    for name, size in required.items()
                ):
                    raise OperationError("Database and object snapshot do not agree")
                manifest = {
                    "format": 1,
                    "id": backup_id,
                    "snapshot_at": taken_at.isoformat(),
                    "schema_revision": revision,
                    "source_commit": source_commit,
                    "deployment": deployment,
                    "postgres_major": 18,
                    "vault_max_versions": versions,
                    "table_counts": table_counts(conn),
                    "database": {
                        "sha256": digest(work / "database.dump.age"),
                        "bytes": (work / "database.dump.age").stat().st_size,
                    },
                    "objects": objects,
                }
                (work / "manifest.json").write_bytes(encode_manifest(manifest))
                conn.execute("COMMIT")
            finally:
                conn.execute("ROLLBACK")
                conn.execute("SELECT pg_advisory_unlock(%s)", (STORAGE_BARRIER,))
        try:
            pack_encrypted(work, partial, recipient)
            # UUID names + hard link publish avoids replacing an existing backup.
            os.link(partial, completed)
            partial.unlink()
            receipt = {
                "format": 1,
                "id": backup_id,
                "file": completed.name,
                "sha256": digest(completed),
                "bytes": completed.stat().st_size,
                "completed_at": datetime.now(UTC).isoformat(),
            }
            receipt_path = destination / (backup_id + ".complete.json")
            publish_json(receipt_path, receipt)
            return receipt
        finally:
            partial.unlink(missing_ok=True)


def unpack_stream(stream, destination):
    """Strict extraction, no tar extract/all, symlinks, directories, or overwrites."""
    seen = set()
    total = 0
    with tarfile.open(fileobj=stream, mode="r|") as archive:
        for member in archive:
            name = member.name
            is_object = name.startswith("objects/") and OBJECT_NAME.fullmatch(name[8:])
            if (
                name in seen
                or not member.isreg()
                or name not in {"manifest.json", "database.dump.age"}
                and not is_object
            ):
                raise OperationError("Invalid backup archive member")
            total += member.size
            bound = (
                MAX_OBJECT
                if is_object
                else (MAX_MANIFEST_BYTES if name == "manifest.json" else MAX_ARCHIVE)
            )
            if (
                not 0 <= member.size <= bound
                or total > MAX_ARCHIVE
                or len(seen) >= MAX_ENTRIES + 2
            ):
                raise OperationError("Backup archive bounds exceeded")
            seen.add(name)
            target = destination / name
            target.parent.mkdir(mode=0o700, exist_ok=True)
            with archive.extractfile(member) as source, target.open("xb") as output:
                os.chmod(target, 0o600)
                shutil.copyfileobj(source, output, 1024 * 1024)
    # Consume remaining encrypted stream to force age's final authentication check.
    while stream.read(1024 * 1024):
        pass
    if not {"manifest.json", "database.dump.age"}.issubset(seen):
        raise OperationError("Incomplete backup archive")


def verify_inventory(work):
    manifest = json.loads((work / "manifest.json").read_text())
    if manifest.get("format") != 1 or manifest.get("postgres_major") != 18:
        raise OperationError("Unsupported backup format")
    declared = {
        "database.dump.age": manifest["database"],
        **{"objects/" + name: item for name, item in manifest["objects"].items()},
    }
    present = {
        path.relative_to(work).as_posix() for path in work.rglob("*") if path.is_file()
    }
    if present != set(declared) | {"manifest.json"}:
        raise OperationError("Backup inventory mismatch")
    for name, item in declared.items():
        if (work / name).stat().st_size != item["bytes"] or digest(work / name) != item[
            "sha256"
        ]:
            raise OperationError("Backup checksum mismatch")
    return manifest


def restore(archive, identity, service_file, output, expected_sha256):
    verify_tools("age", "pg_restore")
    archive, identity = private_file(archive), private_file(identity)
    if (
        not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        or digest(archive) != expected_sha256
    ):
        raise OperationError(
            "Backup does not match the separately trusted completion receipt"
        )
    env, dbname = service_environment(service_file, restore=True)
    parent = private_directory(Path(output).absolute().parent)
    output = parent / Path(output).name
    output.mkdir(mode=0o700, exist_ok=False)
    # A failed restore leaves a quarantine directory + partial database for inspection.
    # It never drops/recreates an existing target or advertises success/startup.
    (output / "QUARANTINE").write_text(
        "No API, node, or production traffic. Recovery gates pending.\n"
    )
    with tempfile.TemporaryDirectory(
        prefix=".sallimbook-restore-", dir=parent
    ) as temporary:
        work = Path(temporary)
        with process(
            ["age", "-d", "-i", str(identity), str(archive)], stdout=subprocess.PIPE
        ) as proc:
            unpack_stream(proc.stdout, work)
        manifest = verify_inventory(work)
        with connect(env) as conn:
            if conn.execute("SELECT current_database()").fetchone()[0] != dbname:
                raise OperationError("Unexpected restore target")
            if conn.execute(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema' "
                "AND c.relkind IN ('r','p','v','m','S','f')"
            ).fetchone()[0]:
                raise OperationError("Restore target must be empty")
        with process(
            ["age", "-d", "-i", str(identity), str(work / "database.dump.age")],
            stdout=subprocess.PIPE,
        ) as decoder:
            with process(
                [
                    "pg_restore",
                    "--dbname=service=sallimbook",
                    "--exit-on-error",
                    "--single-transaction",
                    "--no-owner",
                    "--no-acl",
                ],
                env=env,
                stdin=decoder.stdout,
            ):
                pass
        with connect(env) as conn:
            if (
                conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                != manifest["schema_revision"]
            ):
                raise OperationError("Restored schema revision mismatch")
            if table_counts(conn) != manifest["table_counts"]:
                raise OperationError("Restored table inventory/count mismatch")
        shutil.move(str(work / "objects"), str(output / "objects")) if (
            work / "objects"
        ).exists() else (output / "objects").mkdir(mode=0o700)
        (output / "backup-manifest.json").write_text(
            json.dumps(manifest, sort_keys=True)
        )
        (output / "deployment.json").write_text(
            json.dumps(manifest["deployment"], sort_keys=True)
        )
        result = {
            "status": "quarantined",
            "backup_id": manifest["id"],
            "restored_at": datetime.now(UTC).isoformat(),
            "database": dbname,
            "archive_sha256": digest(archive),
        }
        (output / "restore.json").write_text(json.dumps(result, sort_keys=True))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("create")
    make.add_argument("--service-file", required=True, type=Path)
    make.add_argument("--documents", required=True, type=Path)
    make.add_argument("--destination", required=True, type=Path)
    make.add_argument("--recipient", required=True)
    make.add_argument("--source-commit", required=True)
    make.add_argument("--deployment-manifest", required=True, type=Path)
    recover = sub.add_parser("restore")
    recover.add_argument("--archive", required=True, type=Path)
    recover.add_argument("--identity", required=True, type=Path)
    recover.add_argument("--service-file", required=True, type=Path)
    recover.add_argument("--output", required=True, type=Path)
    recover.add_argument(
        "--expected-sha256",
        required=True,
        help="Archive digest from the separately trusted completed-backup record",
    )
    args = vars(parser.parse_args())
    command = args.pop("command")
    try:
        result = backup(**args) if command == "create" else restore(**args)
    except Exception:
        # Raw subprocess/SQL/config exceptions can include credentials or source data.
        raise SystemExit(
            "Operation failed. No service activated; inspect private state with the operator."
        ) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
