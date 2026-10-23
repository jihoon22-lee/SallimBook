"""Synthetic owned-artifact deletion and fail-closed retention boundaries."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from ops import automation as auto
from ops import backup, deploy, schedule
from ops import cvd_retention as cvd
from tests.operations.test_automation import configuration, private
from tests.operations.test_operations import config as deployment_config


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.enterContext(
            patch.object(cvd.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * 1024**3))
        )
        self.config = configuration(self.root)
        for key in ("state_directory", "build_directory"):
            Path(self.config[key]).mkdir(parents=True, mode=0o700)
        self.manifest = deployment_config()
        deploy.write_config(self.manifest, Path(self.config["deployment_directory"]))
        self.config["deployment_sha256"] = backup.digest(
            Path(self.config["deployment_directory"]) / "deployment.json"
        )
        self.runtime = SimpleNamespace(
            config=self.config,
            project=self.config["project"],
            manifest=self.manifest,
            binding=auto.deployment_binding(self.config),
            journal=auto.Journal(self.config, "cvd-refresh", "d" * 64),
            worker=MagicMock(return_value={"disk_free_bytes": 10 * 1024**3}),
        )
        self.retention = cvd.Retention(self.runtime)
        self.images = {}
        self.containers = set()
        self.calls = []
        self.runtime.docker = self.docker

    def docker(self, *args, **kwargs):
        self.calls.append(args)
        if args[:2] == ("image", "inspect"):
            if args[3] == "{{json .Id}}":
                return json.dumps(self.images.get(args[-1], {}).get("id", args[-1]))
            return json.dumps(self.images[args[-1]])
        if args[:2] == ("container", "ls"):
            return "synthetic-container" if args[-2][9:] in self.containers else ""
        if args[:2] == ("image", "rm"):
            del self.images[args[-1]]
            return ""
        if args[:2] == ("image", "ls"):
            if "--quiet" in args:
                return "\n".join(value["id"] for value in self.images.values())
            return "\n".join(self.images)
        raise AssertionError(args)

    def generation(self):
        journal = auto.Journal(self.config, "cvd-refresh", "d" * 64)
        root = Path(self.config["build_directory"]) / journal.run_id
        root.mkdir(mode=0o700)
        image_id = "sha256:" + journal.run_id.replace("-", "") * 2
        tag = self.retention.tag(root.name)
        deploy.write_config({**self.manifest, "api_image": image_id}, root / "deployment")
        private(root / "image-id", image_id)
        self.retention.seal(root, tag, image_id)
        journal.finish(status="completed")
        self.images[tag] = {
            "id": image_id,
            "tags": [tag],
            "digests": ["synthetic@" + image_id],
            "labels": self.retention.labels(root.name),
        }
        return root, tag, image_id, journal

    def test_only_exact_owned_tag_is_removed_and_tree_is_deleted(self):
        root, tag, _, _ = self.generation()
        result = self.retention.prepare()
        self.assertEqual(result["removed_generations"], [root.name])
        self.assertFalse(root.exists())
        self.assertEqual(
            [call for call in self.calls if call[:2] == ("image", "rm")],
            [("image", "rm", "--no-prune", tag)],
        )
        self.assertFalse(any("--force" in call or "prune" in call for call in self.calls))

    def test_current_previous_and_baseline_are_protected(self):
        previous, _, previous_id, _ = self.generation()
        current, _, current_id, journal = self.generation()
        journal.phase(
            "promotion-started",
            previous_directory=str(previous / "deployment"),
            previous_sha256=backup.digest(previous / "deployment/deployment.json"),
        )
        auto.atomic_json(
            Path(self.config["state_directory"]) / "active-deployment.json",
            {
                "format": 1,
                "project": self.runtime.project,
                "directory": str(current / "deployment"),
                "sha256": backup.digest(current / "deployment/deployment.json"),
                "source_run": current.name,
            },
        )
        self.runtime.binding = auto.deployment_binding(self.config)
        self.runtime.manifest = self.runtime.binding["manifest"]
        paths, images = self.retention.protected()
        self.assertEqual(len(paths), 3)
        self.assertTrue({previous_id, current_id}.issubset(images))
        self.retention.prepare()
        self.assertTrue(previous.exists() and current.exists())

    def test_shared_tag_container_and_wrong_labels_preserve_artifacts(self):
        for reason in ("tag", "container", "label", "id"):
            with self.subTest(reason=reason):
                root, tag, image_id, _ = self.generation()
                if reason == "tag":
                    self.images[tag]["tags"].append("foreign:keep")
                elif reason == "container":
                    self.containers.add(image_id)
                elif reason == "label":
                    self.images[tag]["labels"][cvd.PREFIX + "project"] = "other-project"
                else:
                    self.images[tag]["id"] = "sha256:" + "f" * 64
                self.retention.prepare()
                self.assertTrue(root.exists())

    def test_modified_symlink_hardlink_and_incomplete_are_preserved(self):
        for reason in ("changed", "symlink", "hardlink", "incomplete"):
            with self.subTest(reason=reason):
                root, _, _, journal = self.generation()
                if reason == "changed":
                    (root / "image-id").write_text("changed")
                elif reason == "symlink":
                    (root / "outside").symlink_to(self.root)
                elif reason == "hardlink":
                    os.link(root / "image-id", root / "extra")
                else:
                    (journal.directory / "finished.json").unlink()
                self.retention.prepare()
                self.assertTrue(root.exists())

    def test_other_saved_manifest_reference_is_protected(self):
        root, _, image_id, _ = self.generation()
        other = Path(self.config["build_directory"]) / "legacy"
        other.mkdir(mode=0o700)
        deploy.write_config({**self.manifest, "api_image": image_id}, other / "deployment")
        self.retention.prepare()
        self.assertTrue(root.exists())

    def test_untag_uncertainty_preserves_tree(self):
        root, tag, image_id, _ = self.generation()
        original = self.runtime.docker

        def uncertain(*args, **kwargs):
            if args[:2] == ("image", "ls") and "--quiet" in args:
                return image_id
            return original(*args, **kwargs)

        self.runtime.docker = uncertain
        with self.assertRaisesRegex(auto.AutomationError, "CVD_UNTAG_UNCERTAIN"):
            self.retention.prepare()
        self.assertTrue(root.exists())
        self.assertNotIn(tag, self.images)

    def test_receiptless_generations_and_orphans_stop_at_cap(self):
        for number in range(cvd.MAX_GENERATIONS - 1):
            (Path(self.config["build_directory"]) / str(number)).mkdir(mode=0o700)
        self.images["orphan:tag"] = {"id": "sha256:" + "f" * 64}
        with self.assertRaisesRegex(auto.AutomationError, "CVD_GENERATION_LIMIT"):
            self.retention.prepare()
        self.runtime.worker.assert_not_called()

    def test_low_build_or_daemon_space_stops_before_build(self):
        for host, daemon in ((0, 10 * 1024**3), (10 * 1024**3, 0)):
            with self.subTest(host=host, daemon=daemon):
                self.runtime.worker.return_value = {"disk_free_bytes": daemon}
                with patch.object(
                    cvd.shutil, "disk_usage", return_value=SimpleNamespace(free=host)
                ):
                    with self.assertRaisesRegex(auto.AutomationError, "CVD_BUILD_SPACE_LOW"):
                        self.retention.prepare()

    def test_binding_change_blocks_deletion(self):
        root, _, _, _ = self.generation()
        self.runtime.binding = {**self.runtime.binding, "sha256": "e" * 64}
        with self.assertRaisesRegex(auto.AutomationError, "CVD_BINDING_CHANGED"):
            self.retention.prepare()
        self.assertTrue(root.exists())

    PREVIOUS_OPERATOR = "c" * 40

    def previous_operator(self):
        """The configuration that built earlier generations: another commit and state dir."""
        state = self.root / "previous-state-directory" / self.config["project"]
        state.mkdir(parents=True, mode=0o700)
        config = {
            **self.config,
            "state_directory": str(state),
            "operator_source_commit": self.PREVIOUS_OPERATOR,
        }
        runtime = SimpleNamespace(**{**vars(self.runtime), "config": config})
        return state, config, cvd.Retention(runtime)

    def older_generation(self, previous, *, finished=True):
        """A generation sealed by the previous operator and journalled in its state dir."""
        _, config, retention = previous
        journal = auto.Journal(config, "cvd-refresh", "d" * 64)
        root = Path(self.config["build_directory"]) / journal.run_id
        root.mkdir(mode=0o700)
        image_id = "sha256:" + journal.run_id.replace("-", "") * 2
        tag = retention.tag(root.name)
        deploy.write_config({**self.manifest, "api_image": image_id}, root / "deployment")
        private(root / "image-id", image_id)
        retention.seal(root, tag, image_id)
        if finished:
            journal.finish(status="completed")
        self.images[tag] = {
            "id": image_id,
            "tags": [tag],
            "digests": ["synthetic@" + image_id],
            "labels": retention.labels(root.name),
        }
        return root, tag, image_id

    def promote(self, current, previous):
        """Make `current` the active generation and `previous` its rollback target."""
        current_root, _, _, journal = current
        journal.phase(
            "promotion-started",
            previous_directory=str(previous / "deployment"),
            previous_sha256=backup.digest(previous / "deployment/deployment.json"),
        )
        auto.atomic_json(
            Path(self.config["state_directory"]) / "active-deployment.json",
            {
                "format": 1,
                "project": self.runtime.project,
                "directory": str(current_root / "deployment"),
                "sha256": backup.digest(current_root / "deployment/deployment.json"),
                "source_run": current_root.name,
            },
        )
        self.runtime.binding = auto.deployment_binding(self.config)
        self.runtime.manifest = self.runtime.binding["manifest"]

    def test_generations_of_a_previous_operator_fill_the_cap_until_pruned(self):
        previous = self.previous_operator()
        old = [self.older_generation(previous)[0] for _ in range(cvd.MAX_GENERATIONS)]
        # The regular pre-build retention keeps them (other operator commit, other state).
        with self.assertRaisesRegex(auto.AutomationError, "CVD_GENERATION_LIMIT"):
            self.retention.prepare()
        self.assertTrue(all(root.exists() for root in old))
        result = self.retention.prune([old[-1].name], previous_states=[previous[0]])
        self.assertEqual(sorted(result["removed_generations"]), sorted(r.name for r in old[:-1]))
        self.assertEqual([root.exists() for root in old], [False] * (len(old) - 1) + [True])
        self.assertEqual(self.retention.prepare()["removed_generations"], [])

    def test_prune_keeps_the_active_and_rollback_generations(self):
        previous = self.previous_operator()
        stale = [self.older_generation(previous) for _ in range(2)]
        rollback, rollback_tag, rollback_id = self.older_generation(previous)
        active = self.generation()
        self.promote(active, rollback)
        spare = self.generation()
        paths, images = self.retention.protected()
        self.assertEqual(len(paths), 3)
        self.assertTrue({rollback_id, active[2]}.issubset(images))
        result = self.retention.prune(
            [active[0].name, rollback.name], previous_states=[previous[0]]
        )
        self.assertEqual(
            sorted(result["removed_generations"]),
            sorted([stale[0][0].name, stale[1][0].name, spare[0].name]),
        )
        self.assertTrue(active[0].exists() and rollback.exists())
        self.assertFalse(any(root.exists() for root in (stale[0][0], stale[1][0], spare[0])))
        removed = [call for call in self.calls if call[:2] == ("image", "rm")]
        self.assertEqual(
            sorted(call[-1] for call in removed),
            sorted([stale[0][1], stale[1][1], spare[1]]),
        )
        self.assertTrue(all(call[:3] == ("image", "rm", "--no-prune") for call in removed))
        self.assertIn(rollback_tag, self.images)
        self.assertIn(active[1], self.images)

    def test_prune_never_removes_a_protected_generation_even_if_not_listed(self):
        previous = self.previous_operator()
        rollback, _, _ = self.older_generation(previous)
        active = self.generation()
        self.promote(active, rollback)
        result = self.retention.prune([active[0].name], previous_states=[previous[0]])
        self.assertEqual(result["removed_generations"], [])
        self.assertTrue(active[0].exists() and rollback.exists())
        self.assertEqual(result["protected_generations"], [rollback.name])

    def test_prune_rejects_keep_ids_that_are_not_generations(self):
        root, _, _, _ = self.generation()
        for keep in (["not-a-uuid"], [str(uuid4())], [root.name, "../" + root.name]):
            with self.subTest(keep=keep):
                with self.assertRaisesRegex(auto.AutomationError, "CVD_KEEP"):
                    self.retention.prune(keep)
                self.assertTrue(root.exists())
        with self.assertRaisesRegex(auto.AutomationError, "CVD_KEEP"):
            self.retention.prune([])

    def test_previous_operator_generations_need_their_journal_to_be_pruned(self):
        previous = self.previous_operator()
        keep = self.generation()[0]
        unfinished, _, _ = self.older_generation(previous, finished=False)
        proven, _, _ = self.older_generation(previous)
        # Without the previous state directory nothing proves the generation completed.
        self.assertEqual(self.retention.prune([keep.name])["removed_generations"], [])
        self.assertTrue(unfinished.exists() and proven.exists())
        result = self.retention.prune([keep.name], previous_states=[previous[0]])
        self.assertEqual(result["removed_generations"], [proven.name])
        self.assertTrue(unfinished.exists())
        self.assertIn(unfinished.name, result["skipped_generations"])

    def test_prune_keeps_every_per_generation_check(self):
        previous = self.previous_operator()
        keep = self.generation()[0]
        for reason in ("tag", "container", "label", "changed", "symlink", "hardlink"):
            with self.subTest(reason=reason):
                root, tag, image_id = self.older_generation(previous)
                if reason == "tag":
                    self.images[tag]["tags"].append("foreign:keep")
                elif reason == "container":
                    self.containers.add(image_id)
                elif reason == "label":
                    self.images[tag]["labels"][cvd.PREFIX + "operator-source"] = "e" * 40
                elif reason == "changed":
                    (root / "image-id").write_text("changed")
                elif reason == "symlink":
                    (root / "outside").symlink_to(self.root)
                else:
                    os.link(root / "image-id", root / "extra")
                result = self.retention.prune([keep.name], previous_states=[previous[0]])
                self.assertNotIn(root.name, result["removed_generations"])
                self.assertTrue(root.exists())
                self.assertIn(tag, self.images)
                self.assertFalse(any(call[:2] == ("image", "rm") for call in self.calls))

    def test_binding_change_or_untag_uncertainty_stops_prune_before_deleting_files(self):
        previous = self.previous_operator()
        root, tag, image_id = self.older_generation(previous)
        keep = self.generation()[0]
        original = self.runtime.docker

        def uncertain(*args, **kwargs):
            if args[:2] == ("image", "ls") and "--quiet" in args:
                return image_id
            return original(*args, **kwargs)

        self.runtime.docker = uncertain
        with self.assertRaisesRegex(auto.AutomationError, "CVD_UNTAG_UNCERTAIN"):
            self.retention.prune([keep.name], previous_states=[previous[0]])
        self.assertTrue(root.exists())
        self.assertNotIn(tag, self.images)
        self.runtime.docker = original
        self.runtime.binding = {**self.runtime.binding, "sha256": "e" * 64}
        with self.assertRaisesRegex(auto.AutomationError, "CVD_BINDING_CHANGED"):
            self.retention.prune([keep.name], previous_states=[previous[0]])

    def test_dry_run_reports_without_removing_anything(self):
        previous = self.previous_operator()
        root, tag, _ = self.older_generation(previous)
        keep = self.generation()[0]
        result = self.retention.prune([keep.name], previous_states=[previous[0]], dry_run=True)
        self.assertEqual(result["would_remove_generations"], [root.name])
        self.assertNotIn("removed_generations", result)
        self.assertTrue(root.exists())
        self.assertIn(tag, self.images)
        self.assertFalse(any(call[:2] == ("image", "rm") for call in self.calls))

    def test_prune_is_a_journalled_task_that_cannot_run_through_the_schedule(self):
        self.assertIn("cvd-prune", auto.TASKS)
        self.assertNotIn("cvd-prune", auto.CLI_TASKS)
        self.assertNotIn("cvd-prune", {*schedule.CALENDARS, "startup"})
        auto.Journal(self.config, "restore-check", "d" * 64)
        with (
            patch.object(auto, "load_config", return_value=self.config),
            patch.object(auto, "verify_operator_source"),
            patch.object(auto, "deployment_binding", return_value={}),
            patch("ops.automation_runtime.Runtime") as mocked,
        ):
            with self.assertRaisesRegex(auto.AutomationError, "RECOVERY_REQUIRED"):
                auto.run(
                    self.root / "config",
                    "d" * 64,
                    "cvd-prune",
                    runner=MagicMock(),
                    arguments={"keep": []},
                )
        mocked.return_value.cvd_prune.assert_not_called()

    def test_command_line_maps_to_the_journalled_task(self):
        keep, previous = str(uuid4()), self.root / "previous-state"
        outcome = {"status": "completed", "result": {"removed_generations": []}}
        configuration = self.root / "config.json"
        with (
            patch.object(cvd, "run", return_value=outcome) as run,
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            code = cvd.main(
                [
                    "prune",
                    str(configuration),
                    "--sha256",
                    "d" * 64,
                    "--keep",
                    keep,
                    "--previous-state",
                    str(previous),
                    "--dry-run",
                ]
            )
        self.assertEqual(code, 0)
        run.assert_called_once_with(
            configuration,
            "d" * 64,
            "cvd-prune",
            arguments={"keep": [keep], "previous_states": [previous], "dry_run": True},
        )
        self.assertEqual(json.loads(output.getvalue()), outcome["result"])
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            cvd.main(["prune", str(configuration), "--sha256", "d" * 64])
        with (
            patch.object(cvd, "run", side_effect=auto.AutomationError("CVD_KEEP_UNKNOWN")),
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            code = cvd.main(["prune", str(configuration), "--sha256", "d" * 64, "--keep", keep])
        self.assertEqual(code, 1)
        self.assertEqual(
            json.loads(output.getvalue()), {"status": "failed", "code": "CVD_KEEP_UNKNOWN"}
        )

    def test_backup_schedule_covers_worker_and_actual_orchestration_budget(self):
        # 2 git checks + network + worker image + 2 helper git shows + ack image
        # + ack + 3 cleanup Docker calls + process termination grace.
        overhead = (2 + 1 + 1 + 2 + 1 + 1 + 3) * 60 + 12 * 5
        self.assertGreaterEqual(auto.BACKUP_OVERHEAD_BUDGET, overhead)
        self.assertEqual(auto.LIMITS["backup"], auto.BACKUP_WORKER_TIMEOUT + 900)
        service = schedule.units(self.config, self.root / "configuration.json", "a" * 64)[
            self.runtime.project + "-backup.service"
        ]
        self.assertIn("TimeoutStartSec=2700\n", service)
