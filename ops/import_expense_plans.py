"""Register a private, normalized plan manifest atomically; preview is the default.

Run in the deployed API environment with its normal SALLIMBOOK_DATABASE_URL.
Input is stdin or an owner-only regular file. Output contains counts/status only.
"""

import argparse
import json
import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sallimbook import models  # noqa: F401
from sallimbook.cashflow.expense_import_schemas import ImportRequest
from sallimbook.cashflow.expense_import_service import apply_import, preview_import
from sallimbook.config import Settings
from sallimbook.core.authorization import Principal
from sallimbook.core.database import make_engine
from sallimbook.core.errors import DomainError
from sallimbook.identity.auth_models import HouseholdMember
from sqlalchemy.orm import Session

MAX_BYTES = 2_000_000


def read_private(path):
    if path == "-":
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
    else:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_mode & 0o077
                or info.st_uid != os.geteuid()
            ):
                raise ValueError("Private regular file required")
            data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Manifest too large")
    return data


def run(payload, *, apply=False):
    settings = Settings()
    if settings.database_url is None:
        raise ValueError("Database not configured")
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        with Session(engine) as session:
            if not apply:
                from sqlalchemy import text

                session.execute(text("SET TRANSACTION READ ONLY"))
            member = session.get(HouseholdMember, payload.actor_member_id)
            if (
                member is None
                or member.household_id != payload.household_id
                or member.status != "active"
            ):
                raise DomainError("NOT_FOUND", "등록 대상을 찾을 수 없습니다.", 404)
            principal = Principal(
                user_id=member.user_id,
                member_id=member.id,
                household_id=member.household_id,
                session_id=UUID(int=0),
                device_id=UUID(int=0),
                role=member.role,
                transport="native",
                authenticated_at=datetime.now(UTC),
            )
            return (apply_import if apply else preview_import)(
                session, principal, payload
            )
    finally:
        engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default="-", help="Private JSON file, or - for stdin")
    parser.add_argument(
        "--apply", action="store_true", help="Commit once after all rows validate"
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        help="Create a new owner-only result receipt; never overwrite",
    )
    args = parser.parse_args(argv)
    # Reserve the receipt before mutation, so a bad output path cannot hide a successful commit.
    receipt = None
    try:
        payload = ImportRequest.model_validate_json(read_private(args.file))
        if args.receipt:
            receipt = os.fdopen(
                os.open(
                    args.receipt,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                ),
                "w",
            )
        result = run(payload, apply=args.apply)
        if receipt:
            receipt.write(result.model_dump_json())
            receipt.flush()
            os.fsync(receipt.fileno())
        print(
            json.dumps(
                {
                    "status": result.status,
                    "created_count": result.created_count,
                    "row_count": result.row_count,
                }
            )
        )
        return 0
    except Exception as failure:  # noqa: BLE001 -- never disclose private manifest/SQL values
        # Never print validation errors, SQL parameters, identifiers or raw source rows.
        code = failure.code if isinstance(failure, DomainError) else "IMPORT_REJECTED"
        print(json.dumps({"status": "rejected", "code": code}), file=sys.stderr)
        return 2
    finally:
        if receipt:
            receipt.close()


if __name__ == "__main__":
    raise SystemExit(main())
