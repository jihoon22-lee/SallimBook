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


JAVA_OPTION_VARIABLES = {
    "JAVA_TOOL_OPTIONS": "-javaagent:/synthetic/agent.jar",
    "_JAVA_OPTIONS": "-Dsynthetic=1",
    "JDK_JAVA_OPTIONS": "-Dsynthetic=2",
    "CLASSPATH": "/synthetic/extra.jar",
}


class ReleaseSteps(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.checkout = self.root / "source"
        self.unsigned = (
            self.checkout / "apps/client/android/app/build/outputs/apk/release"
            / "app-release-unsigned.apk"
        )
        self.unsigned.parent.mkdir(parents=True)
        self.unsigned.write_bytes(b"synthetic unsigned")
        (self.checkout / "ops").mkdir()
        (self.checkout / "ops/release.init.gradle").write_text("// synthetic")
        self.sdk = self.root / "sdk"
        self.jdk = self.root / "jdk"
        self.tool_files = {
            "apksigner launcher": self.sdk / "build-tools/36.0.0/apksigner",
            "apksigner jar": self.sdk / "build-tools/36.0.0/lib/apksigner.jar",
            "zipalign": self.sdk / "build-tools/36.0.0/zipalign",
            "apkanalyzer": self.sdk / "cmdline-tools/15859902/bin/apkanalyzer",
            "analyzer jar": self.sdk / "cmdline-tools/15859902/lib/analyzer.jar",
            "java": self.jdk / "bin/java",
            "modules": self.jdk / "lib/modules",
        }
        for path in self.tool_files.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic " + path.name.encode())
        self.keystore = self.root / "synthetic.p12"
        self.store_password = self.root / "store-password"
        self.key_password = self.root / "key-password"
        for path in (self.keystore, self.store_password, self.key_password):
            path.write_text("synthetic")
            path.chmod(0o600)
        self.output = self.root / "out" / "SallimBook.apk"
        self.output.parent.mkdir(mode=0o700)
        self.events = []
        self.during_build = None

    def environment(self):
        return {
            **synthetic_environment(),
            **JAVA_OPTION_VARIABLES,
            "JAVA_HOME": str(self.jdk),
        }

    def build(self):
        def build_command(command, **kwargs):
            self.events.append(("build", [str(item) for item in command], kwargs))
            if self.during_build and command[0] == "./gradlew":
                self.during_build()

        def see(path):
            # What the tools can read at the moment they run.
            if Path(path).is_file():
                info = Path(path).stat()
                self.events.append(
                    ("seen", (str(path), info.st_mode & 0o777, Path(path).read_bytes()), {})
                )

        def tool(command, **kwargs):
            self.events.append(("tool", [str(item) for item in command], kwargs))
            for item in command:
                if str(item).endswith(".apk"):
                    see(item)
            if command[0].endswith("zipalign"):
                # The build tree changing after the build exited must not matter.
                self.unsigned.write_bytes(b"swapped")
            if "sign" in command:
                Path(command[command.index("--out") + 1]).write_bytes(b"synthetic signed")
            return ""

        def inspect(apk, *_args, **kwargs):
            self.events.append(("inspect", [str(apk)], kwargs))
            see(apk)
            return {"signed": kwargs.get("signed")}

        with (
            patch.dict(os.environ, self.environment(), clear=True),
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

    def signing_index(self):
        found = [
            index
            for index, (kind, command, _) in enumerate(self.events)
            if kind == "tool" and command[0].endswith("apksigner") and "sign" in command
        ]
        self.assertEqual(len(found), 1)
        return found[0]

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
        self.assertIn("--no-daemon", builds[2][1])
        self.assertIn("assembleRelease", builds[2][1])
        for _, command, kwargs in builds:
            self.assertLessEqual(set(kwargs["env"]), ALLOWED_KEYS)
            self.assertTrue(set(SECRETS).isdisjoint(kwargs["env"]))
            # The release tool names the selected SDK, not whatever the shell exported.
            self.assertEqual(kwargs["env"]["ANDROID_HOME"], str(self.sdk.absolute()))
            self.assertEqual(kwargs["env"]["JAVA_HOME"], str(self.jdk))
            # The build step is never handed any signing material.
            for secret in (self.keystore, self.store_password, self.key_password):
                self.assertFalse(any(str(secret) in item for item in command))
                self.assertFalse(any(str(secret) in value for value in kwargs["env"].values()))

    def test_signing_starts_only_after_every_build_command_has_exited(self):
        self.build()
        kinds = [kind for kind, _, _ in self.events]
        last_build = max(index for index, kind in enumerate(kinds) if kind == "build")
        signing = self.signing_index()
        self.assertLess(last_build, signing)
        # Signing material is passed as files, never as values.
        command = self.events[signing][1]
        self.assertIn("file:" + str(self.store_password.absolute()), command)
        self.assertIn("file:" + str(self.key_password.absolute()), command)

    def test_signing_environment_is_fixed_and_inherits_no_java_options(self):
        self.build()
        expected = {
            "JAVA_HOME": str(self.jdk.resolve()),
            "PATH": str(self.jdk.resolve() / "bin") + ":/usr/bin:/bin",
            "LANG": "C.UTF-8",
        }
        after_build = [
            event for event in self.events[self.events.index(self.last_build_event()) + 1:]
            if event[0] in {"tool", "inspect"}
        ]
        self.assertGreaterEqual(len(after_build), 4)  # inspect, zipalign, sign, inspect
        for _, _, kwargs in after_build:
            self.assertEqual(kwargs["env"], expected)
            self.assertTrue(set(JAVA_OPTION_VARIABLES).isdisjoint(kwargs["env"]))

    def last_build_event(self):
        return [event for event in self.events if event[0] == "build"][-1]

    def test_a_signing_tool_changed_during_the_build_aborts_before_signing(self):
        def rewrite(path):
            path.write_bytes(b"patched")

        def add(path):
            (path.parent / "added.jar").write_bytes(b"added")

        def relink(path):
            path.unlink()
            path.symlink_to("/usr/bin/true")

        cases = [
            ("apksigner launcher", "rewritten", rewrite),
            ("apksigner jar", "rewritten", rewrite),
            ("zipalign", "rewritten", rewrite),
            ("apkanalyzer", "rewritten", rewrite),
            ("analyzer jar", "rewritten", rewrite),
            ("java", "rewritten", rewrite),
            ("modules", "rewritten", rewrite),
            ("apksigner jar", "file added beside it", add),
            ("java", "file added beside it", add),
            ("zipalign", "removed", lambda path: path.unlink()),
            ("java", "mode changed", lambda path: path.chmod(0o777)),
            ("modules", "replaced by a link", relink),
        ]
        for label, what, change in cases:
            with self.subTest(tool=label, change=what):
                self.setUp()
                path = self.tool_files[label]
                self.during_build = lambda change=change, path=path: change(path)
                with self.assertRaises(release.ReleaseAbort) as caught:
                    self.build()
                self.assertEqual(caught.exception.code, "SIGNING_TOOLS_CHANGED")
                # Nothing from the tool chain ran: no inspection, alignment or signing.
                self.assertFalse(any(kind in {"tool", "inspect"} for kind, _, _ in self.events))
                self.assertFalse(self.output.exists())

    def test_unchanged_tools_pass_and_unrelated_sdk_files_may_change(self):
        (self.sdk / "platforms/android-36").mkdir(parents=True)
        self.during_build = lambda: (self.sdk / "platforms/android-36/android.jar").write_bytes(
            b"installed by the build"
        )
        self.build()
        self.signing_index()

    def test_signing_reads_the_private_copy_not_the_build_tree(self):
        self.build()
        seen = {
            event[1][0]: (event[1][1], event[1][2]) for event in self.events if event[0] == "seen"
        }
        inspected = [command[0] for kind, command, _ in self.events if kind == "inspect"]
        candidate = inspected[0]
        # A private 0700 directory next to the output, owner-only copy of the build output.
        self.assertEqual(Path(candidate).parent.parent, self.output.parent)
        self.assertTrue(Path(candidate).parent.name.startswith(".sallimbook-release-"))
        self.assertEqual(seen[candidate], (0o600, b"synthetic unsigned"))
        commands = [command for kind, command, _ in self.events if kind in {"tool", "inspect"}]
        for command in commands:
            self.assertFalse(any(str(self.checkout) in item for item in command))
        zipalign = next(command for command in commands if command[0].endswith("zipalign"))
        self.assertIn(candidate, zipalign)
        # The build tree is not read again: replacing it after the copy changes nothing.
        self.assertEqual(self.unsigned.read_bytes(), b"swapped")
        self.assertEqual(seen[candidate][1], b"synthetic unsigned")

    def test_build_requires_the_selected_jdk(self):
        with patch.dict(os.environ, {"PATH": "/synthetic/bin"}, clear=True):
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
        except (FileNotFoundError, ProcessLookupError):
            return False
        return state != "Z"

    def test_session_members_scan_proc_by_session_id_and_ignore_zombies(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)

            def process(pid, name, state, session):
                (proc / str(pid)).mkdir()
                (proc / str(pid) / "stat").write_text(
                    f"{pid} ({name}) {state} 1 {pid} {session} 0 -1 4194560 1 0 0 0\n"
                )

            process(101, "sleep", "S", 4242)
            process(102, "a b) c", "R", 4242)  # a command name with spaces and a parenthesis
            process(103, "defunct", "Z", 4242)
            process(104, "other", "S", 999)
            (proc / "105").mkdir()  # exited between listing and reading
            (proc / "self").mkdir()
            self.assertEqual(sorted(release.session_members(4242, proc)), [101, 102])

    def test_a_process_left_in_the_build_session_aborts_the_release(self):
        with (
            patch.object(release, "session_members", return_value=[4242]),
            patch.object(release, "SESSION_SETTLE_SECONDS", 0.2),
            patch.object(release.os, "kill") as kill,
        ):
            with self.assertRaises(release.ReleaseAbort) as caught:
                release.run_build(["sh", "-c", "true"], cwd="/", env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(caught.exception.code, "BUILD_PROCESS_LEFT_RUNNING")
        kill.assert_called_once_with(4242, release.signal.SIGKILL)

    def test_the_release_command_names_only_the_fixed_abort_code(self):
        import json

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(config()))
            arguments = [
                "ops.release", "--manifest", str(path), "--sdk", temporary,
                "--keystore", temporary, "--store-password-file", temporary,
                "--key-password-file", temporary, "--alias", "synthetic", "--output", temporary,
                "--previous-version", "0",
            ]
            abort = release.ReleaseAbort("SIGNING_TOOLS_CHANGED", "detail that stays private")
            with (
                patch("sys.argv", arguments),
                patch.object(release, "build", side_effect=abort),
                self.assertRaises(SystemExit) as caught,
            ):
                release.main()
            self.assertIn("SIGNING_TOOLS_CHANGED", str(caught.exception))
            self.assertNotIn("private", str(caught.exception))
            with (
                patch("sys.argv", arguments),
                patch.object(release, "build", side_effect=ValueError("secret path /x")),
                self.assertRaises(SystemExit) as caught,
            ):
                release.main()
            self.assertNotIn("secret", str(caught.exception))
            self.assertNotIn("(", str(caught.exception))

    def test_failed_build_command_reports_a_generic_error(self):
        with self.assertRaisesRegex(backup.OperationError, "Release tool failed"):
            release.run_build(["sh", "-c", "echo synthetic-secret >&2; exit 3"], cwd="/", env={})


if __name__ == "__main__":
    unittest.main()
