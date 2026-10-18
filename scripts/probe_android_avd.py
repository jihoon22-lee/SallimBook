"""Boot one disposable AVD with a deadline; never reuse a device or ADB server.

Requires the selected SDK's emulator, platform-tools and system image. Results
are environment evidence, not APK acceptance. No application logs are collected.
"""

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path


def run(command, *, env, timeout=30):
    return subprocess.run(
        [str(part) for part in command], env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
        check=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--boot-timeout", type=int, default=600)
    parser.add_argument("--port", type=int, default=5580)
    parser.add_argument("--adb-port", type=int, default=5049)
    parser.add_argument("--software", action="store_true")
    parser.add_argument("--command", nargs=argparse.REMAINDER,
                        help="Run after boot with ANDROID_SERIAL/ADB_SERVER_SOCKET set")
    args = parser.parse_args()
    if not 1 <= args.boot_timeout <= 900:
        parser.error("boot timeout must be 1..900 seconds")
    if args.port % 2 or not 5554 <= args.port <= 5682:
        parser.error("emulator port must be even and in 5554..5682")
    if args.adb_port in (args.port, args.port + 1):
        parser.error("ADB server and emulator ports must differ")
    # Refuse pre-existing output and listeners; never stop someone else's server.
    args.output.mkdir(parents=True, exist_ok=False)
    for port in (args.port, args.port + 1, args.adb_port):
        try:
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(("127.0.0.1", port))
        except OSError:
            blocked = {"status": "BLOCKED_ENV", "reason": "Requested port unavailable",
                       "port": port, "boot_completed": False, "command_status": "NOT_RUN"}
            (args.output / "result.json").write_text(json.dumps(blocked, indent=2) + "\n")
            print(json.dumps(blocked), flush=True)
            raise SystemExit(2) from None
    sdk = args.sdk_root.resolve()
    emulator = sdk / "emulator/emulator"
    adb = sdk / "platform-tools/adb"
    managers = sorted((sdk / "cmdline-tools").glob("*/bin/avdmanager"))
    if not managers or not emulator.is_file() or not adb.is_file():
        parser.error("Install command-line tools, emulator and platform-tools first")
    result = {"image": args.image, "boot_timeout_seconds": args.boot_timeout,
              "software": args.software, "status": "BLOCKED_ENV",
              "boot_completed": False, "command_status": "NOT_RUN"}
    with tempfile.TemporaryDirectory(prefix="sallimbook-avd-") as temporary:
        env = {**os.environ, "ANDROID_HOME": str(sdk), "ANDROID_SDK_ROOT": str(sdk),
               "ANDROID_AVD_HOME": temporary,
               "ADB_SERVER_SOCKET": f"tcp:localhost:{args.adb_port}",
               "ANDROID_ADB_SERVER_PORT": str(args.adb_port),
               "ANDROID_SERIAL": f"emulator-{args.port}",
               "SALLIMBOOK_CLOUD_RESULT_DIRECTORY": str(args.output.resolve() / "tests")}
        process = None
        server_started = False
        try:
            acceleration = run([emulator, "-accel-check"], env=env)
            result["acceleration"] = {"exit_code": acceleration.returncode,
                                      "output": acceleration.stdout.strip()}
            result["emulator_version"] = run([emulator, "-version"], env=env).stdout.strip()
            create = subprocess.run(
                [str(managers[-1]), "create", "avd", "--name", "sallimbook-probe",
                 "--package", args.image, "--path", temporary + "/device.avd"],
                input="no\n", text=True, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=60, check=False,
            )
            if create.returncode:
                result["reason"] = "AVD creation failed"
                (args.output / "avd-create.log").write_text(create.stdout)
                raise SystemExit(2)
            # Google's phone profile may request 12 GiB of userdata. The probe
            # needs only a disposable app install, not a full personal device.
            config = Path(temporary) / "device.avd/config.ini"
            if config.exists():
                lines = [line for line in config.read_text().splitlines()
                         if not line.startswith("disk.dataPartition.size=")]
                config.write_text("\n".join([*lines, "disk.dataPartition.size=2G"]) + "\n")
            server = run([adb, "-P", args.adb_port, "start-server"], env=env)
            if server.returncode:
                result["reason"] = "Dedicated ADB server failed"
                raise SystemExit(2)
            server_started = True
            command = [str(emulator), "-avd", "sallimbook-probe", "-port", str(args.port),
                       "-no-window", "-no-audio", "-no-snapshot", "-no-boot-anim",
                       "-gpu", "swiftshader_indirect", "-memory", "2048", "-cores", "2",
                       "-partition-size", "2048"]
            if args.software:
                command += ["-accel", "off"]
            started = time.monotonic()
            with (args.output / "emulator.log").open("w") as log:
                process = subprocess.Popen(command, env=env, stdout=log, stderr=log)
                while time.monotonic() - started < args.boot_timeout:
                    if process.poll() is not None:
                        result["reason"] = "Emulator exited before boot"
                        result["emulator_exit_code"] = process.returncode
                        break
                    try:
                        boot = run([adb, "-P", args.adb_port, "-s", env["ANDROID_SERIAL"],
                                    "shell", "getprop", "sys.boot_completed"], env=env, timeout=5)
                        if boot.returncode == 0 and boot.stdout.strip() == "1":
                            result["boot_completed"] = True
                            result["status"] = "PASS"
                            break
                    except subprocess.TimeoutExpired:
                        pass
                    time.sleep(2)
                result["boot_seconds"] = round(time.monotonic() - started, 2)
                if not result["boot_completed"]:
                    result.setdefault("reason", "Boot deadline exceeded")
                else:
                    for name, query in {
                        "api": ["getprop", "ro.build.version.sdk"],
                        "abi": ["getprop", "ro.product.cpu.abi"],
                        "webview": ["dumpsys", "webviewupdate"],
                    }.items():
                        result[name] = run([adb, "-P", args.adb_port, "-s",
                                           env["ANDROID_SERIAL"], "shell", *query], env=env).stdout.strip()
                    if args.command:
                        completed = subprocess.run(args.command, env=env, check=False)
                        result["command_status"] = "PASS" if completed.returncode == 0 else "FAIL"
                        result["command_exit_code"] = completed.returncode
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            result["emulator_stopped"] = process is None or process.poll() is not None
            if server_started:
                result["adb_stop_exit_code"] = run(
                    [adb, "-P", args.adb_port, "kill-server"], env=env
                ).returncode
            (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2), flush=True)
    if result["status"] != "PASS" or result["command_status"] == "FAIL":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
