"""Validate systemd artifacts with synthetic files and mocked systemctl only."""

import json
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

    def test_manifest_cannot_introduce_arbitrary_unit(self):
        path = self.directory / "schedule.json"
        value = json.loads(path.read_text())
        value["files"]["existing.service"] = "0" * 64
        private(path, value)
        with self.assertRaisesRegex(automation.AutomationError, "SCHEDULE_FILES"):
            schedule.validate(self.directory, runner=self.runner)
