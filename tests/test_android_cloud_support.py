"""Synthetic subprocesses and XML only; no Android SDK, Docker or DB access."""

import contextlib
import io
import json
import os
import re
import signal
import sys
import tempfile
import textwrap
import threading
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.android_cloud_process import CloudCommandError, checked, stop_group
from scripts.android_cloud_results import (
    ONBOARDING_CLASS,
    ONBOARDING_METHOD,
    ONBOARDING_REASONS,
    ONBOARDING_STAGES,
    failure_details,
    failure_stage,
    save_instrumentation,
)


class CloudSupportTests(unittest.TestCase):
    def test_group_cleanup_waits_for_children_after_leader_exits(self):
        leader = MagicMock(pid=12345)
        leader.poll.return_value = 0
        gone = threading.Event()
        sent = []
        timers = []

        def signal_group(_pid, signum):
            if gone.is_set():
                raise ProcessLookupError()
            if signum:
                sent.append(signum)
                timer = threading.Timer(0.1, gone.set)
                timers.append(timer)
                timer.start()

        try:
            with patch("scripts.android_cloud_process.os.killpg", side_effect=signal_group):
                stop_group(leader, grace=1)
            self.assertEqual(sent, [signal.SIGINT])
        finally:
            for timer in timers:
                timer.join()

    def test_command_failure_never_exposes_stdout_or_stderr(self):
        with self.assertRaises(CloudCommandError) as failure:
            checked(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; print('synthetic-sensitive'); "
                        "print('synthetic-sensitive',file=sys.stderr); sys.exit(1)"
                    ),
                ],
                label="Synthetic command",
                timeout=5,
            )
        self.assertEqual(str(failure.exception), "Synthetic command failed")

    def test_command_timeout_is_bounded(self):
        with self.assertRaisesRegex(CloudCommandError, "timed out"):
            checked(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                label="Synthetic command",
                timeout=0.05,
            )

    def write_case(self, root, *, status="", name="syntheticCase"):
        path = root / "TEST-synthetic.xml"
        path.write_text(
            '<testsuite><properties><property value="synthetic-sensitive"/></properties>'
            f'<testcase classname="io.github.jihoon22lee.sallimbook.Test" name="{name}" time="0.1">'
            f"{status}<system-out>synthetic-sensitive</system-out></testcase></testsuite>"
        )

    def test_result_sanitizes_failure_details_and_properties(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_case(root, status='<failure message="synthetic-sensitive">secret</failure>')
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                save_instrumentation("existing", 1, root, root / "safe")
            content = (root / "safe/existing.xml").read_text()
            self.assertNotIn("synthetic-sensitive", content)
            self.assertNotIn("secret", content)
            self.assertNotIn("system-out", content)
            self.assertIn('failures="1"', content)

    def test_only_exact_public_onboarding_stage_survives_both_redaction_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            suite = ET.Element("testsuite")
            case = ET.SubElement(
                suite, "testcase", classname=ONBOARDING_CLASS, name=ONBOARDING_METHOD
            )
            failure = ET.SubElement(
                case,
                "failure",
                message=(
                    "java.lang.AssertionError: SALLIMBOOK_CLOUD_STAGE: FILL_PASSWORD; "
                    "REASON: ACTION_FAILED; PRE: 1110; POST: 1110"
                ),
            )
            failure.text = "synthetic-sensitive stack and view snapshot"
            ET.SubElement(case, "system-out").text = "synthetic-sensitive"
            ET.ElementTree(suite).write(root / "TEST-current.xml")
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                save_instrumentation("onboarding", 1, root, root / "safe")
            clean = (root / "safe/onboarding.xml").read_text()
            self.assertNotIn("synthetic-sensitive", clean)
            self.assertNotIn("java.lang", clean)
            node = ET.fromstring(clean).find("testcase/failure")
            self.assertEqual(node.get("stage"), "FILL_PASSWORD")
            self.assertEqual(
                failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node),
                {
                    "stage": "FILL_PASSWORD",
                    "reason": "ACTION_FAILED",
                    "pre": "1110",
                    "post": "1110",
                },
            )
            self.assertEqual(
                failure_stage(ONBOARDING_CLASS, ONBOARDING_METHOD, node), "FILL_PASSWORD"
            )

    def test_stage_rejects_other_tests_and_dynamic_or_similar_messages(self):
        for message in (
            "SALLIMBOOK_CLOUD_STAGE: FILL_PASSWORD synthetic-sensitive",
            "synthetic-sensitive SALLIMBOOK_CLOUD_STAGE: FILL_PASSWORD",
            "SALLIMBOOK_CLOUD_STAGE: FILL_PASSWORD\nsynthetic-sensitive",
            "SALLIMBOOK_CLOUD_STAGE: UNKNOWN_STAGE",
            "SALLIMBOOK_CLOUD_STAGE: fill_password",
            "SALLIMBOOK_CLOUD_STAGE: FILL_PASSWORD\n",
            "java.lang.IllegalArgumentException: SALLIMBOOK_CLOUD_STAGE: FILL_PASSWORD",
        ):
            with self.subTest(message=message):
                node = ET.Element("failure", message=message)
                self.assertIsNone(failure_stage(ONBOARDING_CLASS, ONBOARDING_METHOD, node))
        node = ET.Element("failure", message="SALLIMBOOK_CLOUD_STAGE: FILL_PASSWORD")
        self.assertIsNone(failure_stage(ONBOARDING_CLASS + "Other", ONBOARDING_METHOD, node))
        self.assertIsNone(failure_stage(ONBOARDING_CLASS, ONBOARDING_METHOD + "Other", node))
        node = ET.Element("failure", stage="FILL_PASSWORD synthetic-sensitive")
        self.assertIsNone(failure_stage(ONBOARDING_CLASS, ONBOARDING_METHOD, node))
        node = ET.Element("skipped", stage="FILL_PASSWORD")
        self.assertIsNone(failure_stage(ONBOARDING_CLASS, ONBOARDING_METHOD, node))

    def test_android_text_only_failure_accepts_only_the_stackless_marker(self):
        for ending in ("", "\n", "\r\n"):
            node = ET.Element("failure")
            node.text = "java.lang.AssertionError: SALLIMBOOK_CLOUD_STAGE: SETUP_AVAILABLE" + ending
            self.assertEqual(
                failure_stage(ONBOARDING_CLASS, ONBOARDING_METHOD, node), "SETUP_AVAILABLE"
            )
        for text in (
            (
                "java.lang.AssertionError: SALLIMBOOK_CLOUD_STAGE: SETUP_AVAILABLE\n"
                " at synthetic-sensitive"
            ),
            "java.lang.AssertionError: SALLIMBOOK_CLOUD_STAGE: SETUP_AVAILABLE synthetic-sensitive",
            (
                "synthetic-sensitive\njava.lang.AssertionError: "
                "SALLIMBOOK_CLOUD_STAGE: SETUP_AVAILABLE"
            ),
        ):
            node = ET.Element("failure")
            node.text = text
            self.assertIsNone(failure_stage(ONBOARDING_CLASS, ONBOARDING_METHOD, node))

    def test_workflow_redaction_preserves_stage_without_failure_text(self):
        repository = Path(__file__).resolve().parents[1]
        workflow = (repository / ".github/workflows/android-instrumentation.yml").read_text()
        section = workflow.split("      - name: Create redacted evidence", 1)[1]
        inline = textwrap.dedent(
            section.split("python3 - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sallimbook-android-probe/tests"
            source.mkdir(parents=True)
            suite = ET.Element("testsuite")
            for index in range(12):
                ET.SubElement(suite, "testcase", classname="SyntheticTest", name=f"case{index}")
            ET.ElementTree(suite).write(source / "existing.xml")
            suite = ET.Element("testsuite")
            case = ET.SubElement(
                suite, "testcase", classname=ONBOARDING_CLASS, name=ONBOARDING_METHOD
            )
            problem = ET.SubElement(
                case,
                "failure",
                stage="SETUP_AVAILABLE",
                reason="ROOT_NOT_FOCUSED",
                pre="0110",
                post="0010",
                message="synthetic-sensitive",
            )
            problem.text = "synthetic-sensitive trace"
            ET.ElementTree(suite).write(source / "onboarding.xml")
            (source.parent / "result.json").write_text("{}")
            environment = {
                "RUNNER_TEMP": temporary,
                "GITHUB_SHA": "0" * 40,
                "GITHUB_RUN_ID": "123",
                "GITHUB_RUN_ATTEMPT": "1",
                "SALLIMBOOK_CLEANUP_OUTCOME": "success",
                "SALLIMBOOK_RELEASE_OUTCOME": "skipped",
                "GITHUB_STEP_SUMMARY": str(root / "summary"),
            }
            with (
                patch.dict(os.environ, environment),
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                exec(compile(inline, "workflow-evidence", "exec"), {})
            output = root / "sallimbook-android-evidence"
            safe = (output / "onboarding.xml").read_text()
            self.assertNotIn("synthetic-sensitive", safe)
            self.assertIn('stage="SETUP_AVAILABLE"', safe)
            self.assertIn('reason="ROOT_NOT_FOCUSED"', safe)
            self.assertIn('pre="0110"', safe)
            self.assertIn('post="0010"', safe)
            self.assertEqual(json.loads((output / "summary.json").read_text())["status"], "FAIL")

    def test_reason_and_boolean_diagnostics_are_bounded_and_never_copy_dynamic_text(self):
        for reason in ONBOARDING_REASONS:
            for bits in ("1111", "0000", "1010", "----"):
                marker = (
                    f"SALLIMBOOK_CLOUD_STAGE: CANCEL_SCROLL; REASON: {reason}; "
                    f"PRE: {bits}; POST: {bits}"
                )
                node = ET.Element("failure", message=marker)
                self.assertEqual(
                    failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node),
                    {
                        "stage": "CANCEL_SCROLL",
                        "reason": reason,
                        "pre": bits,
                        "post": bits,
                    },
                )
        for value in (
            "synthetic-sensitive",
            "11111",
            "010",
            "0-10",
            "TRUE",
            "1110 synthetic-sensitive",
        ):
            node = ET.Element(
                "failure", stage="CANCEL_SCROLL", reason="ACTION_FAILED", pre=value, post="1110"
            )
            self.assertEqual(failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), {})
        for reason in (
            "java.lang.IllegalStateException",
            "action_failed",
            "ACTION_FAILED synthetic-sensitive",
        ):
            node = ET.Element(
                "failure", stage="CANCEL_SCROLL", reason=reason, pre="1110", post="1110"
            )
            self.assertEqual(failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), {})
        node = ET.Element(
            "failure",
            message=(
                "SALLIMBOOK_CLOUD_STAGE: CANCEL_SCROLL; REASON: ACTION_FAILED; "
                "PRE: 1110; POST: 1110 "
                "synthetic-sensitive"
            ),
        )
        self.assertEqual(failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), {})
        node = ET.Element(
            "failure", stage="CANCEL_SCROLL", reason="ACTION_FAILED", pre="1110", post="1110"
        )
        self.assertEqual(failure_details(ONBOARDING_CLASS + "Other", ONBOARDING_METHOD, node), {})
        self.assertEqual(failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD + "Other", node), {})
        node.set("post", "synthetic-sensitive")
        self.assertEqual(failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), {})

    def test_stage_allowlist_exactly_matches_native_test_enum(self):
        source = Path(__file__).resolve().parents[1] / (
            "apps/client/android/app/src/androidTest/java/io/github/jihoon22lee/"
            "sallimbook/AndroidCloudOnboardingTest.kt"
        )
        body = re.search(r"enum class CloudStage\s*\{([^}]+)\}", source.read_text())[1]
        values = {value.strip() for value in body.split(",")}
        self.assertEqual(values, ONBOARDING_STAGES)
        reasons = re.search(r"enum class CloudReason\s*\{([^}]+)\}", source.read_text())[1]
        self.assertEqual({value.strip() for value in reasons.split(",")}, ONBOARDING_REASONS)
        for value in values:
            for prefix in ("", "java.lang.AssertionError: "):
                node = ET.Element("failure", message=prefix + "SALLIMBOOK_CLOUD_STAGE: " + value)
                self.assertEqual(failure_stage(ONBOARDING_CLASS, ONBOARDING_METHOD, node), value)

    def test_old_pass_xml_cannot_replace_an_empty_current_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_case(root)
            current = root / "new-run"
            current.mkdir()
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                save_instrumentation("existing", 1, current, root / "safe")
            self.assertEqual(ET.parse(root / "safe/existing.xml").getroot().get("tests"), "0")

    def test_duplicate_testcases_do_not_satisfy_expected_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_case(root)
            (root / "TEST-copy.xml").write_bytes((root / "TEST-synthetic.xml").read_bytes())
            with self.assertRaisesRegex(RuntimeError, "Duplicate"):
                save_instrumentation("existing", 2, root, root / "safe")

    def test_skipped_test_is_preserved_and_skipped_onboarding_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_case(
                root,
                status='<skipped message="synthetic-sensitive"/>',
                name="ownerFlagCannotUseKeystoreCipherWithoutActualBiometricAuthorization",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                counts = save_instrumentation("existing", 1, root, root / "safe")
                with self.assertRaisesRegex(RuntimeError, "skipped"):
                    save_instrumentation("onboarding", 1, root, root / "safe")
            self.assertEqual(counts["skipped"], 1)
            self.assertNotIn("synthetic-sensitive", (root / "safe/existing.xml").read_text())


if __name__ == "__main__":
    unittest.main()
