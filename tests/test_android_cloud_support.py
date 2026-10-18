"""Synthetic subprocesses and XML only; no Android SDK, Docker or DB access."""

import ast
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
    ONBOARDING_STATUSES,
    failure_details,
    failure_stage,
    save_instrumentation,
)


class CloudFixtureHttpTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def proxy_type():
        # Execute the actual dependency-free ASGI wrapper, without importing the
        # fixture's PostgreSQL/SDK orchestration into the standard-library suite.
        source = Path(__file__).resolve().parents[1] / "scripts/test_android_cloud.py"
        module = ast.parse(source.read_text(), filename=str(source))
        wrapper = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "SyntheticIdentityProxy"
        )
        identity = next(
            node
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "IDENTITY" for target in node.targets
            )
        )
        namespace = {}
        exec(
            compile(ast.Module(body=[identity, wrapper], type_ignores=[]), str(source), "exec"),
            namespace,
        )
        return namespace["SyntheticIdentityProxy"], namespace["IDENTITY"]

    async def test_http1_response_closes_connection_without_changing_payload_or_identity_checks(
        self,
    ):
        proxy, identity = self.proxy_type()
        for version in ("1.0", "1.1"):
            with self.subTest(version=version):
                request = {"type": "http.request", "body": b"synthetic-request"}
                scope = {
                    "type": "http",
                    "http_version": version,
                    "headers": [
                        (b"x-synthetic", b"preserved"),
                        (b"Tailscale-User-Login", b"ignored"),
                    ],
                    "client": ("127.0.0.1", 12345),
                }
                start = {
                    "type": "http.response.start",
                    "status": 202,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"Connection", b"keep-alive"),
                    ],
                }
                first = {"type": "http.response.body", "body": b'{"available":', "more_body": True}
                last = {"type": "http.response.body", "body": b"true}"}
                received, sent = [], []

                async def receive(request=request):
                    return request

                async def send(message, sent=sent):
                    sent.append(message)

                async def app(
                    inner,
                    incoming,
                    outgoing,
                    received=received,
                    request=request,
                    messages=(start, first, last),
                ):
                    received.append(inner)
                    self.assertIs(await incoming(), request)
                    for message in messages:
                        await outgoing(message)

                await proxy(app)(scope, receive, send)
                self.assertEqual(received[0]["client"], scope["client"])
                self.assertEqual(
                    received[0]["headers"],
                    [(b"x-synthetic", b"preserved"), (b"tailscale-user-login", identity)],
                )
                self.assertEqual(scope["headers"][-1], (b"Tailscale-User-Login", b"ignored"))
                self.assertEqual(sent[0]["status"], 202)
                self.assertEqual(
                    sent[0]["headers"],
                    [(b"content-type", b"application/json"), (b"connection", b"close")],
                )
                self.assertEqual(start["headers"][-1], (b"Connection", b"keep-alive"))
                self.assertIs(sent[1], first)
                self.assertIs(sent[2], last)

    async def test_non_http_and_http2_do_not_receive_a_connection_header(self):
        proxy, _ = self.proxy_type()
        for scope in ({"type": "lifespan"}, {"type": "http", "http_version": "2", "headers": []}):
            sent = []
            message = (
                {"type": "lifespan.startup.complete"}
                if scope["type"] == "lifespan"
                else {"type": "http.response.start", "status": 200, "headers": []}
            )

            async def receive():
                return {"type": "lifespan.startup"}

            async def send(outgoing, sent=sent):
                sent.append(outgoing)

            async def app(inner, incoming, outgoing, scope=scope, message=message):
                if inner["type"] != "http":
                    self.assertIs(inner, scope)
                    self.assertIs(incoming, receive)
                    self.assertIs(outgoing, send)
                await outgoing(message)

            await proxy(app)(scope, receive, send)
            self.assertEqual(sent, [message])
            self.assertIs(sent[0], message)


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
                    "REASON: ACTION_FAILED; PRE: 1110; POST: 1110; "
                    "FLOW: 000; STATUS: REQUEST_PENDING; TAP: 11110; TAP_STATUS: REQUEST_PENDING; "
                    "HOME: 1111000111"
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
                    "flow": "000",
                    "status": "REQUEST_PENDING",
                    "tap": "11110",
                    "tap_status": "REQUEST_PENDING",
                    "home": "1111000111",
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
                flow="000",
                status="NETWORK_UNAVAILABLE",
                tap="11110",
                tap_status="REQUEST_PENDING",
                home="1111000111",
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
            self.assertIn('flow="000"', safe)
            self.assertIn('status="NETWORK_UNAVAILABLE"', safe)
            self.assertIn('tap="11110"', safe)
            self.assertIn('tap_status="REQUEST_PENDING"', safe)
            self.assertIn('home="1111000111"', safe)
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

    def test_flow_and_public_status_diagnostics_reject_unknown_or_sensitive_details(self):
        for status in ONBOARDING_STATUSES:
            for flow in ("000", "111", "101", "---"):
                marker = (
                    "SALLIMBOOK_CLOUD_STAGE: SESSION_CREATED; REASON: ASSERTION; "
                    f"PRE: ----; POST: ----; FLOW: {flow}; STATUS: {status}"
                )
                node = ET.Element("failure", message=marker)
                self.assertEqual(
                    failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node),
                    {
                        "stage": "SESSION_CREATED",
                        "reason": "ASSERTION",
                        "pre": "----",
                        "post": "----",
                        "flow": flow,
                        "status": status,
                    },
                )
        for field, value in (
            ("flow", "1111"),
            ("flow", "1-1"),
            ("flow", "true"),
            ("flow", "111 synthetic-sensitive"),
            ("status", "unknown"),
            ("status", "NETWORK_UNAVAILABLE synthetic-sensitive"),
            ("status", "synthetic-sensitive"),
        ):
            node = ET.Element(
                "failure",
                stage="SESSION_CREATED",
                reason="ASSERTION",
                pre="----",
                post="----",
                flow="000",
                status="NETWORK_UNAVAILABLE",
            )
            node.set(field, value)
            self.assertEqual(failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), {})
        node = ET.Element(
            "failure",
            message=(
                "SALLIMBOOK_CLOUD_STAGE: SESSION_CREATED; REASON: ASSERTION; "
                "PRE: ----; POST: ----; "
                "FLOW: 000; STATUS: NETWORK_UNAVAILABLE synthetic-sensitive"
            ),
        )
        self.assertEqual(failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), {})
        node = ET.Element(
            "failure",
            stage="SESSION_CREATED",
            reason="ASSERTION",
            pre="----",
            post="----",
            flow="000",
            status="NETWORK_UNAVAILABLE",
        )
        self.assertEqual(failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD + "Other", node), {})

    def test_tap_diagnostics_reject_partial_dynamic_or_unrelated_metadata(self):
        baseline = {
            "stage": "SESSION_CREATED",
            "reason": "ASSERTION",
            "pre": "----",
            "post": "----",
            "flow": "000",
            "status": "INPUT_INVALID",
        }
        for bits in ("10000", "11110", "01111", "-----"):
            for status in ONBOARDING_STATUSES:
                expected = {**baseline, "tap": bits, "tap_status": status}
                node = ET.Element("failure", **expected)
                self.assertEqual(
                    failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), expected
                )
                marker = (
                    "SALLIMBOOK_CLOUD_STAGE: SESSION_CREATED; REASON: ASSERTION; "
                    "PRE: ----; POST: ----; FLOW: 000; STATUS: INPUT_INVALID; "
                    f"TAP: {bits}; TAP_STATUS: {status}"
                )
                node = ET.Element("failure", message=marker)
                self.assertEqual(
                    failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), expected
                )
                node.set("message", marker + " synthetic-sensitive")
                self.assertEqual(failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), {})
        for field, value in (
            ("tap", "1111"),
            ("tap", "1-111"),
            ("tap", "true"),
            ("tap", "11111 synthetic-sensitive"),
            ("tap_status", "unknown"),
            ("tap_status", "INPUT_INVALID synthetic-sensitive"),
        ):
            attributes = {
                **baseline,
                "tap": "10000",
                "tap_status": "INPUT_INVALID",
                field: value,
            }
            node = ET.Element("failure", **attributes)
            self.assertEqual(failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), {})
        for missing in ("reason", "pre", "post", "flow", "status", "tap", "tap_status"):
            attributes = {**baseline, "tap": "10000", "tap_status": "INPUT_INVALID"}
            del attributes[missing]
            node = ET.Element("failure", **attributes)
            self.assertEqual(failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), {})
        node = ET.Element("failure", **baseline, tap="10000", tap_status="INPUT_INVALID")
        self.assertEqual(failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD + "Other", node), {})
        node = ET.Element(
            "failure", stage="SESSION_CREATED", tap="10000", tap_status="INPUT_INVALID"
        )
        self.assertEqual(failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), {})

    def test_care_diagnostic_is_only_fixed_enums_after_complete_home_metadata(self):
        attributes = dict(
            stage="AUTHENTICATED_HOME",
            reason="ASSERTION",
            pre="----",
            post="----",
            flow="---",
            status="NOT_CHECKED",
            tap="11110",
            tap_status="REQUEST_PENDING",
            home="1111001100",
        )
        prefix = (
            "SALLIMBOOK_CLOUD_STAGE: AUTHENTICATED_HOME; REASON: ASSERTION; PRE: ----; POST: ----; "
            "FLOW: ---; STATUS: NOT_CHECKED; TAP: 11110; TAP_STATUS: REQUEST_PENDING; "
            "HOME: 1111001100"
        )
        for care, native in (
            ("NETWORK", "OK"),
            ("VALIDATION", "FORBIDDEN"),
            ("OTHER", "TIMEOUT"),
            ("NOT_CHECKED", "NOT_CHECKED"),
        ):
            expected = {**attributes, "care": care, "native_care": native}
            for node in (
                ET.Element("failure", **expected),
                ET.Element("failure", message=f"{prefix}; CARE: {care}; NATIVE_CARE: {native}"),
            ):
                self.assertEqual(
                    failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), expected
                )
        for care, native in (
            ("synthetic-sensitive", "OK"),
            ("NETWORK extra", "OK"),
            ("NETWORK", "OK extra"),
            ("NETWORK", None),
            (None, "OK"),
        ):
            attrs = {**attributes}
            if care is not None:
                attrs["care"] = care
            if native is not None:
                attrs["native_care"] = native
            self.assertEqual(
                failure_details(
                    ONBOARDING_CLASS, ONBOARDING_METHOD, ET.Element("failure", **attrs)
                ),
                {},
            )
        for missing in attributes:
            attrs = {**attributes, "care": "NETWORK", "native_care": "OK"}
            del attrs[missing]
            self.assertEqual(
                failure_details(
                    ONBOARDING_CLASS, ONBOARDING_METHOD, ET.Element("failure", **attrs)
                ),
                {},
            )

    def test_home_diagnostic_accepts_only_ten_bits_after_complete_metadata(self):
        attributes = dict(
            stage="AUTHENTICATED_HOME",
            reason="ASSERTION",
            pre="----",
            post="----",
            flow="---",
            status="NOT_CHECKED",
            tap="11110",
            tap_status="REQUEST_PENDING",
        )
        prefix = (
            "SALLIMBOOK_CLOUD_STAGE: AUTHENTICATED_HOME; REASON: ASSERTION; PRE: ----; POST: ----; "
            "FLOW: ---; STATUS: NOT_CHECKED; TAP: 11110; TAP_STATUS: REQUEST_PENDING; HOME: "
        )
        for bits in ("1111000111", "1000000000", "0000000000", "----------"):
            expected = {**attributes, "home": bits}
            for node in (
                ET.Element("failure", **expected),
                ET.Element("failure", message=prefix + bits),
            ):
                self.assertEqual(
                    failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), expected
                )
        for value in (
            "111100011",
            "11110001111",
            "1---------",
            "true",
            "1111000111 synthetic-sensitive",
        ):
            for node in (
                ET.Element("failure", **attributes, home=value),
                ET.Element("failure", message=prefix + value),
            ):
                self.assertEqual(failure_details(ONBOARDING_CLASS, ONBOARDING_METHOD, node), {})
        for missing in attributes:
            if missing == "stage":
                continue
            partial = {**attributes, "home": "1111000111"}
            del partial[missing]
            self.assertEqual(
                failure_details(
                    ONBOARDING_CLASS, ONBOARDING_METHOD, ET.Element("failure", **partial)
                ),
                {},
            )

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
        statuses = re.search(r"enum class CloudStatus\s*\{([^}]+)\}", source.read_text())[1]
        self.assertEqual({value.strip() for value in statuses.split(",")}, ONBOARDING_STATUSES)
        # Every mapped UI message must be a public literal in the production screen.
        production = (
            source.parents[6]
            / "main/java/io/github/jihoon22lee/sallimbook/auth/NativeOnboardingActivity.kt"
        )
        messages = re.findall(r'"([^"\n]+)" to CloudStatus\.[A-Z_]+', source.read_text())
        self.assertGreater(len(messages), 0)
        for message in messages:
            self.assertIn('"' + message + '"', production.read_text())
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
