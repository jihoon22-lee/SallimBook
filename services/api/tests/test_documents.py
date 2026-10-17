"""Actual PostgreSQL/auth/AEAD attachment lifecycle with synthetic document bytes.

The content inspector is stubbed only in lifecycle tests; its real parsers and resource
bounds have independent tests and the deployed scanner/OCR have a separate tool harness.
"""

import asyncio
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_accounts import asset_payload, make_actor, write_keyring
from test_income import headers

from sallimbook.assets.router import router as asset_router
from sallimbook.config import Settings
from sallimbook.core.audit import AuditEvent
from sallimbook.core.errors import DomainError
from sallimbook.core.http import install_http_contract
from sallimbook.documents import service
from sallimbook.documents.cleanup import cleanup_files
from sallimbook.documents.models import Document, DocumentLink
from sallimbook.documents.router import router
from sallimbook.documents.schemas import DocumentReason
from sallimbook.documents.storage import PrivateStore
from sallimbook.identity.auth_models import AuthSession

pytestmark = pytest.mark.database
CONTENT = b"SYNTHETIC MEDICAL DOCUMENT -- no personal data"


@pytest.fixture
def actors(db_engine):
    first = make_actor(db_engine)
    return first, make_actor(db_engine, first.household_id), make_actor(db_engine)


@pytest.fixture
def document_app(db_engine, tmp_path, monkeypatch):
    key_file = write_keyring(tmp_path / "key.json", {1: AESGCM.generate_key(bit_length=256)})
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(
        environment="test",
        field_encryption_key_file=key_file,
        document_storage_directory=tmp_path / "private",
        _env_file=None,
    )
    install_http_contract(app)
    app.include_router(asset_router)
    app.include_router(router)
    monkeypatch.setattr(service, "validate_document", lambda *args, **kwargs: None)
    return app


def asset(client, actor):
    response = client.post("/api/v1/assets", json=asset_payload(), headers=actor.headers)
    assert response.status_code == 201, response.text
    return response.json()


def pending(client, actor, *, target=None, key=None, content=CONTENT):
    target = target or {"kind": "asset", "id": asset(client, actor)["id"]}
    response = client.post(
        "/api/v1/documents",
        headers=headers(actor, key),
        json={
            "original_name": "합성 의료.pdf",
            "mime_type": "application/pdf",
            "size_bytes": len(content),
            "checksum_sha256": hashlib.sha256(content).hexdigest(),
            "contains_no_card_data": True,
            "target": target,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, actor, row, *, key=None, content=CONTENT, version=None):
    return client.put(
        f"/api/v1/documents/{row['id']}/content",
        content=content,
        headers=headers(actor, key, version or row["version"])
        | {"Content-Type": "application/octet-stream"},
    )


def detail(client, actor, row):
    result = client.get(f"/api/v1/documents/{row['id']}", headers=actor.headers)
    assert result.status_code == 200, result.text
    return result.json()


def test_upload_download_partner_and_encrypted_disk(document_app, actors):
    first, partner, _ = actors
    with TestClient(document_app) as client:
        row = pending(client, first)
        assert (
            client.get(f"/api/v1/documents/{row['id']}/download", headers=first.headers).status_code
            == 409
        )
        result = upload(client, first, row)
        assert result.status_code == 200, result.text
        assert result.json()["version"] == 2
        metadata = detail(client, partner, row)
        assert metadata["state"] == "ready" and metadata["active_link_count"] == 1
        assert not {"storage_key", "nonce", "encryption_key_version"} & metadata.keys()
        download = client.get(f"/api/v1/documents/{row['id']}/download", headers=partner.headers)
        assert download.content == CONTENT and download.status_code == 200
        assert download.headers["cache-control"] == "no-store"
        assert download.headers["x-content-type-options"] == "nosniff"
        assert download.headers["content-disposition"].startswith(
            'attachment; filename="document";'
        )
        assert "sandbox" in download.headers["content-security-policy"]
    stored = list(document_app.state.settings.document_storage_directory.iterdir())
    assert len(stored) == 1 and CONTENT not in stored[0].read_bytes()
    with Session(document_app.state.engine) as session:
        audits = list(
            session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "document"))
        )
        assert {a.action for a in audits} == {"create", "complete", "reveal"}
        assert all("합성 의료" not in str(a.safe_diff) for a in audits)


def test_foreign_household_cannot_list_link_get_upload_download_or_delete(document_app, actors):
    first, _, foreign = actors
    with TestClient(document_app) as client:
        target = asset(client, first)
        row = pending(client, first, target={"kind": "asset", "id": target["id"]})
        for suffix in ("", "/download", "/links"):
            assert (
                client.get(
                    f"/api/v1/documents/{row['id']}" + suffix, headers=foreign.headers
                ).status_code
                == 404
            )
        assert upload(client, foreign, row).status_code == 404
        assert (
            client.post(
                f"/api/v1/documents/{row['id']}/delete",
                json={"reason": "합성"},
                headers=headers(foreign, version=1),
            ).status_code
            == 404
        )
        for actor, doc_id, target_id in (
            (foreign, row["id"], target["id"]),
            (first, row["id"], asset(client, foreign)["id"]),
        ):
            result = client.post(
                "/api/v1/document-links",
                headers=headers(actor, version=1),
                json={"document_id": doc_id, "target": {"kind": "asset", "id": target_id}},
            )
            assert result.status_code == 404
        assert client.get("/api/v1/documents", headers=foreign.headers).json()["items"] == []
        assert (
            client.get(
                "/api/v1/documents",
                headers=foreign.headers,
                params={"target_kind": "asset", "target_id": target["id"]},
            ).status_code
            == 404
        )


def test_replay_preserves_reference_and_rejects_key_payload_reuse(document_app, actors):
    first = actors[0]
    with TestClient(document_app) as client:
        target = {"kind": "asset", "id": asset(client, first)["id"]}
        row = pending(client, first, target=target, key="doc-create")
        assert pending(client, first, target=target, key="doc-create") == row
        result = upload(client, first, row, key="doc-upload")
        assert result.status_code == 200, result.text
        assert upload(client, first, row, key="doc-upload").json() == result.json()
        assert upload(client, first, row, key="different").status_code == 409
        assert len(list(document_app.state.settings.document_storage_directory.iterdir())) == 1
        assert upload(client, first, row, key="doc-upload", version=2).status_code == 409


def test_unlink_reattach_delete_and_idempotent_history(document_app, actors):
    first = actors[0]
    with TestClient(document_app) as client:
        row = pending(client, first)
        assert upload(client, first, row).status_code == 200
        link = client.get(f"/api/v1/documents/{row['id']}/links", headers=first.headers).json()[
            "items"
        ][0]
        request = dict(json={"reason": "합성 연결 정정"}, headers=headers(first, "unlink", 1))
        end = client.post(f"/api/v1/document-links/{link['id']}/end", **request)
        assert end.status_code == 200, end.text
        assert (
            client.post(f"/api/v1/document-links/{link['id']}/end", **request).json() == end.json()
        )
        assert detail(client, first, row)["orphaned_at"] is not None
        assert (
            client.get(f"/api/v1/documents/{row['id']}/download", headers=first.headers).status_code
            == 409
        )
        linked = client.post(
            "/api/v1/document-links",
            headers=headers(first, version=3),
            json={"document_id": row["id"], "target": link["target"]},
        )
        assert linked.status_code == 201, linked.text
        assert detail(client, first, row)["orphaned_at"] is None
        assert (
            client.get(f"/api/v1/documents/{row['id']}/download", headers=first.headers).status_code
            == 200
        )
        deleted = client.post(
            f"/api/v1/documents/{row['id']}/delete",
            headers=headers(first, "delete", 4),
            json={"reason": "합성 삭제"},
        )
        assert deleted.status_code == 200, deleted.text
        assert detail(client, first, row)["active_link_count"] == 0
        assert (
            client.get(f"/api/v1/documents/{row['id']}/download", headers=first.headers).status_code
            == 409
        )
        links = client.get(f"/api/v1/documents/{row['id']}/links", headers=first.headers).json()[
            "items"
        ]
        assert len(links) == 2 and all(not item["active"] for item in links)


@pytest.mark.parametrize("body,status", [(b"different", 422), (b"", 422)])
def test_upload_declared_hash_size_mismatch(document_app, actors, body, status):
    with TestClient(document_app) as client:
        row = pending(client, actors[0])
        assert upload(client, actors[0], row, content=body).status_code == status
        assert detail(client, actors[0], row)["state"] == "pending"


def test_upload_mime_body_limit_and_missing_headers(document_app, actors):
    first = actors[0]
    with TestClient(document_app) as client:
        row = pending(client, first)
        path = f"/api/v1/documents/{row['id']}/content"
        assert (
            client.put(path, content=CONTENT, headers=headers(first, version=1)).status_code == 422
        )
        assert (
            client.put(
                path,
                content=CONTENT,
                headers=headers(first, version=1)
                | {"Content-Type": "application/octet-stream", "Content-Length": "20971521"},
            ).status_code
            == 413
        )
        assert client.put(path, content=CONTENT, headers=first.headers).status_code == 400


def test_failed_inspection_never_stores_or_changes_pending(document_app, actors, monkeypatch):
    def reject(*args, **kwargs):
        raise DomainError("DOCUMENT_MALWARE", "합성 거부", 422)

    monkeypatch.setattr(service, "validate_document", reject)
    with TestClient(document_app) as client:
        row = pending(client, actors[0])
        assert upload(client, actors[0], row).status_code == 422
        assert detail(client, actors[0], row)["state"] == "pending"
    assert not document_app.state.settings.document_storage_directory.exists()


@pytest.mark.parametrize("first_result", ["success", "invalid", "cancelled"])
def test_upload_slot_precedes_body_buffer_and_releases_on_every_exit(
    document_app, actors, first_result
):
    actor = actors[0]
    with TestClient(document_app) as client:
        first = pending(client, actor)
        second = pending(client, actor)

    async def scenario():
        started, continue_body = asyncio.Event(), asyncio.Event()
        rejected_body_reads = 0

        async def slow_body():
            yield CONTENT[:8]
            started.set()
            await continue_body.wait()
            yield CONTENT[8:] if first_result == "success" else b"INVALID"

        async def rejected_body():
            nonlocal rejected_body_reads
            rejected_body_reads += 1
            yield CONTENT

        transport = httpx.ASGITransport(app=document_app)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://synthetic.test"
        ) as client:
            first_request = asyncio.create_task(
                client.put(
                    f"/api/v1/documents/{first['id']}/content",
                    content=slow_body(),
                    headers=headers(actor, version=1)
                    | {"Content-Type": "application/octet-stream"},
                )
            )
            await asyncio.wait_for(started.wait(), timeout=5)
            response = await client.put(
                f"/api/v1/documents/{second['id']}/content",
                content=rejected_body(),
                headers=headers(actor, version=1) | {"Content-Type": "application/octet-stream"},
            )
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "DOCUMENT_UPLOAD_BUSY"
            assert rejected_body_reads == 0
            if first_result == "cancelled":
                first_request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first_request
            else:
                continue_body.set()
                result = await asyncio.wait_for(first_request, timeout=5)
                assert result.status_code == (200 if first_result == "success" else 422)
            retry = await client.put(
                f"/api/v1/documents/{second['id']}/content",
                content=CONTENT,
                headers=headers(actor, version=1) | {"Content-Type": "application/octet-stream"},
            )
            assert retry.status_code == 200, retry.text

    asyncio.run(scenario())


def test_cancelled_http_upload_keeps_slot_until_worker_releases_owned_session(
    document_app, actors, monkeypatch
):
    from sallimbook.documents.router import _UPLOAD_TASKS

    actor = actors[0]
    started, finish = Event(), Event()

    def inspect(*args, **kwargs):
        started.set()
        assert finish.wait(timeout=10)

    monkeypatch.setattr(service, "validate_document", inspect)
    with TestClient(document_app) as client:
        first, second = pending(client, actor), pending(client, actor)

    async def scenario():
        transport = httpx.ASGITransport(app=document_app)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://synthetic.test"
        ) as client:
            first_request = asyncio.create_task(
                client.put(
                    f"/api/v1/documents/{first['id']}/content",
                    content=CONTENT,
                    headers=headers(actor, version=1)
                    | {"Content-Type": "application/octet-stream"},
                )
            )
            assert await asyncio.to_thread(started.wait, 5)
            first_request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first_request
            try:
                response = await client.put(
                    f"/api/v1/documents/{second['id']}/content",
                    content=CONTENT,
                    headers=headers(actor, version=1)
                    | {"Content-Type": "application/octet-stream"},
                )
                assert response.status_code == 503
            finally:
                finish.set()
            await asyncio.wait_for(asyncio.gather(*tuple(_UPLOAD_TASKS)), timeout=5)
            current = await client.get(f"/api/v1/documents/{first['id']}", headers=actor.headers)
            assert current.json()["state"] == "ready"
            retried = await client.put(
                f"/api/v1/documents/{second['id']}/content",
                content=CONTENT,
                headers=headers(actor, version=1) | {"Content-Type": "application/octet-stream"},
            )
            assert retried.status_code == 200, retried.text

    asyncio.run(scenario())


def test_revocation_during_inspection_rechecked_before_storage(document_app, actors, monkeypatch):
    actor = actors[0]

    def revoke(*args, **kwargs):
        with Session(document_app.state.engine) as session:
            auth = session.get(AuthSession, actor.principal.session_id)
            auth.revoked_at = datetime.now(UTC)
            session.commit()

    monkeypatch.setattr(service, "validate_document", revoke)
    with TestClient(document_app) as client:
        row = pending(client, actor)
        assert upload(client, actor, row).status_code == 401
    assert not document_app.state.settings.document_storage_directory.exists()


def test_concurrent_unlink_during_inspection_does_not_store(document_app, actors, monkeypatch):
    actor = actors[0]
    with TestClient(document_app) as client:
        row = pending(client, actor)
        link = client.get(f"/api/v1/documents/{row['id']}/links", headers=actor.headers).json()[
            "items"
        ][0]

        def unlink(*args, **kwargs):
            with Session(document_app.state.engine) as session:
                service.unlink(
                    session,
                    actor.principal,
                    UUID(link["id"]),
                    DocumentReason(reason="합성 변경"),
                    '"1"',
                    "parallel-unlink",
                )

        monkeypatch.setattr(service, "validate_document", unlink)
        assert upload(client, actor, row).status_code == 409
        assert detail(client, actor, row)["state"] == "pending"
    assert not document_app.state.settings.document_storage_directory.exists()


def test_download_rechecks_expiry_after_decryption(document_app, actors, monkeypatch):
    actor = actors[0]
    with TestClient(document_app) as client:
        row = pending(client, actor)
        assert upload(client, actor, row).status_code == 200
        original = PrivateStore.read

        def slow_read(*args, **kwargs):
            result = original(*args, **kwargs)
            monkeypatch.setattr(
                service.identity, "utcnow", lambda: datetime.now(UTC) + timedelta(days=30)
            )
            return result

        monkeypatch.setattr(PrivateStore, "read", slow_read)
        response = client.get(f"/api/v1/documents/{row['id']}/download", headers=actor.headers)
        assert response.status_code == 401 and CONTENT not in response.content


@pytest.mark.parametrize(
    "change", ["name", "checksum", "envelope", "delete", "link_target", "link_delete"]
)
def test_database_guards_reject_overwrite_and_deleted_history(document_app, actors, change):
    actor = actors[0]
    with TestClient(document_app) as client:
        row = pending(client, actor)
        assert upload(client, actor, row).status_code == 200
    with Session(document_app.state.engine) as session:
        doc = session.get(Document, UUID(row["id"]))
        link = session.scalar(select(DocumentLink).where(DocumentLink.document_id == doc.id))
        if change == "name":
            doc.original_name = "changed.pdf"
        elif change == "checksum":
            doc.checksum_sha256 = "1" * 64
        elif change == "envelope":
            doc.nonce = b"1" * 12
        elif change == "delete":
            session.delete(doc)
        elif change == "link_target":
            link.asset_id = uuid4()
        else:
            session.delete(link)
        with pytest.raises(DBAPIError):
            session.commit()


def test_cleanup_preserves_live_unlinked_and_recent_files_and_removes_only_old_orphans(
    document_app, actors
):
    actor = actors[0]
    with TestClient(document_app) as client:
        row = pending(client, actor)
        assert upload(client, actor, row).status_code == 200
    directory = document_app.state.settings.document_storage_directory
    old = datetime.now(UTC) - timedelta(days=3)
    for file in directory.iterdir():
        os.utime(file, (old.timestamp(), old.timestamp()))
    orphan = directory / (uuid4().hex + ".sbdoc")
    orphan.write_bytes(b"synthetic ciphertext orphan")
    orphan.chmod(0o600)
    os.utime(orphan, (old.timestamp(), old.timestamp()))
    recent = directory / (uuid4().hex + ".sbdoc")
    recent.write_bytes(b"synthetic recent")
    recent.chmod(0o600)
    other = directory / "unrelated.txt"
    other.write_text("leave unchanged")
    with Session(document_app.state.engine) as session:
        preview = cleanup_files(session, document_app.state.settings)
        assert preview["eligible"] == 1 and preview["removed"] == 0 and orphan.exists()
        result = cleanup_files(session, document_app.state.settings, apply=True)
        assert result["removed"] == 1 and not orphan.exists()
    assert recent.exists() and other.exists()
    with TestClient(document_app) as client:
        assert (
            client.get(f"/api/v1/documents/{row['id']}/download", headers=actor.headers).content
            == CONTENT
        )


def test_upload_replay_after_delete_returns_original_reference_without_content(
    document_app, actors
):
    actor = actors[0]
    with TestClient(document_app) as client:
        row = pending(client, actor)
        receipt = upload(client, actor, row, key="stable-upload")
        assert receipt.status_code == 200
        deleted = client.post(
            f"/api/v1/documents/{row['id']}/delete",
            headers=headers(actor, version=2),
            json={"reason": "합성 삭제"},
        )
        assert deleted.status_code == 200
        replay = upload(client, actor, row, key="stable-upload")
        assert replay.status_code == 200 and replay.json() == receipt.json()
        assert detail(client, actor, row)["state"] == "deleted"
        assert (
            client.get(f"/api/v1/documents/{row['id']}/download", headers=actor.headers).status_code
            == 409
        )


def test_pending_expiration_and_missing_key_fail_closed(document_app, actors, monkeypatch):
    actor = actors[0]
    with TestClient(document_app) as client:
        row = pending(client, actor)
        document_app.state.settings.field_encryption_key_file = None
        assert upload(client, actor, row).status_code == 503
        assert detail(client, actor, row)["state"] == "pending"

        class OldClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) - timedelta(days=2)

        monkeypatch.setattr(service, "datetime", OldClock)
        expired = pending(client, actor)
        monkeypatch.setattr(service, "datetime", datetime)
        result = upload(client, actor, expired)
        assert result.status_code == 409
        assert result.json()["error"]["code"] == "DOCUMENT_UPLOAD_EXPIRED"
    assert not document_app.state.settings.document_storage_directory.exists()


def test_foreign_typed_target_database_fk_rejects_bypass(document_app, actors):
    actor, _, foreign = actors
    with TestClient(document_app) as client:
        row = pending(client, actor)
        other = asset(client, foreign)
    with Session(document_app.state.engine) as session:
        link = DocumentLink(
            id=uuid4(),
            household_id=actor.household_id,
            document_id=UUID(row["id"]),
            asset_id=UUID(other["id"]),
            active=True,
            created_by_member_id=actor.member_id,
            updated_by_member_id=actor.member_id,
        )
        session.add(link)
        with pytest.raises(DBAPIError):
            session.commit()


def test_list_filters_pages_and_duplicate_link(document_app, actors):
    actor = actors[0]
    with TestClient(document_app) as client:
        target = {"kind": "asset", "id": asset(client, actor)["id"]}
        rows = [pending(client, actor, target=target) for _ in range(3)]
        seen, cursor = [], None
        for _ in range(3):
            params = {"target_kind": "asset", "target_id": target["id"], "limit": 1}
            if cursor:
                params["cursor"] = cursor
            response = client.get("/api/v1/documents", headers=actor.headers, params=params)
            assert response.status_code == 200
            seen.extend(item["id"] for item in response.json()["items"])
            cursor = response.json()["next_cursor"]
        assert set(seen) == {row["id"] for row in rows} and cursor is None
        assert (
            client.get(
                "/api/v1/documents", headers=actor.headers, params={"target_kind": "asset"}
            ).status_code
            == 422
        )
        duplicate = client.post(
            "/api/v1/document-links",
            headers=headers(actor, version=1),
            json={"document_id": rows[0]["id"], "target": target},
        )
        assert duplicate.status_code == 409
        assert detail(client, actor, rows[0])["version"] == 1


def test_database_serializes_document_delete_and_new_link(document_app, actors):
    actor = actors[0]
    with TestClient(document_app) as client:
        row = pending(client, actor)
        assert upload(client, actor, row).status_code == 200
        link = client.get(f"/api/v1/documents/{row['id']}/links", headers=actor.headers).json()[
            "items"
        ][0]
        assert (
            client.post(
                f"/api/v1/document-links/{link['id']}/end",
                headers=headers(actor, version=1),
                json={"reason": "합성 해제"},
            ).status_code
            == 200
        )
    started = Event()

    def insert_link():
        with Session(document_app.state.engine) as session:
            session.add(
                DocumentLink(
                    id=uuid4(),
                    household_id=actor.household_id,
                    document_id=UUID(row["id"]),
                    asset_id=UUID(link["target"]["id"]),
                    active=True,
                    created_by_member_id=actor.member_id,
                    updated_by_member_id=actor.member_id,
                )
            )
            started.set()
            session.commit()

    with (
        document_app.state.engine.connect() as connection,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        transaction = connection.begin()
        connection.execute(
            text(
                "UPDATE documents SET state='deleted', deleted_at=now(), "
                "deletion_reason='synthetic', version=version+1 WHERE id=:id"
            ),
            {"id": row["id"]},
        )
        future = pool.submit(insert_link)
        try:
            assert started.wait(3)
            with pytest.raises(FutureTimeout):
                future.result(timeout=0.2)
            transaction.commit()
            with pytest.raises(DBAPIError):
                future.result(timeout=5)
        finally:
            if transaction.is_active:
                transaction.rollback()
    with Session(document_app.state.engine) as session:
        active = list(
            session.scalars(
                select(DocumentLink).where(
                    DocumentLink.document_id == UUID(row["id"]), DocumentLink.active.is_(True)
                )
            )
        )
        assert active == [] and session.get(Document, UUID(row["id"])).state == "deleted"


def test_slow_upload_body_does_not_block_session_revocation(document_app, actors):
    actor = actors[0]
    with TestClient(document_app) as client:
        row = pending(client, actor)

    def revoke():
        with Session(document_app.state.engine) as session:
            auth = session.get(AuthSession, actor.principal.session_id)
            auth.revoked_at = datetime.now(UTC)
            session.commit()

    async def scenario():
        started, continue_body = asyncio.Event(), asyncio.Event()

        async def content():
            yield CONTENT[:8]
            started.set()
            await continue_body.wait()
            yield CONTENT[8:]

        transport = httpx.ASGITransport(app=document_app)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://synthetic.test"
        ) as client:
            upload_task = asyncio.create_task(
                client.put(
                    f"/api/v1/documents/{row['id']}/content",
                    content=content(),
                    headers=headers(actor, version=1)
                    | {"Content-Type": "application/octet-stream"},
                )
            )
            await asyncio.wait_for(started.wait(), timeout=5)
            revoked = asyncio.create_task(asyncio.to_thread(revoke))
            completed_while_upload_waited = False
            try:
                await asyncio.wait_for(asyncio.shield(revoked), timeout=1)
                completed_while_upload_waited = True
            except TimeoutError:
                pass
            finally:
                continue_body.set()
            response = await asyncio.wait_for(upload_task, timeout=5)
            await asyncio.wait_for(revoked, timeout=5)
            assert completed_while_upload_waited
            assert response.status_code == 401

    asyncio.run(scenario())
    assert not document_app.state.settings.document_storage_directory.exists()
