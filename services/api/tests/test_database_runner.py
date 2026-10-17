"""The test runner must never stop a concurrently owned test service."""

import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from sallimbook.core.database import REQUIRED_SCHEMA_REVISION


def test_readiness_revision_matches_single_migration_head():
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    assert ScriptDirectory.from_config(config).get_heads() == [REQUIRED_SCHEMA_REVISION]


def test_concurrent_database_runner_refuses_before_any_docker_call(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[3] / "scripts/test_database.py"
    spec = importlib.util.spec_from_file_location("database_runner", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "LOCK_DIRECTORY", tmp_path / "host-lock")

    def forbidden(*args, **kwargs):
        pytest.fail("A concurrent runner attempted to operate Docker")

    monkeypatch.setattr(runner.subprocess, "run", forbidden)
    monkeypatch.setattr(runner.subprocess, "check_output", forbidden)
    with runner.test_service_lock():
        # A second checkout still controls the same host Compose resources.
        monkeypatch.setattr(runner, "ROOT", tmp_path / "another-worktree")
        with pytest.raises(SystemExit, match="Another SallimBook database test"):
            runner.main()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://user:pass@production/real_db?application_name=@127.0.0.1:18745/sallimbook_test",
        "postgresql+psycopg://sallimbook:synthetic@127.0.0.1:18745/sallimbook_test?host=production",
        "postgresql+psycopg://sallimbook:synthetic@127.0.0.1:18744/sallimbook_test",
        "postgresql+psycopg://sallimbook:synthetic@127.0.0.1:18745/sallimbook_dev",
        "postgresql://sallimbook:synthetic@127.0.0.1:18745/sallimbook_test",
        "postgresql+psycopg://sallimbook:synthetic@localhost:18745/sallimbook_test",
        "malformed",
    ],
)
def test_runner_rejects_redirected_database_before_any_command(url, tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[3] / "scripts/test_database.py"
    spec = importlib.util.spec_from_file_location("database_runner_validation", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "LOCK_DIRECTORY", tmp_path / "host-lock")
    (tmp_path / ".env").write_text(f"SALLIMBOOK_TEST_DATABASE_URL={url}\n")
    monkeypatch.setattr("sys.argv", ["test_database.py"])

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid test URL reached a subprocess")

    monkeypatch.setattr(runner.subprocess, "run", forbidden)
    monkeypatch.setattr(runner.subprocess, "check_output", forbidden)
    with pytest.raises(SystemExit, match="isolated SallimBook test service"):
        runner.main()


def test_runner_accepts_only_explicit_isolated_database():
    path = Path(__file__).resolve().parents[3] / "scripts/test_database.py"
    spec = importlib.util.spec_from_file_location("database_runner_valid", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.validate_test_url(
        "postgresql+psycopg://sallimbook:synthetic@127.0.0.1:18745/sallimbook_test"
    )
