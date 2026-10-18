"""Probe orchestration tests; these do not count as Android device tests."""

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.inspect_android_cloud_apks import inspect_release

ROOT = Path(__file__).resolve().parents[1]


class AvdProbeTests(unittest.TestCase):
    def exercise(self, *, boot=True, create=True, command=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = root / "sdk"
            programs = {
                "emulator/emulator": (
                    "import sys, time\n"
                    "if '-accel-check' in sys.argv: print('KVM unavailable'); sys.exit(1)\n"
                    "if '-version' in sys.argv: print('synthetic emulator'); sys.exit(0)\n"
                    "time.sleep(30)\n"
                ),
                "cmdline-tools/test/bin/avdmanager": f"raise SystemExit({0 if create else 1})\n",
                "platform-tools/adb": (
                    "import sys\n"
                    f"if 'sys.boot_completed' in sys.argv: print({'1' if boot else '0'!r})\n"
                ),
            }
            for name, source in programs.items():
                path = sdk / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"#!{sys.executable}\n" + source)
                path.chmod(0o755)
            output = root / "result"
            argv = [sys.executable, str(ROOT / "scripts/probe_android_avd.py"),
                    "--sdk-root", str(sdk), "--image", "synthetic", "--output", str(output),
                    "--software", "--boot-timeout", "1", "--port", "5680", "--adb-port", "15049"]
            if command:
                argv += ["--command", *command]
            completed = subprocess.run(argv, capture_output=True, text=True, timeout=15, check=False)
            result = json.loads((output / "result.json").read_text())
            self.assertTrue(result["emulator_stopped"])
            if create:
                self.assertEqual(result["adb_stop_exit_code"], 0)
            return completed.returncode, result

    def test_success_is_only_boot_evidence(self):
        code, result = self.exercise()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["command_status"], "NOT_RUN")
        self.assertEqual(result["acceleration"]["exit_code"], 1)

    def test_deadline_is_blocked_not_pass(self):
        code, result = self.exercise(boot=False)
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "BLOCKED_ENV")
        self.assertEqual(result["reason"], "Boot deadline exceeded")

    def test_creation_failure_has_nonzero_exit(self):
        code, result = self.exercise(create=False)
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "BLOCKED_ENV")
        self.assertEqual(result["command_status"], "NOT_RUN")

    def test_command_failure_is_preserved(self):
        code, result = self.exercise(command=[sys.executable, "-c", "raise SystemExit(7)"])
        self.assertEqual(code, 2)
        self.assertEqual(result["command_status"], "FAIL")
        self.assertEqual(result["command_exit_code"], 7)


class ReleaseIsolationTests(unittest.TestCase):
    def test_scans_secondary_dex_and_binary_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "synthetic.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("classes.dex", b"ordinary classes")
                archive.writestr("classes2.dex", b"CvcAcceptanceActivity")
                archive.writestr("resources.arsc", "sallimbook_cloud_ca".encode("utf-16-le"))
            result = inspect_release(apk)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual({match["entry"] for match in result["matches"]},
                             {"classes2.dex", "resources.arsc"})

    def test_absent_markers_are_only_structural_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "synthetic.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("classes.dex", b"ordinary classes")
            self.assertEqual(inspect_release(apk)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
