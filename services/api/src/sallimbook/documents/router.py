import asyncio
from threading import BoundedSemaphore
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from anyio import fail_after
from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from sallimbook.core.errors import DomainError, ErrorResponse
from sallimbook.documents import service
from sallimbook.documents.models import MAX_DOCUMENT_BYTES
from sallimbook.documents.schemas import (
    DocumentCreate,
    DocumentKind,
    DocumentLinkCreate,
    DocumentLinkListResponse,
    DocumentListResponse,
    DocumentMutationReference,
    DocumentReason,
    DocumentResponse,
)
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(
    prefix="/api/v1",
    tags=["documents"],
    responses={code: {"model": ErrorResponse} for code in (408, 413)},
)
IfMatch = Annotated[str, Header(alias="If-Match")]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]
Limit = Annotated[int, Query(ge=1, le=200)]
# Bound the complete body + inspection lifetime, before allocating any body buffer.
# Keep dispatched thread jobs alive when the HTTP task is cancelled; their buffers
# still occupy the slot until the synchronous worker actually completes.
_UPLOAD_SLOT = BoundedSemaphore(1)
_UPLOAD_TASKS: set[asyncio.Task] = set()


def _upload_finished(task: asyncio.Task) -> None:
    _UPLOAD_TASKS.discard(task)
    _UPLOAD_SLOT.release()
    if not task.cancelled():
        task.exception()  # Observe failures even if the disconnected caller is gone.


def _store_upload(engine, principal, document_id, content, if_match, key, settings):
    # A cancelled request closes its dependency session. The worker owns a separate
    # session for its complete lifetime and revalidates the live principal itself.
    with Session(engine) as worker_session:
        return service.upload_content(
            worker_session, principal, document_id, content, if_match, key, settings
        )


def _result(response, result):
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post(
    "/documents",
    response_model=DocumentMutationReference,
    status_code=201,
    operation_id="createDocument",
)
def create_document(
    payload: DocumentCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    idempotency_key: IdempotencyKey,
):
    result = service.create_document(session, principal, payload, idempotency_key)
    response.headers["Location"] = f"/api/v1/documents/{result.id}"
    return _result(response, result)


@router.get("/documents", response_model=DocumentListResponse, operation_id="listDocuments")
def list_documents(
    principal: PrincipalDependency,
    session: SessionDependency,
    target_kind: DocumentKind | None = None,
    target_id: UUID | None = None,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_documents(
        session, principal, target_kind=target_kind, target_id=target_id, cursor=cursor, limit=limit
    )


@router.get("/documents/{document_id}", response_model=DocumentResponse, operation_id="getDocument")
def get_document(
    document_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
):
    return _result(response, service.get_document(session, principal, document_id))


@router.put(
    "/documents/{document_id}/content",
    response_model=DocumentMutationReference,
    operation_id="uploadDocumentContent",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {
                    "schema": {
                        "type": "string",
                        "format": "binary",
                        "description": "Original bytes; maximum 20MiB. Never card images.",
                    }
                }
            },
        }
    },
)
async def upload_content(
    document_id: UUID,
    request: Request,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    if request.headers.get("content-type", "").lower().strip() != "application/octet-stream":
        raise DomainError("DOCUMENT_CONTENT_TYPE", "파일 원본 전송 형식을 확인해 주세요.", 422)
    raw_length = request.headers.get("content-length")
    if raw_length is not None:
        if not raw_length.isascii() or not raw_length.isdecimal():
            raise DomainError("DOCUMENT_CONTENT_LENGTH", "파일 크기를 확인해 주세요.", 422)
        if len(raw_length) > 10 or int(raw_length) > MAX_DOCUMENT_BYTES:
            raise DomainError("DOCUMENT_TOO_LARGE", "첨부파일은 20MiB 이하로 선택해 주세요.", 413)
    # authenticate() updates last_seen under a session-row lock. Release that short
    # transaction before waiting on an untrusted network body so logout/revocation
    # remains available. The service revalidates the live session after inspection.
    await run_in_threadpool(session.commit)
    if not _UPLOAD_SLOT.acquire(blocking=False):
        raise DomainError(
            "DOCUMENT_UPLOAD_BUSY",
            "다른 첨부파일을 처리하고 있습니다. 잠시 뒤 다시 시도해 주세요.",
            503,
        )
    handed_to_worker = False
    try:
        content = bytearray()
        try:
            with fail_after(120):
                async for chunk in request.stream():
                    if len(content) + len(chunk) > MAX_DOCUMENT_BYTES:
                        raise DomainError(
                            "DOCUMENT_TOO_LARGE", "첨부파일은 20MiB 이하로 선택해 주세요.", 413
                        )
                    content.extend(chunk)
        except TimeoutError:
            raise DomainError(
                "DOCUMENT_UPLOAD_TIMEOUT", "파일 전송 시간이 초과됐습니다. 다시 확인해 주세요.", 408
            ) from None
        if not content or (raw_length is not None and len(content) != int(raw_length)):
            raise DomainError("DOCUMENT_CONTENT_LENGTH", "파일 크기를 확인해 주세요.", 422)
        task = asyncio.create_task(
            run_in_threadpool(
                _store_upload,
                request.app.state.engine,
                principal,
                document_id,
                bytes(content),
                if_match,
                idempotency_key,
                request.app.state.settings,
            )
        )
        _UPLOAD_TASKS.add(task)
        task.add_done_callback(_upload_finished)
        handed_to_worker = True
        result = await asyncio.shield(task)
    finally:
        if not handed_to_worker:
            _UPLOAD_SLOT.release()
    return _result(response, result)


@router.get(
    "/documents/{document_id}/download",
    operation_id="downloadDocument",
    response_class=Response,
    responses={
        200: {
            "content": {
                mime: {"schema": {"type": "string", "format": "binary"}}
                for mime in ("application/pdf", "image/jpeg", "image/png")
            }
        }
    },
)
def download_document(
    document_id: UUID, request: Request, principal: PrincipalDependency, session: SessionDependency
):
    content, mime, name = service.download_content(
        session, principal, document_id, request.app.state.settings
    )
    return Response(
        content=content,
        media_type=mime,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Content-Disposition": "attachment; filename=\"document\"; filename*=UTF-8''"
            + quote(name),
            "Pragma": "no-cache",
        },
    )


@router.post(
    "/documents/{document_id}/delete",
    response_model=DocumentMutationReference,
    operation_id="deleteDocument",
)
def delete_document(
    document_id: UUID,
    payload: DocumentReason,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _result(
        response,
        service.delete_document(
            session, principal, document_id, payload, if_match, idempotency_key
        ),
    )


@router.post(
    "/document-links",
    response_model=DocumentMutationReference,
    status_code=201,
    operation_id="createDocumentLink",
)
def create_link(
    payload: DocumentLinkCreate,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _result(
        response, service.create_link(session, principal, payload, if_match, idempotency_key)
    )


@router.get(
    "/documents/{document_id}/links",
    response_model=DocumentLinkListResponse,
    operation_id="listDocumentLinks",
)
def list_links(
    document_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    cursor: UUID | None = None,
    limit: Limit = 50,
):
    return service.list_links(session, principal, document_id, cursor=cursor, limit=limit)


@router.post(
    "/document-links/{link_id}/end",
    response_model=DocumentMutationReference,
    operation_id="endDocumentLink",
)
def end_link(
    link_id: UUID,
    payload: DocumentReason,
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
):
    return _result(
        response, service.unlink(session, principal, link_id, payload, if_match, idempotency_key)
    )
