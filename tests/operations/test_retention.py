"""Synthetic encrypted bytes only; no services, keys, or real backup directories."""

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from ops import retention as r
from ops.backup import OperationError


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.replica = self.root / "replica"
        self.documents = self.root / "documents"
        self.proof = self.root / "proof"
        self.plans = self.root / "plans"
        for directory in (self.source, self.replica, self.documents, self.proof, self.plans):
            directory.mkdir(mode=0o700)
        self.now = datetime(2026, 10, 18, 12, tzinfo=UTC)

    def write(self, path, value):
        path.write_bytes(value if isinstance(value, bytes) else r.canonical(value))
        path.chmod(0o600)

    def backup(self, days=0, when=None, backup_id=None):
        backup_id = backup_id or str(uuid4())
        data = ("synthetic encrypted fixture " + backup_id).encode()
        value = {"format": 1, "id": backup_id, "file": backup_id + ".tar.age",
                 "sha256": r.sha(data), "bytes": len(data),
                 "completed_at": (when or self.now - timedelta(days=days)).isoformat()}
        self.write(self.source / value["file"], data)
        self.write(self.source / (backup_id + ".complete.json"), value)
        return value

    def copy(self, value):
        return r.replicate_backup(self.source, self.replica, value["id"],
                                  documents=self.documents, now=self.now)

    def evidence(self, value, full=True, directory=None):
        directory = directory or self.proof
        restored = self.now - timedelta(minutes=2)
        raw = {"status": "quarantined", "backup_id": value["id"],
               "restored_at": restored.isoformat(), "database": "sallimbook_test_restorecheck",
               "archive_sha256": value["sha256"]}
        manifest = {"format": 1, "id": value["id"]}
        self.write(directory / "restore.json", raw)
        self.write(directory / "backup-manifest.json", manifest)
        if full:
            proof = {"format": 1, "status": "restored-integrity-verified",
                     "backup_id": value["id"], "archive_sha256": value["sha256"],
                     "restored_at": raw["restored_at"], "verified_at": self.now.isoformat(),
                     "restore_manifest_sha256": r.sha(r.canonical(manifest)),
                     "restore_receipt_sha256": r.sha(r.canonical(raw)),
                     "checks": {"schema": True, "table_counts": True,
                                "objects": True, "field_ciphertexts": True}}
            self.write(directory / "restore-integrity.json", proof)

    def plan(self, **kwargs):
        options = {"documents": self.documents, "replica": self.replica,
                   "replica_scope": "external-declared", "restore_evidence": self.proof,
                   "now": self.now}
        options.update(kwargs)
        return r.plan_retention(self.source, **options)

    def ready(self):
        old = self.backup(days=500)
        restored = self.backup(days=400)
        latest = self.backup(days=1)
        self.copy(old)
        self.evidence(restored)
        return old, restored, latest

    def saved(self, plan=None):
        plan = plan or self.plan()
        path = self.plans / (str(uuid4()) + ".json")
        r.save_plan(path, plan)
        return path, plan["plan_sha256"]

    def test_catalog_hashes_encrypted_bytes_without_writes(self):
        value = self.backup()
        before = set(self.source.iterdir())
        result = r.catalog_backups(self.source, now=self.now)
        self.assertEqual(result["backups"], [value])
        self.assertEqual(before, set(self.source.iterdir()))
        self.write(self.source / value["file"], b"corrupt")
        with self.assertRaises(OperationError):
            r.catalog_backups(self.source, now=self.now)

    def test_retention_union_utc_boundary_and_missing_buckets(self):
        dates = [self.now - timedelta(days=n) for n in range(450)]
        values = [self.backup(when=when) for when in dates]
        keep = r.retained(values, self.now)
        for value in values[:14]:
            self.assertIn("daily", keep[value["id"]])
        self.assertNotIn("daily", keep.get(values[14]["id"], []))
        self.assertEqual(sum("weekly" in reasons for reasons in keep.values()), 8)
        self.assertEqual(sum("monthly" in reasons for reasons in keep.values()), 12)
        only_old = [values[-1]]
        self.assertEqual(r.retained(only_old, self.now), {values[-1]["id"]: ["latest"]})

    def test_equal_timestamp_deterministic_uuid_tie(self):
        first = self.backup(backup_id="00000000-0000-4000-8000-000000000001")
        second = self.backup(backup_id="00000000-0000-4000-8000-000000000002")
        self.assertEqual(set(r.retained([second, first], self.now)), {second["id"]})

    def test_metadata_only_protects_but_cannot_authorize_deletion(self):
        old = self.backup(days=500)
        restored = self.backup(days=400)
        self.backup(days=1)
        self.copy(old)
        self.evidence(restored, full=False)
        plan = self.plan()["plan"]
        self.assertEqual(plan["delete"], [])
        self.assertIn("restore-integrity-required", plan["pending"])
        self.assertIn(restored["id"], plan["keep"])

    def test_local_replica_never_claims_independence(self):
        self.ready()
        plan = self.plan(replica_scope="local")["plan"]
        self.assertFalse(plan["independent_storage_verified"])
        self.assertEqual(plan["delete"], [])
        self.assertIn("independent-replica-declaration-required", plan["pending"])

    def test_full_evidence_protects_latest_and_last_restore(self):
        old, restored, latest = self.ready()
        plan = self.plan()["plan"]
        self.assertEqual(plan["delete"], [old["id"]])
        self.assertIn("last-verified-restore", plan["keep"][restored["id"]])
        self.assertIn("latest", plan["keep"][latest["id"]])

    def test_apply_removes_only_reviewed_originals(self):
        old, restored, latest = self.ready()
        path, digest = self.saved()
        result = r.apply_retention(path, digest, now=self.now)
        self.assertEqual(result["deleted"], [old["id"]])
        self.assertFalse((self.source / old["file"]).exists())
        self.assertTrue((self.replica / old["id"] / old["file"]).exists())
        self.assertEqual({item["id"] for item in r.catalog_backups(self.source, now=self.now)
                          ["backups"]}, {restored["id"], latest["id"]})
        with self.assertRaises(OperationError):
            r.apply_retention(path, digest, now=self.now)

    def test_pending_plan_cannot_be_applied(self):
        self.backup(days=1)
        plan = self.plan(restore_evidence=None)
        path, digest = self.saved(plan)
        with self.assertRaises(OperationError):
            r.apply_retention(path, digest, now=self.now)

    def test_no_candidates_can_apply_without_deleting_only_backup(self):
        value = self.backup(days=1)
        self.evidence(value)
        path, digest = self.saved()
        self.assertEqual(r.apply_retention(path, digest, now=self.now)["deleted"], [])
        self.assertTrue((self.source / value["file"]).exists())

    def test_missing_replica_protects_candidate(self):
        self.ready()
        missing = self.backup(days=600)
        self.assertEqual(self.plan()["plan"]["keep"][missing["id"]], ["replica-missing"])

    def test_replication_is_verified_and_idempotent(self):
        value = self.backup(days=1)
        result = self.copy(value)
        self.assertFalse(result["independent_storage_verified"])
        before = (self.replica / value["id"] / "replica-verification.json").stat()
        self.copy(value)
        after = (self.replica / value["id"] / "replica-verification.json").stat()
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)

    def test_recover_only_complete_interrupted_copy(self):
        value = self.backup(days=1)
        target = self.replica / value["id"]
        target.mkdir(mode=0o700)
        self.write(target / value["file"], (self.source / value["file"]).read_bytes())
        r.recover_replica(self.source, self.replica, value["id"], documents=self.documents,
                          now=self.now)
        self.assertTrue((target / "replica-verification.json").exists())

    def test_short_interrupted_copy_is_preserved_without_promotion(self):
        value = self.backup(days=1)
        target = self.replica / value["id"]
        target.mkdir(mode=0o700)
        self.write(target / value["file"], b"partial")
        with self.assertRaises(OperationError):
            r.recover_replica(self.source, self.replica, value["id"], documents=self.documents,
                              now=self.now)
        self.assertEqual((target / value["file"]).read_bytes(), b"partial")
        self.assertFalse((target / "replica-verification.json").exists())

    def test_partial_and_orphan_block_all_pruning(self):
        self.ready()
        self.write(self.source / (str(uuid4()) + ".partial"), b"partial")
        orphan = self.backup(days=700)
        (self.source / (orphan["id"] + ".complete.json")).unlink()
        plan = self.plan()["plan"]
        self.assertEqual(plan["delete"], [])
        self.assertIn("incomplete-source", plan["pending"])

    def test_malformed_duplicate_and_boolean_fields_rejected(self):
        value = self.backup()
        target = self.source / (value["id"] + ".complete.json")
        for data in (b'{"format":1,"format":1}', b'{"format":NaN}',
                     r.canonical({**value, "bytes": True}),
                     r.canonical({**value, "format": True}),
                     r.canonical({**value, "id": "../bad"})):
            with self.subTest(data=data):
                self.write(target, data)
                with self.assertRaises(OperationError):
                    r.catalog_backups(self.source, now=self.now)

    def test_future_and_non_utc_timestamps_rejected(self):
        value = self.backup()
        target = self.source / (value["id"] + ".complete.json")
        for when in ((self.now + timedelta(seconds=1)).isoformat(),
                     "2026-10-18T12:00:00+09:00", "2026-10-18T12:00:00", "9999-12-31T00:00:00Z"):
            self.write(target, {**value, "completed_at": when})
            with self.assertRaises(OperationError):
                r.catalog_backups(self.source, now=self.now)

    def test_symlink_hardlink_permissions_and_uid_fail_closed(self):
        value = self.backup()
        archive = self.source / value["file"]
        archive.chmod(0o644)
        with self.assertRaises(OperationError):
            r.catalog_backups(self.source, now=self.now)
        archive.chmod(0o600)
        link = self.root / "hardlink"
        os.link(archive, link)
        with self.assertRaises(OperationError):
            r.catalog_backups(self.source, now=self.now)
        link.unlink()
        moved = self.root / "archive"
        archive.rename(moved)
        archive.symlink_to(moved)
        with self.assertRaises((OperationError, OSError)):
            r.catalog_backups(self.source, now=self.now)
        with self.assertRaises(OperationError):
            r.catalog_backups(self.source, now=self.now, expected_uid=os.geteuid() + 1)

    def test_symlink_ancestor_and_overlapping_paths_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(OSError):
            r.catalog_backups(alias, now=self.now)
        with self.assertRaises(OperationError):
            self.plan(replica=self.source, restore_evidence=None)
        with self.assertRaises(OperationError):
            self.plan(replica=self.source / "nested", restore_evidence=None)

    def test_plan_digest_expiry_and_source_drift_prevent_mutation(self):
        old, _, _ = self.ready()
        path, digest = self.saved()
        for invalid_digest, when in (("0" * 64, self.now),
                                     (digest, self.now + timedelta(hours=25)),
                                     (digest, self.now - timedelta(seconds=1))):
            with self.assertRaises(OperationError):
                r.apply_retention(path, invalid_digest, now=when)
        self.backup(days=2)
        with self.assertRaises(OperationError):
            r.apply_retention(path, digest, now=self.now)
        self.assertTrue((self.source / old["file"]).exists())

    def test_replica_drift_prevents_deletion(self):
        old, _, _ = self.ready()
        path, digest = self.saved()
        self.write(self.replica / old["id"] / old["file"], b"changed")
        with self.assertRaises(OperationError):
            r.apply_retention(path, digest, now=self.now)
        self.assertTrue((self.source / old["file"]).exists())

    def test_restore_manifest_drift_and_false_checks_rejected(self):
        self.ready()
        path = self.proof / "restore-integrity.json"
        data = json.loads(path.read_text())
        data["checks"]["field_ciphertexts"] = 1
        self.write(path, data)
        with self.assertRaises(OperationError):
            self.plan()
        data["checks"]["field_ciphertexts"] = True
        self.write(path, data)
        self.write(self.proof / "backup-manifest.json", {"format": 1, "id": str(uuid4())})
        with self.assertRaises(OperationError):
            self.plan()

    def test_multiple_restore_evidence_protected(self):
        old, restored, _ = self.ready()
        extra = self.root / "proof2"
        extra.mkdir(mode=0o700)
        self.evidence(old, directory=extra)
        plan = self.plan(restore_evidence=[self.proof, extra])["plan"]
        self.assertEqual(plan["delete"], [])
        self.assertIn(old["id"], plan["keep"])
        self.assertIn(restored["id"], plan["keep"])

    def test_concurrent_apply_is_rejected(self):
        old, _, _ = self.ready()
        path, digest = self.saved()
        with r.Directory(self.source) as source, r.locked(source):
            with self.assertRaises(OperationError):
                r.apply_retention(path, digest, now=self.now)
        self.assertTrue((self.source / old["file"]).exists())

    def test_interrupted_prune_preserves_staged_bytes_and_blocks_next_plan(self):
        old, _, _ = self.ready()
        path, digest = self.saved()
        real_unlink = os.unlink

        def interrupt(name, *args, **kwargs):
            if name == old["file"]:
                raise KeyboardInterrupt()
            return real_unlink(name, *args, **kwargs)

        with patch("ops.retention.os.unlink", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                r.apply_retention(path, digest, now=self.now)
        jobs = list(self.source.glob(".retention-*"))
        self.assertEqual(len(jobs), 1)
        self.assertTrue((jobs[0] / old["file"]).exists())
        self.assertTrue((self.replica / old["id"] / old["file"]).exists())
        self.assertIn("incomplete-source", self.plan()["plan"]["pending"])

    def test_plan_and_catalog_never_create_locks(self):
        self.ready()
        self.assertFalse((self.source / ".retention.lock").exists())
        self.plan()
        r.catalog_backups(self.source, now=self.now)
        self.assertFalse((self.source / ".retention.lock").exists())

    def test_output_cannot_overwrite_plan_or_live_directories(self):
        self.ready()
        plan = self.plan()
        path, _ = self.saved(plan)
        with self.assertRaises(FileExistsError):
            r.save_plan(path, plan)
        with self.assertRaises(OperationError):
            r.save_plan(self.source / "plan.json", plan)


    def test_interrupted_copy_requires_explicit_recovery(self):
        value = self.backup(days=1)
        real_write = r.Directory.write

        def interrupt(directory, name, data):
            if name.endswith(".complete.json"):
                raise KeyboardInterrupt()
            return real_write(directory, name, data)

        with patch.object(r.Directory, "write", interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.copy(value)
        target = self.replica / value["id"]
        self.assertEqual((target / value["file"]).read_bytes(),
                         (self.source / value["file"]).read_bytes())
        with self.assertRaises(OperationError):
            self.copy(value)
        r.recover_replica(self.source, self.replica, value["id"],
                          documents=self.documents, now=self.now)
        self.assertTrue((target / "replica-verification.json").exists())

    def test_fifo_does_not_block_or_count_as_backup(self):
        value = self.backup()
        archive = self.source / value["file"]
        archive.unlink()
        os.mkfifo(archive, 0o600)
        with self.assertRaises(OperationError):
            r.catalog_backups(self.source, now=self.now)

    def test_restore_proof_rewrite_after_plan_rejected(self):
        old, _, _ = self.ready()
        path, digest = self.saved()
        proof = self.proof / "restore-integrity.json"
        data = proof.read_bytes()
        self.write(proof, data)
        with self.assertRaises(OperationError):
            r.apply_retention(path, digest, now=self.now)
        self.assertTrue((self.source / old["file"]).exists())

    def test_replica_existing_corrupt_bytes_are_not_overwritten(self):
        value = self.backup(days=1)
        self.copy(value)
        target = self.replica / value["id"] / value["file"]
        self.write(target, b"corruption remains for review")
        with self.assertRaises(OperationError):
            self.copy(value)
        self.assertEqual(target.read_bytes(), b"corruption remains for review")

    def test_empty_catalog_is_valid_but_never_authorizes_apply(self):
        result = r.catalog_backups(self.source, now=self.now)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["backups"], [])
        plan = self.plan(restore_evidence=None)["plan"]
        self.assertEqual(plan["delete"], [])
        self.assertIn("restore-integrity-required", plan["pending"])

    def test_catalog_unknown_file_and_entry_limit_rejected(self):
        self.backup()
        self.write(self.source / "unexpected.txt", b"synthetic")
        with self.assertRaises(OperationError):
            r.catalog_backups(self.source, now=self.now)
        (self.source / "unexpected.txt").unlink()
        with patch.object(r, "MAX_ITEMS", 0):
            with self.assertRaises(OperationError):
                r.catalog_backups(self.source, now=self.now)

    def test_replica_lock_contention_preserves_source(self):
        value = self.backup(days=1)
        with r.Directory(self.replica) as copies, r.locked(copies):
            with self.assertRaises(OperationError):
                self.copy(value)
        self.assertTrue((self.source / value["file"]).exists())



    def test_unacknowledged_automation_marker_preserves_backup_and_pauses_prune(self):
        old, _, _ = self.ready()
        marker = self.source / (".automation-" + str(uuid4()) + ".json")
        self.write(marker, old)
        plan = self.plan()["plan"]
        self.assertEqual(plan["delete"], [])
        self.assertIn("automation-pending", plan["keep"][old["id"]])
        self.assertIn("incomplete-source", plan["pending"])
        marker.unlink()  # Simulate verified worker acknowledgement after host journal fsync.
        self.assertEqual(self.plan()["plan"]["delete"], [old["id"]])

    def test_automation_marker_requires_uuid_exact_receipt_and_current_backup(self):
        value = self.backup(days=1)
        marker = self.source / (".automation-" + str(uuid4()) + ".json")
        for invalid in ({**value, "format": True}, {**value, "sha256": "0" * 64},
                        {**value, "id": str(uuid4())}, {**value, "extra": "forbidden"}):
            self.write(marker, invalid)
            with self.assertRaises(OperationError):
                r.catalog_backups(self.source, now=self.now)
        marker.unlink()
        self.write(self.source / ".automation-invalid.json", value)
        with self.assertRaises(OperationError):
            r.catalog_backups(self.source, now=self.now)

    def test_automation_marker_symlink_is_rejected(self):
        value = self.backup(days=1)
        marker = self.source / (".automation-" + str(uuid4()) + ".json")
        marker.symlink_to(self.source / (value["id"] + ".complete.json"))
        with self.assertRaises(OSError):
            r.catalog_backups(self.source, now=self.now)


if __name__ == "__main__":
    unittest.main()
