"""Opt-in synthetic PostgreSQL/age integration; owns only the existing test service.

Run with the API environment and verified age/pg_dump/pg_restore on PATH. Never
prints test passwords, generated identities, ciphertexts, or raw API responses.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from ops import backup, recovery
from scripts.test_database import COMPOSE, test_service_lock, validate_test_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api/tests"))


def run_synthetic(admin_url, temporary):
    import psycopg
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from psycopg import sql
    from sallimbook.accounts.router import router as account_router
    from sallimbook.assets.router import router as asset_router
    from sallimbook.cards.router import router as card_router
    from sallimbook.config import Settings
    from sallimbook.core.database import make_engine
    from sallimbook.core.http import install_http_contract
    from sallimbook.documents import service as document_service
    from sallimbook.documents.router import router as document_router
    from sallimbook.identity import service as identity
    from sallimbook.identity.passkeys.models import StepUpPurpose
    from sallimbook.identity.schemas import LoginRequest
    from sallimbook.vault.router import router as vault_router
    from test_accounts import create_account, make_actor, write_keyring
    from test_documents import CONTENT, pending, upload
    from test_income import headers
    from test_vault import (
        accept,
        card,
        finalize,
        initialize,
        prepare,
        rotation_detail,
        share,
        stage,
        start_rotation,
        status,
        step_up,
        write_secret,
    )

    parsed = make_url(admin_url)
    suffix = uuid4().hex[:12]
    source_name = "sallimbook_ops_" + suffix + "_test"
    target_name = "sallimbook_ops_" + suffix + "_restorecheck"
    source_url = parsed.set(database=source_name).render_as_string(hide_password=False)
    target_url = parsed.set(database=target_name).render_as_string(hide_password=False)
    admin = psycopg.connect(
        host=parsed.host,
        port=parsed.port,
        user=parsed.username,
        password=parsed.password,
        dbname=parsed.database,
        autocommit=True,
    )
    engines = []
    created = []
    try:
        for name in (source_name, target_name):
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            created.append(name)
        source = make_engine(source_url)
        target = make_engine(target_url)
        engines.extend([source, target])
        with source.connect() as connection:
            config = Config(str(ROOT / "services/api/alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        first = make_actor(source)
        partner = make_actor(source, first.household_id)
        # These are disposable synthetic test keys. They are never printed or
        # retained; no real deployment/signing/keyring identity is touched.
        keyring = write_keyring(
            temporary / "synthetic-field-keyring.json", {1: bytes(range(32))}
        )
        documents = temporary / "documents"
        documents.mkdir(mode=0o700)

        def app(engine, objects):
            result = FastAPI()
            result.state.engine = engine
            result.state.settings = Settings(
                environment="test",
                field_encryption_key_file=keyring,
                document_storage_directory=objects,
                _env_file=None,
            )
            install_http_contract(result)
            for router in (
                account_router,
                asset_router,
                card_router,
                document_router,
                vault_router,
            ):
                result.include_router(router)
            return result

        with (
            TestClient(app(source, documents)) as client,
            patch.object(document_service, "validate_document", return_value=None),
        ):
            create_account(client, first)
            row = pending(client, first)
            assert upload(client, first, row).status_code == 200
            initialize(client, first)
            accept(client, partner, share(client, first, partner))
            card_row = card(client, first)
            assert write_secret(client, first, card_row).status_code == 200
            pending_rotation = prepare(
                client, first, start_rotation(client, first), [first, partner]
            )
            assert pending_rotation["key_version"] == 2
        with Session(source) as session:
            step_up(
                session, first, StepUpPurpose.VAULT_KEY_ROTATION, first.household_id
            )

        def service(name):
            path = temporary / (name + ".conf")
            path.write_text(
                "[sallimbook]\n"
                + "\n".join(
                    key + "=" + str(value)
                    for key, value in {
                        "host": parsed.host,
                        "port": parsed.port,
                        "user": parsed.username,
                        "password": parsed.password,
                        "dbname": name,
                        "sslmode": "disable",
                    }.items()
                )
                + "\n"
            )
            path.chmod(0o600)
            return path

        source_service, target_service = service(source_name), service(target_name)
        age_identity = temporary / "synthetic-age-identity.txt"
        subprocess.run(
            ["age-keygen", "-o", str(age_identity)], check=True, capture_output=True
        )
        age_identity.chmod(0o600)
        recipient = subprocess.check_output(
            ["age-keygen", "-y", str(age_identity)], text=True
        ).strip()
        destination = temporary / "backups"
        destination.mkdir(mode=0o700)
        deployment_manifest = temporary / "deployment.json"
        deployment_manifest.write_text(
            json.dumps(
                {
                    "format": 1,
                    "project": "sallimbook-staging",
                    "fqdn": "synthetic.example.ts.net",
                    "certificate_sha256": ":".join(["AB"] * 32),
                    "api_image": "example.invalid/api:test@sha256:" + "1" * 64,
                    "web_image": "example.invalid/web:test@sha256:" + "2" * 64,
                    "runtime_directory": "/srv/sallimbook/sallimbook-staging",
                    "version_code": 2,
                    "version_name": "0.1.1",
                    "source_commit": "a" * 40,
                }
            )
        )
        env, _ = backup.service_environment(source_service)

        # Reproduce a transaction that writes while backup waits for the storage
        # barrier. The exported snapshot MUST contain this committed update.
        with backup.connect(env) as writer, ThreadPoolExecutor(max_workers=1) as pool:
            writer.execute("SELECT pg_advisory_lock(%s)", (backup.STORAGE_BARRIER,))
            future = pool.submit(
                backup.backup,
                source_service,
                documents,
                destination,
                recipient,
                "a" * 40,
                deployment_manifest,
            )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                waiting = writer.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name='sallimbook-backup' "
                    "AND pid<>pg_backend_pid() AND wait_event='advisory'"
                ).fetchone()[0]
                if waiting:
                    break
                time.sleep(0.02)
            assert waiting and not future.done()
            writer.execute(
                "UPDATE households SET name='synthetic-after-storage-lock',version=version+1"
            )
            writer.execute("SELECT pg_advisory_unlock(%s)", (backup.STORAGE_BARRIER,))
            receipt = future.result(timeout=60)
        archive = destination / receipt["file"]
        assert CONTENT not in archive.read_bytes()
        assert list(destination.glob("*.partial")) == []
        assert len(list(destination.glob("*.complete.json"))) == 1
        restored = temporary / "restored"
        backup.restore(
            archive, age_identity, target_service, restored, receipt["sha256"]
        )
        with target.connect() as connection:
            assert (
                connection.execute(text("SELECT name FROM households")).scalar_one()
                == "synthetic-after-storage-lock"
            )
        with source.connect() as original, target.connect() as copied:
            tables = (
                original.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                )
                .scalars()
                .all()
            )
            for table in tables:
                assert (
                    original.execute(
                        text(f'SELECT count(*) FROM "{table}"')
                    ).scalar_one()
                    == copied.execute(
                        text(f'SELECT count(*) FROM "{table}"')
                    ).scalar_one()
                )
        with backup.connect(
            backup.service_environment(target_service, restore=True)[0]
        ) as conn:
            counts = recovery.check_ciphertexts(conn, restored / "objects", keyring)
            assert counts == {"documents": 1, "account_numbers": 1, "policy_numbers": 0}
        source.dispose()
        target.dispose()  # Preparation rejects live API/pool connections.
        recovery.prepare(
            target_service,
            restored,
            lambda index: f"Synthetic new restore password {index}!",
        )
        manifest = json.loads((restored / "backup-manifest.json").read_text())
        assert manifest["vault_max_versions"] == {str(first.household_id): 2}
        evidence = temporary / "synthetic-acceptance.json"
        evidence.write_text(
            json.dumps(
                {
                    "format": 1,
                    "backup_id": manifest["id"],
                    "acknowledgements": dict.fromkeys(recovery.ACKS, True),
                    "evidence_sha256": "b" * 64,
                }
            )
        )
        try:
            recovery.verify(target_service, restored, keyring, evidence)
            raise AssertionError("Old vault/pending rotation unexpectedly approved")
        except backup.OperationError:
            pass
        with TestClient(app(target, restored / "objects")) as client:
            assert (
                client.get("/api/v1/vault/status", headers=first.headers).status_code
                == 401
            )
            new_actors = []
            for index, actor in enumerate((first, partner), start=1):
                with Session(target) as session:
                    result = identity.login(
                        session,
                        LoginRequest(
                            login_name=actor.login_name,
                            password=f"Synthetic new restore password {index}!",
                            device_label="Synthetic recovery device",
                        ),
                        "synthetic-restore",
                        "native",
                    )
                    principal = identity.authenticate(session, result.token, "native")
                    session.commit()
                    assert principal.device_id != actor.principal.device_id
                    new_actors.append(
                        replace(actor, token=result.token, principal=principal)
                    )
            first, partner = new_actors
            rotation = rotation_detail(client, first, pending_rotation["id"])
            aborted = client.post(
                f"/api/v1/vault/rotations/{rotation['id']}/abort",
                json={},
                headers=headers(first, version=rotation["version"]),
            )
            assert aborted.status_code == 200
            rotation = prepare(
                client, first, start_rotation(client, first), [first, partner], seed=500
            )
            assert (
                rotation["key_version"]
                > manifest["vault_max_versions"][str(first.household_id)]
            )
            for target_card in rotation["cards"]:
                rotation = stage(client, first, rotation, target_card, seed=600)
            assert finalize(client, first, rotation).status_code == 200
            assert status(client, first)["current_key_version"] == 3
        result = recovery.verify(target_service, restored, keyring, evidence)
        assert (
            result["status"] == "ready-for-operator-review"
            and (restored / "QUARANTINE").exists()
        )
        # Wrong expected digest fails before restore database mutation.
        try:
            backup.restore(
                archive, age_identity, target_service, temporary / "wrong", "0" * 64
            )
            raise AssertionError("Wrong digest accepted")
        except backup.OperationError:
            assert not (temporary / "wrong").exists()
        print(
            "PASS: encrypted backup/restore, lock-before-snapshot, table counts, document+account AEAD, auth reset, pending abort/new rotation gate; synthetic metadata vault fixtures only."
        )
    finally:
        for engine in engines:
            engine.dispose()
        for name in created:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(name)
                )
            )
        admin.close()


def main():
    backup.verify_tools("age", "pg_dump", "pg_restore")
    values = {
        key: value
        for key, value in dotenv_values(ROOT / ".env").items()
        if value is not None
    }
    url = values.get("SALLIMBOOK_TEST_DATABASE_URL", "")
    validate_test_url(url)
    env = {**os.environ, **values}
    with test_service_lock():
        running = subprocess.check_output(
            COMPOSE + ["ps", "--status", "running", "-q", "db-test"],
            cwd=ROOT,
            env=env,
            text=True,
        ).strip()
        if running:
            raise SystemExit("Test service already running; nothing changed")
        try:
            subprocess.run(
                COMPOSE + ["up", "-d", "--wait", "db-test"],
                cwd=ROOT,
                env=env,
                check=True,
            )
            with tempfile.TemporaryDirectory(
                prefix="sallimbook-ops-synthetic-"
            ) as temporary:
                run_synthetic(url, Path(temporary))
        finally:
            subprocess.run(COMPOSE + ["stop", "db-test"], cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
