"""Render, validate, install and activate only dedicated user systemd units."""

import argparse
import json
import os
import sys
from pathlib import Path

from ops.automation import (
    LIMITS,
    ROOT,
    AutomationError,
    Runner,
    atomic_json,
    canonical_path,
    load_config,
    now_text,
    read_json,
    verify_operator_source,
)
from ops.backup import digest, private_directory, private_file, publish_json

# The health service's pre-step. Bump when the rendered drop-in changes so a schedule
# rendered from another template version never validates as this one.
DISK_CHECK_TEMPLATE_VERSION = 1

CALENDARS = {
    "backup": "*-*-* 03:15:00 Asia/Seoul",
    "health": "*-*-* *:15:00 Asia/Seoul",
    "restore-check": "*-*-01 04:30:00 Asia/Seoul",
    "cvd-refresh": "*-*-* 05:00:00 Asia/Seoul",
}


def units(config, configuration, sha256):
    """Literal argv; paths are restricted before any systemd interpolation."""
    configuration = canonical_path(str(configuration))
    source = canonical_path(str(ROOT))
    project = config["project"]
    result = {}
    for task in ("startup", *CALENDARS):
        name = project + "-" + task
        dependency = (
            ""
            if task == "startup"
            else (
                "Requires=" + project + "-startup.service\nAfter=" + project + "-startup.service\n"
            )
        )
        result[name + ".service"] = (
            "[Unit]\nDescription=SallimBook "
            + task
            + " ("
            + project
            + ")\n"
            + dependency
            + "\n[Service]\nType=oneshot\nWorkingDirectory="
            + str(source)
            + "\nUMask=0077\nEnvironment=PYTHONDONTWRITEBYTECODE=1\n"
            + "ExecStart="
            + config["python_executable"]
            + " -m ops.automation run "
            + str(configuration)
            + " --sha256 "
            + sha256
            + " --task "
            + task
            + "\nTimeoutStartSec="
            # ExecStartPre shares the service's start timeout.
            + str(LIMITS[task] + (LIMITS["disk-check"] if task == "health" else 0))
            + "\nTimeoutStopSec=15\n"
            + "KillMode=control-group\nStandardOutput=journal\nStandardError=journal\n"
            + (
                "Restart=on-failure\nRestartPreventExitStatus=1\nRestartSec=60\n"
                if task != "startup"
                else ""
            )
            + (
                "RemainAfterExit=yes\n\n[Install]\nWantedBy=default.target\n"
                if task == "startup"
                else ""
            )
        )
        if task in CALENDARS:
            result[name + ".timer"] = (
                "[Unit]\nDescription=SallimBook "
                + task
                + " schedule ("
                + project
                + ")\n"
                + "\n[Timer]\nOnCalendar="
                + CALENDARS[task]
                + "\nPersistent=true\nRandomizedDelaySec=120\nAccuracySec=30s\nUnit="
                + name
                + ".service\n\n[Install]\nWantedBy=timers.target\n"
            )
    return result


def dropins(config, configuration, sha256):
    """Drop-ins keyed by path relative to the unit directory; never named as units.

    The disk check is a pre-step of the hourly health service, so it also fails the
    service when the health task itself cannot start.
    """
    configuration = canonical_path(str(configuration))
    return {
        config["project"]
        + "-health.service.d/10-disk-check.conf": (
            "# SallimBook disk-check drop-in, template v"
            + str(DISK_CHECK_TEMPLATE_VERSION)
            + "; rendered by ops.schedule, do not edit\n[Service]\nExecStartPre="
            + config["python_executable"]
            + " -m ops.automation run "
            + str(configuration)
            + " --sha256 "
            + sha256
            + " --task disk-check\n"
        )
    }


def render(configuration, sha256, output):
    configuration = private_file(configuration)
    config = load_config(configuration, sha256)
    canonical_path(str(output))
    output = Path(output)
    output.mkdir(mode=0o700, exist_ok=False)
    content = units(config, configuration, sha256)
    extras = dropins(config, configuration, sha256)
    for name, value in {**content, **extras}.items():
        path = output / name
        path.parent.mkdir(mode=0o700, exist_ok=True)
        with path.open("x") as stream:
            stream.write(value)
        path.chmod(0o600)
    publish_json(
        output / "schedule.json",
        {
            "format": 1,
            "project": config["project"],
            "operator_source_commit": config["operator_source_commit"],
            "configuration": str(configuration),
            "configuration_sha256": sha256,
            "files": {name: digest(output / name) for name in (*content, *extras)},
        },
    )
    return {"status": "schedule-rendered", "units": len(content), "dropins": len(extras)}


def validate(directory, *, runner=None):
    directory = private_directory(directory)
    record = read_json(directory / "schedule.json")
    if (
        set(record)
        != {
            "format",
            "project",
            "operator_source_commit",
            "configuration",
            "configuration_sha256",
            "files",
        }
        or record["format"] != 1
    ):
        raise AutomationError("SCHEDULE_MANIFEST")
    config = load_config(record["configuration"], record["configuration_sha256"])
    if (config["project"], config["operator_source_commit"]) != (
        record["project"],
        record["operator_source_commit"],
    ):
        raise AutomationError("SCHEDULE_IDENTITY")
    expected = units(config, record["configuration"], record["configuration_sha256"])
    extras = dropins(config, record["configuration"], record["configuration_sha256"])
    folders = {Path(name).parent.name for name in extras}
    allowed = set(expected) | folders | {
        "schedule.json",
        "installation.json",
        "activation.json",
        "activation-failed.json",
    }
    if (
        set(record["files"]) != {*expected, *extras}
        or set(path.name for path in directory.iterdir()) - allowed
    ):
        raise AutomationError("SCHEDULE_FILES")
    for folder in folders:
        listing = {
            folder + "/" + path.name for path in private_directory(directory / folder).iterdir()
        }
        if listing != {name for name in extras if name.startswith(folder + "/")}:
            raise AutomationError("SCHEDULE_FILES")
    for name, value in {**expected, **extras}.items():
        path = private_file(directory / name)
        if path.read_text() != value or digest(path) != record["files"][name]:
            raise AutomationError("SCHEDULE_CHANGED")
    runner = runner or Runner(config)
    verify_operator_source(config, runner)
    runner.run(
        ["/usr/bin/systemd-analyze", "--user", "verify", *[directory / name for name in expected]],
        timeout=30,
    )
    return config, record, expected, runner


def unit_directory():
    # Do not follow an environment-selected system or another user's directory.
    import pwd

    return Path(pwd.getpwuid(os.geteuid()).pw_dir) / ".config/systemd/user"


def check_collisions(names, runner):
    # Include user, vendor and generator search paths reported by systemd itself.
    paths = runner.run(
        ["/usr/bin/systemd-analyze", "--user", "unit-paths"], timeout=15
    ).splitlines()
    for raw in paths:
        root = Path(raw)
        if not root.is_absolute():
            raise AutomationError("UNIT_SEARCH_PATH")
        for name in names:
            for path in (root / name, root / (name + ".d")):
                if path.exists() or path.is_symlink():
                    raise AutomationError("UNIT_ALREADY_EXISTS")
            if any(root.glob("*.wants/" + name)) or any(root.glob("*.requires/" + name)):
                raise AutomationError("UNIT_ALREADY_ENABLED")


def install(directory, *, runner=None):
    directory = private_directory(directory)
    config, record, expected, runner = validate(directory, runner=runner)
    receipt = directory / "installation.json"
    if receipt.exists() or receipt.is_symlink():
        raise AutomationError("SCHEDULE_ALREADY_INSTALLED")
    destination = unit_directory()
    if any(path.is_symlink() for path in (destination, *destination.parents)):
        raise AutomationError("UNIT_DIRECTORY_SYMLINK")
    # A unit's `.d` directory counts as a collision, so no drop-in directory exists yet.
    check_collisions(expected, runner)
    extras = dropins(config, record["configuration"], record["configuration_sha256"])
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    created, folders, written = [], [], {}
    try:
        for name, value in {**expected, **extras}.items():
            path = destination / name
            if name in extras and not path.parent.exists():
                path.parent.mkdir(mode=0o700)
                folders.append(path.parent)
            with path.open("x") as stream:
                stream.write(value)
            path.chmod(0o600)
            created.append(path)
            written[path] = value
        runner.run(["/usr/bin/systemctl", "--user", "daemon-reload"], timeout=30)
        publish_json(
            receipt,
            {
                "format": 1,
                "status": "installed-inactive",
                "project": config["project"],
                "schedule_sha256": digest(directory / "schedule.json"),
                "directory": str(destination),
                "files": record["files"],
            },
        )
    except Exception:
        # Only the newly created byte-identical files belong to this attempt.
        for path in created:
            if not path.is_symlink() and path.read_text() == written[path]:
                path.unlink()
        for folder in folders:
            if not any(folder.iterdir()):
                folder.rmdir()
        raise
    return {"status": "installed-inactive", "units": len(expected), "dropins": len(extras)}


def activate(directory, *, runner=None):
    directory = private_directory(directory)
    config, record, expected, runner = validate(directory, runner=runner)
    receipt = read_json(directory / "installation.json")
    destination = unit_directory()
    if receipt != {
        "format": 1,
        "status": "installed-inactive",
        "project": config["project"],
        "schedule_sha256": digest(directory / "schedule.json"),
        "directory": str(destination),
        "files": record["files"],
    }:
        raise AutomationError("INSTALLATION_CHANGED")
    if (directory / "activation.json").exists():
        raise AutomationError("SCHEDULE_ALREADY_ACTIVATED")
    extras = dropins(config, record["configuration"], record["configuration_sha256"])
    for name, value in expected.items():
        path = private_file(destination / name)
        if path.read_text() != value:
            raise AutomationError("INSTALLED_UNIT_CHANGED")
        # Only this tool's own rendered drop-ins, byte-identical, may sit next to a unit.
        wanted = {
            destination / drop: text
            for drop, text in extras.items()
            if drop.startswith(name + ".d/")
        }
        folder = destination / (name + ".d")
        if folder.is_symlink() or (folder.exists() and not wanted):
            raise AutomationError("INSTALLED_UNIT_CHANGED")
        if wanted:
            private_directory(folder)
            if set(folder.iterdir()) != set(wanted) or any(
                private_file(drop).read_text() != text for drop, text in wanted.items()
            ):
                raise AutomationError("INSTALLED_UNIT_CHANGED")
        # Catch a vendor/runtime drop-in added between install and activation, and a
        # rendered drop-in systemd has not loaded.
        loaded = runner.run(
            ["/usr/bin/systemctl", "--user", "show", "--property=DropInPaths", "--value", name],
            timeout=15,
        ).split()
        if set(loaded) != {str(drop) for drop in wanted} or len(loaded) != len(wanted):
            raise AutomationError("INSTALLED_UNIT_OVERRIDE")
    active = [config["project"] + "-startup.service"] + [
        config["project"] + "-" + task + ".timer" for task in CALENDARS
    ]
    enabled = []
    try:
        for name in active:
            enabled.append(name)
            runner.run(
                ["/usr/bin/systemctl", "--user", "enable", "--now", name],
                timeout=LIMITS["startup"] + 30,
            )
        publish_json(
            directory / "activation.json",
            {
                "format": 1,
                "status": "activated",
                "project": config["project"],
                "units": active,
                "installation_sha256": digest(directory / "installation.json"),
            },
        )
    except Exception:
        failed, completed = [], []
        for name in reversed(enabled):
            try:
                runner.run(["/usr/bin/systemctl", "--user", "disable", "--now", name], timeout=30)
                completed.append(name)
            except Exception:
                failed.append(name)
        atomic_json(
            directory / "activation-failed.json",
            {
                "format": 1,
                "status": "activation-failed",
                "project": config["project"],
                "recorded_at": now_text(),
                "attempted_units": enabled,
                "rollback_completed": completed,
                "rollback_failed": failed,
                "installation_sha256": digest(directory / "installation.json"),
            },
        )
        if failed:
            raise AutomationError("ACTIVATION_ROLLBACK_INCOMPLETE") from None
        raise
    return {"status": "activated", "units": active}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    rendering = commands.add_parser("render")
    rendering.add_argument("configuration", type=Path)
    rendering.add_argument("--sha256", required=True)
    rendering.add_argument("--output", type=Path, required=True)
    for name in ("validate", "install", "activate"):
        commands.add_parser(name).add_argument("directory", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "render":
            result = render(args.configuration, args.sha256, args.output)
        elif args.command == "validate":
            validate(args.directory)
            result = {"status": "schedule-validated"}
        else:
            result = globals()[args.command](args.directory)
    except Exception as failure:
        code = failure.code if isinstance(failure, AutomationError) else "SCHEDULE_FAILED"
        print(json.dumps({"status": "failed", "code": code}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
