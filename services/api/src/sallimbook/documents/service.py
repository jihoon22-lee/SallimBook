"""Typed household attachment relationships and authenticated content lifecycle."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select, text

from sallimbook.assets.locking import lock_asset_scope
from sallimbook.assets.models import Asset
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.idempotency import IdempotentResult, run_idempotent
from sallimbook.core.pagination import keyset_page
from sallimbook.documents.models import Document, DocumentLink, DocumentStorageReservation
from sallimbook.documents.quota import STORAGE_BARRIER, reserve
from sallimbook.documents.schemas import (
    DocumentLinkListResponse,
    DocumentLinkResponse,
    DocumentListResponse,
    DocumentMutationReference,
    DocumentResponse,
    DocumentTarget,
)
from sallimbook.documents.storage import PrivateStore, load_keys
from sallimbook.documents.validation import validate_document
from sallimbook.homecare.models import Appliance
from sallimbook.identity import service as identity
from sallimbook.identity.auth_models import HouseholdMember
from sallimbook.insurance.event_models import InsuranceClaim, MedicalExpense
from sallimbook.insurance.models import InsuranceCase, InsurancePolicy, MedicalNode

TARGETS = {
    "policy": InsurancePolicy,
    "case": InsuranceCase,
    "medical_node": MedicalNode,
    "expense": MedicalExpense,
    "claim": InsuranceClaim,
    "appliance": Appliance,
    "asset": Asset,
}
TTL = timedelta(hours=24)


def _actors(principal):
    return dict(
        household_id=principal.household_id,
        created_by_member_id=principal.member_id,
        updated_by_member_id=principal.member_id,
    )


def _touch(row, principal):
    before = row.version
    row.version += 1
    row.updated_by_member_id = principal.member_id
    row.updated_at = datetime.now(UTC)
    return before


def _audit(session, principal, row, action, fields=(), before=None):
    record_event(
        session,
        principal,
        entity_type="document" if isinstance(row, Document) else "document_link",
        entity_id=row.id,
        action=action,
        before_version=before,
        after_version=row.version,
        changed_fields=fields,
    )


def _lock(session, principal):
    auth, devices = identity.lock_session_devices(session, principal)
    lock_asset_scope(session, principal)
    member = scoped_entity(session, HouseholdMember, principal.member_id, principal)
    if member.status != "active" or member.user_id != principal.user_id:
        raise DomainError("UNAUTHENTICATED", "로그인이 필요합니다.", 401)

    def recheck():
        identity.validate_locked_session(principal, auth, devices[principal.device_id])

    recheck()
    return recheck


def _count(session, principal, document_id):
    return session.scalar(
        select(func.count())
        .select_from(DocumentLink)
        .where(
            DocumentLink.household_id == principal.household_id,
            DocumentLink.document_id == document_id,
            DocumentLink.active.is_(True),
        )
    )


def _response(session, principal, row):
    return DocumentResponse(
        **{
            name: getattr(row, name)
            for name in DocumentResponse.model_fields
            if name != "active_link_count"
        },
        active_link_count=_count(session, principal, row.id),
    )


def _link_response(row):
    target = next(
        DocumentTarget(kind=kind, id=getattr(row, kind + "_id"))
        for kind in TARGETS
        if getattr(row, kind + "_id") is not None
    )
    return DocumentLinkResponse(
        **{
            name: getattr(row, name)
            for name in DocumentLinkResponse.model_fields
            if name != "target"
        },
        target=target,
    )


def _target(session, principal, target):
    return scoped_entity(session, TARGETS[target.kind], target.id, principal)


def _usable(row):
    if row.state == "deleted":
        raise DomainError("DOCUMENT_UNAVAILABLE", "삭제된 첨부파일입니다.", 409)
    if row.state == "pending" and row.pending_expires_at <= datetime.now(UTC):
        raise DomainError("DOCUMENT_UPLOAD_EXPIRED", "첨부파일을 다시 등록해 주세요.", 409)


def _linked(session, principal, row):
    if not _count(session, principal, row.id):
        raise DomainError("DOCUMENT_UNLINKED", "연결된 항목이 없는 첨부파일입니다.", 409)


def _new_link(session, principal, document, target):
    _target(session, principal, target)
    existing = session.scalar(
        select(DocumentLink.id).where(
            DocumentLink.household_id == principal.household_id,
            DocumentLink.document_id == document.id,
            DocumentLink.active.is_(True),
            getattr(DocumentLink, target.kind + "_id") == target.id,
        )
    )
    if existing:
        raise DomainError("DOCUMENT_ALREADY_LINKED", "이미 연결된 첨부파일입니다.", 409)
    row = DocumentLink(
        id=uuid4(),
        document_id=document.id,
        active=True,
        **{target.kind + "_id": target.id},
        **_actors(principal),
    )
    session.add(row)
    session.flush()
    _audit(session, principal, row, "create", ("document_id", target.kind + "_id"))
    return row


def _mutation(session, principal, operation, key, payload, execute, recheck):
    result = run_idempotent(session, principal, operation, key, payload, execute)
    session.flush()
    recheck()
    session.commit()
    return DocumentMutationReference(id=result.resource_id, version=result.resource_version)


def create_document(session, principal, payload, key):
    recheck = _lock(session, principal)

    def execute():
        row = Document(
            id=uuid4(),
            **payload.model_dump(exclude={"target", "contains_no_card_data"}),
            state="pending",
            pending_expires_at=datetime.now(UTC) + TTL,
            **_actors(principal),
        )
        session.add(row)
        session.flush()
        _new_link(session, principal, row, payload.target)
        _audit(session, principal, row, "create", ("state", "target"))
        return IdempotentResult(row.id, "document", row.version)

    return _mutation(
        session,
        principal,
        "document.create",
        key,
        payload.model_dump(mode="json"),
        execute,
        recheck,
    )


def get_document(session, principal, document_id):
    recheck = _lock(session, principal)
    row = scoped_entity(session, Document, document_id, principal)
    result = _response(session, principal, row)
    recheck()
    session.commit()
    return result


def list_documents(session, principal, *, target_kind=None, target_id=None, cursor=None, limit=50):
    recheck = _lock(session, principal)
    if (target_kind is None) != (target_id is None):
        raise DomainError("INVALID_DOCUMENT_TARGET", "연결 종류와 항목을 함께 지정해 주세요.", 422)
    query = select(Document).where(
        Document.household_id == principal.household_id, Document.state != "deleted"
    )
    if target_kind is not None:
        target = DocumentTarget(kind=target_kind, id=target_id)
        _target(session, principal, target)
        query = query.where(
            Document.id.in_(
                select(DocumentLink.document_id).where(
                    DocumentLink.household_id == principal.household_id,
                    DocumentLink.active.is_(True),
                    getattr(DocumentLink, target.kind + "_id") == target.id,
                )
            )
        )
    rows, next_cursor = keyset_page(
        session,
        query,
        model=Document,
        household_id=principal.household_id,
        keys=(Document.created_at,),
        cursor=cursor,
        limit=limit,
    )
    result = DocumentListResponse(
        items=[_response(session, principal, row) for row in rows], next_cursor=next_cursor
    )
    recheck()
    session.commit()
    return result


def upload_content(session, principal, document_id, content, if_match, key, settings):
    # No domain or session locks are held during isolated parsing/scanning/OCR.
    row = scoped_entity(session, Document, document_id, principal)
    digest = hashlib.sha256(content).hexdigest()
    if len(content) != row.size_bytes or digest != row.checksum_sha256:
        raise DomainError("DOCUMENT_CONTENT_MISMATCH", "첨부파일 크기와 해시를 확인해 주세요.", 422)
    mime = row.mime_type
    needs_inspection = row.state == "pending"
    if needs_inspection:
        _usable(row)
        _linked(session, principal, row)
    session.rollback()
    if needs_inspection:
        validate_document(
            content,
            mime,
            scanner_socket=(
                str(settings.document_scanner_socket)
                if settings.document_scanner_socket is not None
                else None
            ),
            tesseract_path=str(settings.document_tesseract_path),
            pdftoppm_path=str(settings.document_pdftoppm_path),
            inspector_socket=(
                str(settings.document_inspector_socket)
                if settings.document_inspector_socket is not None
                else None
            ),
        )
    recheck = _lock(session, principal)
    store = PrivateStore(settings.document_storage_directory)

    def execute():
        # The independently committed reservation checks a composite FK against this row.
        # NO KEY UPDATE retains writer exclusion while allowing its KEY SHARE check.
        row = session.scalar(
            select(Document)
            .where(Document.id == document_id, Document.household_id == principal.household_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise DomainError("NOT_FOUND", "첨부파일을 찾을 수 없습니다.", 404)
        require_version(row, if_match)
        _usable(row)
        _linked(session, principal, row)
        if row.state != "pending":
            raise DomainError("DOCUMENT_CONTENT_EXISTS", "이미 업로드한 첨부파일입니다.", 409)
        recheck()
        session.execute(text(f"SELECT pg_advisory_xact_lock({STORAGE_BARRIER})"))
        keyring = load_keys(settings.field_encryption_key_file)
        name = reserve(session.get_bind(), row, settings, store)
        envelope = store.put(row, content, keyring, storage_key=name)
        before = _touch(row, principal)
        row.storage_key = envelope.storage_key
        row.encryption_key_version = envelope.key_version
        row.nonce = envelope.nonce
        row.stored_at = datetime.now(UTC)
        row.state = "ready"
        _audit(session, principal, row, "complete", ("state",), before)
        session.flush()
        recheck()
        return IdempotentResult(row.id, "document", row.version, 200)

    try:
        return _mutation(
            session,
            principal,
            "document.upload",
            key,
            {
                "id": str(document_id),
                "if_match": if_match,
                "size_bytes": len(content),
                "checksum_sha256": digest,
            },
            execute,
            recheck,
        )
    except BaseException:
        session.rollback()
        # A failed commit may have succeeded remotely. Only the reconciler removes orphan bytes.
        # It keeps every referenced key and uses a 24h grace period for incomplete transactions.
        raise


def download_content(session, principal, document_id, settings):
    recheck = _lock(session, principal)
    row = scoped_entity(session, Document, document_id, principal, for_update=True)
    _usable(row)
    _linked(session, principal, row)
    if row.state != "ready":
        raise DomainError("DOCUMENT_NOT_READY", "첨부파일 업로드를 완료해 주세요.", 409)
    recheck()
    content = PrivateStore(settings.document_storage_directory).read(
        row, load_keys(settings.field_encryption_key_file)
    )
    recheck()
    _audit(session, principal, row, "reveal")
    session.flush()
    recheck()
    result = (content, row.mime_type, row.original_name)
    session.commit()
    return result


def create_link(session, principal, payload, if_match, key):
    recheck = _lock(session, principal)

    def execute():
        document = scoped_entity(session, Document, payload.document_id, principal, for_update=True)
        require_version(document, if_match)
        _usable(document)
        row = _new_link(session, principal, document, payload.target)
        before = _touch(document, principal)
        document.orphaned_at = None
        _audit(session, principal, document, "update", ("links",), before)
        return IdempotentResult(row.id, "document_link", row.version)

    return _mutation(
        session,
        principal,
        "document.link",
        key,
        payload.model_dump(mode="json") | {"if_match": if_match},
        execute,
        recheck,
    )


def list_links(session, principal, document_id, *, cursor=None, limit=50):
    recheck = _lock(session, principal)
    scoped_entity(session, Document, document_id, principal)
    query = select(DocumentLink).where(
        DocumentLink.household_id == principal.household_id, DocumentLink.document_id == document_id
    )
    rows, next_cursor = keyset_page(
        session,
        query,
        model=DocumentLink,
        household_id=principal.household_id,
        keys=(DocumentLink.created_at,),
        cursor=cursor,
        limit=limit,
    )
    result = DocumentLinkListResponse(
        items=[_link_response(row) for row in rows], next_cursor=next_cursor
    )
    recheck()
    session.commit()
    return result


def unlink(session, principal, link_id, payload, if_match, key):
    recheck = _lock(session, principal)

    def execute():
        # The household writer lock serializes API mutations; retain the same
        # parent-before-child order as document deletion and direct storage writes.
        reference = scoped_entity(session, DocumentLink, link_id, principal)
        document = scoped_entity(
            session, Document, reference.document_id, principal, for_update=True
        )
        row = scoped_entity(session, DocumentLink, link_id, principal, for_update=True)
        require_version(row, if_match)
        if not row.active:
            raise DomainError("DOCUMENT_LINK_ENDED", "이미 해제한 연결입니다.", 409)
        now = datetime.now(UTC)
        before = _touch(row, principal)
        row.active, row.ended_at, row.end_reason = False, now, payload.reason
        _audit(session, principal, row, "archive", ("active", "end_reason"), before)
        session.flush()
        remaining_links = _count(session, principal, document.id)
        before = _touch(document, principal)
        if not remaining_links:
            document.orphaned_at = now
        _audit(session, principal, document, "update", ("links",), before)
        return IdempotentResult(row.id, "document_link", row.version, 200)

    return _mutation(
        session,
        principal,
        "document.unlink",
        key,
        {"id": str(link_id), "if_match": if_match, "reason": payload.reason},
        execute,
        recheck,
    )


def delete_document(session, principal, document_id, payload, if_match, key):
    recheck = _lock(session, principal)

    def execute():
        row = scoped_entity(session, Document, document_id, principal, for_update=True)
        require_version(row, if_match)
        if row.state == "deleted":
            raise DomainError("DOCUMENT_UNAVAILABLE", "이미 삭제한 첨부파일입니다.", 409)
        now = datetime.now(UTC)
        links = session.scalars(
            select(DocumentLink)
            .where(
                DocumentLink.household_id == principal.household_id,
                DocumentLink.document_id == row.id,
                DocumentLink.active.is_(True),
            )
            .with_for_update()
        )
        for link in links:
            before = _touch(link, principal)
            link.active, link.ended_at, link.end_reason = False, now, payload.reason
            _audit(session, principal, link, "archive", ("active",), before)
        before = _touch(row, principal)
        row.state, row.deleted_at, row.deletion_reason = "deleted", now, payload.reason
        _audit(session, principal, row, "delete", ("state",), before)
        # A deleted document no longer counts toward the quota. Its ciphertext stays until
        # the cleanup grace period ends; the free-disk check still guards the disk itself.
        for reservation in session.scalars(
            select(DocumentStorageReservation)
            .where(
                DocumentStorageReservation.household_id == principal.household_id,
                DocumentStorageReservation.document_id == row.id,
                DocumentStorageReservation.released_at.is_(None),
            )
            .with_for_update()
        ):
            reservation.released_at = now
        return IdempotentResult(row.id, "document", row.version, 200)

    return _mutation(
        session,
        principal,
        "document.delete",
        key,
        {"id": str(document_id), "if_match": if_match, "reason": payload.reason},
        execute,
        recheck,
    )
