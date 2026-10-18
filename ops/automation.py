"""Explicit, serialized SallimBook operator jobs; no work occurs while importing."""

import argparse
import fcntl
import json
import os
import re
import signal
import stat
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ops.backup import OperationError, digest, private_directory, private_file, publish_json
from ops.deploy import render
from ops.deploy import validate as validate_deployment

ROOT = Path(__file__).resolve().parents[1]
TASKS = {"backup", "health", "restore-check", "cvd-refresh", "startup", "recover"}
BACKUP_WORKER_TIMEOUT = 1800
# Source checks, network/image checks, helper extraction, ack and failed-worker cleanup.
BACKUP_OVERHEAD_BUDGET = 900
LIMITS = {
    "backup": BACKUP_WORKER_TIMEOUT + BACKUP_OVERHEAD_BUDGET,
    "health": 300,
    "restore-check": 7200,
    "cvd-refresh": 3600,
    "startup": 600,
    "recover": 600,
}
PATH_KEYS = {
    "deployment_directory",
    "state_directory",
    "backup_directory",
    "backup_service_file",
    "backup_recipient_file",
    "restore_directory",
    "restore_identity_file",
    "build_directory",
    "sdk_directory",
    "java_home",
    "python_executable",
    "uv_executable",
}
KEYS = PATH_KEYS | {"format", "project", "operator_source_commit", "deployment_sha256"}


class AutomationError(OperationError):
    def __init__(self, code):
        self.code = code
        super().__init__("SallimBook automation failed: " + code)


def now_text():
    return datetime.now(UTC).isoformat()


def canonical_path(value):
    if not isinstance(value, str) or not re.fullmatch(r"/[a-zA-Z0-9_./-]+", value):
        raise AutomationError("CONFIG_PATH")
    path = Path(value)
    if ".." in path.parts or str(path) != value or len(path.parts) < 3:
        raise AutomationError("CONFIG_PATH")
    return path


def validate_config(value):
    if not isinstance(value, dict) or set(value) != KEYS or type(value["format"]) is not int:
        raise AutomationError("CONFIG_FIELDS")
    if value["format"] != 1 or value["project"] not in {"sallimbook-prod", "sallimbook-staging"}:
        raise AutomationError("CONFIG_PROJECT")
    for key, width in (("operator_source_commit", 40), ("deployment_sha256", 64)):
        if not isinstance(value[key], str) or not re.fullmatch(
            r"[0-9a-f]{" + str(width) + "}", value[key]
        ):
            raise AutomationError("CONFIG_DIGEST")
    paths = {key: canonical_path(value[key]) for key in PATH_KEYS}
    directories = [
        paths[key]
        for key in ("state_directory", "backup_directory", "restore_directory", "build_directory")
    ]
    for path in directories:
        if path.name != value["project"] or len(path.parts) < 4:
            raise AutomationError("CONFIG_DEDICATED_DIRECTORY")
        for other in directories:
            if path != other and (path.is_relative_to(other) or other.is_relative_to(path)):
                raise AutomationError("CONFIG_OVERLAP")
    if len(set(directories)) != len(directories):
        raise AutomationError("CONFIG_OVERLAP")
    for key in ("backup_service_file", "backup_recipient_file", "restore_identity_file"):
        if any(paths[key].is_relative_to(path) for path in directories):
            raise AutomationError("CONFIG_SECRET_STORAGE")
    if paths["deployment_directory"] in directories:
        raise AutomationError("CONFIG_OVERLAP")
    if any(path.is_relative_to(ROOT) or ROOT.is_relative_to(path) for path in directories):
        raise AutomationError("CONFIG_SOURCE_OVERLAP")
    return dict(value)


def read_json(path, *, private=True, limit=65536):
    path = private_file(path) if private else Path(path)
    if path.is_symlink() or path.stat().st_size > limit:
        raise AutomationError("STATE_FILE")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise AutomationError("STATE_FILE")
    return value


def load_config(path, expected_sha256):
    path = private_file(path)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or digest(path) != expected_sha256:
        raise AutomationError("CONFIG_CHANGED")
    value = validate_config(read_json(path))
    for key in ("state_directory", "build_directory"):
        private_directory(value[key])
    # UID 1000 may not traverse a UID 10001/0700 ancestor. The container worker
    # performs the authoritative checks for backup, documents and secret files.
    for key in PATH_KEYS - {"python_executable", "uv_executable"}:
        candidate = Path(value[key])
        for parent in (candidate, *candidate.parents):
            try:
                if parent.is_symlink():
                    raise AutomationError("CONFIG_SYMLINK")
            except PermissionError:
                break
    for key in ("python_executable", "uv_executable"):
        if not Path(value[key]).is_file() or not os.access(value[key], os.X_OK):
            raise AutomationError("TOOL_MISSING")
    for key in ("sdk_directory", "java_home"):
        if not Path(value[key]).is_dir():
            raise AutomationError("TOOL_MISSING")
    return value


def command_environment(config):
    # Keep credentials and unrelated proxy/PG/Vite overrides out of child jobs.
    result = {
        key: os.environ[key]
        for key in ("HOME", "USER", "LOGNAME", "XDG_RUNTIME_DIR")
        if key in os.environ
    }
    result.update(
        PATH=str(Path(config["uv_executable"]).parent) + ":/usr/local/bin:/usr/bin:/bin",
        JAVA_HOME=config["java_home"],
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUNBUFFERED="1",
        TZ="UTC",
        LANG="C.UTF-8",
        LC_ALL="C.UTF-8",
    )
    return result


class Runner:
    """Never print a command's raw output or error, including failed DB utilities."""

    def __init__(self, config):
        self.environment = command_environment(config)

    def run(self, args, *, timeout=60, cwd=ROOT):
        process = subprocess.Popen(
            [str(arg) for arg in args],
            cwd=cwd,
            env=self.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            raise AutomationError("COMMAND_TIMEOUT") from None
        if process.returncode:
            raise AutomationError("COMMAND_FAILED")
        if len(output) > 2 * 1024 * 1024:
            raise AutomationError("COMMAND_OUTPUT_LIMIT")
        return output.decode("utf-8")


def verify_operator_source(config, runner):
    revision = runner.run(["git", "rev-parse", "HEAD"]).strip()
    dirty = runner.run(["git", "status", "--porcelain"])
    if revision != config["operator_source_commit"] or dirty.strip():
        raise AutomationError("OPERATOR_SOURCE_CHANGED")


def validate_rendered(directory, expected_sha256, project):
    directory = Path(directory)
    private_directory(directory)
    manifest = directory / "deployment.json"
    if manifest.is_symlink() or digest(manifest) != expected_sha256:
        raise AutomationError("DEPLOYMENT_CHANGED")
    value = validate_deployment(read_json(manifest, private=False))
    if value["project"] != project:
        raise AutomationError("DEPLOYMENT_PROJECT")
    for name, expected in render(value).items():
        path = directory / name
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise AutomationError("DEPLOYMENT_SYMLINK")
        content = path.read_text()
        actual = content if isinstance(expected, str) else json.loads(content)
        if actual != expected:
            raise AutomationError("DEPLOYMENT_DRIFT")
    return value


def deployment_binding(config):
    original = validate_rendered(
        config["deployment_directory"], config["deployment_sha256"], config["project"]
    )
    runtime = Path(original["runtime_directory"])
    for key in ("state_directory", "backup_directory", "restore_directory", "build_directory"):
        path = Path(config[key])
        if path.is_relative_to(runtime) or runtime.is_relative_to(path):
            raise AutomationError("RUNTIME_STORAGE_OVERLAP")
    pointer_path = Path(config["state_directory"]) / "active-deployment.json"
    if not pointer_path.exists() and not pointer_path.is_symlink():
        return {
            "directory": config["deployment_directory"],
            "sha256": config["deployment_sha256"],
            "manifest": original,
            "source_run": None,
        }
    pointer = read_json(pointer_path)
    if set(pointer) != {"format", "project", "directory", "sha256", "source_run"} or (
        pointer["format"] != 1 or pointer["project"] != config["project"]
    ):
        raise AutomationError("DEPLOYMENT_POINTER")
    directory = canonical_path(pointer["directory"])
    if not directory.is_relative_to(Path(config["build_directory"])):
        raise AutomationError("DEPLOYMENT_POINTER")
    active = validate_rendered(directory, pointer["sha256"], config["project"])
    if {key: value for key, value in active.items() if key != "api_image"} != (
        {key: value for key, value in original.items() if key != "api_image"}
    ):
        raise AutomationError("DEPLOYMENT_SCOPE_CHANGED")
    return {
        "directory": str(directory),
        "sha256": pointer["sha256"],
        "manifest": active,
        "source_run": pointer["source_run"],
    }


def atomic_json(path, value):
    path = Path(path)
    private_directory(path.parent)
    if path.exists() or path.is_symlink():
        private_file(path)
    temporary = path.parent / ("." + path.name + "." + uuid4().hex)
    try:
        publish_json(temporary, value)
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def project_lock(state):
    path = private_directory(state) / "automation.lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        info = os.fstat(descriptor)
        if (
            info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise AutomationError("LOCK_FILE")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AutomationError("ALREADY_RUNNING") from None
        yield
    finally:
        os.close(descriptor)


class Journal:
    def __init__(self, config, task, config_sha256):
        self.config = config
        self.config_sha256 = config_sha256
        self.run_id = str(uuid4())
        self.task = task
        state = private_directory(config["state_directory"])
        runs = state / "runs"
        runs.mkdir(mode=0o700, exist_ok=True)
        private_directory(runs)
        self.directory = runs / self.run_id
        self.directory.mkdir(mode=0o700)
        self.started_at = now_text()
        publish_json(
            self.directory / "started.json",
            {
                "format": 1,
                "run_id": self.run_id,
                "task": task,
                "started_at": self.started_at,
                "config_sha256": config_sha256,
                "project": config["project"],
                "operator_source_commit": config["operator_source_commit"],
            },
        )

    def phase(self, phase_name, **fields):
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", phase_name):
            raise AutomationError("JOURNAL_PHASE")
        publish_json(self.directory / (phase_name + ".json"), {"at": now_text(), **fields})

    def finish(self, *, status, result=None, error=None):
        value = {
            "format": 1,
            "run_id": self.run_id,
            "task": self.task,
            "status": status,
            "started_at": self.started_at,
            "completed_at": now_text(),
            "operator_source_commit": self.config["operator_source_commit"],
        }
        if result is not None:
            value["result"] = result
        if error is not None:
            value["error"] = error
        publish_json(self.directory / "finished.json", value)
        atomic_json(Path(self.config["state_directory"]) / ("latest-" + self.task + ".json"), value)
        return value


def unfinished_runs(config, *, exclude=None):
    runs = Path(config["state_directory"]) / "runs"
    if not runs.exists():
        return []
    private_directory(runs)
    result = []
    for path in sorted(runs.iterdir()):
        private_directory(path)
        if path.name == exclude:
            continue
        if (path / "recovered.json").exists():
            read_json(path / "recovered.json")
            continue
        if (path / "finished.json").exists() and not (path / "needs-recovery.json").exists():
            read_json(path / "finished.json")
            continue
        value = read_json(path / "started.json")
        if value.get("run_id") != path.name or value.get("project") != config["project"]:
            raise AutomationError("JOURNAL_IDENTITY")
        result.append((path, value))
    return result


def run(config_path, expected_sha256, task, *, runner=None):
    if task not in TASKS:
        raise AutomationError("UNKNOWN_TASK")
    config = load_config(config_path, expected_sha256)
    runner = runner or Runner(config)
    verify_operator_source(config, runner)
    with project_lock(config["state_directory"]):
        journal = Journal(config, task, expected_sha256)
        try:
            from ops.automation_runtime import Runtime

            binding = deployment_binding(config)
            runtime = Runtime(config, binding, runner, journal)
            pending = unfinished_runs(config, exclude=journal.run_id)
            if pending and task not in {"startup", "recover", "health"}:
                raise AutomationError("RECOVERY_REQUIRED")
            if task in {"startup", "recover"}:
                runtime.recover(pending)
            if task == "recover":
                result = {"reconciled_runs": len(pending)}
            elif task == "health":
                result = runtime.health()
                if pending:
                    raise AutomationError("RECOVERY_REQUIRED")
            else:
                result = getattr(runtime, task.replace("-", "_"))()
            return journal.finish(status="completed", result=result)
        except Exception as failure:
            code = failure.code if isinstance(failure, AutomationError) else "OPERATION_FAILED"
            journal.finish(status="failed", error=code)
            raise AutomationError(code) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "run"))
    parser.add_argument("configuration", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--task", choices=sorted(TASKS))
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "validate":
            config = load_config(args.configuration, args.sha256)
            verify_operator_source(config, Runner(config))
            binding = deployment_binding(config)
            result = {
                "status": "configuration-validated",
                "project": config["project"],
                "operator_source_commit": config["operator_source_commit"],
                "app_source_commit": binding["manifest"]["source_commit"],
            }
        else:
            if args.task is None:
                raise AutomationError("TASK_REQUIRED")
            outcome = run(args.configuration, args.sha256, args.task)
            result = {key: outcome[key] for key in ("status", "task", "run_id")}
    except Exception as failure:
        code = (
            failure.code if isinstance(failure, AutomationError) else "CONFIG_OR_OPERATION_FAILED"
        )
        print(json.dumps({"status": "failed", "code": code}))
        return 75 if code == "ALREADY_RUNNING" else 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    # Runtime imports this module by its canonical name. Use that same Runner
    # and AutomationError so retry handlers also catch errors from `python -m`.
    from ops.automation import main as canonical_main

    sys.exit(canonical_main())
