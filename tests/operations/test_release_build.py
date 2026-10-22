"""The release build sees an allowlisted environment and signing starts after it exited.

No real key, SDK or package install: every subprocess is replaced or synthetic.
"""

import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ops import backup, build_context, release
from tests.operations.test_operations import config

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_KEYS = {
    "PATH",
    "HOME",
    "JAVA_HOME",
    "ANDROID_HOME",
    "GRADLE_USER_HOME",
    "LANG",
    "PNPM_HOME",
    "npm_config_store_dir",
    "NPM_CONFIG_STORE_DIR",
    "XDG_DATA_HOME",
}
SECRETS = {
    "SSH_AUTH_SOCK": "/synthetic/agent.sock",
    "NODE_OPTIONS": "--require /synthetic/hook.js",
    "VITE_API_ORIGIN": "https://synthetic.invalid",
    "GITHUB_TOKEN": "synthetic-token",
    "AWS_SECRET_ACCESS_KEY": "synthetic-secret",
    "SALLIMBOOK_DATABASE_URL": "postgresql://synthetic",
    "PGPASSWORD": "synthetic-password",
    "JAVA_TOOL_OPTIONS": "-javaagent:/synthetic/agent.jar",
    "GRADLE_OPTS": "-Dsynthetic=1",
    "npm_config_registry": "https://synthetic.invalid/",
}


def synthetic_environment():
    return {
        "PATH": "/synthetic/bin",
        "HOME": "/synthetic/home",
        "JAVA_HOME": "/synthetic/jdk",
        "ANDROID_HOME": "/synthetic/ignored-sdk",
        "GRADLE_USER_HOME": "/synthetic/gradle",
        "LANG": "C.UTF-8",
        "PNPM_HOME": "/synthetic/pnpm",
        "npm_config_store_dir": "/synthetic/store",
        "XDG_DATA_HOME": "/synthetic/data",
        **SECRETS,
    }


class BuildEnvironment(unittest.TestCase):
    def test_environment_is_an_exact_allowlist(self):
        self.assertEqual(set(build_context.BUILD_ENVIRONMENT_KEYS), ALLOWED_KEYS)
        with patch.dict(os.environ, synthetic_environment(), clear=True):
            environment = build_context.build_environment()
        self.assertEqual(set(environment), ALLOWED_KEYS & set(synthetic_environment()))
        self.assertTrue(set(SECRETS).isdisjoint(environment))
        with patch.dict(os.environ, {"PATH": "/synthetic/bin"}, clear=True):
            self.assertEqual(build_context.build_environment(), {"PATH": "/synthetic/bin"})

    def test_lockfile_has_no_dependency_that_needs_an_install_script(self):
        # `pnpm install --ignore-scripts` skips every dependency lifecycle script. A package
        # that needs one must be listed here and run explicitly by the build, not silently
        # dropped. pnpm records such packages (preinstall/install/postinstall/binding.gyp).
        lock = (ROOT / "pnpm-lock.yaml").read_text()
        needing, current = set(), None
        for line in lock.splitlines():
            entry = re.fullmatch(r"  '?([^\s'][^']*?)'?:", line)
            if entry:
                current = entry.group(1)
            elif line.strip() == "requiresBuild: true" and current:
                needing.add(current)
        self.assertEqual(needing, set(build_context.INSTALL_SCRIPT_PACKAGES))

    def test_stage_snapshot_installs_without_scripts_in_the_allowlisted_environment(self):
        calls = []

        def record(command, **kwargs):
            calls.append((command, kwargs))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "source"
            (checkout / "apps/client/dist").mkdir(parents=True)
            (checkout / "apps/client/dist/index.html").write_text("synthetic")
            (checkout / "ops").mkdir()
            (checkout / "ops/Dockerfile.web").write_text("FROM scratch\n")
            output = root / "context"
            output.mkdir()
            with (
                patch.dict(os.environ, synthetic_environment(), clear=True),
                patch.object(build_context, "stage_api_snapshot", return_value="0" * 64),
                patch.object(build_context.subprocess, "run", side_effect=record),
            ):
                build_context.stage_snapshot(output, "a" * 40, checkout)
        self.assertEqual(
            [command for command, _ in calls],
            [["pnpm", "install", "--frozen-lockfile", "--ignore-scripts"], ["pnpm", "build"]],
        )
        for _, kwargs in calls:
            self.assertEqual(kwargs["cwd"], checkout)
            self.assertLessEqual(set(kwargs["env"]), ALLOWED_KEYS)
            self.assertTrue(set(SECRETS).isdisjoint(kwargs["env"]))


class ReleaseSteps(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.checkout = self.root / "source"
        apk_directory = self.checkout / "apps/client/android/app/build/outputs/apk/release"
        apk_directory.mkdir(parents=True)
        (apk_directory / "app-release-unsigned.apk").write_bytes(b"synthetic unsigned")
        (self.checkout / "ops").mkdir()
        (self.checkout / "ops/release.init.gradle").write_text("// synthetic")
        self.sdk = self.root / "sdk"
        self.keystore = self.root / "synthetic.p12"
        self.store_password = self.root / "store-password"
        self.key_password = self.root / "key-password"
        for path in (self.keystore, self.store_password, self.key_password):
            path.write_text("synthetic")
            path.chmod(0o600)
        self.output = self.root / "out" / "SallimBook.apk"
        self.output.parent.mkdir(mode=0o700)
        self.events = []

    def build(self):
        def build_command(command, **kwargs):
            self.events.append(("build", [str(item) for item in command], kwargs))

        def tool(command, **kwargs):
            self.events.append(("tool", [str(item) for item in command], kwargs))
            if "sign" in command:
                Path(command[command.index("--out") + 1]).write_bytes(b"synthetic signed")
            return ""

        def inspect(apk, *_args, **kwargs):
            self.events.append(("inspect", [str(apk)], kwargs))
            return {"signed": kwargs.get("signed")}

        binaries = {key: self.sdk / key for key in ("apksigner", "zipalign", "apkanalyzer")}
        with (
            patch.dict(os.environ, synthetic_environment(), clear=True),
            patch.object(release, "tools", return_value=binaries),
            patch.object(release, "run_build", side_effect=build_command),
            patch.object(release, "run", side_effect=tool),
            patch.object(release, "inspect_apk", side_effect=inspect),
        ):
            release.build_snapshot(
                config(),
                self.sdk,
                self.keystore,
                self.store_password,
                self.key_password,
                "synthetic",
                self.output,
                self.checkout,
            )

    def test_build_runs_install_without_scripts_with_only_allowlisted_environment(self):
        self.build()
        builds = [event for event in self.events if event[0] == "build"]
        self.assertEqual(
            [command for _, command, _ in builds[:2]],
            [
                ["pnpm", "install", "--frozen-lockfile", "--ignore-scripts"],
                ["pnpm", "android:sync"],
            ],
        )
        self.assertEqual(builds[2][1][0], "./gradlew")
        self.assertIn("assembleRelease", builds[2][1])
        for _, command, kwargs in builds:
            self.assertLessEqual(set(kwargs["env"]), ALLOWED_KEYS)
            self.assertTrue(set(SECRETS).isdisjoint(kwargs["env"]))
            # The release tool names the selected SDK, not whatever the shell exported.
            self.assertEqual(kwargs["env"]["ANDROID_HOME"], str(self.sdk.absolute()))
            self.assertEqual(kwargs["env"]["JAVA_HOME"], "/synthetic/jdk")
            # The build step is never handed any signing material.
            for secret in (self.keystore, self.store_password, self.key_password):
                self.assertFalse(any(str(secret) in item for item in command))
                self.assertFalse(any(str(secret) in value for value in kwargs["env"].values()))

    def test_signing_starts_only_after_every_build_command_has_exited(self):
        self.build()
        kinds = [kind for kind, _, _ in self.events]
        last_build = max(index for index, kind in enumerate(kinds) if kind == "build")
        signing = [
            index
            for index, (kind, command, _) in enumerate(self.events)
            if kind == "tool" and command[0].endswith("apksigner") and "sign" in command
        ]
        self.assertEqual(len(signing), 1)
        self.assertLess(last_build, signing[0])
        sign_environment = self.events[signing[0]][2]["env"]
        self.assertLessEqual(set(sign_environment), ALLOWED_KEYS)
        self.assertTrue(set(SECRETS).isdisjoint(sign_environment))
        # Signing material is passed as files, never as values.
        command = self.events[signing[0]][1]
        self.assertIn("file:" + str(self.store_password.absolute()), command)
        self.assertIn("file:" + str(self.key_password.absolute()), command)

    def test_build_requires_the_selected_jdk(self):
        with (
            patch.dict(os.environ, {"PATH": "/synthetic/bin"}, clear=True),
            patch.object(release, "tools"),
        ):
            with self.assertRaisesRegex(backup.OperationError, "JAVA_HOME"):
                release.build_snapshot(
                    config(),
                    self.sdk,
                    self.keystore,
                    self.store_password,
                    self.key_password,
                    "synthetic",
                    self.output,
                    self.checkout,
                )


class BuildProcesses(unittest.TestCase):
    def test_descendants_of_a_build_command_do_not_outlive_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "child.pid"
            release.run_build(
                ["sh", "-c", f"sleep 300 & echo $! > {marker}"],
                cwd=temporary,
                env={"PATH": os.environ["PATH"]},
            )
            child = int(marker.read_text())
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and self.alive(child):
                time.sleep(0.05)
            self.assertFalse(self.alive(child), "a build descendant survived")

    @staticmethod
    def alive(pid):
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except FileNotFoundError:
            return False
        return state != "Z"

    def test_failed_build_command_reports_a_generic_error(self):
        with self.assertRaisesRegex(backup.OperationError, "Release tool failed"):
            release.run_build(["sh", "-c", "echo synthetic-secret >&2; exit 3"], cwd="/", env={})


if __name__ == "__main__":
    unittest.main()
