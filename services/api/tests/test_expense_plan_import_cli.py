"""Operator input boundary never prints sensitive source material."""

import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[3] / "ops/import_expense_plans.py"
spec = importlib.util.spec_from_file_location("plan_import_cli", MODULE)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def test_cli_rejects_open_permissions_symlinks_and_private_validation_output(tmp_path, capsys):
    path = tmp_path / "manifest.json"
    path.write_text('{"private-example":"do-not-echo-synthetic-value"}')
    path.chmod(0o644)
    with pytest.raises(ValueError):
        cli.read_private(str(path))
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        cli.read_private(str(link))
    assert cli.main(["--file", str(path)]) == 2
    output = capsys.readouterr()
    assert "do-not-echo-synthetic-value" not in output.err + output.out
    assert "IMPORT_REJECTED" in output.err
