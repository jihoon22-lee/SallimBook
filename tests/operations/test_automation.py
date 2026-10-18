"""Synthetic scheduler/restore boundaries: never starts Docker or a database."""

import io
import json
import os
import stat
import sys
import tarfile
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from ops import automation as auto
from ops import automation_runtime as runtime
from ops import automation_worker as worker
from ops import backup, build_context, restore_check
from tests.operations.test_operations import config as deployment_config


def configuration(root):
    project = "sallimbook-staging"
    value = {
        "format": 1,
        "project": project,
        "operator_source_commit": "b" * 40,
        "deployment_sha256": "c" * 64,
    }
    for key in auto.PATH_KEYS:
        value[key] = (
            str(root / key / project)
            if key
            in {"state_directory", "backup_directory", "restore_directory", "build_directory"}
            else str(root / key)
        )
    return value


def private(path, content):
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    path.chmod(0o600)
    return path


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = configuration(self.root)
        for key in ("state_directory", "build_directory"):
            Path(self.config[key]).mkdir(parents=True, mode=0o700)

    def test_config_rejects_secret_in_storage_paths_and_interpolation(self):
        self.assertEqual(auto.validate_config(self.config), self.config)
        bad_values = [
            {"backup_service_file": self.config["backup_directory"] + "/secret"},
            {"restore_directory": self.config["backup_directory"]},
            {"project": "existing-project"},
            {"sdk_directory": "/tmp/a b"},
            {"sdk_directory": "/tmp/$HOME"},
            {"sdk_directory": "/tmp/%h"},
            {"sdk_directory": "/tmp/a/../b"},
            {"unknown": True},
        ]
        for updates in bad_values:
            with self.subTest(updates=updates), self.assertRaises(auto.AutomationError):
                auto.validate_config({**self.config, **updates})

    def test_lock_excludes_parallel_jobs_and_preserves_foreign_file(self):
        with auto.project_lock(self.config["state_directory"]):
            with self.assertRaisesRegex(auto.AutomationError, "ALREADY_RUNNING"):
                with auto.project_lock(self.config["state_directory"]):
                    self.fail("second job entered")
        path = Path(self.config["state_directory"]) / "automation.lock"
        path.unlink()
        target = private(self.root / "foreign", "unchanged")
        path.symlink_to(target)
        with self.assertRaises(OSError):
            with auto.project_lock(self.config["state_directory"]):
                self.fail("symlink accepted")
        self.assertEqual(target.read_text(), "unchanged")

    def test_candidate_manifest_is_accepted_by_the_deployed_backup_policy(self):
        value = {**deployment_config(), "api_image": "sha256:" + "f" * 64}
        path = private(self.root / "candidate.json", value)
        job = {"app_source_commit": value["source_commit"]}
        self.assertEqual(
            worker.verify_candidate_deployment(job, path)["status"], "image-source-verified"
        )
        with patch("ops.deploy.validate", side_effect=ValueError("older image policy")):
            with self.assertRaisesRegex(ValueError, "older image policy"):
                worker.verify_candidate_deployment(job, path)
        with self.assertRaisesRegex(backup.OperationError, "source differs"):
            worker.verify_candidate_deployment({"app_source_commit": "e" * 40}, path)

    def test_journal_records_failure_and_keeps_recovery_marker_pending(self):
        item = auto.Journal(self.config, "restore-check", "d" * 64)
        self.assertEqual(len(auto.unfinished_runs(self.config)), 1)
        item.phase("needs-recovery", reason="synthetic")
        item.finish(status="failed", error="RESOURCE_CLEANUP_FAILED")
        self.assertEqual(len(auto.unfinished_runs(self.config)), 1)
        backup.publish_json(item.directory / "recovered.json", {"status": "reconciled"})
        self.assertEqual(auto.unfinished_runs(self.config), [])
        self.assertEqual(stat.S_IMODE((item.directory / "finished.json").stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            item.finish(status="completed")

    def test_atomic_pointer_refuses_symlinks_and_writes_private_file(self):
        target = Path(self.config["state_directory"]) / "pointer.json"
        auto.atomic_json(target, {"version": 1})
        auto.atomic_json(target, {"version": 2})
        self.assertEqual(auto.read_json(target), {"version": 2})
        target.unlink()
        foreign = private(self.root / "foreign", "preserve")
        target.symlink_to(foreign)
        with self.assertRaises(backup.OperationError):
            auto.atomic_json(target, {"version": 3})
        self.assertEqual(foreign.read_text(), "preserve")

    def test_runner_timeout_and_failures_do_not_report_secret_output(self):
        runner = auto.Runner(self.config)
        with self.assertRaisesRegex(auto.AutomationError, "COMMAND_TIMEOUT"):
            runner.run([sys.executable, "-c", "import time; time.sleep(3)"], timeout=0.05)
        with self.assertRaises(auto.AutomationError) as failure:
            runner.run([sys.executable, "-c", "print('synthetic-secret'); raise SystemExit(2)"])
        self.assertNotIn("synthetic-secret", str(failure.exception))
        with patch.dict(os.environ, {"PGPASSWORD": "synthetic", "VITE_TOKEN": "synthetic"}):
            environment = auto.command_environment(self.config)
        self.assertNotIn("PGPASSWORD", environment)
        self.assertNotIn("VITE_TOKEN", environment)

    def test_worker_file_key_value_regression(self):
        good = (
            "[sallimbook]\nhost=db\nport=5432\ndbname=sallimbook_prod\n"
            "user=sallimbook_app\npassword=synthetic\nsslmode=disable\n"
        )
        path = private(self.root / "pgservice.conf", good)
        self.assertEqual(worker.validate_service_file(path), path)
        for wrong in (
            good.replace("host=db", "host = db"),
            good + "host=db\n",
            good.replace("host=db", "host=other"),
            good + "options=-c role=admin\n",
        ):
            private(path, wrong)
            with self.assertRaises(backup.OperationError):
                worker.validate_service_file(path)

    def test_restore_preparation_matches_real_connect_required_fields(self):
        job = {"run_id": str(uuid4())}
        self.assertEqual(worker.prepare_restore(job, self.root), {"status": "restore-prepared"})
        prepared = self.root / job["run_id"]
        service = prepared / "service.conf"
        env, database = backup.service_environment(service, restore=True)
        self.assertTrue(database.endswith("_restorecheck"))
        content = service.read_text()
        self.assertNotIn(" = ", content)
        self.assertEqual(stat.S_IMODE(service.stat().st_mode), 0o600)
        fake_driver = MagicMock()
        with (
            patch.dict(sys.modules, {"psycopg": fake_driver}),
            patch.dict(os.environ, {}, clear=True),
        ):
            backup.connect(env)
            parameters = fake_driver.connect.call_args.kwargs
            self.assertEqual(parameters["password"], (prepared / "db-password").read_text())
            self.assertGreater(len(parameters["password"]), 32)
            self.assertEqual(parameters["sslmode"], "disable")
            worker.create_restore_database(service)
            self.assertEqual(fake_driver.connect.call_args.kwargs["dbname"], "postgres")
            fake_driver.sql.SQL.assert_called_once_with("CREATE DATABASE {} TEMPLATE template0")
            fake_driver.sql.Identifier.assert_called_once_with(database)
        self.assertFalse((prepared / "admin-service.conf").exists())
        with self.assertRaises(FileExistsError):
            worker.prepare_restore(job, self.root)

    def test_backup_evidence_reads_actual_archive_and_detects_tamper(self):
        identifier = str(uuid4())
        path = private(self.root / (identifier + ".tar.age"), "synthetic-encrypted-archive")
        value = {
            "format": 1,
            "id": identifier,
            "file": path.name,
            "sha256": backup.digest(path),
            "bytes": path.stat().st_size,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        private(self.root / (identifier + ".complete.json"), value)
        self.assertEqual(worker.verify_backup_receipt(self.root, value), value)
        path.write_text("X" * value["bytes"])
        self.assertEqual(worker.verify_backup_receipt(self.root, value, check_hash=False), value)
        with self.assertRaisesRegex(backup.OperationError, "checksum"):
            worker.verify_backup_receipt(self.root, value)
        value["file"] = "../escape.tar.age"
        with self.assertRaises(backup.OperationError):
            worker.verify_backup_receipt(self.root, value)

    def test_ack_removes_only_verified_run_marker_after_host_anchor(self):
        identifier, run_id = str(uuid4()), str(uuid4())
        archive = private(self.root / (identifier + ".tar.age"), "synthetic ciphertext")
        value = {
            "format": 1,
            "id": identifier,
            "file": archive.name,
            "sha256": backup.digest(archive),
            "bytes": archive.stat().st_size,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        private(self.root / (identifier + ".complete.json"), value)
        marker = private(self.root / (".automation-" + run_id + ".json"), value)
        other = private(self.root / (".automation-" + str(uuid4()) + ".json"), value)
        result = worker.acknowledge_backup({"run_id": run_id, "backup": value}, self.root)
        self.assertEqual(result["status"], "backup-acknowledged")
        self.assertFalse(marker.exists())
        self.assertTrue(archive.exists())
        self.assertTrue(other.exists())
        self.assertEqual(
            worker.check_backup({"action": "backup-result", "run_id": run_id}, self.root),
            {"status": "backup-result-absent"},
        )

    def test_operator_bundle_checks_both_actual_helpers(self):
        files = {}
        for name in ("automation_worker.py", "restore_check.py"):
            files[name] = backup.digest(private(self.root / name, "synthetic source"))
        private(self.root / "operator-source.json", {"source_commit": "a" * 40, "files": files})
        worker.verify_operator_bundle(self.root, "a" * 40)
        (self.root / "restore_check.py").write_text("changed")
        with self.assertRaises(backup.OperationError):
            worker.verify_operator_bundle(self.root, "a" * 40)

    def test_failed_run_has_redacted_receipt(self):
        with (
            patch.object(auto, "load_config", return_value=self.config),
            patch.object(auto, "verify_operator_source"),
            patch.object(auto, "deployment_binding", return_value={}),
            patch.object(runtime, "Runtime") as mocked,
        ):
            mocked.return_value.backup.side_effect = ValueError("synthetic-secret")
            with self.assertRaisesRegex(auto.AutomationError, "OPERATION_FAILED"):
                auto.run(self.root / "config", "d" * 64, "backup", runner=MagicMock())
        result = auto.read_json(Path(self.config["state_directory"]) / "latest-backup.json")
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("synthetic-secret", json.dumps(result))

    def test_pending_run_blocks_new_backup_before_worker(self):
        auto.Journal(self.config, "restore-check", "d" * 64)
        with (
            patch.object(auto, "load_config", return_value=self.config),
            patch.object(auto, "verify_operator_source"),
            patch.object(auto, "deployment_binding", return_value={}),
            patch.object(runtime, "Runtime") as mocked,
        ):
            with self.assertRaisesRegex(auto.AutomationError, "RECOVERY_REQUIRED"):
                auto.run(self.root / "config", "d" * 64, "backup", runner=MagicMock())
        mocked.return_value.backup.assert_not_called()


class RestoreIntegrity(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.objects = self.root / "objects"
        self.objects.mkdir(mode=0o700)
        self.keyring = private(self.root / "keyring.json", {})
        private(self.root / "QUARANTINE", "quarantined")
        self.object = private(self.objects / ("a" * 32 + ".sbdoc"), "synthetic ciphertext")
        self.archive_sha = "e" * 64
        self.manifest = {
            "format": 1,
            "id": str(uuid4()),
            "schema_revision": "0030",
            "table_counts": {"synthetic": 3},
            "objects": {
                self.object.name: {
                    "bytes": self.object.stat().st_size,
                    "sha256": backup.digest(self.object),
                }
            },
        }
        self.restored = {
            "status": "quarantined",
            "database": "sallimbook_test_restorecheck",
            "backup_id": self.manifest["id"],
            "archive_sha256": self.archive_sha,
            "restored_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        }
        private(self.root / "restore.json", self.restored)
        private(self.root / "backup-manifest.json", self.manifest)
        self.connection = MagicMock()
        self.connection.execute.return_value.fetchone.return_value = ("0030",)
        stack = self.enterContext(ExitStack())
        stack.enter_context(
            patch.object(
                restore_check, "service_environment", return_value=({}, self.restored["database"])
            )
        )
        connection = stack.enter_context(patch.object(restore_check, "connect"))
        connection.return_value.__enter__.return_value = self.connection
        self.counts = stack.enter_context(
            patch.object(restore_check, "table_counts", return_value=self.manifest["table_counts"])
        )
        self.ciphertexts = stack.enter_context(patch.object(restore_check, "check_ciphertexts"))

    def verify(self):
        return restore_check.verify_restored_integrity(
            self.root / "service", self.root, self.keyring, self.archive_sha
        )

    def test_success_requires_actual_queries_hashes_and_authenticated_decryptions(self):
        result = self.verify()
        self.ciphertexts.assert_called_once_with(self.connection, self.objects, self.keyring)
        self.counts.assert_called_once_with(self.connection)
        queries = [call.args[0] for call in self.connection.execute.call_args_list]
        self.assertIn("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY", queries)
        self.assertIn("COMMIT", queries)
        self.assertEqual(result["checks"], dict.fromkeys(sorted(restore_check.CHECKS), True))
        self.assertEqual(
            result["restore_receipt_sha256"], backup.digest(self.root / "restore.json")
        )
        self.assertTrue((self.root / "QUARANTINE").exists())
        self.assertNotIn("synthetic", json.dumps(result))
        with self.assertRaisesRegex(backup.OperationError, "already exists"):
            self.verify()
        self.ciphertexts.assert_called_once()

    def test_bad_authenticated_ciphertext_never_creates_evidence(self):
        self.ciphertexts.side_effect = backup.OperationError("synthetic wrong key")
        with self.assertRaises(backup.OperationError):
            self.verify()
        self.assertFalse((self.root / restore_check.RECEIPT_NAME).exists())
        self.assertTrue(self.object.exists())
        self.assertTrue((self.root / "QUARANTINE").exists())

    def test_changed_object_or_counts_fail(self):
        self.object.write_text("tampered")
        with self.assertRaisesRegex(backup.OperationError, "checksum"):
            self.verify()
        self.ciphertexts.assert_not_called()
        self.object.write_text("synthetic ciphertext")
        self.counts.return_value = {"synthetic": 4}
        with self.assertRaisesRegex(backup.OperationError, "table inventory"):
            self.verify()
        self.assertFalse((self.root / restore_check.RECEIPT_NAME).exists())

    def test_metadata_race_fails_before_receipt(self):
        self.ciphertexts.side_effect = lambda *_: private(self.root / "restore.json", {})
        with self.assertRaisesRegex(backup.OperationError, "changed"):
            self.verify()
        self.assertFalse((self.root / restore_check.RECEIPT_NAME).exists())


class RuntimeBoundaries(unittest.TestCase):
    setUp = Boundaries.setUp

    def test_health_checks_build_and_daemon_filesystems(self):
        item = self.make_runtime()
        receipt = {"completed_at": datetime.now(UTC).isoformat()}
        for state_free, build_free, docker_free in (
            (2 * 1024**3, 2 * 1024**3, 2 * 1024**3),
            (2 * 1024**3, 0, 2 * 1024**3),
            (2 * 1024**3, 2 * 1024**3, 0),
        ):
            with (
                self.subTest(build_free=build_free, docker_free=docker_free),
                patch.object(item, "services", return_value={}),
                patch.object(item, "scanner", return_value={"fresh": True}),
                patch.object(item, "latest_backup", return_value=receipt),
                patch.object(
                    item,
                    "worker",
                    side_effect=[
                        {"disk_free_bytes": 2 * 1024**3},
                        {"disk_free_bytes": docker_free},
                    ],
                ) as worker_call,
                patch.object(
                    runtime.shutil,
                    "disk_usage",
                    side_effect=[MagicMock(free=state_free), MagicMock(free=build_free)],
                ),
            ):
                if min(build_free, docker_free) == 0:
                    with self.assertRaisesRegex(auto.AutomationError, "DISK_SPACE_LOW"):
                        item.health()
                else:
                    result = item.health()
                    self.assertEqual(result["build_disk_free_bytes"], build_free)
                    self.assertEqual(result["docker_disk_free_bytes"], docker_free)
                self.assertEqual(worker_call.call_args.args, ("storage",))
                self.assertEqual(worker_call.call_args.kwargs, {"timeout": 60})

    def make_runtime(self):
        journal = auto.Journal(self.config, "cvd-refresh", "d" * 64)
        binding = {
            "directory": str(self.root / "deployment"),
            "sha256": "c" * 64,
            "manifest": deployment_config(),
            "source_run": None,
        }
        return runtime.Runtime(self.config, binding, MagicMock(), journal)

    def test_worker_uses_readonly_nonroot_and_no_secret_argv(self):
        item = self.make_runtime()
        with patch.object(item, "bundle", return_value=self.root / "tools"):
            args = item.worker_args("synthetic", self.root / "job.json")
        self.assertIn("10001:10001", args)
        self.assertIn("--read-only", args)
        self.assertIn("no-new-privileges:true", args)
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertNotIn("--env", args)
        self.assertNotIn("/var/run/docker.sock", " ".join(args))

    def test_unowned_resource_is_never_removed(self):
        item = self.make_runtime()
        with (
            patch.object(item, "owned_containers", return_value=set()),
            patch.object(item, "docker") as docker,
        ):
            item.remove_container("existing-server")
        docker.assert_not_called()

    def test_lost_backup_response_is_recoverable_even_after_container_cleanup(self):
        item = self.make_runtime()
        item.journal.task = "backup"
        started = auto.read_json(item.journal.directory / "started.json")
        started["task"] = "backup"
        private(item.journal.directory / "started.json", started)
        with (
            patch.object(item, "database_network", return_value="synthetic-network"),
            patch.object(item, "worker", side_effect=auto.AutomationError("COMMAND_TIMEOUT")),
        ):
            with self.assertRaisesRegex(auto.AutomationError, "COMMAND_TIMEOUT"):
                item.backup()
        item.journal.finish(status="failed", error="COMMAND_TIMEOUT")
        pending = auto.unfinished_runs(self.config)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0][1]["run_id"], item.journal.run_id)
        recovery = self.make_runtime()
        with (
            patch.object(
                recovery,
                "worker",
                return_value={"status": "backup-verified", "backup": {"id": "synthetic"}},
            ),
            patch.object(recovery, "register_backup") as register,
            patch.object(recovery, "acknowledge_backup") as ack,
        ):
            recovery.recover(pending)
        register.assert_called_once_with({"id": "synthetic"})
        ack.assert_called_once_with({"id": "synthetic"}, run_id=item.journal.run_id)
        self.assertTrue((item.journal.directory / "recovered.json").exists())

    def test_cleanup_failure_keeps_recovery_marker(self):
        item = self.make_runtime()
        with (
            patch.object(item, "image"),
            patch.object(item, "worker_args", return_value=[]),
            patch.object(item, "docker", side_effect=auto.AutomationError("COMMAND_TIMEOUT")),
            patch.object(
                item, "remove_container", side_effect=auto.AutomationError("COMMAND_FAILED")
            ),
        ):
            with self.assertRaisesRegex(auto.AutomationError, "RESOURCE_CLEANUP_FAILED"):
                item.worker("backup")
        self.assertTrue((item.journal.directory / "needs-recovery.json").exists())

    def test_startup_preflight_failure_prevents_compose(self):
        item = self.make_runtime()
        with (
            patch.object(item, "preflight", side_effect=auto.AutomationError("PREFLIGHT_FAILED")),
            patch.object(item, "compose") as compose,
        ):
            with self.assertRaises(auto.AutomationError):
                item.startup()
        compose.assert_not_called()

    def test_restore_network_has_no_ports_and_failure_preserves_volume(self):
        item = self.make_runtime()
        calls = []

        def docker(*args, **kwargs):
            calls.append(args)
            return ""

        def worker_call(action, **kwargs):
            if action == "restore-prepare":
                return {"status": "restore-prepared"}
            if action == "restore-check":
                raise auto.AutomationError("SYNTHETIC_RESTORE_FAILURE")
            return {"status": "backup-verified"}

        with (
            patch.object(item, "latest_backup", return_value={}),
            patch.object(item, "docker", side_effect=docker),
            patch.object(item, "worker", side_effect=worker_call),
            patch.object(item, "_remove_owned") as cleanup,
        ):
            with self.assertRaisesRegex(auto.AutomationError, "SYNTHETIC_RESTORE_FAILURE"):
                item.restore_check()
        self.assertTrue(any(call[:3] == ("network", "create", "--internal") for call in calls))
        self.assertFalse(any("--publish" in call or "--network=host" in call for call in calls))
        self.assertEqual(
            [call.args[0] for call in cleanup.call_args_list], ["container", "network"]
        )
        self.assertTrue((item.journal.directory / "restore-quarantined.json").exists())

    def test_cvd_candidate_failure_leaves_old_deployment_and_images(self):
        item = self.make_runtime()

        @contextmanager
        def source(*args):
            yield self.root

        def build(*args, **kwargs):
            if args[0] == "build":
                Path(args[args.index("--iidfile") + 1]).write_text("sha256:" + "f" * 64)
            return ""

        with ExitStack() as stack:
            stack.enter_context(patch("ops.cvd_retention.Retention.prepare"))
            stack.enter_context(patch.object(item, "preflight"))
            stack.enter_context(patch.object(item, "services"))
            stack.enter_context(
                patch.object(item, "scanner", return_value={"fresh": True, "refresh_due": True})
            )
            stack.enter_context(patch.object(runtime, "source_snapshot", source))
            stack.enter_context(patch.object(runtime, "stage_api_snapshot", return_value="d" * 64))
            docker = stack.enter_context(patch.object(item, "docker", side_effect=build))
            stack.enter_context(patch.object(item, "image", return_value="sha256:" + "f" * 64))
            stack.enter_context(
                patch.object(item, "worker", return_value={"status": "image-source-verified"})
            )
            stack.enter_context(
                patch.object(
                    item,
                    "candidate_scanner",
                    side_effect=auto.AutomationError("CANDIDATE_SCANNER_STALE"),
                )
            )
            compose = stack.enter_context(patch.object(item, "compose"))
            with self.assertRaisesRegex(auto.AutomationError, "CANDIDATE_SCANNER_STALE"):
                item.cvd_refresh()
        compose.assert_not_called()
        self.assertFalse((Path(self.config["state_directory"]) / "active-deployment.json").exists())
        self.assertTrue(all(call.args[0] != "image" for call in docker.call_args_list))

    @contextmanager
    def prepared_cvd(self, item):
        @contextmanager
        def source(*args):
            yield self.root

        def build(*args, **kwargs):
            if args[0] == "build":
                Path(args[args.index("--iidfile") + 1]).write_text("sha256:" + "f" * 64)
            return ""

        with ExitStack() as stack:
            stack.enter_context(patch("ops.cvd_retention.Retention.prepare"))
            stack.enter_context(patch.object(item, "preflight"))
            stack.enter_context(
                patch.object(
                    item,
                    "scanner",
                    side_effect=[
                        {"fresh": True, "refresh_due": True},
                        {"fresh": True, "refresh_due": False},
                    ],
                )
            )
            stack.enter_context(patch.object(runtime, "source_snapshot", source))
            stack.enter_context(patch.object(runtime, "stage_api_snapshot", return_value="d" * 64))
            stack.enter_context(patch.object(item, "docker", side_effect=build))
            stack.enter_context(patch.object(item, "image", return_value="sha256:" + "f" * 64))
            stack.enter_context(
                patch.object(item, "worker", return_value={"status": "image-source-verified"})
            )
            stack.enter_context(
                patch.object(item, "candidate_scanner", return_value={"fresh": True})
            )
            compose = stack.enter_context(patch.object(item, "compose"))
            yield compose

    def test_cvd_failed_promotion_rolls_back_before_pointer_commit(self):
        item = self.make_runtime()
        original = dict(item.manifest)
        with (
            self.prepared_cvd(item) as compose,
            patch.object(
                item, "services", side_effect=[{}, auto.AutomationError("SERVICE_UNHEALTHY"), {}]
            ),
        ):
            with self.assertRaisesRegex(auto.AutomationError, "SERVICE_UNHEALTHY"):
                item.cvd_refresh()
        self.assertEqual(compose.call_count, 2)
        self.assertIn("binding", compose.call_args_list[0].kwargs)
        self.assertNotIn("binding", compose.call_args_list[1].kwargs)
        self.assertEqual(item.manifest, original)
        self.assertFalse((Path(self.config["state_directory"]) / "active-deployment.json").exists())
        self.assertTrue((item.journal.directory / "promotion-rolled-back.json").exists())

    def test_cvd_uncertain_atomic_commit_preserves_new_services_for_recovery(self):
        item = self.make_runtime()

        def committed_then_failed(path, value):
            auto.atomic_json(path, value)
            raise OSError("synthetic fsync failure")

        with (
            self.prepared_cvd(item) as compose,
            patch.object(item, "services", return_value={}),
            patch.object(runtime, "atomic_json", side_effect=committed_then_failed),
        ):
            with self.assertRaisesRegex(auto.AutomationError, "PROMOTION_COMMIT_UNCERTAIN"):
                item.cvd_refresh()
        self.assertEqual(compose.call_count, 1)
        self.assertTrue((item.journal.directory / "needs-recovery.json").exists())
        pointer = auto.read_json(Path(self.config["state_directory"]) / "active-deployment.json")
        self.assertEqual(pointer["source_run"], item.journal.run_id)

    def test_successful_cvd_keeps_web_apk_and_app_source_binding(self):
        item = self.make_runtime()
        with self.prepared_cvd(item) as compose, patch.object(item, "services", return_value={}):
            result = item.cvd_refresh()
        candidate = compose.call_args.kwargs["binding"]["manifest"]
        self.assertEqual(candidate["api_image"], "sha256:" + "f" * 64)
        self.assertEqual(
            {k: v for k, v in candidate.items() if k != "api_image"},
            {k: v for k, v in item.manifest.items() if k != "api_image"},
        )
        self.assertEqual(result["status"], "scanner-refresh-promoted")
        self.assertTrue(result["web_and_apk_unchanged"])

    def test_recovery_cleans_only_recorded_owned_containers_and_networks(self):
        item = self.make_runtime()
        previous = auto.Journal(self.config, "restore-check", "d" * 64)
        for number, kind in enumerate(("container", "network", "volume")):
            previous.phase("resource-" + str(number), kind=kind, name="synthetic-" + kind)
        with (
            patch.object(item, "remove_container") as containers,
            patch.object(item, "_remove_owned") as remove,
        ):
            item.recover(auto.unfinished_runs(self.config, exclude=item.journal.run_id))
        containers.assert_called_once_with("synthetic-container", run_id=previous.run_id)
        remove.assert_called_once_with("network", "synthetic-network", previous.run_id)
        self.assertTrue((previous.directory / "recovered.json").exists())


class BuildPermissions(unittest.TestCase):
    def test_exact_git_archive_directories_remain_traversable_under_private_umask(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as archive:
            member = tarfile.TarInfo("src")
            member.type = tarfile.DIRTYPE
            member.mode = 0o755
            archive.addfile(member)
            member = tarfile.TarInfo("src/app.py")
            member.mode = 0o644
            member.size = 4
            archive.addfile(member, io.BytesIO(b"pass"))
        data.seek(0)
        process = MagicMock()
        process.stdout = data
        process.wait.return_value = 0
        with tempfile.TemporaryDirectory() as temporary:
            old_umask = os.umask(0o077)
            try:
                with patch.object(build_context.subprocess, "Popen", return_value=process):
                    with build_context.source_snapshot("a" * 40, Path(temporary)) as checkout:
                        self.assertEqual(stat.S_IMODE((checkout / "src").stat().st_mode), 0o755)
                        self.assertEqual(
                            stat.S_IMODE((checkout / "src/app.py").stat().st_mode), 0o644
                        )
            finally:
                os.umask(old_umask)

    def test_api_only_staging_works_under_private_umask(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "source"
            for directory in (
                "services/api/src",
                "services/api/migrations",
                "ops",
                "infra/documents",
            ):
                (checkout / directory).mkdir(parents=True)
            for name in (
                "services/api/uv.lock",
                "services/api/alembic.ini",
                "ops/Dockerfile.api",
                "infra/documents/freshclam.conf",
                "infra/documents/clamd.conf",
            ):
                (checkout / name).write_text("synthetic")
            old_umask = os.umask(0o077)
            try:
                with (
                    patch.object(
                        build_context.subprocess,
                        "check_output",
                        return_value=b"pkg --hash=sha256:abcd",
                    ),
                    patch.object(build_context.subprocess, "run") as command,
                ):
                    build_context.stage_api_snapshot(root / "api", "a" * 40, checkout)
            finally:
                os.umask(old_umask)
            command.assert_not_called()
            for name in (
                "source-revision.json",
                "requirements.txt",
                "alembic.ini",
                "freshclam.conf",
                "clamd.conf",
            ):
                self.assertEqual(stat.S_IMODE((root / "api" / name).stat().st_mode), 0o644)
            self.assertFalse((root / "web").exists())
