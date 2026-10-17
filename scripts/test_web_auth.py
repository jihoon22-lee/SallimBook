"""Real browser HTTPS authentication against the dedicated temporary PostgreSQL service.

Run: uv run --project services/api python scripts/test_web_auth.py
No existing server, system trust store, or production configuration is changed.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import uvicorn
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from fastapi import Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from sallimbook.config import Settings
from sallimbook.core.database import make_engine
from sallimbook.identity import service
from sallimbook.identity.auth_models import AuthSession
from sallimbook.identity.schemas import InvitationAcceptance
from sallimbook.main import create_app
from sqlalchemy import text, update
from sqlalchemy.orm import Session
from test_database import COMPOSE, ROOT, test_service_lock, validate_test_url


def execute(*, passkeys: bool = False, finance: bool = False) -> None:
    values = {
        key: value for key, value in dotenv_values(ROOT / ".env").items() if value
    }
    url = values.get("SALLIMBOOK_TEST_DATABASE_URL", "")
    validate_test_url(url)
    environment = {**os.environ, **values}
    if subprocess.check_output(
        COMPOSE + ["ps", "--status", "running", "-q", "db-test"],
        env=environment,
        text=True,
    ).strip():
        raise SystemExit("Test DB already running; nothing changed.")
    subprocess.run(
        ["pnpm", "--filter", "@sallimbook/client", "build"], cwd=ROOT, check=True
    )
    try:
        subprocess.run(
            COMPOSE + ["up", "-d", "--wait", "db-test"], env=environment, check=True
        )
        run_browser(url, passkeys=passkeys, finance=finance)
    finally:
        subprocess.run(COMPOSE + ["stop", "db-test"], env=environment, check=True)


def run_browser(url: str, *, passkeys: bool = False, finance: bool = False) -> None:
    schema = "sallimbook_test_" + uuid4().hex
    admin = make_engine(url)
    engine = make_engine(url, schema=schema)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    server = None
    thread = None
    try:
        with engine.connect() as connection:
            config = Config(str(ROOT / "services/api/alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        password = secrets.token_urlsafe(32)
        with Session(engine) as session:
            invitation = service.create_bootstrap_invitation(
                session, "합성 HTTPS 검증 가계", "synthetic_https_owner"
            )
            session.commit()
            service.accept_invitation(
                session,
                InvitationAcceptance(
                    token=invitation.token,
                    password=password,
                    display_name="합성 HTTPS 구성원",
                ),
                "synthetic-browser-harness",
            )
        with tempfile.TemporaryDirectory(prefix="sallimbook-https-") as directory:
            private = Path(directory)
            field_keys = private / "field-keys.json"
            if finance:
                field_keys.touch(mode=0o600)
                field_keys.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "active_key_version": 1,
                            "keys": {
                                "1": base64.b64encode(secrets.token_bytes(32)).decode(
                                    "ascii"
                                )
                            },
                        }
                    )
                )
            key, cert = private / "key.pem", private / "cert.pem"
            subprocess.run(
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
                    "subjectAltName=DNS:localhost,DNS:sallimbook-passkey.test,IP:127.0.0.1",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            key.chmod(0o600)
            public = subprocess.check_output(
                ["openssl", "x509", "-in", str(cert), "-pubkey", "-noout"]
            )
            der = subprocess.check_output(
                ["openssl", "pkey", "-pubin", "-outform", "DER"], input=public
            )
            spki = base64.b64encode(hashlib.sha256(der).digest()).decode()
            listener = socket.socket()
            try:
                listener.bind(("127.0.0.1", 0))
                host = "sallimbook-passkey.test" if passkeys else "127.0.0.1"
                origin = f"https://{host}:{listener.getsockname()[1]}"
                settings = Settings(
                    environment="test",
                    database_url=None,
                    allowed_origins=[origin],
                    webauthn_rp_id=host if passkeys else None,
                    webauthn_web_origins=[origin] if passkeys else [],
                    webauthn_native_origins=[],
                    field_encryption_key_file=field_keys if finance else None,
                )
                app = create_app(settings)

                @asynccontextmanager
                async def lifespan(app):
                    app.state.settings = settings
                    app.state.engine = engine
                    yield

                app.router.lifespan_context = lifespan
                dist = (ROOT / "apps/client/dist").resolve()
                control = secrets.token_urlsafe(32)
                if passkeys:

                    @app.post("/__test/expire-freshness", include_in_schema=False)
                    def expire_freshness(
                        x_test_control: str | None = Header(default=None),
                    ):
                        # Test-only clock setup on this disposable schema; never installed by create_app.
                        if not x_test_control or not secrets.compare_digest(
                            x_test_control, control
                        ):
                            raise HTTPException(status_code=403)
                        with Session(engine) as session:
                            session.execute(
                                update(AuthSession).values(
                                    authenticated_at=datetime.now(UTC)
                                    - timedelta(minutes=6)
                                )
                            )
                            session.commit()
                        return {"aged": True}

                @app.get("/__test/cross-site", include_in_schema=False)
                def cross_site():
                    # A separate synthetic site may frame the API; keep the real app CSP intact.
                    return HTMLResponse(
                        "<!doctype html><title>Synthetic other site</title>"
                    )

                @app.get("/{path:path}", include_in_schema=False)
                def frontend(path: str):
                    candidate = (dist / path).resolve()
                    if not candidate.is_relative_to(dist) or not candidate.is_file():
                        candidate = dist / "index.html"
                    return FileResponse(candidate)

                server = uvicorn.Server(
                    uvicorn.Config(
                        app,
                        ssl_keyfile=str(key),
                        ssl_certfile=str(cert),
                        access_log=False,
                        log_level="critical",
                    )
                )
                thread = threading.Thread(
                    target=server.run, kwargs={"sockets": [listener]}, daemon=True
                )
                thread.start()
                deadline = time.monotonic() + 15
                while (
                    not server.started
                    and thread.is_alive()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.05)
                if not server.started:
                    raise SystemExit("Isolated HTTPS server did not start.")
                fixture = private / "fixture.json"
                fixture.touch(mode=0o600)
                fixture.write_text(
                    json.dumps(
                        {
                            "password": password,
                            "login": "synthetic_https_owner",
                            "control": control,
                        }
                    )
                )
                result = subprocess.run(
                    [
                        "pnpm",
                        "--filter",
                        "@sallimbook/client",
                        "exec",
                        "playwright",
                        "test",
                        "--config",
                        "playwright.https.config.ts",
                    ],
                    cwd=ROOT,
                    env={
                        **os.environ,
                        "SALLIMBOOK_HTTPS_ORIGIN": origin,
                        "SALLIMBOOK_HTTPS_SPKI": spki,
                        "SALLIMBOOK_HTTPS_FIXTURE": str(fixture),
                        "SALLIMBOOK_HTTPS_OUTPUT": str(private / "artifacts"),
                        "SALLIMBOOK_HTTPS_PASSKEYS": "1" if passkeys else "0",
                        "SALLIMBOOK_HTTPS_FINANCE": "1" if finance else "0",
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )
                # Browser failure details stay private; never print form snapshots or credentials.
                if result.returncode:
                    locations = sorted(
                        set(
                            re.findall(
                                r"(?:auth|passkeys|finance)-https\.spec\.ts:\d+:\d+",
                                result.stdout + result.stderr,
                            )
                        )
                    )
                    print("Failed test source locations: " + ", ".join(locations))
                    phases = re.findall(r"SAFE_PHASE=([A-Z_]+)", result.stdout)
                    print("Observed synthetic markers: " + ", ".join(phases))
                    raise SystemExit(
                        "HTTPS browser checks failed; private artifacts discarded."
                    )
                print(
                    "HTTPS browser checks passed (real API/PostgreSQL, no HTTP route mocks)."
                    + (
                        " WebAuthn: real virtual-authenticator signatures."
                        if passkeys
                        else ""
                    )
                )
            finally:
                if server:
                    server.should_exit = True
                if thread:
                    thread.join(timeout=10)
                listener.close()
    finally:
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=10)
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--passkeys",
        action="store_true",
        help="Use an isolated .test RP and Chromium virtual authenticator.",
    )
    parser.add_argument(
        "--finance",
        action="store_true",
        help="Verify asset/account UI with an ephemeral keyring and real scoped WebAuthn.",
    )
    args = parser.parse_args()
    with test_service_lock():
        execute(passkeys=args.passkeys or args.finance, finance=args.finance)
