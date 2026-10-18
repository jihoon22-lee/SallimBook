"""Read-only runtime checks before an operator considers starting the rendered deployment."""

import argparse
import json
import stat
import subprocess
from pathlib import Path

from ops.backup import OperationError, digest, private_file
from ops.build_context import REVISION_LABEL, ROLE_LABEL
from ops.database import APPLICATION_ROLE
from ops.deploy import POSTGRES, render, validate
from ops.release import inspect_apk


def verify_download_apk(directory, config, sdk):
    apk = directory / "downloads/SallimBook.apk"
    if apk.is_symlink() or any(parent.is_symlink() for parent in apk.parents):
        raise OperationError("Download APK symlink paths are forbidden")
    if not apk.exists():
        return {"status": "not-present"}
    if sdk is None:
        raise OperationError("--sdk is required to verify a present download APK")
    before = apk.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) not in {0o444, 0o644}
    ):
        raise OperationError("Download APK must be a readable non-shared regular file")
    expected = digest(apk)
    # A neighbouring release receipt is not proof of the currently served bytes.
    # Always run the real SDK signature, identity, version and security checks.
    verified = inspect_apk(apk, config, sdk, signed=True)
    after = apk.lstat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (
        any(getattr(before, field) != getattr(after, field) for field in fields)
        or verified.get("signed") is not True
        or verified.get("sha256") != expected
        or digest(apk) != expected
    ):
        raise OperationError("Download APK changed during verification")
    return {"status": "verified", **verified}


def verify_image_details(details, *, revision=None, role=None):
    if (
        len(details) != 1
        or details[0].get("Architecture") != "amd64"
        or details[0].get("Os") != "linux"
    ):
        raise OperationError("Deployment image platform mismatch")
    if revision is not None:
        labels = details[0].get("Config", {}).get("Labels") or {}
        if labels.get(REVISION_LABEL) != revision or labels.get(ROLE_LABEL) != role:
            raise OperationError("Application image source revision or role mismatch")


def validate_database_settings(values, password):
    # Reject non-database settings before parsing or importing database tooling.
    # Security/origin/storage values come only from the validated renderer.
    if set(values) != {"SALLIMBOOK_DATABASE_URL"}:
        raise OperationError("Unexpected runtime environment setting")
    from sqlalchemy.engine import make_url

    raw = values.get("SALLIMBOOK_DATABASE_URL", "")
    try:
        url = make_url(raw)
        valid = (
            url.drivername == "postgresql+psycopg"
            and url.host == "db"
            and url.port == 5432
            and url.database == "sallimbook_prod"
            and url.username == APPLICATION_ROLE
            and url.password == password
            and not url.query
            and len(password) >= 24
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise OperationError("Dedicated database URL/password mismatch")


def check(config_directory, verify_database=False, sdk=None):
    directory = Path(config_directory).absolute()
    config = validate(json.loads((directory / "deployment.json").read_text()))
    generated = render(config)
    for name, expected in generated.items():
        raw = (directory / name).read_text()
        actual = raw if isinstance(expected, str) else json.loads(raw)
        if actual != expected:
            raise OperationError("Rendered deployment configuration drift")
    download_apk = verify_download_apk(directory, config, sdk)
    runtime = Path(config["runtime_directory"])
    environment_file = private_file(runtime / "api.env")
    password_file = private_file(runtime / "app-db-password")
    administrator_file = private_file(runtime / "db-admin-password")
    password = password_file.read_text().removesuffix("\n")
    if "\n" in password or "\r" in password:
        raise OperationError("DB password file must contain one line")
    administrator_password = administrator_file.read_text().removesuffix("\n")
    if administrator_password == password or len(administrator_password) < 24:
        raise OperationError("Separate strong admin/runtime DB passwords required")
    values = {}
    for line in environment_file.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key in values:
            raise OperationError("Invalid raw runtime environment file")
        values[key] = value
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
    inspected_images = {}
    for image in images:
        result = subprocess.run(
            ["docker", "image", "inspect", image], check=False, capture_output=True, timeout=15
        )
        if result.returncode:
            raise OperationError("A verified deployment image is missing locally")
        details = json.loads(result.stdout)
        verify_image_details(details)
        inspected_images[image] = details
    for role in ("api", "web"):
        verify_image_details(
            inspected_images[config[role + "_image"]],
            revision=config["source_commit"], role=role,
        )
    if verify_database:
        network = config["project"] + "_database"
        result = subprocess.run(
            ["docker", "network", "inspect", network], check=False, capture_output=True, timeout=15
        )
        if result.returncode:
            raise OperationError("Dedicated database network is not ready")
        inspected = json.loads(result.stdout)[0]
        if (
            not inspected["Internal"]
            or inspected["Labels"].get("com.docker.compose.project")
            != config["project"]
        ):
            raise OperationError("Unexpected database network identity")
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                network,
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--memory",
                "128m",
                "--memory-swap",
                "128m",
                "--env-file",
                str(environment_file),
                "--entrypoint",
                "python",
                config["api_image"],
                "-m",
                "ops.database",
                "verify-runtime",
            ],
            check=False,
            capture_output=True,
            timeout=30,
        )
        if (
            result.returncode
            or json.loads(result.stdout).get("status") != "runtime-role-verified"
        ):
            raise OperationError("Runtime database privilege verification failed")
    return {
        "status": "configuration-checked",
        "source_commit": config["source_commit"],
        "images": len(images),
        "postgres_image": POSTGRES,
        "runtime_uid": 10001,
        "download_apk": download_apk,
        "database_role_check": "passed"
        if verify_database
        else "required-before-api-start",
        "operator_deployment_acceptance": "pending",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path)
    parser.add_argument("--verify-database", action="store_true")
    parser.add_argument(
        "--sdk", type=Path, help="Required whenever downloads/SallimBook.apk exists"
    )
    args = parser.parse_args()
    try:
        report = check(args.configuration, args.verify_database, args.sdk)
    except Exception:  # noqa: BLE001 — redact subprocess/config errors at the CLI boundary.
        raise SystemExit(
            "Preflight failed. No service or existing host configuration was changed."
        ) from None
    print(json.dumps(report, sort_keys=True))
