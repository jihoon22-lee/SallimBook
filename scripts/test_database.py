"""Run database checks using only SallimBook's ephemeral test service."""

import argparse
import fcntl
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(ROOT / ".env"),
    "-f",
    str(ROOT / "infra/compose.dev.yaml"),
    "-p",
    "sallimbook-dev",
]


def validate_test_url(raw: str) -> None:
    try:
        url = make_url(raw)
        valid = (
            url.drivername == "postgresql+psycopg"
            and url.host == "127.0.0.1"
            and url.port == 18745
            and url.database == "sallimbook_test"
            and url.username == "sallimbook"
            and bool(url.password)
            and not url.query
        )
    except (ArgumentError, ValueError):
        valid = False
    if not valid:
        raise SystemExit("Test URL must target the isolated SallimBook test service.")


@contextmanager
def test_service_lock():
    directory = ROOT / ".cache"
    directory.mkdir(mode=0o700, exist_ok=True)
    with (directory / "database-test.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(
                "Another SallimBook database test is running; nothing was changed."
            ) from None
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def run_checks() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not (ROOT / ".env").is_file():
        raise SystemExit("Run python3 scripts/setup_dev.py first.")
    values = {
        key: value
        for key, value in dotenv_values(ROOT / ".env").items()
        if value is not None
    }
    environment = {**os.environ, **values}
    url = values.get("SALLIMBOOK_TEST_DATABASE_URL", "")
    validate_test_url(url)
    running = subprocess.check_output(
        COMPOSE + ["ps", "--status", "running", "-q", "db-test"],
        cwd=ROOT,
        env=environment,
        text=True,
    ).strip()
    if running:
        raise SystemExit("SallimBook test DB is already running; it was not changed.")
    environment["SALLIMBOOK_DATABASE_URL"] = url
    alembic = [
        "uv",
        "run",
        "--project",
        "services/api",
        "alembic",
        "-c",
        "services/api/alembic.ini",
    ]
    try:
        subprocess.run(
            COMPOSE + ["up", "-d", "--wait", "db-test"],
            cwd=ROOT,
            env=environment,
            check=True,
        )
        for command in (
            alembic + ["upgrade", "head"],
            [
                "uv",
                "run",
                "--project",
                "services/api",
                "pytest",
                *(args.pytest_args or ["services/api/tests"]),
            ],
            alembic + ["check"],
            alembic + ["downgrade", "base"],
            alembic + ["upgrade", "head"],
        ):
            subprocess.run(command, cwd=ROOT, env=environment, check=True)
    finally:
        # Never stop the development DB or any other project's services; never remove a volume.
        subprocess.run(
            COMPOSE + ["stop", "db-test"], cwd=ROOT, env=environment, check=True
        )


def main() -> None:
    with test_service_lock():
        run_checks()


if __name__ == "__main__":
    main()
