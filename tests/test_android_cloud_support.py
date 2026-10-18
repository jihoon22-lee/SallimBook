"""Synthetic subprocesses and XML only; no Android SDK, Docker or DB access."""

import contextlib
import io
import signal
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.android_cloud_process import CloudCommandError, checked, stop_group
from scripts.android_cloud_results import save_instrumentation


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
