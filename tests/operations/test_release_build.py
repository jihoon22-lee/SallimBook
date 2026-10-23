"""The release build sees an allowlisted environment and signing starts after it exited.

No real key, SDK or package install: every subprocess is replaced or synthetic.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
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


class FakeBuild:
    """Stands in for build processes and their reaping; nothing real is started or killed."""

    def __init__(self, events, *, status=0):
        self.events = events
        self.status = status

    def popen(self, args, **kwargs):
        self.events.append(("build-start", [str(item) for item in args], kwargs))
        return SimpleNamespace(pid=1, wait=lambda: self.status)

    def patches(self):
        stack = ExitStack()
        stack.enter_context(patch.object(release.subprocess, "Popen", side_effect=self.popen))
        stack.enter_context(
            patch.object(
                release, "reap_leftovers", side_effect=lambda: self.events.append(("reap", [], {}))
            )
        )
        stack.enter_context(
            patch.object(
                release,
                "check_containment",
                side_effect=lambda: self.events.append(("contain", [], {})),
            )
        )
        return stack


class ReleaseSteps(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.checkout = self.root / "source"
        self.unsigned = (
            self.checkout
            / "apps/client/android/app/build/outputs/apk/release"
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

    def build(self, builds=None):
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

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, self.environment(), clear=True))
            stack.enter_context(patch.object(release, "run", side_effect=tool))
            stack.enter_context(patch.object(release, "inspect_apk", side_effect=inspect))
            if builds is None:
                stack.enter_context(patch.object(release, "run_build", side_effect=build_command))
                stack.enter_context(patch.object(release, "check_containment"))
            else:
                stack.enter_context(builds.patches())
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
        # A normal build then leaves no Kotlin compile daemon behind.
        self.assertIn("-Pkotlin.compiler.execution.strategy=in-process", builds[2][1])
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
            event
            for event in self.events[self.events.index(self.last_build_event()) + 1 :]
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

    def test_private_directory_is_created_only_after_the_build_has_exited(self):
        seen = []

        def look():
            # Build code runs as this user; a directory it can see could be pre-populated.
            seen.append(sorted(p.name for p in self.output.parent.glob(".sallimbook-release-*")))

        self.during_build = look
        self.build()
        self.assertEqual(seen, [[]])
        # And it is gone again when the release finishes or aborts.
        self.assertEqual(list(self.output.parent.glob(".sallimbook-release-*")), [])
        self.setUp()
        self.during_build = lambda: self.tool_files["java"].write_bytes(b"patched")
        with self.assertRaises(release.ReleaseAbort):
            self.build()
        self.assertEqual(list(self.output.parent.glob(".sallimbook-release-*")), [])

    def test_each_build_command_is_reaped_before_the_fingerprints_are_verified_and_signing_starts(
        self,
    ):
        original = release.signing_fingerprints

        def logged(*arguments):
            self.events.append(("fingerprint", [], {}))
            return original(*arguments)

        with patch.object(release, "signing_fingerprints", side_effect=logged):
            self.build(FakeBuild(self.events))
        kinds = [kind for kind, _, _ in self.events]
        pinned, verified = [i for i, kind in enumerate(kinds) if kind == "fingerprint"]
        # Containment is in place and proven before the tools are pinned or anything builds.
        self.assertEqual(kinds.index("contain"), 0)
        self.assertLess(kinds.index("contain"), pinned)
        # pnpm install, pnpm android:sync and gradle: each one reaped before the next starts.
        built = [kind for kind in kinds if kind in {"build-start", "reap"}]
        self.assertEqual(built, ["build-start", "reap"] * 3)
        last_reap = max(i for i, kind in enumerate(kinds) if kind == "reap")
        first_tool = min(i for i, kind in enumerate(kinds) if kind in {"tool", "inspect"})
        self.assertLess(last_reap, verified)
        self.assertLess(verified, first_tool)
        self.assertLess(verified, self.signing_index())

    def test_a_leftover_that_cannot_be_killed_aborts_before_any_signing_tool_runs(self):
        builds = FakeBuild(self.events)

        def real_reaping():
            # Fake build processes and containment; the real reap loop sees one that stays.
            stack = ExitStack()
            stack.enter_context(patch.object(release.subprocess, "Popen", side_effect=builds.popen))
            stack.enter_context(patch.object(release, "check_containment"))
            stack.enter_context(patch.object(release, "child_processes", return_value=[4321]))
            stack.enter_context(patch.object(release.os, "kill"))
            stack.enter_context(patch.object(release.os, "waitpid"))
            stack.enter_context(patch.object(release, "LEFTOVER_SETTLE_SECONDS", 0.2))
            return stack

        with self.assertRaises(release.ReleaseAbort) as caught:
            self.build(SimpleNamespace(patches=real_reaping))
        self.assertEqual(caught.exception.code, "BUILD_PROCESS_LEFT_RUNNING")
        # The first build command never got a successor, and nothing was signed.
        self.assertEqual([kind for kind, _, _ in self.events].count("build-start"), 1)
        self.assertFalse(any(kind in {"tool", "inspect"} for kind, _, _ in self.events))
        self.assertFalse(self.output.exists())

    def test_without_containment_the_release_fails_closed_before_building(self):
        refusing = SimpleNamespace(prctl=lambda *_: -1)
        with (
            patch.object(release.ctypes, "CDLL", return_value=refusing),
            self.assertRaises(release.ReleaseAbort) as caught,
        ):
            self.build(SimpleNamespace(patches=ExitStack))
        self.assertEqual(caught.exception.code, "BUILD_CONTAINMENT_UNAVAILABLE")
        self.assertFalse(any(kind in {"tool", "inspect"} for kind, _, _ in self.events))

    def test_previous_apk_is_inspected_with_the_fixed_signing_environment(self):
        calls = []
        previous = self.root / "previous.apk"
        previous.write_bytes(b"synthetic previous")
        binaries = {key: self.sdk / key for key in ("apksigner", "zipalign", "apkanalyzer")}

        def tool(command, **kwargs):
            calls.append(("run", [str(item) for item in command], kwargs))
            if command[:2] == ["git", "rev-parse"]:
                return config()["source_commit"]
            return "0.1.0" if "version-name" in command else ""

        def inspect(apk, *arguments, **kwargs):
            calls.append(("inspect", [str(apk)], kwargs))
            return {}

        from contextlib import contextmanager

        @contextmanager
        def snapshot(*arguments):
            yield self.checkout

        with (
            patch.dict(os.environ, self.environment(), clear=True),
            patch.object(release, "tools", return_value=binaries),
            patch.object(release, "run", side_effect=tool),
            patch.object(release, "inspect_apk", side_effect=inspect),
            patch.object(release, "source_snapshot", snapshot),
            patch.object(release, "build_snapshot", return_value={}),
            patch.object(release, "ROOT", self.root / "outside-the-repository"),
        ):
            release.build(
                {**config(), "version_code": 3},
                self.sdk,
                self.keystore,
                self.store_password,
                self.key_password,
                "synthetic",
                self.output,
                2,
                previous,
            )
        expected = {
            "JAVA_HOME": str(self.jdk.resolve()),
            "PATH": str(self.jdk.resolve() / "bin") + ":/usr/bin:/bin",
            "LANG": "C.UTF-8",
        }
        previous_calls = [
            call for call in calls if call[0] == "inspect" or "version-name" in call[1]
        ]
        self.assertEqual(len(previous_calls), 2)
        for _, _, kwargs in previous_calls:
            self.assertEqual(kwargs["env"], expected)

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


class BuildContainment(unittest.TestCase):
    ENVIRONMENT = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/synthetic/home",
        "JAVA_HOME": "/synthetic/jdk",
    }

    def run_build(self, command, builds):
        environment = {"SSH_AUTH_SOCK": "/synthetic/agent", "GITHUB_TOKEN": "synthetic"}
        with builds.patches(), patch.dict(os.environ, environment, clear=True):
            release.run_build(command, cwd="/synthetic/work", env=self.ENVIRONMENT)

    def test_every_build_command_gets_exactly_the_allowlisted_environment(self):
        events = []
        self.run_build(["pnpm", "install"], FakeBuild(events))
        self.run_build(["./gradlew", "assembleRelease"], FakeBuild(events))
        starts = [event for event in events if event[0] == "build-start"]
        self.assertEqual(
            [argv for _, argv, _ in starts], [["pnpm", "install"], ["./gradlew", "assembleRelease"]]
        )
        for _, _, kwargs in starts:
            # Nothing of the caller's environment reaches the build.
            self.assertEqual(kwargs["env"], self.ENVIRONMENT)
            self.assertEqual(kwargs["cwd"], "/synthetic/work")
            self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)

    def test_a_failed_or_interrupted_build_is_still_reaped(self):
        events = []
        with self.assertRaisesRegex(backup.OperationError, "Release tool failed"):
            self.run_build(["gradle"], FakeBuild(events, status=1))
        self.assertEqual([event[0] for event in events], ["build-start", "reap"])

        class Interrupted(FakeBuild):
            def popen(self, args, **kwargs):
                self.events.append(("build-start", list(args), kwargs))
                return SimpleNamespace(pid=1, wait=self.interrupt)

            @staticmethod
            def interrupt():
                raise KeyboardInterrupt

        events = []
        with self.assertRaises(KeyboardInterrupt):
            self.run_build(["gradle"], Interrupted(events))
        self.assertEqual([event[0] for event in events], ["build-start", "reap"])

    def test_leftovers_are_killed_and_one_that_stays_aborts_the_release(self):
        killed, children = [], [[4321, 4322], []]
        with (
            patch.object(release, "child_processes", side_effect=lambda: children.pop(0)),
            patch.object(release.os, "kill", side_effect=lambda pid, sig: killed.append(pid)),
            patch.object(release.os, "waitpid"),
            patch.object(release.time, "sleep"),
        ):
            release.reap_leftovers()
        self.assertEqual(killed, [4321, 4322])
        with (
            patch.object(release, "child_processes", return_value=[4321]),
            patch.object(release.os, "kill"),
            patch.object(release.os, "waitpid"),
            patch.object(release, "LEFTOVER_SETTLE_SECONDS", 0.2),
            self.assertRaises(release.ReleaseAbort) as caught,
        ):
            release.reap_leftovers()
        self.assertEqual(caught.exception.code, "BUILD_PROCESS_LEFT_RUNNING")

    def test_a_host_that_cannot_collect_orphans_fails_closed_without_a_fallback(self):
        cases = (
            {"CDLL": SimpleNamespace(prctl=lambda *_: -1)},
            {"CDLL": OSError("no libc")},
            {"CDLL": SimpleNamespace(prctl=lambda *_: 0), "children": [[999]]},
            # The probe's detached process never came back as a child.
            {"CDLL": SimpleNamespace(prctl=lambda *_: 0), "children": [[], [], []]},
        )
        for case in cases:
            with self.subTest(case=case):
                library = case["CDLL"]
                children = list(case.get("children", [[]]))
                with (
                    patch.object(
                        release.ctypes,
                        "CDLL",
                        side_effect=library if isinstance(library, Exception) else None,
                        return_value=None if isinstance(library, Exception) else library,
                    ),
                    patch.object(
                        release,
                        "child_processes",
                        side_effect=lambda left=children: left.pop(0) if left else [],
                    ),
                    self.assertRaises(release.ReleaseAbort) as caught,
                ):
                    release.check_containment()
                self.assertEqual(caught.exception.code, "BUILD_CONTAINMENT_UNAVAILABLE")

    def real_release_process(self, script):
        """Run `script` in a fresh interpreter, so the subreaper never applies to the tests."""
        return subprocess.run(
            [sys.executable, "-I", "-c", script],
            cwd=ROOT,
            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_a_real_detached_build_daemon_is_killed_before_the_build_returns(self):
        with tempfile.TemporaryDirectory() as temporary:
            pids = Path(temporary) / "pids"
            script = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from ops import release
release.check_containment()
# One daemon detaches with setsid, another with a double fork; both outlive the command.
release.run_build(
    ["/bin/sh", "-c",
     "setsid /bin/sleep 60 </dev/null >/dev/null 2>&1 & echo $! >> {pids}; "
     "(/bin/sleep 61 </dev/null >/dev/null 2>&1 & echo $! >> {pids}) &"],
    cwd={temporary!r},
    env={{"PATH": "/usr/bin:/bin"}},
)
print("returned", release.child_processes())
"""
            result = self.real_release_process(script)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("returned []", result.stdout)
            started = [int(line) for line in pids.read_text().split()]
            self.assertEqual(len(started), 2)
            for pid in started:
                self.assertFalse(Path(f"/proc/{pid}").exists(), f"process {pid} survived")

    def test_the_release_command_names_only_the_fixed_abort_code(self):
        import json

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(config()))
            arguments = [
                "ops.release",
                "--manifest",
                str(path),
                "--sdk",
                temporary,
                "--keystore",
                temporary,
                "--store-password-file",
                temporary,
                "--key-password-file",
                temporary,
                "--alias",
                "synthetic",
                "--output",
                temporary,
                "--previous-version",
                "0",
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


if __name__ == "__main__":
    unittest.main()
