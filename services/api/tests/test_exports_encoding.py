"""Synthetic archive formats, resource bounds, classification and cancellation lifetime."""

import asyncio
import csv
import hashlib
import io
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import BoundedSemaphore
from uuid import uuid4
from zipfile import ZipFile

import pytest
from pydantic import ValidationError
from sqlalchemy import Column, MetaData, String, Table

from sallimbook import models  # noqa: F401
from sallimbook.audit.service import _decode, _encode, safe_row
from sallimbook.core.database import Base
from sallimbook.core.errors import DomainError
from sallimbook.exports.archive import (
    ArchiveBuilder,
    BoundedBuffer,
    Budget,
    Limits,
    scalar,
)
from sallimbook.exports.catalog import (
    PRIVATE_COLUMNS,
    PRIVATE_TABLES,
    PUBLIC_COLUMNS,
    validate_catalog,
)
from sallimbook.exports.runtime import ExportLease, ExportResponse
from sallimbook.exports.schemas import ExportRequest


def archive(rows, *, limits=None, formats=("json", "csv")):
    budget = Budget(limits=limits or Limits())
    builder = ArchiveBuilder(budget, uuid4(), datetime.now(UTC))
    try:
        builder.table("synthetic", tuple(rows[0]), lambda: iter(rows), formats)
        return builder.finish(), budget
    except BaseException:
        builder.close()
        raise


def test_catalog_covers_current_schema_and_rejects_new_fields_or_tables():
    validate_catalog(Base.metadata)
    metadata = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(metadata)
    metadata.tables["cards"].append_column(Column("new_sensitive_value", String))
    with pytest.raises(ValueError, match="column classification"):
        validate_catalog(metadata)
    Table("future_secret", metadata, Column("value", String))
    with pytest.raises(ValueError, match="table classification"):
        validate_catalog(metadata)
    assert "document_storage_reservations" in PRIVATE_TABLES
    assert all(
        name.startswith("vault_") or name in PRIVATE_TABLES
        for name in PRIVATE_TABLES
        if "vault" in name
    )
    for table, fields in PRIVATE_COLUMNS.items():
        assert not set(fields) & set(PUBLIC_COLUMNS[table])
    assert "account_number_ciphertext" not in PUBLIC_COLUMNS["financial_accounts"]
    assert "policy_number_ciphertext" not in PUBLIC_COLUMNS["insurance_policies"]
    assert "user_id" not in PUBLIC_COLUMNS["household_members"]


@pytest.mark.parametrize(
    "value",
    [
        "=1+1",
        "+cmd",
        "-cmd",
        "@SUM(1)",
        "\t=1",
        "\r=1",
        "\n=1",
        "＝1",
        "＋1",
        "－1",
        "＠1",
        'a,"=1',
        "text:",
        "\\N",
        "",
        "한글",
    ],
)
def test_csv_visible_prefix_preserves_strings_and_cannot_start_a_formula(value):
    result, _ = archive(
        [{"text": value, "amount_krw": Decimal("9007199254740993"), "absent": None, "zero_krw": 0}]
    )
    try:
        with ZipFile(result.buffer) as z:
            parsed = list(csv.DictReader(io.StringIO(z.read("csv/synthetic.csv").decode())))[0]
            assert parsed["text"] == "text:" + value
            assert parsed["text"][5:] == value
            assert parsed["amount_krw"] == "text:9007199254740993"
            assert parsed["absent"] == "\\N" and parsed["zero_krw"] == "text:0"
            original = json.loads(z.read("json/synthetic.json"))[0]
            assert original == {
                "text": value,
                "amount_krw": "9007199254740993",
                "absent": None,
                "zero_krw": "0",
            }
    finally:
        result.close()


def test_exact_types_and_manifest_checksums_fixed_paths():
    row = {
        "period_month": date(2026, 1, 1),
        "when": datetime(2026, 1, 1, tzinfo=UTC),
        "id": uuid4(),
        "active": True,
        "quantity": -3,
    }
    result, budget = archive([row])
    try:
        assert budget.rows == 1
        with ZipFile(result.buffer) as z:
            manifest = json.loads(z.read("manifest.json"))
            assert manifest["format"] == "sallimbook-user-export-v1"
            assert manifest["timezone"] == "Asia/Seoul"
            for entry in manifest["entries"]:
                content = z.read(entry["path"])
                assert hashlib.sha256(content).hexdigest() == entry["sha256"]
                assert len(content) == entry["size_bytes"] and entry["row_count"] == 1
            data = json.loads(z.read("json/synthetic.json"))[0]
            assert data["period_month"] == "2026-01"
            assert data["when"] == "2026-01-01T00:00:00Z"
            assert data["active"] is True and data["quantity"] == -3
    finally:
        result.close()


@pytest.mark.parametrize(
    "limits", [Limits(rows=1), Limits(metadata_bytes=1), Limits(archive_bytes=128)]
)
def test_overflow_rejects_whole_archive(limits):
    with pytest.raises(DomainError) as error:
        archive([{"text": "one"}, {"text": "two"}], limits=limits)
    assert error.value.code == "EXPORT_TOO_LARGE"


def test_document_limit_and_paths_never_use_original_names():
    builder = ArchiveBuilder(Budget(limits=Limits(document_bytes=3)), uuid4(), datetime.now(UTC))
    identifier = uuid4()
    builder.document(identifier, "application/pdf", b"abc")
    with pytest.raises(DomainError):
        builder.document(uuid4(), "image/png", b"x")
    assert builder.manifest["entries"][0]["path"] == f"documents/{identifier}.pdf"
    builder.close()


def test_archive_seek_rewrites_still_enforce_maximum_and_timeout():
    buffer = BoundedBuffer(4)
    buffer.write(b"abcd")
    buffer.seek(0)
    buffer.write(b"ab")
    with pytest.raises(DomainError):
        buffer.write(b"xyz")
    budget = Budget(limits=Limits(build_seconds=0))
    with pytest.raises(DomainError, match="EXPORT_TIMEOUT"):
        budget.check()


@pytest.mark.parametrize("value", [1.2, b"secret", {"secret": "value"}, datetime(2026, 1, 1)])
def test_unsupported_values_do_not_silently_serialize(value):
    with pytest.raises(ValueError):
        scalar(value)


@pytest.mark.parametrize(
    "payload",
    [
        {"formats": []},
        {"formats": ["json", "json"]},
        {"formats": ["sql"]},
        {"document_ids": [str(uuid4())] * 2},
        {"document_ids": [str(uuid4()) for _ in range(11)]},
        {"household_id": str(uuid4())},
    ],
)
def test_export_request_rejects_duplicates_limits_and_scope_override(payload):
    with pytest.raises(ValidationError):
        ExportRequest.model_validate(payload)


def lease():
    slot = BoundedSemaphore(1)
    assert slot.acquire(blocking=False)
    return ExportLease(slot, Budget()), slot


def test_cancelled_worker_holds_admission_until_actual_worker_done():
    active, slot = lease()
    active.abandon()
    assert not slot.acquire(blocking=False)
    result, _ = archive([{"text": "synthetic"}])
    active.worker_done(result)
    assert result.buffer.closed
    assert slot.acquire(blocking=False)


def test_ready_result_is_closed_on_abandon_and_release_is_idempotent():
    active, slot = lease()
    result, _ = archive([{"text": "synthetic"}])
    active.worker_done(result)
    assert not slot.acquire(blocking=False)
    active.abandon()
    active.abandon()
    assert result.buffer.closed and slot.acquire(blocking=False)


def test_response_holds_slot_during_blocked_network_and_releases_after_cancel():
    async def run():
        active, slot = lease()
        result, _ = archive([{"text": "synthetic"}])
        active.worker_done(result)
        response = ExportResponse(active)
        sending = asyncio.Event()
        unblock = asyncio.Event()

        async def send(message):
            if message["type"] == "http.response.body":
                sending.set()
                await unblock.wait()

        async def receive():
            await unblock.wait()
            return {"type": "http.disconnect"}

        task = asyncio.create_task(
            response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        )
        await asyncio.wait_for(sending.wait(), 1)
        assert not slot.acquire(blocking=False)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert result.buffer.closed and slot.acquire(blocking=False)

    asyncio.run(run())


def safe_audit(**changes):
    return {
        "id": uuid4(),
        "actor_member_id": uuid4(),
        "entity_type": "asset",
        "entity_id": uuid4(),
        "action": "create",
        "request_id": None,
        "before_version": None,
        "after_version": 1,
        "occurred_at": datetime.now(UTC),
        "safe_diff": {"changed_fields": ["name"]},
        **changes,
    }


@pytest.mark.parametrize(
    "diff",
    [
        {"changed_fields": ["synthetic_secret_value"]},
        {"changed_fields": ["name"], "value": "secret"},
        {"changed_fields": "secret"},
        {"changed_fields": [42]},
    ],
)
def test_audit_raw_values_never_return(diff):
    with pytest.raises(DomainError, match="AUDIT_METADATA_INVALID"):
        safe_row(safe_audit(safe_diff=diff))
    assert "safe_diff" not in safe_row(safe_audit())


def test_cursor_binding_canonical_format_and_exact_tuple():
    timestamp = datetime.now(UTC)
    identifier = uuid4()
    encoded = _encode([timestamp.isoformat(), str(identifier), "binding"])
    assert _decode(encoded, "binding") == (timestamp, identifier)
    for bad, binding in [
        (encoded, "foreign"),
        (encoded + "=", "binding"),
        (_encode([timestamp.isoformat(), str(identifier)]), "binding"),
        (_encode(["2026-01-01", str(identifier), "binding"]), "binding"),
    ]:
        with pytest.raises(DomainError, match="INVALID_CURSOR"):
            _decode(bad, binding)


def test_cancelled_route_keeps_real_worker_slot_until_thread_completion(monkeypatch):
    from threading import Event
    from types import SimpleNamespace

    from fastapi import FastAPI
    from starlette.requests import Request

    from sallimbook.exports import router as routes

    started, allow_finish, actually_finished = Event(), Event(), Event()
    produced = []
    slot = BoundedSemaphore(1)
    monkeypatch.setattr(routes, "_EXPORT_SLOT", slot)

    def worker(*args, budget):
        started.set()
        try:
            assert allow_finish.wait(3)
            artifact, _ = archive([{"text": "synthetic"}])
            produced.append(artifact)
            return artifact
        finally:
            actually_finished.set()

    monkeypatch.setattr(routes, "prepare", worker)

    async def run():
        app = FastAPI()
        app.state.engine = object()
        app.state.settings = object()
        request = Request({"type": "http", "app": app, "headers": []})
        request.state.request_id = str(uuid4())
        session = SimpleNamespace(commit=lambda: None)
        task = asyncio.create_task(
            routes.create_export(
                ExportRequest(),
                request,
                object(),
                session,
                None,
            )
        )
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not slot.acquire(blocking=False)
            with pytest.raises(DomainError, match="EXPORT_BUSY"):
                await routes.create_export(ExportRequest(), request, object(), session, None)
        finally:
            allow_finish.set()
            assert await asyncio.to_thread(actually_finished.wait, 2)
            for pending in tuple(routes._EXPORT_TASKS):
                await pending
        assert produced[0].buffer.closed and slot.acquire(blocking=False)

    asyncio.run(run())


def test_response_deadline_closes_buffer_and_releases_slot():
    async def run():
        active, slot = lease()
        active.budget.limits = Limits(transfer_seconds=0.01)
        artifact, _ = archive([{"text": "synthetic"}])
        active.worker_done(artifact)
        response = ExportResponse(active)
        never = asyncio.Event()

        async def blocked(_):
            await never.wait()

        async def receive():
            await never.wait()

        with pytest.raises(TimeoutError):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, blocked)
        assert artifact.buffer.closed and slot.acquire(blocking=False)

    asyncio.run(run())


def test_discarded_response_releases_slot_even_if_asgi_is_never_called():
    import gc

    active, slot = lease()
    artifact, _ = archive([{"text": "synthetic"}])
    active.worker_done(artifact)
    response = ExportResponse(active)
    assert not slot.acquire(blocking=False)
    del response
    gc.collect()
    assert artifact.buffer.closed and slot.acquire(blocking=False)
