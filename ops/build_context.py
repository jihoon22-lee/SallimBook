"""Stage a minimal, secret-free Docker context from exact reviewed source."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def source_snapshot(commit, parent):
    """Build from committed bytes only, never ignored .env/public/keystore files."""
    with tempfile.TemporaryDirectory(
        prefix=".sallimbook-source-", dir=parent
    ) as temporary:
        checkout = Path(temporary)
        proc = subprocess.Popen(
            ["git", "archive", "--format=tar", commit],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
                for member in archive:
                    name = Path(member.name)
                    if (
                        name.is_absolute()
                        or ".." in name.parts
                        or not (member.isdir() or member.isreg())
                    ):
                        raise ValueError(
                            "Build source contains an unsupported path or link"
                        )
                    target = checkout / name
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with (
                            archive.extractfile(member) as source,
                            target.open("xb") as output,
                        ):
                            shutil.copyfileobj(source, output)
                        target.chmod(member.mode & 0o777)
            if proc.wait(timeout=30):
                raise ValueError("Committed source export failed")
            yield checkout
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.kill()
            proc.wait()


def build_environment():
    # Vite intentionally exposes VITE_* to bundled JS. Only committed build inputs
    # may select those values; do not inherit an operator's unrelated environment.
    return {
        key: value for key, value in os.environ.items() if not key.startswith("VITE_")
    }


def stage(output, commit):
    actual = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    ).strip()
    if actual != commit or dirty:
        raise ValueError("An exact clean reviewed commit is required")
    output = output.absolute()
    if output.is_relative_to(ROOT):
        raise ValueError("Stage build context outside the source tree")
    output.mkdir(mode=0o700, exist_ok=False)
    with source_snapshot(commit, output.parent) as checkout:
        stage_snapshot(output, commit, checkout)


def stage_snapshot(output, commit, checkout):
    api, web = output / "api", output / "web"
    api.mkdir()
    web.mkdir()
    lock = checkout / "services/api/uv.lock"
    lock_hash = hashlib.sha256(lock.read_bytes()).hexdigest()
    requirements = subprocess.check_output(
        [
            "uv",
            "export",
            "--project",
            "services/api",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--format",
            "requirements-txt",
        ],
        cwd=checkout,
    )
    if (
        b"--hash=sha256:" not in requirements
        or hashlib.sha256(lock.read_bytes()).hexdigest() != lock_hash
    ):
        raise ValueError("Frozen dependency export failed")
    (api / "requirements.txt").write_bytes(requirements)
    for source, target in (
        ("services/api/src", "src"),
        ("services/api/migrations", "migrations"),
        ("ops", "ops"),
    ):
        shutil.copytree(
            checkout / source,
            api / target,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
    shutil.copyfile(checkout / "services/api/alembic.ini", api / "alembic.ini")
    shutil.copyfile(checkout / "ops/Dockerfile.api", api / "Dockerfile")
    shutil.copyfile(checkout / "infra/documents/freshclam.conf", api / "freshclam.conf")
    scanner = (checkout / "infra/documents/clamd.conf").read_text()
    scanner = scanner.replace(
        "/run/sallimbook/clamd.sock", "/run/scanner/clamd.sock"
    ).replace("/run/sallimbook/spool", "/tmp")
    (api / "clamd.conf").write_text(scanner)
    subprocess.run(
        ["pnpm", "install", "--frozen-lockfile"],
        cwd=checkout,
        env=build_environment(),
        check=True,
    )
    subprocess.run(["pnpm", "build"], cwd=checkout, env=build_environment(), check=True)
    shutil.copytree(checkout / "apps/client/dist", web / "dist")
    shutil.copyfile(checkout / "ops/Dockerfile.web", web / "Dockerfile")
    files = {
        path.relative_to(output).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in output.rglob("*")
        if path.is_file()
    }
    (output / "build-inputs.json").write_text(
        json.dumps(
            {"source_commit": commit, "api_lock_sha256": lock_hash, "files": files},
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    stage(args.output, args.commit)
    print("Minimal build contexts staged. No images built or services started.")
