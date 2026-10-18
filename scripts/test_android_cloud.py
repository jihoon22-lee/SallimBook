"""Disposable real HTTPS/PostgreSQL fixture for native Android onboarding.

--host-only checks fixture readiness, never claims Android acceptance.
Otherwise run from probe_android_avd.py --command so only its owned AVD is used.
No passwords, session bodies, screenshots, logcat or UI hierarchy are collected.
"""

import argparse
import hashlib
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import uvicorn
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sallimbook.config import Settings
from sallimbook.core.database import make_engine
from sallimbook.main import create_app
from sqlalchemy import text
from test_database import COMPOSE, ROOT, test_service_lock, validate_test_url

ANDROID = ROOT / "apps/client/android"
IDENTITY = b"synthetic-android@example.invalid"


def save_instrumentation(label, expected):
    """Keep testcase statuses, never Gradle's device logs or view diagnostics."""
    destination = Path(os.environ["SALLIMBOOK_CLOUD_RESULT_DIRECTORY"])
    destination.mkdir(parents=True, exist_ok=True)
    suite = ET.Element("testsuite", name=label)
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for file in sorted((ANDROID / "app/build/outputs/androidTest-results/connected").rglob("TEST-*.xml")):
        for original in ET.parse(file).getroot().iter("testcase"):
            case = ET.SubElement(suite, "testcase", {
                key: value for key, value in original.attrib.items() if key in {"name", "classname", "time"}
            })
            counts["tests"] += 1
            for tag, counter in (("failure", "failures"), ("error", "errors"), ("skipped", "skipped")):
                if original.find(tag) is not None:
                    counts[counter] += 1
                    reason = "Device runner reported " + tag + "; raw diagnostics withheld"
                    if tag == "skipped" and case.get("name", "").startswith("ownerFlagCannot"):
                        reason = "Requires API 33+, enrolled strong biometric and clean synthetic Keystore namespace"
                    ET.SubElement(case, tag, message=reason)
    for name, count in counts.items():
        suite.set(name, str(count))
    ET.ElementTree(suite).write(destination / f"{label}.xml", encoding="utf-8", xml_declaration=True)
    print(json.dumps({"suite": label, **counts}), flush=True)
    if counts["tests"] != expected or counts["failures"] or counts["errors"]:
        raise RuntimeError("Instrumentation count or outcome failed; inspect sanitized XML")
    if label == "onboarding" and counts["skipped"]:
        raise RuntimeError("Onboarding was skipped, not passed")


def owned_adb():
    sdk = Path(os.environ["ANDROID_HOME"])
    serial = os.environ["ANDROID_SERIAL"]
    adb = [str(sdk / "platform-tools/adb"), "-s", serial]
    avd = subprocess.check_output([*adb, "emu", "avd", "name"], text=True, timeout=15)
    if avd.splitlines()[0] != "sallimbook-probe":
        raise RuntimeError("Refusing a device not owned by the disposable probe")
    return adb


def existing_instrumentation():
    adb = owned_adb()
    subprocess.run([*adb, "shell", "input", "keyevent", "KEYCODE_WAKEUP"], check=True, timeout=15)
    subprocess.run([*adb, "shell", "wm", "dismiss-keyguard"], check=True, timeout=15)
    env = {**os.environ, "ORG_GRADLE_PROJECT_sallimbookApiOrigin": ""}
    env.pop("ORG_GRADLE_PROJECT_sallimbookCloudFixture", None)
    try:
        subprocess.run([
            str(ANDROID / "gradlew"), "-p", str(ANDROID), "--no-daemon", "--max-workers=1",
            ":app:connectedDebugAndroidTest",
            ("-Pandroid.testInstrumentationRunnerArguments.class="
             "io.github.jihoon22lee.sallimbook.SecureBridgeWebViewTest,"
             "io.github.jihoon22lee.sallimbook.NativeVaultCvcAcceptanceTest"),
        ], env=env, check=True)
    finally:
        save_instrumentation("existing", 12)


class SyntheticIdentityProxy:
    """Loopback-only test proxy input; actual ASGI peer validation stays enabled."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope)
            scope["headers"] = [
                (key, value) for key, value in scope["headers"]
                if not key.lower().startswith(b"tailscale-")
            ] + [(b"tailscale-user-login", IDENTITY)]
        await self.app(scope, receive, send)


def debug_resources(private, cert):
    directory = private / "debug"
    (directory / "res/raw").mkdir(parents=True)
    (directory / "res/xml").mkdir()
    shutil.copyfile(cert, directory / "res/raw/sallimbook_cloud_ca.pem")
    manifest = ET.parse(ANDROID / "app/src/debug/AndroidManifest.xml")
    manifest.getroot().find("application").set(
        "{http://schemas.android.com/apk/res/android}networkSecurityConfig",
        "@xml/sallimbook_cloud_network",
    )
    manifest.write(directory / "AndroidManifest.xml", encoding="utf-8", xml_declaration=True)
    (directory / "res/xml/sallimbook_cloud_network.xml").write_text(
        '<network-security-config><base-config cleartextTrafficPermitted="false">'
        '<trust-anchors><certificates src="system"/></trust-anchors></base-config>'
        '<debug-overrides><trust-anchors><certificates src="@raw/sallimbook_cloud_ca"/>'
        '</trust-anchors></debug-overrides></network-security-config>\n'
    )
    return directory


def run_fixture(url, host_only, build_only=False):
    schema = "sallimbook_test_" + uuid4().hex
    admin = make_engine(url)
    engine = make_engine(url, schema=schema)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    server = None
    thread = None
    reverse = None
    try:
        with engine.connect() as connection:
            config = Config(str(ROOT / "services/api/alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with tempfile.TemporaryDirectory(prefix="sallimbook-android-https-") as temporary:
            private = Path(temporary)
            private.chmod(0o700)
            key, cert = private / "key.pem", private / "cert.pem"
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                "-keyout", str(key), "-out", str(cert), "-subj", "/CN=localhost",
                "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            key.chmod(0o600)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
                origin = f"https://127.0.0.1:{port}"
                settings = Settings(
                    _env_file=None, environment="test", database_url=None,
                    allowed_origins=[origin],
                    self_setup_identity_sha256=hashlib.sha256(IDENTITY).hexdigest(),
                    self_setup_proxy_host="localhost",
                )
                app = create_app(settings)

                @asynccontextmanager
                async def lifespan(app):
                    app.state.settings = settings
                    app.state.engine = engine
                    yield

                app.router.lifespan_context = lifespan
                server = uvicorn.Server(uvicorn.Config(
                    SyntheticIdentityProxy(app), ssl_keyfile=str(key), ssl_certfile=str(cert),
                    access_log=False, proxy_headers=False, log_level="critical",
                ))
                thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
                thread.start()
                deadline = time.monotonic() + 15
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.05)
                if not server.started:
                    raise RuntimeError("Isolated TLS server did not start")
                # Use the test CA and normal hostname verification, never trust-all.
                context = ssl.create_default_context(cafile=str(cert))
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)
                )
                with opener.open(origin + "/api/v1/household/setup", timeout=10) as response:
                    if json.load(response) != {"available": True}:
                        raise RuntimeError("Fresh schema is not available for setup")
                print("PASS: fresh PostgreSQL schema + real migration + hostname-verified HTTPS setup status", flush=True)
                try:
                    with (
                        socket.create_connection(("127.0.0.1", port), timeout=5) as raw,
                        context.wrap_socket(raw, server_hostname="wrong.synthetic.invalid"),
                    ):
                        raise RuntimeError("TLS accepted the wrong hostname")
                except ssl.SSLCertVerificationError:
                    print("PASS: wrong TLS hostname rejected", flush=True)
                resources = debug_resources(private, cert)
                if not host_only:
                    if not build_only:
                        adb = owned_adb()
                        subprocess.run([*adb, "reverse", f"tcp:{port}", f"tcp:{port}"], check=True)
                        reverse = (adb, port)
                    env = {**os.environ, "ORG_GRADLE_PROJECT_sallimbookApiOrigin": origin,
                           "ORG_GRADLE_PROJECT_sallimbookCloudFixture": str(resources)}
                    gradle = [
                        str(ANDROID / "gradlew"), "-p", str(ANDROID), "--no-daemon", "--max-workers=1",
                        *([":app:assembleDebug", ":app:assembleDebugAndroidTest"] if build_only
                          else [":app:connectedDebugAndroidTest"]),
                        "-Pandroid.testInstrumentationRunnerArguments.sallimbookCloudFixture=true",
                        ("-Pandroid.testInstrumentationRunnerArguments.class="
                         "io.github.jihoon22lee.sallimbook.AndroidCloudOnboardingTest"),
                    ]
                    try:
                        subprocess.run(gradle, env=env, check=True)
                    finally:
                        if not build_only:
                            save_instrumentation("onboarding", 1)
                    if build_only:
                        # Same opt-in overlay property, but no test origin in the
                        # normal release. Inspect this APK's resources/all DEX.
                        subprocess.run([
                            str(ANDROID / "gradlew"), "-p", str(ANDROID), "--no-daemon",
                            "--max-workers=1", ":app:assembleRelease",
                        ], env={**env, "ORG_GRADLE_PROJECT_sallimbookApiOrigin": ""}, check=True)
                # Finish before deleting TLS material or disposing the test schema.
                server.should_exit = True
                thread.join(timeout=15)
                if thread.is_alive():
                    raise RuntimeError("TLS fixture did not stop")
    finally:
        if reverse:
            adb, port = reverse
            subprocess.run([*adb, "reverse", "--remove", f"tcp:{port}"], check=False)
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=15)
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
        print("Removed owned schema and stopped owned TLS fixture.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--host-only", action="store_true")
    mode.add_argument("--build-only", action="store_true", help="Build fixture APKs without device acceptance")
    mode.add_argument("--existing-only", action="store_true", help="Run the original 12 instrumented tests only")
    args = parser.parse_args()
    if not (args.host_only or args.build_only) and not os.environ.get("ANDROID_SERIAL", "").startswith("emulator-"):
        parser.error("Run from the disposable AVD probe, or use --host-only")
    if not (args.host_only or args.build_only):
        existing_instrumentation()
        if args.existing_only:
            return
    with test_service_lock():
        values = {key: value for key, value in dotenv_values(ROOT / ".env").items() if value}
        url = values.get("SALLIMBOOK_TEST_DATABASE_URL", "")
        validate_test_url(url)
        environment = {**os.environ, **values}
        if subprocess.check_output(COMPOSE + ["ps", "--status", "running", "-q", "db-test"],
                                   env=environment, text=True).strip():
            raise SystemExit("Test DB is already in use; nothing changed")
        try:
            subprocess.run(COMPOSE + ["up", "-d", "--wait", "db-test"], env=environment, check=True)
            run_fixture(url, args.host_only, args.build_only)
        finally:
            subprocess.run(COMPOSE + ["stop", "db-test"], env=environment, check=True)


if __name__ == "__main__":
    main()
