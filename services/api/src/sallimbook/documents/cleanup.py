"""Remove only unreferenced/deleted ciphertext after a 24-hour grace period.

Expired pending rows and unlinked ready rows retain their metadata and link history.
An unlinked ready document can be reattached until explicitly deleted by the household.
This operator job cannot delete active referenced content or arbitrary store files.
"""

import os
import stat
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from sallimbook.documents.models import Document
from sallimbook.documents.storage import STORAGE_NAME, PrivateStore


def cleanup_files(session, settings, *, apply=False, now=None):
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=24)
    # Uploads take the shared form before writing, retained through the metadata commit.
    # This barrier avoids deleting content while its transaction is not visible yet.
    session.execute(text("SELECT pg_advisory_xact_lock(91544042505043)"))
    keep = set(
        session.scalars(
            select(Document.storage_key).where(
                Document.storage_key.is_not(None),
                (Document.state != "deleted") | (Document.deleted_at > cutoff),
            )
        )
    )
    counts = {"eligible": 0, "removed": 0, "ignored": 0}
    with PrivateStore(settings.document_storage_directory).directory() as directory:
        # scandir does not materialize an unbounded list. Only service-owned opaque objects qualify.
        with os.scandir(directory) as entries:
            for entry in entries:
                if not STORAGE_NAME.fullmatch(entry.name) or entry.name in keep:
                    counts["ignored"] += 1
                    continue
                info = entry.stat(follow_symlinks=False)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_nlink != 1
                    or info.st_mtime > cutoff.timestamp()
                ):
                    counts["ignored"] += 1
                    continue
                counts["eligible"] += 1
                if apply:
                    os.unlink(entry.name, dir_fd=directory)
                    counts["removed"] += 1
        if apply:
            os.fsync(directory)
    session.commit()
    return counts
