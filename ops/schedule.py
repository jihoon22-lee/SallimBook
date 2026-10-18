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
    canonical_path,
    load_config,
    read_json,
    verify_operator_source,
)
from ops.backup import digest, private_directory, private_file, publish_json

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
            + str(LIMITS[task])
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


def render(configuration, sha256, output):
    configuration = private_file(configuration)
    config = load_config(configuration, sha256)
    canonical_path(str(output))
    output = Path(output)
    output.mkdir(mode=0o700, exist_ok=False)
    content = units(config, configuration, sha256)
    for name, value in content.items():
        path = output / name
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
            "files": {name: digest(output / name) for name in content},
        },
    )
    return {"status": "schedule-rendered", "units": len(content)}


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
    allowed = set(expected) | {"schedule.json", "installation.json", "activation.json"}
    if (
        set(record["files"]) != set(expected)
        or set(path.name for path in directory.iterdir()) - allowed
    ):
        raise AutomationError("SCHEDULE_FILES")
    for name, value in expected.items():
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
    check_collisions(expected, runner)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    created = []
    try:
        for name, value in expected.items():
            path = destination / name
            with path.open("x") as stream:
                stream.write(value)
            path.chmod(0o600)
            created.append(path)
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
            if not path.is_symlink() and path.read_text() == expected[path.name]:
                path.unlink()
        raise
    return {"status": "installed-inactive", "units": len(created)}


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
    for name, value in expected.items():
        path = private_file(destination / name)
        if path.read_text() != value or (destination / (name + ".d")).exists():
            raise AutomationError("INSTALLED_UNIT_CHANGED")
        # Catch a vendor/runtime drop-in added between install and activation.
        dropins = runner.run(
            ["/usr/bin/systemctl", "--user", "show", "--property=DropInPaths", "--value", name],
            timeout=15,
        ).strip()
        if dropins:
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
        for name in reversed(enabled):
            runner.run(["/usr/bin/systemctl", "--user", "disable", "--now", name], timeout=30)
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
