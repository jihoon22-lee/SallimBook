"""Real browser HTTPS authentication against the dedicated temporary PostgreSQL service.

Run: uv run --project services/api python scripts/test_web_auth.py
No existing server, system trust store, or production configuration is changed.
"""

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
from pathlib import Path
from uuid import uuid4

import uvicorn
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from fastapi.responses import FileResponse, HTMLResponse
from sallimbook.config import Settings
from sallimbook.core.database import make_engine
from sallimbook.identity import service
from sallimbook.identity.schemas import InvitationAcceptance
from sallimbook.main import create_app
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_database import COMPOSE, ROOT, test_service_lock, validate_test_url


def execute() -> None:
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
        run_browser(url)
    finally:
        subprocess.run(COMPOSE + ["stop", "db-test"], env=environment, check=True)


def run_browser(url: str) -> None:
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
                    "subjectAltName=DNS:localhost,IP:127.0.0.1",
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
                origin = f"https://127.0.0.1:{listener.getsockname()[1]}"
                app = create_app(
                    Settings(
                        environment="test", database_url=None, allowed_origins=[origin]
                    )
                )

                @asynccontextmanager
                async def lifespan(app):
                    app.state.settings = Settings(
                        environment="test", database_url=None, allowed_origins=[origin]
                    )
                    app.state.engine = engine
                    yield

                app.router.lifespan_context = lifespan
                dist = (ROOT / "apps/client/dist").resolve()

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
                    json.dumps({"password": password, "login": "synthetic_https_owner"})
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
                                r"auth-https\.spec\.ts:\d+:\d+",
                                result.stdout + result.stderr,
                            )
                        )
                    )
                    print("Failed test source locations: " + ", ".join(locations))
                    raise SystemExit(
                        "HTTPS browser checks failed; private artifacts discarded."
                    )
                print(
                    "HTTPS browser checks: 2 passed (real API/PostgreSQL, no HTTP route mocks)."
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
    with test_service_lock():
        execute()
