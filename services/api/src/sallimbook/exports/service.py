"""Read one PostgreSQL snapshot, then authorize issuance in a fresh transaction."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from sallimbook import models  # noqa: F401 -- complete model registry for catalog validation
from sallimbook.assets.locking import lock_asset_scope
from sallimbook.audit.service import AUDIT_COLUMNS, projection, safe_row
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import scoped_entity
from sallimbook.core.database import Base
from sallimbook.core.errors import DomainError
from sallimbook.documents.models import Document, DocumentLink
from sallimbook.documents.storage import PrivateStore, load_keys
from sallimbook.exports.archive import ArchiveBuilder, too_large
from sallimbook.exports.catalog import PUBLIC_COLUMNS, validate_catalog
from sallimbook.identity import service as identity
from sallimbook.identity.auth_models import HouseholdMember, User
from sallimbook.identity.passkeys.models import StepUpPurpose
from sallimbook.identity.passkeys.service import check_step_up


@dataclass(frozen=True)
class SelectedDocument:
    id: object
    version: int
    checksum_sha256: str
    size_bytes: int


def _authorize(session, principal, token, budget):
    session.execute(text("SET LOCAL statement_timeout = '30000ms'"))
    session.execute(text("SET LOCAL lock_timeout = '5000ms'"))
    auth, devices = identity.lock_session_devices(session, principal)
    # Credential/grant locks precede household/domain locks in both phases.
    grant = (
        check_step_up(session, principal, token, StepUpPurpose.DATA_EXPORT, principal.household_id)
        if token is not None
        else None
    )
    lock_asset_scope(session, principal)
    member = scoped_entity(session, HouseholdMember, principal.member_id, principal)
    if member.status != "active" or member.user_id != principal.user_id:
        raise DomainError("UNAUTHENTICATED", "로그인이 필요합니다.", 401)

    def recheck(*, consumed=False):
        budget.check()
        now = identity.validate_locked_session(
            principal,
            auth,
            devices[principal.device_id],
            recent_login=grant is None,
        )
        if grant is not None and (
            grant.expires_at <= now or (grant.consumed_at is not None and not consumed)
        ):
            raise DomainError("STEP_UP_REQUIRED", "이 작업을 다시 인증해 주세요.", 403)
        return now

    recheck()
    deadlines = [budget.issuance_deadline, auth.expires_at]
    if auth.access_expires_at is not None:
        deadlines.append(auth.access_expires_at)
    deadlines.append(grant.expires_at if grant else auth.authenticated_at + timedelta(minutes=5))
    return grant, recheck, min(deadlines)


def _selected(session, principal, identifier, *, lock=False):
    row = scoped_entity(session, Document, identifier, principal, for_update=lock)
    if row.state != "ready" or not session.scalar(
        select(DocumentLink.id)
        .where(
            DocumentLink.household_id == principal.household_id,
            DocumentLink.document_id == identifier,
            DocumentLink.active.is_(True),
        )
        .limit(1)
    ):
        raise DomainError("EXPORT_DOCUMENT_CHANGED", "선택한 첨부파일 상태를 확인해 주세요.", 409)
    return row


def prepare(engine, principal, payload, token, settings, request_id, budget):
    validate_catalog(Base.metadata)
    if len(payload.document_ids) > budget.limits.documents:
        raise too_large()
    with Session(engine) as session:
        _, _, issuance_deadline = _authorize(session, principal, token, budget)
        session.commit()
    selected = []
    builder = None
    artifact = None
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                # This is deliberately the first statement; no ORM query predates isolation.
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(text("SET LOCAL statement_timeout = '30000ms'"))
                connection.execute(text("SET LOCAL lock_timeout = '5000ms'"))
                snapshot_at = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
                builder = ArchiveBuilder(budget, principal.household_id, snapshot_at)
                builder.manifest["issuance_deadline_at"] = issuance_deadline.isoformat()
                with Session(bind=connection) as snapshot:
                    for name, columns in PUBLIC_COLUMNS.items():
                        table = Base.metadata.tables[name]
                        scope = table.c.id if name == "households" else table.c.household_id
                        query = (
                            select(*(table.c[column] for column in columns))
                            .where(scope == principal.household_id)
                            .order_by(*table.primary_key.columns)
                        )
                        builder.table(
                            name,
                            columns,
                            lambda q=query: snapshot.execute(
                                q.execution_options(yield_per=500)
                            ).mappings(),
                            payload.formats,
                        )
                    query = (
                        select(HouseholdMember.id.label("member_id"), User.display_name)
                        .join(
                            User,
                            User.id == HouseholdMember.user_id,
                        )
                        .where(HouseholdMember.household_id == principal.household_id)
                        .order_by(HouseholdMember.id)
                    )
                    builder.table(
                        "member_names",
                        ("member_id", "display_name"),
                        lambda: snapshot.execute(query).mappings(),
                        payload.formats,
                    )
                    audit_query = projection(principal.household_id).order_by(
                        models.AuditEvent.occurred_at, models.AuditEvent.id
                    )
                    builder.table(
                        "audit_events",
                        AUDIT_COLUMNS,
                        lambda: (
                            safe_row(row)
                            for row in snapshot.execute(
                                audit_query.execution_options(yield_per=500)
                            ).mappings()
                        ),
                        payload.formats,
                    )
                    total = 0
                    for identifier in sorted(payload.document_ids):
                        budget.check()
                        row = _selected(snapshot, principal, identifier)
                        total += row.size_bytes
                        if total > budget.limits.document_bytes:
                            raise too_large()
                        content = PrivateStore(settings.document_storage_directory).read(
                            row, load_keys(settings.field_encryption_key_file)
                        )
                        builder.document(row.id, row.mime_type, content)
                        del content
                        selected.append(
                            SelectedDocument(
                                row.id, row.version, row.checksum_sha256, row.size_bytes
                            )
                        )
                artifact = builder.finish()
                artifact.issuance_deadline = issuance_deadline
        # All snapshot reads, decryption and ZIP work have finished; acquire current barriers.
        with Session(engine) as session:
            grant, recheck, current_deadline = _authorize(session, principal, token, budget)
            for previous in selected:
                row = _selected(session, principal, previous.id, lock=True)
                if (row.version, row.checksum_sha256, row.size_bytes) != (
                    previous.version,
                    previous.checksum_sha256,
                    previous.size_bytes,
                ):
                    raise DomainError(
                        "EXPORT_DOCUMENT_CHANGED", "선택한 첨부파일이 변경됐습니다.", 409
                    )
                record_event(
                    session,
                    principal,
                    entity_type="document",
                    entity_id=row.id,
                    action="reveal",
                    before_version=row.version,
                    after_version=row.version,
                    request_id=request_id,
                )
            record_event(
                session,
                principal,
                entity_type="user_export",
                entity_id=artifact.export_id,
                action="export",
                before_version=None,
                after_version=None,
                changed_fields=("formats", "selected_documents"),
                request_id=request_id,
            )
            session.flush()
            now = recheck()
            if now >= issuance_deadline or now >= current_deadline:
                raise DomainError("EXPORT_TIMEOUT", "내보내기 유효 시간이 지났습니다.", 408)
            if grant is not None:
                grant.consumed_at = now
                session.flush()
            if recheck(consumed=grant is not None) >= issuance_deadline:
                raise DomainError("EXPORT_TIMEOUT", "내보내기 유효 시간이 지났습니다.", 408)
            session.commit()
        return artifact
    except BaseException as error:
        if artifact is not None:
            artifact.close()
        elif builder is not None:
            builder.close()
        if isinstance(error, DBAPIError):
            code = getattr(error.orig, "sqlstate", None)
            if code == "57014":
                raise DomainError(
                    "EXPORT_TIMEOUT", "내보내기 준비 시간이 초과됐습니다.", 408
                ) from None
            if code in {"55P03", "40P01"}:
                raise DomainError("EXPORT_BUSY", "다른 작업을 처리하고 있습니다.", 503) from None
            if code == "40001":
                raise DomainError(
                    "EXPORT_CONFLICT", "자료가 변경됐습니다. 다시 시도해 주세요.", 409
                ) from None
        raise
