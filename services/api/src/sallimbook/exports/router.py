import asyncio
from threading import BoundedSemaphore
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response
from starlette.concurrency import run_in_threadpool

from sallimbook.core.errors import DomainError, ErrorResponse
from sallimbook.exports.archive import Budget
from sallimbook.exports.runtime import ExportLease, ExportResponse
from sallimbook.exports.schemas import ExportRequest
from sallimbook.exports.service import prepare
from sallimbook.identity.dependencies import PrincipalDependency, SessionDependency

router = APIRouter(prefix="/api/v1", tags=["exports"])
_EXPORT_SLOT = BoundedSemaphore(1)
_EXPORT_TASKS: set[asyncio.Task] = set()


def _finished(task):
    _EXPORT_TASKS.discard(task)
    if not task.cancelled():
        task.exception()


def _prepare(lease, *args):
    artifact = None
    try:
        artifact = prepare(*args, budget=lease.budget)
        return artifact
    finally:
        # Executed by the actual synchronous worker, not a cancelled asyncio wrapper.
        lease.worker_done(artifact)


@router.post(
    "/exports",
    operation_id="createUserExport",
    response_class=Response,
    responses={
        200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}},
        408: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
    },
)
async def create_export(
    payload: ExportRequest,
    request: Request,
    principal: PrincipalDependency,
    session: SessionDependency,
    step_up_token: Annotated[str | None, Header(alias="X-Step-Up-Token", max_length=128)] = None,
):
    budget = Budget()
    await run_in_threadpool(session.commit)
    if not _EXPORT_SLOT.acquire(blocking=False):
        raise DomainError("EXPORT_BUSY", "다른 내보내기를 처리하고 있습니다.", 503)
    lease = ExportLease(_EXPORT_SLOT, budget)
    dispatched = False
    try:
        task = asyncio.create_task(
            run_in_threadpool(
                _prepare,
                lease,
                request.app.state.engine,
                principal,
                payload,
                step_up_token,
                request.app.state.settings,
                request.state.request_id,
            )
        )
        _EXPORT_TASKS.add(task)
        task.add_done_callback(_finished)
        dispatched = True
        await asyncio.wait_for(asyncio.shield(task), timeout=budget.remaining())
        return ExportResponse(lease)
    except BaseException as error:
        lease.abandon()
        if not dispatched:
            lease.worker_done(None)
        if isinstance(error, TimeoutError):
            raise DomainError("EXPORT_TIMEOUT", "내보내기 준비 시간이 초과됐습니다.", 408) from None
        raise
