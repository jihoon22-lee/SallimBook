"""Admission remains occupied until the real worker and response have both finished."""

from threading import BoundedSemaphore, Lock
from weakref import finalize

from anyio import fail_after
from starlette.responses import StreamingResponse


class ExportLease:
    def __init__(self, slot: BoundedSemaphore, budget):
        self.slot = slot
        self.budget = budget
        self.lock = Lock()
        self.finished = False
        self.abandoned = False
        self.released = False
        self.claimed = False
        self.artifact = None

    def _release(self):
        if not self.released:
            if self.artifact is not None:
                self.artifact.close()
                self.artifact = None
            self.released = True
            self.slot.release()

    def worker_done(self, artifact):
        with self.lock:
            self.finished = True
            self.artifact = artifact
            if self.abandoned or artifact is None:
                self._release()

    def abandon(self):
        self.budget.cancel.set()
        with self.lock:
            self.abandoned = True
            if self.finished and not self.claimed:
                self._release()

    def claim(self):
        with self.lock:
            if self.abandoned or not self.finished or self.artifact is None or self.claimed:
                raise RuntimeError("Export response is unavailable")
            self.claimed = True
            return self.artifact

    def response_done(self):
        with self.lock:
            self._release()


class ExportResponse(StreamingResponse):
    def __init__(self, lease):
        self.lease = lease
        artifact = lease.claim()
        # The server may discard a prepared response before ever calling ASGI.
        self._cleanup = finalize(self, lease.response_done)

        async def chunks():
            while content := artifact.buffer.read(64 * 1024):
                yield content

        try:
            super().__init__(
                chunks(),
                media_type="application/zip",
                headers={
                    "Content-Length": str(artifact.size),
                    "Content-Disposition": (
                        f'attachment; filename="sallimbook-{artifact.export_id}.zip"'
                    ),
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                    "X-Content-Type-Options": "nosniff",
                    "X-Export-ID": str(artifact.export_id),
                    "X-Export-SHA256": artifact.sha256,
                },
            )
        except BaseException:
            self._cleanup()
            raise

    async def __call__(self, scope, receive, send):
        try:
            with fail_after(self.lease.budget.limits.transfer_seconds):
                await super().__call__(scope, receive, send)
        finally:
            self._cleanup()
