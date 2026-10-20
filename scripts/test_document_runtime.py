"""Test-only real document tools in disposable containers: ClamAV and the isolated inspector.

No production parser limits change. The inspector container runs the production inspection
server with the production memory limit and no network, capabilities or writable root, so
OCR/render tools run as children of the RLIMIT-bounded worker exactly as deployed. Only a
private Unix socket directory is shared with this process; never filenames, HTTP, caller
commands, environment overrides, parser bypasses, or plaintext disk spools.
"""

import importlib.util
import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from sallimbook.core.errors import DomainError
from sallimbook.documents.validation import (
    check_inspector_availability,
    check_scanner_availability,
)
from test_document_tools import IMAGE, tool_lock

# Scripts run without the repository root on the import path; ops/deploy.py is stdlib-only.
_deploy_spec = importlib.util.spec_from_file_location(
    "sallimbook_ops_deploy", Path(__file__).resolve().parents[1] / "ops/deploy.py"
)
_deploy = importlib.util.module_from_spec(_deploy_spec)
_deploy_spec.loader.exec_module(_deploy)
INSPECTOR_MEMORY = _deploy.INSPECTOR_MEMORY
LABEL = "io.sallimbook.purpose=document-https-test"


def _wait_ready(check, path, message):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            check(str(path))
            return
        except DomainError:
            time.sleep(0.2)
    raise RuntimeError(message)


def _start(arguments):
    container = subprocess.check_output(
        ["docker", "run", "--detach", *arguments], text=True, stderr=subprocess.DEVNULL
    ).strip()
    if not re.fullmatch(r"[a-f0-9]{64}", container):
        raise RuntimeError("Private test container unavailable")
    return container


@contextmanager
def document_runtime():
    with tool_lock(), tempfile.TemporaryDirectory(prefix="sb-doc-tools-") as directory:
        private = Path(directory)
        private.chmod(0o700)
        socket_dir = private / "sockets"
        socket_dir.mkdir(mode=0o700)
        spool = socket_dir / "spool"
        spool.mkdir(mode=0o700)
        image = subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE], text=True
        ).strip()
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise RuntimeError("Pinned test tool image unavailable")
        containers = []
        try:
            uid, gid = os.getuid(), os.getgid()
            isolated = [
                "--label", LABEL, "--network", "none", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--user", f"{uid}:{gid}",
                "--ulimit", "core=0", "--mount", f"type=bind,src={socket_dir},dst=/run/sallimbook",
            ]
            containers.append(_start([
                "--name", "sallimbook-document-https-" + uuid4().hex, *isolated,
                "--memory", "4g", "--memory-swap", "4g", "--cpus", "2", "--pids-limit", "64",
                "--tmpfs", f"/run/sallimbook/spool:rw,noexec,nosuid,nodev,size=96m,mode=0700,uid={uid},gid={gid}",
                image, "/usr/local/sbin/clamd", "--config-file=/etc/sallimbook/clamd.conf",
            ]))
            scanner_socket = socket_dir / "clamd.sock"
            _wait_ready(
                check_scanner_availability, scanner_socket,
                "Real document scanner did not become ready",
            )
            info = scanner_socket.stat()
            if info.st_uid != uid or info.st_mode & 0o777 != 0o600:
                raise RuntimeError("Private scanner permissions changed")
            containers.append(_start([
                "--name", "sallimbook-document-https-inspector-" + uuid4().hex, *isolated,
                "--memory", INSPECTOR_MEMORY, "--memory-swap", INSPECTOR_MEMORY,
                "--pids-limit", "32",
                "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size=16m,mode=0700,uid={uid},gid={gid}",
                image, "python", "-B", "-m", "sallimbook.documents.inspector",
                "--socket", "/run/sallimbook/inspector.sock",
            ]))
            inspector_socket = socket_dir / "inspector.sock"
            _wait_ready(
                check_inspector_availability, inspector_socket,
                "Isolated document inspector did not become ready",
            )
            info = inspector_socket.stat()
            if info.st_uid != uid or info.st_mode & 0o777 != 0o660:
                raise RuntimeError("Private inspector permissions changed")
            yield {
                "document_scanner_socket": scanner_socket,
                "document_inspector_socket": inspector_socket,
            }
        finally:
            for container in containers:
                subprocess.run(
                    ["docker", "rm", "--force", container],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
                )
