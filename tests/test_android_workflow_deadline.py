"""Check the hosted deadline against the probe's actual bounded operations.

No SDK, network, Docker or wall-clock waiting: cleanup runs with a synthetic
clock, and the probe's call sites supply their own timeout values.
"""

import ast
import math
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import android_cloud_process as process

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/android-instrumentation.yml"
PROBE = ROOT / "scripts/probe_android_avd.py"
PROBE_HEADROOM_SECONDS = 300
JOB_HEADROOM_MINUTES = 14


class WorkflowDeadlineTests(unittest.TestCase):
    def cleanup_budget(self, *, grace=None):
        elapsed = 0.0

        def sleep(seconds):
            nonlocal elapsed
            elapsed += seconds
            self.assertLess(elapsed, 1000, "Cleanup must retain a finite deadline")

        with (
            patch.object(process, "group_alive", return_value=True),
            patch.object(process.os, "killpg"),
            patch.object(process.time, "monotonic", side_effect=lambda: elapsed),
            patch.object(process.time, "sleep", side_effect=sleep),
            self.assertRaises(process.CloudCommandError),
        ):
            process.stop_group(MagicMock(pid=12345), **({} if grace is None else {"grace": grace}))
        # Include the real polling loop's final sleep overshoot, rounded upward.
        return math.ceil(elapsed)

    def workflow(self, source):
        job = int(re.search(r"^    timeout-minutes: (\d+)$", source, re.M)[1])
        steps = re.split(r"^      - ", source.split("    steps:\n", 1)[1], flags=re.M)[1:]
        limits = []
        for step in steps:
            matches = re.findall(r"^        timeout-minutes: (\d+)$", step, re.M)
            self.assertEqual(len(matches), 1, "Every setup/test/evidence step needs a bound")
            limits.append(int(matches[0]))
        native = next(step for step in steps if "        id: instrument\n" in step)
        return {
            "job": job,
            "steps": sum(limits),
            "native": int(re.search(r"timeout-minutes: (\d+)", native)[1]),
            "boot": int(re.search(r"--boot-timeout (\d+)", native)[1]),
            "command": int(re.search(r"--command-timeout (\d+)", native)[1]),
        }

    def probe_budget(self, workflow):
        tree = ast.parse(PROBE.read_text())
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        main = functions["main"]
        defaults = dict(
            zip(functions["run"].args.kwonlyargs, functions["run"].args.kw_defaults, strict=True)
        )
        default = next(
            ast.literal_eval(value) for arg, value in defaults.items() if arg.arg == "timeout"
        )
        calls = sorted(
            (
                node
                for node in ast.walk(main)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "run"
            ),
            key=lambda node: node.lineno,
        )
        # Every run site is accounted for. A new call requires a budget review.
        self.assertEqual(len(calls), 7)
        markers = (
            "-accel-check",
            "-version",
            "create",
            "start-server",
            "sys.boot_completed",
            None,
            "kill-server",
        )
        for call, marker in zip(calls, markers, strict=True):
            if marker:
                self.assertTrue(
                    any(
                        isinstance(node, ast.Constant) and node.value == marker
                        for node in ast.walk(call.args[0])
                    )
                )
        timeouts = [
            next(
                (ast.literal_eval(arg.value) for arg in call.keywords if arg.arg == "timeout"),
                default,
            )
            for call in calls
        ]
        status_loop = next(
            node
            for node in ast.walk(main)
            if isinstance(node, ast.For) and calls[5] in list(ast.walk(node))
        )
        self.assertIsInstance(status_loop.iter, ast.Call)
        self.assertIsInstance(status_loop.iter.func.value, ast.Dict)
        statuses = len(status_loop.iter.func.value.keys)
        boot_loop = next(
            node
            for node in ast.walk(main)
            if isinstance(node, ast.While) and calls[4] in list(ast.walk(node))
        )
        self.assertEqual(ast.unparse(boot_loop.test.comparators[0]), "args.boot_timeout")
        waits = [
            node
            for node in ast.walk(main)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "wait"
        ]
        self.assertEqual(len(waits), 1)
        self.assertEqual(ast.unparse(waits[0]), "child.wait(timeout=args.command_timeout)")
        sleeps = [
            node
            for node in ast.walk(boot_loop)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "sleep"
        ]
        self.assertEqual(len(sleeps), 1)
        poll = ast.literal_eval(sleeps[0].args[0])
        cleanup_calls = [
            node
            for node in ast.walk(main)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "stop_group"
        ]
        self.assertEqual(len(cleanup_calls), 2)
        child_cleanup = next(node for node in cleanup_calls if node.args[0].id == "child")
        emulator_cleanup = next(node for node in cleanup_calls if node.args[0].id == "process")
        self.assertEqual(emulator_cleanup.keywords, [])
        run_cleanup = [
            node
            for node in ast.walk(functions["run"])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "stop_group"
        ]
        self.assertEqual(len(run_cleanup), 1)
        self.assertEqual(run_cleanup[0].keywords, [])
        grace = next(
            ast.literal_eval(arg.value) for arg in child_cleanup.keywords if arg.arg == "grace"
        )
        regular_stop = self.cleanup_budget()
        command_stop = self.cleanup_budget(grace=grace)
        # run() can time out and enter stop_group(). Budget that cost for every
        # call, even though a setup/status failure usually skips later phases.
        return {
            "prepare": sum(timeouts[:4]) + 4 * regular_stop,
            # A loop iteration can start just before its deadline, then spend
            # one full ADB timeout, group cleanup and polling sleep beyond it.
            "boot": workflow["boot"] + timeouts[4] + regular_stop + poll,
            "status": statuses * (timeouts[5] + regular_stop),
            "command": workflow["command"],
            "cleanup": command_stop + regular_stop + timeouts[6] + regular_stop,
        }

    def assert_budget(self, workflow, budget):
        self.assertGreaterEqual(
            workflow["native"] * 60, sum(budget.values()) + PROBE_HEADROOM_SECONDS
        )
        self.assertGreaterEqual(workflow["job"], workflow["steps"] + JOB_HEADROOM_MINUTES)

    def test_workflow_covers_all_probe_calls_and_post_steps(self):
        workflow = self.workflow(WORKFLOW.read_text())
        budget = self.probe_budget(workflow)
        self.assertEqual(
            budget, {"prepare": 234, "boot": 628, "status": 153, "command": 1800, "cleanup": 188}
        )
        self.assert_budget(workflow, budget)

    def test_former_45_minute_native_limit_is_rejected(self):
        workflow = self.workflow(WORKFLOW.read_text())
        with self.assertRaises(AssertionError):
            self.assert_budget({**workflow, "native": 45}, self.probe_budget(workflow))

    def test_job_must_also_reserve_cleanup_evidence_and_upload(self):
        workflow = self.workflow(WORKFLOW.read_text())
        with self.assertRaises(AssertionError):
            self.assert_budget({**workflow, "job": workflow["steps"]}, self.probe_budget(workflow))

    def test_unbounded_setup_or_upload_step_is_rejected(self):
        source = WORKFLOW.read_text().replace("        timeout-minutes: 5\n", "", 1)
        with self.assertRaises(AssertionError):
            self.workflow(source)


if __name__ == "__main__":
    unittest.main()
