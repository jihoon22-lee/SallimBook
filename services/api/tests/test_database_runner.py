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

    def forbidden(*args, **kwargs):
        pytest.fail("A concurrent runner attempted to operate Docker")

    monkeypatch.setattr(runner.subprocess, "run", forbidden)
    monkeypatch.setattr(runner.subprocess, "check_output", forbidden)
    with runner.test_service_lock():
        with pytest.raises(SystemExit, match="Another SallimBook database test"):
            runner.main()
