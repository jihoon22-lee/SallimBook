"""Build/run only SallimBook's isolated document-tool integration container.

Uses a dedicated lock; coordinate separately with any active browser tests. No host packages, network service, database,
user volumes, credentials, or plaintext documents are mounted into the test container.
"""

import argparse
import fcntl
import hashlib
import json
import subprocess
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "sallimbook-document-tools:sb023-20261018"
# Must match infra/documents/run_checks.py MEASURE_CASES (pinned by a unit test).
MEASURE_CASES = (
    "pdf-text-a4-1",
    "pdf-text-a4-2",
    "pdf-text-a4-4",
    "pdf-text-a4-8",
    "pdf-image-a4-1",
    "pdf-image-a4-4",
    "jpeg-photo-3072x2304",
    "jpeg-photo-4000x3000",
    "jpeg-photo-4608x3456",
)


@contextmanager
def tool_lock():
    directory = Path.home() / ".cache" / "sallimbook"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / "document-tools-test.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(
                "Another document-tool test is running; nothing was changed."
            ) from None
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def container_args(image_id: str, command: list[str] | None = None) -> list[str]:
    """docker create arguments: no network, read-only, no capabilities, bounded resources."""
    return [
        "docker",
        "create",
        "--name",
        "sallimbook-document-test-" + uuid.uuid4().hex,
        "--label",
        "io.sallimbook.purpose=document-validation-test",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "10001:10001",
        "--memory",
        "4g",
        "--memory-swap",
        "4g",
        "--cpus",
        "2",
        "--pids-limit",
        "64",
        "--ulimit",
        "core=0",
        "--tmpfs",
        "/run/sallimbook:rw,noexec,nosuid,nodev,size=96m,mode=0700,uid=10001,gid=10001",
        image_id,
        *(command or []),
    ]


def measure(image_id: str) -> int:
    """One fresh container per case so each cgroup memory.peak belongs to that case only."""
    failures = 0
    for case in MEASURE_CASES:
        container = None
        try:
            container = subprocess.check_output(
                container_args(
                    image_id,
                    ["python", "-B", "/opt/sallimbook/run_checks.py", "--measure", case],
                ),
                text=True,
            ).strip()
            result = subprocess.run(
                ["docker", "start", "--attach", container], timeout=900, check=False
            )
            failures += result.returncode != 0
        finally:
            if container:
                subprocess.run(
                    ["docker", "rm", "--force", container],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--measure", action="store_true")
    args = parser.parse_args()
    lock = json.loads((ROOT / "infra/documents/toolchain.lock.json").read_text())
    for filename, field in (
        ("services/api/uv.lock", "api_uv_lock_sha256"),
        ("infra/documents/requirements.txt", "requirements_sha256"),
    ):
        if hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() != lock[field]:
            raise SystemExit(
                "Refresh the reviewed document-tool dependency export before building."
            )
    with tool_lock():
        if not args.skip_build:
            subprocess.run(
                [
                    "docker",
                    "build",
                    "--platform",
                    "linux/amd64",
                    "--build-arg",
                    "SALLIMBOOK_CVD_REFRESH=" + datetime.now(UTC).date().isoformat(),
                    "-f",
                    "infra/documents/Dockerfile",
                    "-t",
                    IMAGE,
                    ".",
                ],
                cwd=ROOT,
                check=True,
            )
        if args.build_only:
            return 0
        image_id = subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE], text=True
        ).strip()
        if not image_id.startswith("sha256:") or len(image_id) != 71:
            raise SystemExit("Document test image is unavailable.")
        if args.measure:
            print(json.dumps({"image_id": image_id}))
            return measure(image_id)
        container = None
        try:
            container = subprocess.check_output(container_args(image_id), text=True).strip()
            result = subprocess.run(
                ["docker", "start", "--attach", container], timeout=360, check=False
            )
            print(
                json.dumps(
                    {
                        "image_id": image_id,
                        "exit_code": result.returncode,
                        "scope": "synthetic isolated tools; not production deployment",
                    }
                )
            )
            return result.returncode
        finally:
            if container:
                subprocess.run(
                    ["docker", "rm", "--force", container],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )


if __name__ == "__main__":
    raise SystemExit(main())
