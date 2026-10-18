"""Bounded, disk-free versioned JSON/CSV ZIP encoding."""

import csv
import hashlib
import io
import json
import time
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Event
from uuid import UUID, uuid4

from sallimbook.core.errors import DomainError

MIB = 1024 * 1024


@dataclass(frozen=True)
class Limits:
    build_seconds: float = 30
    transfer_seconds: float = 120
    rows: int = 100_000
    metadata_bytes: int = 16 * MIB
    document_bytes: int = 40 * MIB
    archive_bytes: int = 64 * MIB
    documents: int = 10


@dataclass
class Budget:
    limits: Limits = field(default_factory=Limits)
    cancel: Event = field(default_factory=Event)
    started: float = field(default_factory=time.monotonic)
    accepted_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    rows: int = 0
    metadata_bytes: int = 0
    document_bytes: int = 0

    @property
    def issuance_deadline(self):
        return self.accepted_at + timedelta(seconds=self.limits.build_seconds)

    def remaining(self):
        return max(0, self.limits.build_seconds - (time.monotonic() - self.started))

    def check(self):
        if self.cancel.is_set() or self.remaining() <= 0:
            raise DomainError("EXPORT_TIMEOUT", "내보내기 준비 시간이 초과됐습니다.", 408)

    def add(self, kind, size):
        self.check()
        current = getattr(self, kind) + size
        if current > getattr(self.limits, kind):
            raise too_large()
        setattr(self, kind, current)


def too_large():
    return DomainError("EXPORT_TOO_LARGE", "내보내기 한도를 초과했습니다.", 413)


class BoundedBuffer(io.BytesIO):
    def __init__(self, maximum):
        super().__init__()
        self.maximum = maximum

    def write(self, content):
        if self.tell() + len(content) > self.maximum:
            raise too_large()
        return super().write(content)


def scalar(value, name=""):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value) if name.endswith("_krw") else value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Timestamp must be timezone aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.strftime("%Y-%m") if name == "period_month" else value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise ValueError("Unsupported export value type")


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def csv_cell(value):
    # A visible prefix survives spreadsheet quote normalization; null remains distinguishable.
    if value is None:
        return "\\N"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        value = json_bytes(value).decode()
    if not isinstance(value, str):
        raise ValueError("Unsupported CSV value")
    return "text:" + value


@dataclass
class Artifact:
    buffer: BoundedBuffer
    export_id: UUID
    size: int
    sha256: str
    issuance_deadline: datetime

    def close(self):
        self.buffer.close()


class ArchiveBuilder:
    def __init__(self, budget, household_id, snapshot_at, export_id=None):
        self.budget = budget
        self.export_id = export_id or uuid4()
        self.buffer = BoundedBuffer(budget.limits.archive_bytes)
        self.archive = zipfile.ZipFile(
            self.buffer, "w", compression=zipfile.ZIP_STORED, allowZip64=False
        )
        self.manifest = {
            "format": "sallimbook-user-export-v1",
            "export_id": str(self.export_id),
            "household_id": str(household_id),
            "snapshot_at": scalar(snapshot_at),
            "issuance_deadline_at": scalar(budget.issuance_deadline),
            "currency": "KRW",
            "timezone": "Asia/Seoul",
            "csv": {
                "encoding": "UTF-8",
                "quoting": "all",
                "line_ending": "CRLF",
                "string_prefix": "text:",
                "null": "\\N",
                "decode": "Remove exactly one text: prefix from strings; unprefixed \\N is null.",
            },
            "excluded": [
                "authentication_and_sessions",
                "vault_and_card_secrets",
                "full_account_and_policy_numbers",
                "encryption_material",
                "private_storage_and_quota",
                "unselected_document_content",
            ],
            "semantics": (
                "Manual records and revisions; no balance recomputation. "
                "Cash rows occur once; links are references."
            ),
            "document_content": (
                "Selected originals are unredacted. They may contain sensitive text."
            ),
            "entries": [],
        }

    def _entry(self, path, chunks, *, metadata=True, rows=None):
        digest = hashlib.sha256()
        size = 0
        with self.archive.open(path, "w") as entry:
            for chunk in chunks:
                self.budget.check()
                if metadata:
                    self.budget.add("metadata_bytes", len(chunk))
                digest.update(chunk)
                size += len(chunk)
                entry.write(chunk)
        item = {"path": path, "size_bytes": size, "sha256": digest.hexdigest()}
        if rows is not None:
            item["row_count"] = rows()
        self.manifest["entries"].append(item)

    def table(self, name, columns, rows_factory, formats):
        counts = []
        for fmt in formats:
            count = 0

            def chunks(fmt=fmt):
                nonlocal count
                if fmt == "json":
                    yield b"["
                else:
                    stream = io.StringIO(newline="")
                    writer = csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
                    writer.writerow(columns)
                    yield stream.getvalue().encode()
                for raw in rows_factory():
                    self.budget.check()
                    if not counts:
                        self.budget.add("rows", 1)
                    row = {column: scalar(raw[column], column) for column in columns}
                    if fmt == "json":
                        yield (b"," if count else b"") + json_bytes(row)
                    else:
                        stream.seek(0)
                        stream.truncate()
                        writer.writerow([csv_cell(row[column]) for column in columns])
                        yield stream.getvalue().encode()
                    count += 1
                if fmt == "json":
                    yield b"]"

            self._entry(
                f"{fmt}/{name}.{fmt}",
                chunks(),
                rows=lambda: count,  # noqa: B023 -- consumed synchronously below
            )
            counts.append(count)
        if len(set(counts)) > 1:
            raise ValueError("Snapshot projection changed")

    def document(self, identifier, mime, content):
        self.budget.add("document_bytes", len(content))
        suffix = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}[mime]
        self._entry(f"documents/{identifier}.{suffix}", (content,), metadata=False)

    def finish(self):
        content = json_bytes(self.manifest)
        self.budget.add("metadata_bytes", len(content))
        self.archive.writestr("manifest.json", content)
        self.archive.close()
        self.budget.check()
        size = self.buffer.tell()
        with self.buffer.getbuffer() as view:
            digest = hashlib.sha256(view).hexdigest()
        self.buffer.seek(0)
        return Artifact(self.buffer, self.export_id, size, digest, self.budget.issuance_deadline)

    def close(self):
        try:
            self.archive.close()
        finally:
            self.buffer.close()
