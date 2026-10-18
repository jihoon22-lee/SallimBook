"""Stage a minimal, secret-free Docker context from exact reviewed source."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION_LABEL = "org.opencontainers.image.revision"
ROLE_LABEL = "io.sallimbook.image-role"


def write_image_source(context, template, commit, role):
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or role not in {"api", "web"}:
        raise ValueError("Exact source revision and application image role required")
    (context / "source-revision.json").write_text(
        json.dumps({"source_commit": commit, "image_role": role}, sort_keys=True) + "\n"
    )
    # Literal generated labels cannot be forgotten or changed through a build ARG.
    # Both the image metadata and filesystem record the archived source revision.
    (context / "Dockerfile").write_text(
        template.read_text().rstrip() + "\n"
        "COPY source-revision.json /usr/share/sallimbook/source-revision.json\n"
        f'LABEL {REVISION_LABEL}="{commit}" {ROLE_LABEL}="{role}"\n'
    )
    for name in ("source-revision.json", "Dockerfile"):
        (context / name).chmod(0o644)


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
                        target.chmod(member.mode & 0o777)
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


def stage_api_snapshot(api, commit, checkout, *, uv="uv"):
    """Stage only the API from an already verified exact source archive."""
    api.mkdir(exist_ok=False)
    lock = checkout / "services/api/uv.lock"
    lock_hash = hashlib.sha256(lock.read_bytes()).hexdigest()
    requirements = subprocess.check_output(
        [
            uv,
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
        timeout=180,
        stderr=subprocess.DEVNULL,
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
    write_image_source(api, checkout / "ops/Dockerfile.api", commit, "api")
    shutil.copyfile(checkout / "infra/documents/freshclam.conf", api / "freshclam.conf")
    scanner = (checkout / "infra/documents/clamd.conf").read_text()
    scanner = scanner.replace(
        "/run/sallimbook/clamd.sock", "/run/scanner/clamd.sock"
    ).replace("/run/sallimbook/spool", "/tmp")
    (api / "clamd.conf").write_text(scanner)
    # The scheduler uses umask 077. These are public build inputs copied into an
    # image that runs as UID 10001, not operator secrets.
    for name in ("requirements.txt", "alembic.ini", "freshclam.conf", "clamd.conf"):
        (api / name).chmod(0o644)
    return lock_hash


def stage_snapshot(output, commit, checkout):
    api, web = output / "api", output / "web"
    lock_hash = stage_api_snapshot(api, commit, checkout)
    web.mkdir()
    subprocess.run(
        ["pnpm", "install", "--frozen-lockfile"],
        cwd=checkout,
        env=build_environment(),
        check=True,
    )
    subprocess.run(["pnpm", "build"], cwd=checkout, env=build_environment(), check=True)
    shutil.copytree(checkout / "apps/client/dist", web / "dist")
    write_image_source(web, checkout / "ops/Dockerfile.web", commit, "web")
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
