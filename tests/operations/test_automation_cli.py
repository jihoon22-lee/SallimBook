"""Real CLI module boundary with synthetic Docker responses, never a real DB."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Installed only in each test subprocess through its temporary PYTHONPATH.
# Preserve the real main/run/Runner/Runtime.restore_check and their exception
# types. Substitute configuration and Docker responses to avoid real services.
SITECUSTOMIZE = r"""
import argparse
import atexit
import json
import os
import subprocess
import sys
from pathlib import Path

original_parse = argparse.ArgumentParser.parse_args
root = Path(os.environ['SALLIMBOOK_CLI_FIXTURE'])
trace = {'ready_attempts': 0, 'restore_checks': 0, 'removed_volume': False}
atexit.register(lambda: (root / 'trace.json').write_text(json.dumps(trace)))

def parse_args(parser, *args, **kwargs):
    result = original_parse(parser, *args, **kwargs)
    import ops.automation as canonical
    import ops.automation_runtime as runtime
    state = root / 'state'
    state.mkdir(mode=0o700)
    config = {
        'project': 'sallimbook-staging', 'operator_source_commit': 'a' * 40,
        'state_directory': str(state), 'backup_directory': str(root / 'unused-backup'),
        'restore_directory': str(root / 'unused-restore'),
        'restore_identity_file': str(root / 'unused-identity'),
        'uv_executable': '/unused/uv', 'java_home': '/unused/jdk',
    }
    binding = {'directory': str(root), 'sha256': 'b' * 64, 'source_run': None,
               'manifest': {'source_commit': 'a' * 40,
                            'runtime_directory': str(root / 'unused-runtime')}}
    # Both invocation styles get the same synthetic input. Their real Runner
    # and AutomationError definitions are deliberately left untouched.
    for module in (canonical, sys.modules['__main__']):
        module.load_config = lambda *_: config
        module.verify_operator_source = lambda *_: None
        module.deployment_binding = lambda *_: binding

    def worker(self, action, **kwargs):
        if action == 'restore-prepare':
            return {'status': 'restore-prepared'}
        if action == 'restore-check':
            trace['restore_checks'] += 1
            return {'status': 'restored-integrity-verified'}
        assert action == 'backup-verify'
        return {'status': 'backup-verified'}

    def remove(self, kind, *_):
        if kind == 'volume':
            trace['removed_volume'] = True

    runtime.Runtime.latest_backup = lambda *_: {}
    runtime.Runtime.worker = worker
    runtime.Runtime._remove_owned = remove
    clock = [0]
    runtime.time.monotonic = lambda: clock[0]
    def sleep(seconds):
        clock[0] += seconds
    runtime.time.sleep = sleep

    class DockerProcess:
        def __init__(self, command, **kwargs):
            assert command[:3] == runtime.DOCKER, 'Only synthetic Docker calls are allowed'
            assert kwargs['start_new_session'] is True
            self.returncode = 0
            if command[3] == 'exec':
                assert command[-5:] == ['pg_isready', '-U', 'sallimbook_restore', '-d', 'postgres']
                trace['ready_attempts'] += 1
                # PostgreSQL normally needs at least one startup poll.
                self.returncode = 2 if (trace['ready_attempts'] == 1 or
                    os.environ.get('SALLIMBOOK_CLI_NOT_READY') == '1') else 0
        def communicate(self, timeout):
            return (b'SYNTHETIC_PRIVATE_DIAGNOSTIC' if self.returncode else b''), None

    subprocess.Popen = DockerProcess
    return result

argparse.ArgumentParser.parse_args = parse_args
"""


class AutomationCliTests(unittest.TestCase):
    def invoke(self, entrypoint, *, not_ready=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sitecustomize.py").write_text(textwrap.dedent(SITECUSTOMIZE))
            environment = {
                **os.environ,
                "PYTHONPATH": str(root) + os.pathsep + str(ROOT),
                "PYTHONDONTWRITEBYTECODE": "1",
                "SALLIMBOOK_CLI_FIXTURE": str(root),
                "SALLIMBOOK_CLI_NOT_READY": "1" if not_ready else "0",
            }
            result = subprocess.run(
                [
                    sys.executable,
                    *entrypoint,
                    "run",
                    str(root / "configuration.json"),
                    "--sha256",
                    "b" * 64,
                    "--task",
                    "restore-check",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result, json.loads((root / "trace.json").read_text())

    def test_module_and_imported_entrypoints_both_retry_database_startup(self):
        for entrypoint in (
            ["-m", "ops.automation"],
            ["-c", "from ops.automation import main; raise SystemExit(main())"],
        ):
            with self.subTest(entrypoint=entrypoint):
                result, trace = self.invoke(entrypoint)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["status"], "completed")
                self.assertEqual(
                    trace,
                    {
                        "ready_attempts": 2,
                        "restore_checks": 1,
                        "removed_volume": True,
                    },
                )

    def test_cli_still_fails_when_database_readiness_deadline_expires(self):
        result, trace = self.invoke(["-m", "ops.automation"], not_ready=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "status": "failed",
                "code": "RESTORE_DATABASE_UNAVAILABLE",
            },
        )
        self.assertGreater(trace["ready_attempts"], 1)
        self.assertEqual(trace["restore_checks"], 0)
        self.assertFalse(trace["removed_volume"])
        self.assertNotIn("SYNTHETIC_PRIVATE_DIAGNOSTIC", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
