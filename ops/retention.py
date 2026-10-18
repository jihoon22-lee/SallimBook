"""Read-only backup plans and explicit, evidence-gated encrypted archive pruning."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from ops.backup import MAX_ARCHIVE, OperationError

MAX_ITEMS = 10000
MAX_JSON = 2 * 1024 * 1024
MAX_PLAN = 16 * 1024 * 1024
POLICY = {"daily": 14, "weekly": 8, "monthly": 12, "timezone": "UTC"}
HEX = re.compile(r"[0-9a-f]{64}")
TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)")
RECEIPT = {"format", "id", "file", "sha256", "bytes", "completed_at"}


def require(condition, message="Backup evidence validation failed"):
    if not condition:
        raise OperationError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def timestamp(value):
    require(isinstance(value, str) and TIME.fullmatch(value))
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperationError("Invalid evidence timestamp") from exc
    require(2 <= result.year <= 9998)
    return result


def clock(now=None):
    value = now if now is not None else datetime.now(UTC)
    require(isinstance(value, datetime) and value.utcoffset() == timedelta(0))
    require(2 <= value.year <= 9998)
    return value


def identifier(value):
    require(isinstance(value, str))
    try:
        require(str(UUID(value)) == value)
    except ValueError as exc:
        raise OperationError("Invalid backup identifier") from exc
    return value


def uid_check(expected_uid):
    require(expected_uid is None or (type(expected_uid) is int and expected_uid == os.geteuid()),
            "Run as the backup owner; UID overrides are forbidden")


def fingerprint(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_uid, stat.S_IMODE(info.st_mode)]


class Directory:
    """All child operations stay relative to an opened, symlink-free directory."""

    def __init__(self, path):
        path = Path(path)
        require(path.is_absolute() and ".." not in path.parts, "Absolute private path required")
        self.path = path
        self.fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[1:]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=self.fd)
                os.close(self.fd)
                self.fd = child
            info = os.fstat(self.fd)
            require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                    "Private owner-only directory required")
            self.identity = [info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode)]
        except BaseException:
            os.close(self.fd)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        os.close(self.fd)

    def check(self):
        with Directory(self.path) as fresh:
            require(fresh.identity == self.identity, "Directory changed during operation")

    def names(self):
        names = sorted(os.listdir(self.fd))
        require(len(names) <= MAX_ITEMS * 4, "Backup directory entry limit exceeded")
        return names

    def read(self, name, limit=MAX_JSON, collect=True):
        require(isinstance(name, str) and name not in {"", ".", ".."} and "/" not in name)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        try:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid()
                    and stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1,
                    "Private single-link regular file required")
            require(0 < before.st_size <= limit, "Evidence file size outside bounds")
            digest = hashlib.sha256()
            parts = []
            count = 0
            while block := os.read(fd, 1024 * 1024):
                count += len(block)
                require(count <= limit)
                digest.update(block)
                if collect:
                    parts.append(block)
            after = os.fstat(fd)
            current = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            require(fingerprint(before) == fingerprint(after) == fingerprint(current)
                    and count == before.st_size, "Evidence changed during read")
            self.check()
            return b"".join(parts), {"sha256": digest.hexdigest(), "stat": fingerprint(after)}
        finally:
            os.close(fd)

    def json(self, name, limit=MAX_JSON):
        raw, snapshot = self.read(name, limit)

        def pairs(items):
            result = {}
            for key, value in items:
                require(key not in result, "Duplicate JSON field")
                result[key] = value
            return result

        try:
            data = json.loads(raw, object_pairs_hook=pairs,
                              parse_constant=lambda _: require(False))
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise OperationError("Invalid evidence JSON") from exc
        require(isinstance(data, dict))
        return data, snapshot

    def write(self, name, value):
        raw = canonical(value)
        require(len(raw) <= MAX_PLAN)
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=self.fd)
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self.fd)


@contextmanager
def locked(directory):
    fd = os.open(".retention.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                 0o600, dir_fd=directory.fd)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OperationError("Another retention operation is active") from exc
        yield
    finally:
        os.close(fd)


def disjoint(*paths):
    values = [Path(path) for path in paths if path is not None]
    for index, left in enumerate(values):
        for right in values[index + 1:]:
            require(left != right and left not in right.parents and right not in left.parents,
                    "Backup, replica, documents and evidence directories must be disjoint")


def distinct_directories(*identities):
    keys = [tuple(identity[:2]) for identity in identities if identity is not None]
    require(len(keys) == len(set(keys)), "Directory aliases are forbidden")


def receipt(directory, backup_id, now):
    value, metadata = directory.json(backup_id + ".complete.json", 65536)
    require(set(value) == RECEIPT and type(value["format"]) is int and value["format"] == 1)
    require(identifier(value["id"]) == backup_id and value["file"] == backup_id + ".tar.age")
    require(isinstance(value["sha256"], str) and HEX.fullmatch(value["sha256"]))
    require(type(value["bytes"]) is int and 0 < value["bytes"] <= MAX_ARCHIVE)
    require(timestamp(value["completed_at"]) <= now, "Future backup receipt forbidden")
    _, archive = directory.read(value["file"], MAX_ARCHIVE, collect=False)
    require(archive["sha256"] == value["sha256"] and archive["stat"][2] == value["bytes"],
            "Encrypted backup checksum or length mismatch")
    return value, {"receipt": metadata, "archive": archive}


def catalog(directory, now):
    names = directory.names()
    backups, incomplete, snapshots = [], [], {}
    markers = {}
    seen = set()
    for name in names:
        if name in seen or name == ".retention.lock":
            continue
        if name.startswith(".automation-") and name.endswith(".json"):
            identifier(name.removeprefix(".automation-").removesuffix(".json"))
            value, snapshot = directory.json(name, 65536)
            markers[name] = (value, snapshot)
            continue
        if name.startswith(".retention-"):
            identifier(name.removeprefix(".retention-"))
            with Directory(directory.path / name) as job:
                entries = job.names()
                if entries == ["intent.json", "result.json"]:
                    intent, _ = job.json("intent.json", MAX_PLAN)
                    result, _ = job.json("result.json")
                    require(result == {"format": 1, "status": "applied",
                                       "plan_sha256": sha(canonical(intent)),
                                       "deleted": intent["delete"]})
                else:
                    incomplete.append({"id": None, "kind": "interrupted-retention"})
            continue
        if name.endswith(".complete.json") or name.endswith(".tar.age"):
            suffix = ".complete.json" if name.endswith(".complete.json") else ".tar.age"
            backup_id = identifier(name.removesuffix(suffix))
            pair = {backup_id + ".complete.json", backup_id + ".tar.age"}
            seen.update(pair)
            if pair.issubset(names):
                value, snapshot = receipt(directory, backup_id, now)
                backups.append(value)
                snapshots[backup_id] = snapshot
            else:
                # Even an orphan must be a private regular file, never a link.
                directory.read(name, MAX_ARCHIVE, collect=False)
                incomplete.append({"id": backup_id, "kind": "orphan"})
        elif name.endswith(".partial") or name.startswith(".sallimbook-backup-"):
            info = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
            require(info.st_uid == os.geteuid() and not stat.S_ISLNK(info.st_mode))
            require((stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                     and stat.S_IMODE(info.st_mode) == 0o600)
                    or (stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700))
            incomplete.append({"id": None, "kind": "partial"})
        else:
            raise OperationError("Unexpected backup directory entry")
    require(len(backups) <= MAX_ITEMS)
    by_id = {item["id"]: item for item in backups}
    for value, _ in markers.values():
        backup_id = identifier(value.get("id"))
        require(backup_id in by_id and canonical(value) == canonical(by_id[backup_id]),
                "Automation marker does not match a verified backup")
        incomplete.append({"id": backup_id, "kind": "automation-pending"})
    require(names == directory.names(), "Backup inventory changed during verification")
    directory.check()
    return {"format": 1, "status": "incomplete" if incomplete else "verified",
            "checked_at": now.isoformat(), "backups": sorted(backups, key=lambda item: item["id"]),
            "incomplete": incomplete}, {"directory": directory.identity, "files": snapshots,
                                        "automation": {name: item[1]
                                                       for name, item in markers.items()}}


def catalog_backups(source, *, now=None, expected_uid=None):
    uid_check(expected_uid)
    with Directory(source) as directory:
        return catalog(directory, clock(now))[0]


def replica_receipt(value, now):
    return {"format": 1, "status": "replica-verified", "backup_id": value["id"],
            "sha256": value["sha256"], "bytes": value["bytes"],
            "verified_at": now.isoformat(), "independent_storage_verified": False}


def verify_replica(root, value, now):
    with Directory(root.path / value["id"]) as target:
        require(target.names() == sorted([value["file"], value["id"] + ".complete.json",
                                          "replica-verification.json"]))
        copied, snapshot = receipt(target, value["id"], now)
        require(copied == value, "Replica metadata differs from original")
        proof, proof_snapshot = target.json("replica-verification.json", 65536)
        verified_at = timestamp(proof.get("verified_at"))
        require(verified_at <= now and verified_at >= timestamp(value["completed_at"]))
        require(proof == replica_receipt(value, verified_at))
        return {"directory": target.identity, "files": snapshot, "proof": proof_snapshot}


def replicate_backup(source, replica, backup_id, *, documents, now=None, expected_uid=None):
    uid_check(expected_uid)
    now = clock(now)
    backup_id = identifier(backup_id)
    disjoint(source, replica, documents)
    with Directory(source) as origin, Directory(replica) as copies, Directory(documents) as docs:
        distinct_directories(origin.identity, copies.identity, docs.identity)
        with locked(copies):
            value, before = receipt(origin, backup_id, now)
            if backup_id in copies.names():
                verify_replica(copies, value, now)
                return replica_receipt(value, now)
            os.mkdir(backup_id, 0o700, dir_fd=copies.fd)
            os.fsync(copies.fd)
            with Directory(copies.path / backup_id) as target:
                src = os.open(value["file"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                              dir_fd=origin.fd)
                dst = os.open(value["file"], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=target.fd)
                try:
                    require(fingerprint(os.fstat(src)) == before["archive"]["stat"])
                    count = 0
                    while block := os.read(src, 1024 * 1024):
                        count += len(block)
                        require(count <= value["bytes"])
                        view = memoryview(block)
                        while view:
                            written = os.write(dst, view)
                            require(written > 0)
                            view = view[written:]
                    os.fsync(dst)
                finally:
                    os.close(src)
                    os.close(dst)
                require(receipt(origin, backup_id, now) == (value, before),
                        "Original changed during replication")
                _, copied = target.read(value["file"], MAX_ARCHIVE, collect=False)
                require(copied["sha256"] == value["sha256"]
                        and copied["stat"][2] == value["bytes"])
                target.write(backup_id + ".complete.json", value)
                target.write("replica-verification.json", replica_receipt(value, now))
            verify_replica(copies, value, now)
            return replica_receipt(value, now)


def recover_replica(source, replica, backup_id, *, documents, now=None, expected_uid=None):
    """Finish metadata only after a complete interrupted ciphertext copy matches."""
    uid_check(expected_uid)
    now = clock(now)
    backup_id = identifier(backup_id)
    disjoint(source, replica, documents)
    with Directory(source) as origin, Directory(replica) as copies, Directory(documents) as docs:
        distinct_directories(origin.identity, copies.identity, docs.identity)
        with locked(copies), Directory(copies.path / backup_id) as target:
            value, before = receipt(origin, backup_id, now)
            allowed = {value["file"], backup_id + ".complete.json", "replica-verification.json"}
            require(set(target.names()).issubset(allowed) and value["file"] in target.names())
            _, copied = target.read(value["file"], MAX_ARCHIVE, collect=False)
            require(copied["sha256"] == value["sha256"]
                    and copied["stat"][2] == value["bytes"], "Incomplete replica needs review")
            metadata_name = backup_id + ".complete.json"
            if metadata_name in target.names():
                require(target.json(metadata_name)[0] == value)
            else:
                target.write(metadata_name, value)
            require(receipt(origin, backup_id, now) == (value, before))
            if "replica-verification.json" not in target.names():
                target.write("replica-verification.json", replica_receipt(value, now))
            verify_replica(copies, value, now)
            return replica_receipt(value, now)


def evidence_paths(value):
    if value is None:
        return []
    values = [value] if isinstance(value, (str, Path)) else list(value)
    require(len(values) <= MAX_ITEMS)
    paths = sorted(str(Path(item)) for item in values)
    require(len(paths) == len(set(paths)))
    return paths


def restore_proofs(paths, backups, now):
    protected, verified, snapshots = set(), [], {}
    for path in paths:
        with Directory(path) as directory:
            raw, raw_snapshot = directory.json("restore.json", 65536)
            require(set(raw) == {"status", "backup_id", "restored_at", "database",
                                 "archive_sha256"} and raw["status"] == "quarantined")
            backup_id = identifier(raw["backup_id"])
            restored = timestamp(raw["restored_at"])
            require(restored <= now and isinstance(raw["database"], str)
                    and re.fullmatch(r"sallimbook_[a-z0-9_]+_restorecheck", raw["database"]))
            require(isinstance(raw["archive_sha256"], str) and HEX.fullmatch(raw["archive_sha256"]))
            require(backup_id in backups and raw["archive_sha256"] == backups[backup_id]["sha256"])
            require(restored >= timestamp(backups[backup_id]["completed_at"]))
            protected.add(backup_id)
            snapshot = {"directory": directory.identity, "restore": raw_snapshot}
            if "restore-integrity.json" in directory.names():
                manifest, manifest_snapshot = directory.json("backup-manifest.json")
                require(type(manifest.get("format")) is int and manifest["format"] == 1
                        and manifest.get("id") == backup_id)
                proof, proof_snapshot = directory.json("restore-integrity.json", 65536)
                when = timestamp(proof.get("verified_at"))
                require(restored <= when <= now)
                expected = {"format": 1, "status": "restored-integrity-verified",
                            "backup_id": backup_id, "archive_sha256": raw["archive_sha256"],
                            "restored_at": raw["restored_at"], "verified_at": proof["verified_at"],
                            "restore_manifest_sha256": manifest_snapshot["sha256"],
                            "restore_receipt_sha256": raw_snapshot["sha256"],
                            "checks": {"schema": True, "table_counts": True,
                                       "objects": True, "field_ciphertexts": True}}
                require(canonical(proof) == canonical(expected), "Full restore proof required")
                snapshot.update(manifest=manifest_snapshot, integrity=proof_snapshot)
                verified.append((when, backup_id))
            snapshots[path] = snapshot
    return protected, max(verified)[1] if verified else None, snapshots


def retained(backups, now):
    keep = {}
    if not backups:
        return keep
    latest = max(backups, key=lambda item: (timestamp(item["completed_at"]), item["id"]))
    keep[latest["id"]] = ["latest"]
    daily = {(now.date() - timedelta(days=n)).isoformat() for n in range(14)}
    monday = now.date() - timedelta(days=now.weekday())
    weekly = {(monday - timedelta(weeks=n)).isoformat() for n in range(8)}
    month = now.year * 12 + now.month - 1
    monthly = {month - n for n in range(12)}
    buckets = {}
    for item in backups:
        when = timestamp(item["completed_at"])
        keys = [("daily", when.date().isoformat(), daily),
                ("weekly", (when.date() - timedelta(days=when.weekday())).isoformat(), weekly),
                ("monthly", when.year * 12 + when.month - 1, monthly)]
        for reason, key, allowed in keys:
            if key in allowed:
                candidate = (when, item["id"])
                buckets[reason, key] = max(candidate, buckets.get((reason, key), candidate))
    for (reason, _), (_, backup_id) in buckets.items():
        keep.setdefault(backup_id, []).append(reason)
    return {key: sorted(set(value)) for key, value in keep.items()}


def plan_retention(source, *, documents, replica=None, replica_scope="local",
                   restore_evidence=None, now=None, expected_uid=None):
    uid_check(expected_uid)
    now = clock(now)
    require(replica_scope in {"local", "external-declared"})
    paths = evidence_paths(restore_evidence)
    disjoint(source, documents, replica, *paths)
    with Directory(documents) as docs, Directory(source) as origin:
        inventory, source_snapshot = catalog(origin, now)
        backups = {item["id"]: item for item in inventory["backups"]}
        protected, last_restore, proofs = restore_proofs(paths, backups, now)
        keep = retained(list(backups.values()), now)
        for item in inventory["incomplete"]:
            if item["kind"] == "automation-pending":
                keep.setdefault(item["id"], []).append("automation-pending")
        for backup_id in protected:
            keep.setdefault(backup_id, []).append("restore-evidence")
        if last_restore:
            keep[last_restore].append("last-verified-restore")
        pending = []
        if inventory["incomplete"]:
            pending.append("incomplete-source")
        if last_restore is None:
            pending.append("restore-integrity-required")
        if replica is None or replica_scope != "external-declared":
            pending.append("independent-replica-declaration-required")
        copies = {}
        replica_identity = None
        candidates = sorted(set(backups) - set(keep))
        if replica is not None:
            with Directory(replica) as root:
                replica_identity = root.identity
                for backup_id in candidates:
                    if backup_id not in root.names():
                        keep[backup_id] = ["replica-missing"]
                    else:
                        copies[backup_id] = verify_replica(root, backups[backup_id], now)
                root.check()
        distinct_directories(origin.identity, docs.identity, replica_identity,
                             *(proof["directory"] for proof in proofs.values()))
        delete = sorted(set(candidates) - set(keep)) if not pending else []
        for backup_id in set(backups) - set(keep) - set(delete):
            keep[backup_id] = ["pending-evidence"]
        payload = {"policy": POLICY, "as_of": now.isoformat(),
                   "config": {"source": str(origin.path), "documents": str(docs.path),
                              "replica": str(Path(replica)) if replica is not None else None,
                              "replica_scope": replica_scope, "restore_evidence": paths},
                   "inventory": inventory, "source_snapshot": source_snapshot,
                   "documents_identity": docs.identity, "replica_identity": replica_identity,
                   "replica_snapshots": copies, "restore_snapshots": proofs,
                   "last_verified_restore": last_restore,
                   "keep": {key: sorted(set(value)) for key, value in sorted(keep.items())},
                   "delete": delete, "pending": sorted(pending),
                   "independent_storage_verified": False}
        return {"format": 1, "plan_sha256": sha(canonical(payload)), "plan": payload}


def save_plan(path, value):
    path = Path(path)
    require(path.is_absolute())
    config = value["plan"]["config"]
    disjoint(path.parent, config["source"], config["documents"], config["replica"],
             *config["restore_evidence"])
    with Directory(path.parent) as directory:
        directory.write(path.name, value)


def apply_retention(plan_file, expected_plan_sha256, *, now=None, expected_uid=None):
    uid_check(expected_uid)
    now = clock(now)
    path = Path(plan_file)
    with Directory(path.parent) as location:
        wrapper, _ = location.json(path.name, MAX_PLAN)
    require(set(wrapper) == {"format", "plan_sha256", "plan"}
            and type(wrapper["format"]) is int and wrapper["format"] == 1)
    require(isinstance(expected_plan_sha256, str) and HEX.fullmatch(expected_plan_sha256))
    payload = wrapper["plan"]
    require(isinstance(payload, dict) and sha(canonical(payload)) == expected_plan_sha256
            and wrapper["plan_sha256"] == expected_plan_sha256, "Reviewed plan digest mismatch")
    as_of = timestamp(payload.get("as_of"))
    require(timedelta(0) <= now - as_of <= timedelta(hours=24), "Retention plan expired")
    config = payload.get("config")
    require(isinstance(config, dict) and set(config) == {"source", "documents", "replica",
                                                        "replica_scope", "restore_evidence"})
    disjoint(path.parent, config["source"], config["documents"], config["replica"],
             *config["restore_evidence"])
    with Directory(config["source"]) as origin, locked(origin):
        fresh = plan_retention(**config, now=as_of, expected_uid=expected_uid)
        require(canonical(fresh) == canonical(wrapper), "Backup plan evidence has changed")
        require(not payload["pending"], "Retention evidence is still pending")
        result = {"format": 1, "status": "applied", "plan_sha256": expected_plan_sha256,
                  "deleted": payload["delete"]}
        if not payload["delete"]:
            return result
        job_name = ".retention-" + str(uuid4())
        os.mkdir(job_name, 0o700, dir_fd=origin.fd)
        os.fsync(origin.fd)
        with Directory(origin.path / job_name) as job:
            job.write("intent.json", payload)
            # An interruption leaves a visible incomplete journal and never removes a replica.
            for backup_id in payload["delete"]:
                require(receipt(origin, backup_id, as_of)[1]
                        == payload["source_snapshot"]["files"][backup_id])
                with Directory(config["replica"]) as copies:
                    require(verify_replica(copies, next(item for item in payload["inventory"]
                            ["backups"] if item["id"] == backup_id), as_of)
                            == payload["replica_snapshots"][backup_id])
                origin.check()
                job.check()
                for suffix in (".tar.age", ".complete.json"):
                    name = backup_id + suffix
                    require(name not in job.names())
                    os.rename(name, name, src_dir_fd=origin.fd, dst_dir_fd=job.fd)
                    os.fsync(origin.fd)
                    os.fsync(job.fd)
            # Check every retained original and every candidate copy before the first unlink.
            for backup_id in payload["keep"]:
                require(receipt(origin, backup_id, as_of)[1]
                        == payload["source_snapshot"]["files"][backup_id])
            with Directory(config["replica"]) as copies:
                for backup_id in payload["delete"]:
                    value, _ = receipt(job, backup_id, as_of)
                    require(verify_replica(copies, value, as_of)
                            == payload["replica_snapshots"][backup_id])
            require(restore_proofs(
                config["restore_evidence"],
                {item["id"]: item for item in payload["inventory"]["backups"]}, as_of
            )[2] == payload["restore_snapshots"], "Restore proof changed during pruning")
            for backup_id in payload["delete"]:
                for suffix in (".tar.age", ".complete.json"):
                    os.unlink(backup_id + suffix, dir_fd=job.fd)
                    os.fsync(job.fd)
            job.write("result.json", result)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("catalog", "replicate", "recover-replica", "plan"):
        action = sub.add_parser(command)
        action.add_argument("--source", required=True, type=Path)
        if command != "catalog":
            action.add_argument("--documents", required=True, type=Path)
            action.add_argument("--replica", required=command != "plan", type=Path)
        if command in {"replicate", "recover-replica"}:
            action.add_argument("--backup-id", required=True)
        if command == "plan":
            action.add_argument("--replica-scope", choices=["local", "external-declared"],
                                default="local")
            action.add_argument("--restore-evidence", action="append", type=Path)
            action.add_argument("--output", required=True, type=Path)
    action = sub.add_parser("apply")
    action.add_argument("--plan", required=True, type=Path)
    action.add_argument("--expected-plan-sha256", required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        if command == "catalog":
            result = catalog_backups(**args)
        elif command in {"replicate", "recover-replica"}:
            result = (replicate_backup if command == "replicate" else recover_replica)(**args)
        elif command == "plan":
            output = args.pop("output")
            result = plan_retention(**args)
            save_plan(output, result)
        else:
            result = apply_retention(args.pop("plan"), **args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OperationError, OSError, ValueError, TypeError, KeyError, OverflowError):
        print('{"status":"failed","reason":"backup evidence or operation rejected"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
