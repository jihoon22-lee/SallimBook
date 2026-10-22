"""Validate systemd artifacts with synthetic files and mocked systemctl only."""

import json
import shutil
import stat
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
        self.assertEqual(len(list(self.destination.iterdir())), 10)
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

    @property
    def dropin_name(self):
        return self.config["project"] + "-health.service.d/10-disk-check.conf"

    def test_render_includes_the_versioned_disk_check_dropin(self):
        path = self.directory / self.dropin_name
        text = path.read_text()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertIn(f"template v{schedule.DISK_CHECK_TEMPLATE_VERSION}", text.splitlines()[0])
        self.assertEqual(text.splitlines()[1], "[Service]")
        pre = [line for line in text.splitlines() if line.startswith("ExecStartPre=")]
        self.assertEqual(
            pre,
            [
                "ExecStartPre="
                + self.config["python_executable"]
                + " -m ops.automation run "
                + str(self.configuration)
                + " --sha256 "
                + self.sha
                + " --task disk-check"
            ],
        )
        self.assertNotIn("/bin/sh", text)
        record = automation.read_json(self.directory / "schedule.json")
        self.assertEqual(record["files"][self.dropin_name], backup.digest(path))
        self.assertEqual(len(record["files"]), 10)
        # The pre-step shares the health service's start timeout.
        health = (self.directory / (self.config["project"] + "-health.service")).read_text()
        timeout = automation.LIMITS["health"] + automation.LIMITS["disk-check"]
        self.assertIn(f"TimeoutStartSec={timeout}\n", health)
        task = pre[0].rsplit(" ", 1)[1]
        self.assertIn(task, automation.TASKS)

    def test_validate_covers_the_dropin(self):
        schedule.validate(self.directory, runner=self.runner)
        verified = next(call for call in self.calls if call[:3] == [
            "/usr/bin/systemd-analyze", "--user", "verify"
        ])
        self.assertEqual(len(verified), 12)  # only unit files are named; systemd finds the .d dir
        self.assertFalse(any(arg.endswith(".conf") for arg in verified))
        path = self.directory / self.dropin_name
        original = path.read_text()
        path.write_text(original + "ExecStartPre=/bin/false\n")
        with self.assertRaisesRegex(automation.AutomationError, "SCHEDULE_CHANGED"):
            schedule.validate(self.directory, runner=self.runner)
        path.write_text(original)
        extra = private(path.parent / "99-extra.conf", "[Service]\nExecStartPre=/bin/false\n")
        with self.assertRaisesRegex(automation.AutomationError, "SCHEDULE_FILES"):
            schedule.validate(self.directory, runner=self.runner)
        extra.unlink()
        (self.directory / "stray.d").mkdir(mode=0o700)
        with self.assertRaisesRegex(automation.AutomationError, "SCHEDULE_FILES"):
            schedule.validate(self.directory, runner=self.runner)

    def test_install_and_activate_accept_only_the_rendered_dropin(self):
        schedule.install(self.directory, runner=self.runner)
        installed = self.destination / self.dropin_name
        self.assertEqual(installed.read_text(), (self.directory / self.dropin_name).read_text())
        self.assertEqual(stat.S_IMODE(installed.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(installed.parent.stat().st_mode), 0o700)
        result = schedule.activate(self.directory, runner=self.runner)
        self.assertEqual(len(result["units"]), 5)
        self.assertTrue((self.directory / "activation.json").exists())

    def test_activate_refuses_any_other_dropin(self):
        project = self.config["project"]
        show = ["--user", "show", "--property=DropInPaths"]
        original = self.runner.run.side_effect
        for reason in ("changed", "extra file", "other unit", "other path", "not loaded"):
            with self.subTest(reason=reason):
                case = self.root / reason.replace(" ", "-")
                case.mkdir(mode=0o700)
                self.destination = case / "units"
                schedule.unit_directory.return_value = self.destination
                rendered = case / "schedule"
                schedule.render(self.configuration, self.sha, rendered)
                schedule.install(rendered, runner=self.runner)
                dropin = self.destination / self.dropin_name
                if reason == "changed":
                    dropin.write_text(dropin.read_text() + "ExecStartPre=/bin/false\n")
                elif reason == "extra file":
                    private(dropin.parent / "99-extra.conf", "[Service]\n")
                elif reason == "other unit":
                    other = self.destination / (project + "-backup.service.d")
                    other.mkdir(mode=0o700)
                    private(other / "10-disk-check.conf", dropin.read_text())
                elif reason == "other path":
                    # A vendor or runtime override that systemd also loads.
                    self.runner.run.side_effect = lambda args, mine=dropin, **kwargs: (
                        f"{mine} /etc/systemd/user/{args[-1]}.d/50.conf\n"
                        if args[1:4] == show
                        else original(args, **kwargs)
                    )
                else:
                    self.runner.run.side_effect = lambda args, **kwargs: (
                        "\n" if args[1:4] == show else original(args, **kwargs)
                    )
                self.calls.clear()
                with self.assertRaisesRegex(
                    automation.AutomationError, "INSTALLED_UNIT_(CHANGED|OVERRIDE)"
                ):
                    schedule.activate(rendered, runner=self.runner)
                self.runner.run.side_effect = original
                self.assertFalse(any("enable" in call for call in self.calls))
                self.assertFalse((rendered / "activation.json").exists())

    def test_handmade_dropin_blocks_install_and_is_preserved(self):
        existing = self.destination / (self.config["project"] + "-health.service.d")
        existing.mkdir(parents=True)
        handmade = private(existing / "10-hand-made.conf", "[Service]\nExecStartPre=/bin/true\n")
        with self.assertRaisesRegex(automation.AutomationError, "UNIT_ALREADY_EXISTS"):
            schedule.install(self.directory, runner=self.runner)
        self.assertEqual(handmade.read_text(), "[Service]\nExecStartPre=/bin/true\n")
        self.assertEqual(
            [path.name for path in self.destination.iterdir()], [existing.name]
        )

    def test_failed_install_removes_the_new_dropin_and_its_directory(self):
        original = self.runner.run.side_effect

        def failing(args, **kwargs):
            if args[-1] == "daemon-reload":
                raise automation.AutomationError("COMMAND_FAILED")
            return original(args, **kwargs)

        self.runner.run.side_effect = failing
        with self.assertRaises(automation.AutomationError):
            schedule.install(self.directory, runner=self.runner)
        self.assertEqual(list(self.destination.iterdir()), [])
