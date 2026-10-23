"""Validate systemd artifacts with synthetic files and mocked systemctl only."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ops import automation, backup, schedule
from tests.operations.test_automation import configuration, private


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = configuration(self.root)
        self.configuration = private(self.root / "configuration.json", self.config)
        self.sha = backup.digest(self.configuration)
        self.directory = self.root / "rendered"
        self.destination = self.root / "user-units"
        self.runner = MagicMock()
        self.calls = []

        def command(args, **kwargs):
            self.calls.append([str(value) for value in args])
            if args[0] == "git":
                return self.config["operator_source_commit"] if args[1] == "rev-parse" else ""
            if args[1:] == ["--user", "unit-paths"]:
                return str(self.destination) + "\n"
            if args[1:4] == ["--user", "show", "--property=DropInPaths"]:
                directory = self.destination / (args[-1] + ".d")
                return " ".join(str(path) for path in sorted(directory.glob("*.conf"))) + "\n"
            return ""

        self.runner.run.side_effect = command
        self.enterContext(patch.object(schedule, "load_config", return_value=self.config))
        self.enterContext(patch.object(schedule, "unit_directory", return_value=self.destination))
        schedule.render(self.configuration, self.sha, self.directory)

    def test_render_is_pinned_and_never_installs_or_activates(self):
        self.assertEqual(len(list(self.directory.glob("*.service"))), 5)
        self.assertEqual(len(list(self.directory.glob("*.timer"))), 4)
        self.assertFalse(self.destination.exists())
        for path in self.directory.glob("*.service"):
            value = path.read_text()
            self.assertIn("--sha256 " + self.sha, value)
            self.assertIn("UMask=0077", value)
            self.assertNotIn("/bin/sh", value)
            if "startup" not in path.name:
                self.assertIn("RestartPreventExitStatus=1", value)
        for path in self.directory.glob("*.timer"):
            self.assertIn("Asia/Seoul", path.read_text())
            self.assertIn("Persistent=true", path.read_text())

    def test_validate_checks_all_files_without_systemctl(self):
        schedule.validate(self.directory, runner=self.runner)
        self.assertTrue(
            any(call[:3] == ["/usr/bin/systemd-analyze", "--user", "verify"] for call in self.calls)
        )
        self.assertFalse(any(call[0] == "/usr/bin/systemctl" for call in self.calls))
        path = next(self.directory.glob("*.service"))
        path.write_text(path.read_text() + "ExecStartPost=/bin/false\n")
        with self.assertRaisesRegex(automation.AutomationError, "SCHEDULE_CHANGED"):
            schedule.validate(self.directory, runner=self.runner)

    def test_install_only_new_files_and_reload(self):
        result = schedule.install(self.directory, runner=self.runner)
        self.assertEqual(result["status"], "installed-inactive")
        self.assertEqual(len(list(self.destination.iterdir())), 9)
        self.assertEqual(
            [call for call in self.calls if call[0] == "/usr/bin/systemctl"],
            [["/usr/bin/systemctl", "--user", "daemon-reload"]],
        )
        with self.assertRaisesRegex(automation.AutomationError, "ALREADY_INSTALLED"):
            schedule.install(self.directory, runner=self.runner)

    def test_existing_unit_or_dropin_is_preserved(self):
        self.destination.mkdir()
        name = self.config["project"] + "-backup.service"
        path = private(self.destination / name, "existing user unit")
        with self.assertRaisesRegex(automation.AutomationError, "UNIT_ALREADY_EXISTS"):
            schedule.install(self.directory, runner=self.runner)
        self.assertEqual(path.read_text(), "existing user unit")
        self.assertEqual(len(list(self.destination.iterdir())), 1)
        path.unlink()
        (self.destination / (name + ".d")).mkdir()
        with self.assertRaisesRegex(automation.AutomationError, "UNIT_ALREADY_EXISTS"):
            schedule.install(self.directory, runner=self.runner)

    def test_activate_is_explicit_and_only_enables_five_own_units(self):
        schedule.install(self.directory, runner=self.runner)
        self.calls.clear()
        result = schedule.activate(self.directory, runner=self.runner)
        enabled = [call[-1] for call in self.calls if "enable" in call]
        self.assertEqual(enabled, result["units"])
        self.assertEqual(len(enabled), 5)
        self.assertEqual(enabled[0], self.config["project"] + "-startup.service")
        self.assertTrue(all(name.startswith(self.config["project"] + "-") for name in enabled))
        self.assertFalse(any("loginctl" in arg for call in self.calls for arg in call))

    def test_activation_rejects_changed_installation(self):
        schedule.install(self.directory, runner=self.runner)
        name = self.config["project"] + "-backup.service"
        (self.destination / name).write_text("changed by user")
        with self.assertRaisesRegex(automation.AutomationError, "INSTALLED_UNIT_CHANGED"):
            schedule.activate(self.directory, runner=self.runner)
        self.assertFalse(any("enable" in call for call in self.calls))

    def test_partial_activation_rolls_back_only_attempted_own_units(self):
        schedule.install(self.directory, runner=self.runner)
        original = self.runner.run.side_effect

        def command(args, **kwargs):
            if "enable" in args and "backup.timer" in args[-1]:
                self.calls.append(args)
                raise automation.AutomationError("COMMAND_FAILED")
            return original(args, **kwargs)

        self.runner.run.side_effect = command
        with self.assertRaises(automation.AutomationError):
            schedule.activate(self.directory, runner=self.runner)
        disabled = [call[-1] for call in self.calls if "disable" in call]
        self.assertEqual(
            disabled,
            [self.config["project"] + "-backup.timer", self.config["project"] + "-startup.service"],
        )
        self.assertFalse((self.directory / "activation.json").exists())

    def test_failed_disable_does_not_skip_remaining_rollback_and_is_recorded(self):
        schedule.install(self.directory, runner=self.runner)
        original = self.runner.run.side_effect

        def command(args, **kwargs):
            if ("enable" in args and "health.timer" in args[-1]) or (
                "disable" in args and "health.timer" in args[-1]
            ):
                self.calls.append(args)
                raise automation.AutomationError("COMMAND_FAILED")
            return original(args, **kwargs)

        self.runner.run.side_effect = command
        with self.assertRaisesRegex(automation.AutomationError, "ACTIVATION_ROLLBACK_INCOMPLETE"):
            schedule.activate(self.directory, runner=self.runner)
        disabled = [call[-1] for call in self.calls if "disable" in call]
        prefix = self.config["project"] + "-"
        self.assertEqual(
            disabled, [prefix + "health.timer", prefix + "backup.timer", prefix + "startup.service"]
        )
        failure = automation.read_json(self.directory / "activation-failed.json")
        self.assertEqual(failure["rollback_failed"], [prefix + "health.timer"])
        self.assertEqual(
            failure["rollback_completed"], [prefix + "backup.timer", prefix + "startup.service"]
        )
        self.assertFalse((self.directory / "activation.json").exists())

    def test_manifest_cannot_introduce_arbitrary_unit(self):
        path = self.directory / "schedule.json"
        value = json.loads(path.read_text())
        value["files"]["existing.service"] = "0" * 64
        private(path, value)
        with self.assertRaisesRegex(automation.AutomationError, "SCHEDULE_FILES"):
            schedule.validate(self.directory, runner=self.runner)

    def test_rollback_renders_a_fresh_directory_from_the_same_configuration(self):
        schedule.install(self.directory, runner=self.runner)
        schedule.activate(self.directory, runner=self.runner)
        # The operator removes the switched units first; the used directory stays refused.
        for path in self.destination.iterdir():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        with self.assertRaisesRegex(automation.AutomationError, "SCHEDULE_ALREADY_INSTALLED"):
            schedule.install(self.directory, runner=self.runner)
        with self.assertRaises(FileExistsError):
            schedule.render(self.configuration, self.sha, self.directory)
        fresh = self.root / "rollback-schedule"
        schedule.render(self.configuration, self.sha, fresh)
        schedule.validate(fresh, runner=self.runner)
        self.assertEqual(schedule.install(fresh, runner=self.runner)["units"], 9)
        self.assertEqual(len(schedule.activate(fresh, runner=self.runner)["units"]), 5)
        self.assertTrue((fresh / "activation.json").exists())

    def test_rendered_schedule_has_no_pre_step_and_no_dropin(self):
        # `Restart=on-failure` also applies to ExecStartPre, and RestartPreventExitStatus covers
        # only the main process, so a pre-step failing on DISK_SPACE_LOW would retry every
        # minute. The disk check is the first step of the health task instead.
        project = self.config["project"]
        self.assertEqual(sorted(path.name for path in self.directory.glob("*.d")), [])
        self.assertEqual(sorted(path.name for path in self.directory.glob("**/*.conf")), [])
        for path in self.directory.glob("*.service"):
            self.assertNotIn("ExecStartPre", path.read_text())
        health = (self.directory / (project + "-health.service")).read_text()
        self.assertIn("RestartPreventExitStatus=1", health)
        self.assertIn(f"TimeoutStartSec={automation.LIMITS['health']}\n", health)
        record = automation.read_json(self.directory / "schedule.json")
        self.assertEqual(len(record["files"]), 9)

    def test_activate_still_refuses_a_foreign_dropin(self):
        project = self.config["project"]
        schedule.install(self.directory, runner=self.runner)
        folder = self.destination / (project + "-health.service.d")
        folder.mkdir(mode=0o700)
        private(folder / "backup-pause-disk-check.conf", "[Service]\nExecStartPre=/bin/true\n")
        with self.assertRaisesRegex(automation.AutomationError, "INSTALLED_UNIT_CHANGED"):
            schedule.activate(self.directory, runner=self.runner)
        shutil.rmtree(folder)
        # A drop-in systemd loads from a path this tool never wrote.
        original = self.runner.run.side_effect
        self.runner.run.side_effect = lambda args, **kwargs: (
            f"/etc/systemd/user/{args[-1]}.d/50.conf\n"
            if args[1:4] == ["--user", "show", "--property=DropInPaths"]
            else original(args, **kwargs)
        )
        self.calls.clear()
        with self.assertRaisesRegex(automation.AutomationError, "INSTALLED_UNIT_OVERRIDE"):
            schedule.activate(self.directory, runner=self.runner)
        self.assertFalse(any("enable" in call for call in self.calls))
        self.assertFalse((self.directory / "activation.json").exists())

    def test_handmade_health_dropin_blocks_install_and_is_preserved(self):
        existing = self.destination / (self.config["project"] + "-health.service.d")
        existing.mkdir(parents=True)
        handmade = private(
            existing / "backup-pause-disk-check.conf", "[Service]\nExecStartPre=/bin/true\n"
        )
        with self.assertRaisesRegex(automation.AutomationError, "UNIT_ALREADY_EXISTS"):
            schedule.install(self.directory, runner=self.runner)
        self.assertEqual(handmade.read_text(), "[Service]\nExecStartPre=/bin/true\n")
        self.assertEqual([path.name for path in self.destination.iterdir()], [existing.name])
