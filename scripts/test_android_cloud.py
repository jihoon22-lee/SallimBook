"""Disposable real HTTPS/PostgreSQL fixture for native Android onboarding.

--host-only checks fixture readiness, never claims Android acceptance.
Otherwise run from probe_android_avd.py --command so only its owned AVD is used.
Only sanitized testcase outcomes are shared. Gradle output is discarded; raw
device reports use a private temporary directory that is removed after each run.
"""

import argparse
import hashlib
import json
import os
import shutil
import socket
import ssl
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
from android_cloud_process import CloudCommandError, checked, interrupt_cleanup
from android_cloud_results import save_instrumentation
from dotenv import dotenv_values
from sallimbook.config import Settings
from sallimbook.core.database import make_engine
from sallimbook.main import create_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from test_database import COMPOSE, ROOT, test_service_lock, validate_test_url

ANDROID = ROOT / "apps/client/android"
IDENTITY = b"synthetic-android@example.invalid"


def instrument(label, expected, arguments, env):
    # A new result directory prevents a failed Gradle invocation from recycling
    # previous PASS XML. Raw XML/logcat/HTML stays private and is removed afterward.
    with tempfile.TemporaryDirectory(prefix="sallimbook-android-instrumentation-") as temporary:
        env = {**env, "ORG_GRADLE_PROJECT_sallimbookCloudResults": temporary}
        try:
            checked(arguments, env=env, label="Android instrumentation", timeout=900)
        finally:
            save_instrumentation(
                label,
                expected,
                Path(temporary) / "results",
                os.environ["SALLIMBOOK_CLOUD_RESULT_DIRECTORY"],
            )


def owned_adb():
    sdk = Path(os.environ["ANDROID_HOME"])
    serial = os.environ["ANDROID_SERIAL"]
    adb = [str(sdk / "platform-tools/adb"), "-s", serial]
    avd = checked(
        [*adb, "emu", "avd", "name"], label="Owned AVD identity", timeout=15, capture=True
    )
    if avd.splitlines()[0] != "sallimbook-probe":
        raise RuntimeError("Refusing a device not owned by the disposable probe")
    return adb


def existing_instrumentation():
    adb = owned_adb()
    checked([*adb, "shell", "input", "keyevent", "KEYCODE_WAKEUP"], label="AVD wake", timeout=15)
    checked([*adb, "shell", "wm", "dismiss-keyguard"], label="AVD keyguard", timeout=15)
    env = {**os.environ, "ORG_GRADLE_PROJECT_sallimbookApiOrigin": ""}
    env.pop("ORG_GRADLE_PROJECT_sallimbookCloudFixture", None)
    instrument(
        "existing",
        12,
        [
            str(ANDROID / "gradlew"),
            "-p",
            str(ANDROID),
            "--no-daemon",
            "--max-workers=1",
            ":app:connectedDebugAndroidTest",
            (
                "-Pandroid.testInstrumentationRunnerArguments.class="
                "io.github.jihoon22lee.sallimbook.SecureBridgeWebViewTest,"
                "io.github.jihoon22lee.sallimbook.NativeVaultCvcAcceptanceTest"
            ),
        ],
        env,
    )


class SyntheticIdentityProxy:
    """Loopback test identity and explicit HTTP/1 connection lifetime."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope)
            scope["headers"] = [
                (key, value)
                for key, value in scope["headers"]
                if not key.lower().startswith(b"tailscale-")
            ] + [(b"tailscale-user-login", IDENTITY)]
            if scope.get("http_version") in {"1.0", "1.1"}:
                # The fixture's 5s idle close can strand a pooled native GET while
                # the user edits the form. Tell the no-retry client to open a new
                # connection, without changing production transport or timeouts.
                async def send_closed(message):
                    if message["type"] == "http.response.start":
                        message = dict(message)
                        message["headers"] = [
                            (key, value)
                            for key, value in message.get("headers", [])
                            if key.lower() != b"connection"
                        ] + [(b"connection", b"close")]
                    await send(message)

                await self.app(scope, receive, send_closed)
                return
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
        "</trust-anchors></debug-overrides></network-security-config>\n"
    )
    return directory


def run_fixture(url, host_only, build_only=False):
    schema = "sallimbook_test_" + uuid4().hex
    admin = make_engine(url)
    engine = make_engine(url, schema=schema)
    server = None
    thread = None
    reverse = None
    try:
        with admin.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            connection.execute(text("SET LOCAL statement_timeout = '30s'"))
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        with engine.connect() as connection:
            connection.execute(text("SET statement_timeout = '120s'"))
            connection.commit()
            config = Config(str(ROOT / "services/api/alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with tempfile.TemporaryDirectory(prefix="sallimbook-android-https-") as temporary:
            private = Path(temporary)
            private.chmod(0o700)
            key, cert = private / "key.pem", private / "cert.pem"
            checked(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-days",
                    "1",
                    "-keyout",
                    str(key),
                    "-out",
                    str(cert),
                    "-subj",
                    "/CN=localhost",
                    "-addext",
                    "subjectAltName=DNS:localhost,IP:127.0.0.1",
                ],
                label="Disposable TLS certificate",
                timeout=30,
            )
            key.chmod(0o600)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
                origin = f"https://127.0.0.1:{port}"
                settings = Settings(
                    _env_file=None,
                    environment="test",
                    database_url=None,
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
                server = uvicorn.Server(
                    uvicorn.Config(
                        SyntheticIdentityProxy(app),
                        ssl_keyfile=str(key),
                        ssl_certfile=str(cert),
                        access_log=False,
                        proxy_headers=False,
                        log_level="critical",
                        timeout_graceful_shutdown=5,
                    )
                )
                thread = threading.Thread(
                    target=server.run, kwargs={"sockets": [listener]}, daemon=True
                )
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
                print(
                    "PASS: fresh PostgreSQL schema + real migration + "
                    "hostname-verified HTTPS setup status",
                    flush=True,
                )
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
                        checked(
                            [*adb, "reverse", f"tcp:{port}", f"tcp:{port}"],
                            label="AVD reverse",
                            timeout=15,
                        )
                        reverse = (adb, port)
                    env = {
                        **os.environ,
                        "ORG_GRADLE_PROJECT_sallimbookApiOrigin": origin,
                        "ORG_GRADLE_PROJECT_sallimbookCloudFixture": str(resources),
                    }
                    gradle = [
                        str(ANDROID / "gradlew"),
                        "-p",
                        str(ANDROID),
                        "--no-daemon",
                        "--max-workers=1",
                        *(
                            [":app:assembleDebug", ":app:assembleDebugAndroidTest"]
                            if build_only
                            else [":app:connectedDebugAndroidTest"]
                        ),
                        "-Pandroid.testInstrumentationRunnerArguments.sallimbookCloudFixture=true",
                        (
                            "-Pandroid.testInstrumentationRunnerArguments.class="
                            "io.github.jihoon22lee.sallimbook.AndroidCloudOnboardingTest"
                        ),
                    ]
                    if build_only:
                        checked(gradle, env=env, label="Fixture APK build", timeout=900)
                    else:
                        instrument("onboarding", 1, gradle, env)
                    if build_only:
                        # Same opt-in overlay property, but no test origin in the
                        # normal release. Inspect this APK's resources/all DEX.
                        checked(
                            [
                                str(ANDROID / "gradlew"),
                                "-p",
                                str(ANDROID),
                                "--no-daemon",
                                "--max-workers=1",
                                ":app:assembleRelease",
                            ],
                            env={**env, "ORG_GRADLE_PROJECT_sallimbookApiOrigin": ""},
                            label="Release isolation build",
                            timeout=900,
                        )
                # Finish before deleting TLS material or disposing the test schema.
                server.should_exit = True
                thread.join(timeout=15)
                if thread.is_alive():
                    raise RuntimeError("TLS fixture did not stop")
    finally:
        failed = False
        if reverse:
            adb, port = reverse
            try:
                checked(
                    [*adb, "reverse", "--remove", f"tcp:{port}"],
                    label="AVD reverse cleanup",
                    timeout=15,
                )
            except CloudCommandError, OSError:
                failed = True
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=15)
            failed = failed or thread.is_alive()
        engine.dispose()
        try:
            with admin.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '5s'"))
                connection.execute(text("SET LOCAL statement_timeout = '30s'"))
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        except SQLAlchemyError:
            failed = True
        finally:
            admin.dispose()
        if failed:
            raise RuntimeError("Owned fixture cleanup incomplete") from None
        print("Removed owned schema and stopped owned TLS fixture.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--host-only", action="store_true")
    mode.add_argument(
        "--build-only", action="store_true", help="Build fixture APKs without device acceptance"
    )
    mode.add_argument(
        "--existing-only", action="store_true", help="Run the original 12 instrumented tests only"
    )
    args = parser.parse_args()
    if not (args.host_only or args.build_only) and not os.environ.get(
        "ANDROID_SERIAL", ""
    ).startswith("emulator-"):
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
        if checked(
            COMPOSE + ["ps", "--status", "running", "-q", "db-test"],
            env=environment,
            label="Test DB ownership",
            timeout=30,
            capture=True,
        ).strip():
            raise SystemExit("Test DB is already in use; nothing changed")
        try:
            checked(
                COMPOSE + ["up", "-d", "--wait", "--wait-timeout", "90", "db-test"],
                env=environment,
                label="Isolated test DB start",
                timeout=120,
            )
            run_fixture(url, args.host_only, args.build_only)
        finally:
            checked(
                COMPOSE + ["stop", "db-test"],
                env=environment,
                label="Isolated test DB stop",
                timeout=45,
            )


if __name__ == "__main__":
    with interrupt_cleanup():
        try:
            main()
        except Exception, KeyboardInterrupt:  # noqa: BLE001 - CLI boundary must redact secrets.
            raise SystemExit(
                "FAIL: Android fixture command or cleanup failed; raw diagnostics withheld"
            ) from None
