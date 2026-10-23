"""Crash-safe persistent storage accounting across API processes.

Callers hold the exclusive cleanup/write barrier until their document transaction ends.
The reservation has its own commit so rollback or an unknown commit outcome cannot lose
the charge for an orphan file. A document NO KEY UPDATE lock permits its FK check.
"""

import os
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from sallimbook.core.errors import DomainError
from sallimbook.documents.models import Document, DocumentStorageReservation

STORAGE_BARRIER = 91544042505043
QUOTA_LOCK = 91544042505044


def reserve(engine, row, settings, store):
    size = row.size_bytes + 16  # AES-GCM authentication tag also occupies disk.
    with Session(engine) as accounting:
        accounting.execute(text(f"SELECT pg_advisory_xact_lock({QUOTA_LOCK})"))
        active = DocumentStorageReservation.released_at.is_(None)
        for household, byte_limit, count_limit in (
            (None, settings.document_global_quota_bytes, settings.document_global_quota_count),
            (
                row.household_id,
                settings.document_household_quota_bytes,
                settings.document_household_quota_count,
            ),
        ):
            query = select(
                func.coalesce(func.sum(DocumentStorageReservation.size_bytes), 0),
                func.count(),
            ).where(active)
            if household is not None:
                query = query.where(DocumentStorageReservation.household_id == household)
            if household is not None:
                # A document the household deleted no longer counts toward its own quota. Its
                # ciphertext still counts toward the global quota until cleanup removes it, so
                # deleting and uploading again cannot grow the disk beyond that bound.
                query = query.join(
                    Document,
                    (Document.id == DocumentStorageReservation.document_id)
                    & (Document.household_id == DocumentStorageReservation.household_id),
                ).where(Document.state != "deleted")
            used, count = accounting.execute(query).one()
            if used + size > byte_limit or count + 1 > count_limit:
                raise DomainError(
                    "DOCUMENT_STORAGE_QUOTA_EXCEEDED",
                    "첨부파일 저장 한도에 도달했어요. "
                    "필요 없는 첨부파일을 삭제한 뒤 다시 시도해 주세요.",
                    413,
                )
        with store.directory() as directory:
            disk = os.fstatvfs(directory)
            if disk.f_bavail * disk.f_frsize < size + settings.document_min_free_bytes:
                raise DomainError(
                    "DOCUMENT_STORAGE_CAPACITY_UNAVAILABLE",
                    "첨부파일 저장 공간이 부족합니다. 관리자에게 저장소 확인을 요청해 주세요.",
                    503,
                )
        name = uuid4().hex + ".sbdoc"
        accounting.add(
            DocumentStorageReservation(
                storage_key=name,
                household_id=row.household_id,
                document_id=row.id,
                size_bytes=size,
            )
        )
        accounting.commit()
        return name
