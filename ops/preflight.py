"""Read-only runtime checks before an operator considers starting the rendered deployment."""

import argparse
import json
import stat
import subprocess
from pathlib import Path

from ops.backup import OperationError, private_file
from ops.deploy import POSTGRES, render, validate


def validate_database_settings(values, password):
    from sqlalchemy.engine import make_url

    raw = values.get("SALLIMBOOK_DATABASE_URL", "")
    try:
        url = make_url(raw)
        valid = (
            url.drivername == "postgresql+psycopg"
            and url.host == "db"
            and url.port == 5432
            and url.database == "sallimbook_prod"
            and url.username == "sallimbook"
            and url.password == password
            and not url.query
            and len(password) >= 24
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise OperationError("Dedicated database URL/password mismatch")
    # Other security/origin/storage values come from the validated renderer and
    # cannot drift in a forgotten env file. Quota overrides remain explicit JSON
    # manifest work rather than silently weakening production admission here.
    if set(values) != {"SALLIMBOOK_DATABASE_URL"}:
        raise OperationError("Unexpected runtime environment setting")


def check(config_directory):
    from dotenv import dotenv_values

    directory = Path(config_directory).absolute()
    config = validate(json.loads((directory / "deployment.json").read_text()))
    generated = render(config)
    for name, expected in generated.items():
        raw = (directory / name).read_text()
        actual = raw if isinstance(expected, str) else json.loads(raw)
        if actual != expected:
            raise OperationError("Rendered deployment configuration drift")
    runtime = Path(config["runtime_directory"])
    environment_file = private_file(runtime / "api.env")
    password_file = private_file(runtime / "db-password")
    password = password_file.read_text()
    if password.endswith("\n"):
        password = password[:-1]
    if "\n" in password or "\r" in password:
        raise OperationError("DB password file must contain one line")
    values = dotenv_values(environment_file, interpolate=False)
    validate_database_settings(values, password)
    for name, mode, is_directory in (
        ("field-keyring.json", {0o400, 0o600}, False),
        ("documents", {0o700}, True),
    ):
        path = runtime / name
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise OperationError("Runtime symlink paths are forbidden")
        info = path.stat()
        if (
            info.st_uid != 10001
            or stat.S_IMODE(info.st_mode) not in mode
            or (
                not stat.S_ISDIR(info.st_mode)
                if is_directory
                else not stat.S_ISREG(info.st_mode)
            )
        ):
            raise OperationError(
                "Runtime keyring/documents must be owned by API UID 10001"
            )
    # Image inspection is read-only. No pull/start/register command is performed.
    images = {
        service["image"] for service in generated["compose.json"]["services"].values()
    }
    for image in images:
        result = subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True, timeout=15
        )
        if result.returncode:
            raise OperationError("A verified deployment image is missing locally")
        details = json.loads(result.stdout)
        if (
            len(details) != 1
            or details[0]["Architecture"] != "amd64"
            or details[0]["Os"] != "linux"
        ):
            raise OperationError("Deployment image platform mismatch")
    return {
        "status": "configuration-checked",
        "source_commit": config["source_commit"],
        "images": len(images),
        "postgres_image": POSTGRES,
        "runtime_uid": 10001,
        "operator_deployment_acceptance": "pending",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path)
    args = parser.parse_args()
    try:
        report = check(args.configuration)
    except Exception:
        raise SystemExit(
            "Preflight failed. No service or existing host configuration was changed."
        ) from None
    print(json.dumps(report, sort_keys=True))
