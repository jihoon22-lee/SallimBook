"""Isolated document inspection service: no network, secrets, storage or database.

One request per connection: a 5 byte header (kind, length), exactly `length` document
bytes, then the client's half-close. The reply is at most 1 KiB of fixed JSON. Every
document is parsed by a fresh RLIMIT-bounded worker; this process never decodes it.
"""

import argparse
import json
import os
import signal
import socketserver
import stat
import struct
import sys
import threading
import time
from pathlib import Path

from sallimbook.documents._validation_worker import ProcessFailure, ProcessTimeout, bounded_process
from sallimbook.documents.validation import (
    INSPECT_KINDS,
    MAX_DOCUMENT_BYTES,
    MAX_INSPECTOR_REPLY,
    PING,
    WORKER_SECONDS,
)

WORKER = Path(__file__).with_name("_validation_worker.py").resolve()
RECEIVE_SECONDS = 30.0
MAX_CONNECTIONS = 4
_MIMES = {kind: mime for mime, kind in INSPECT_KINDS.items()}


def worker_command(mime: str, tesseract: str, pdftoppm: str) -> list[str]:
    tool = pdftoppm if mime == "application/pdf" else "-"
    return [sys.executable, "-I", "-B", str(WORKER), mime, tesseract, tool]


def _error(code: str) -> bytes:
    return json.dumps({"error": code}, separators=(",", ":")).encode()


def _receive(connection, count: int, deadline: float) -> bytes:
    data = bytearray()
    while len(data) < count:
        connection.settimeout(max(0.001, deadline - time.monotonic()))
        chunk = connection.recv(min(64 * 1024, count - len(data)))
        if not chunk:
            raise ValueError
        data.extend(chunk)
    return bytes(data)


def _at_end(connection, deadline: float) -> bool:
    connection.settimeout(max(0.001, deadline - time.monotonic()))
    return connection.recv(1) == b""


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        if not self.server.connections.acquire(blocking=False):
            return
        try:
            reply = self._reply()
            if reply is not None:
                self.request.settimeout(5)
                self.request.sendall(reply)
        except OSError, ValueError, struct.error:
            # Malformed or vanished clients get no reply; nothing is logged.
            return
        finally:
            self.server.connections.release()

    def _reply(self) -> bytes | None:
        deadline = time.monotonic() + RECEIVE_SECONDS
        kind, length = struct.unpack("!BI", _receive(self.request, 5, deadline))
        if kind == PING:
            return b'{"status":"ok"}' if length == 0 and _at_end(self.request, deadline) else None
        mime = _MIMES.get(kind)
        if mime is None or not 1 <= length <= MAX_DOCUMENT_BYTES:
            return None
        data = _receive(self.request, length, deadline)
        if not _at_end(self.request, deadline):
            return None
        if not self.server.inspection.acquire(blocking=False):
            return _error("DOCUMENT_SCAN_UNAVAILABLE")
        try:
            return bounded_process(
                worker_command(mime, self.server.tesseract, self.server.pdftoppm),
                data,
                timeout=WORKER_SECONDS,
                output_limit=MAX_INSPECTOR_REPLY,
                new_session=True,
            )
        except ProcessTimeout:
            return _error("DOCUMENT_TOO_COMPLEX")
        except ProcessFailure:
            return _error("DOCUMENT_SCAN_UNAVAILABLE")
        finally:
            self.server.inspection.release()


class InspectorServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    request_queue_size = MAX_CONNECTIONS

    def __init__(self, path: str, *, tesseract: str, pdftoppm: str):
        self.tesseract = tesseract
        self.pdftoppm = pdftoppm
        self.connections = threading.BoundedSemaphore(MAX_CONNECTIONS)
        # One expensive inspection at a time; others fail fast instead of queuing bytes.
        self.inspection = threading.BoundedSemaphore(1)
        super().__init__(path, _Handler)
        os.chmod(path, 0o660)

    def handle_error(self, request, client_address) -> None:
        # Tracebacks can carry parser paths or document-derived text. Never print them.
        return


def make_server(
    path: str, *, tesseract: str = "/usr/bin/tesseract", pdftoppm: str = "/usr/bin/pdftoppm"
) -> InspectorServer:
    try:
        if stat.S_ISSOCK(os.lstat(path).st_mode):
            os.unlink(path)  # A socket left by a previous container in the shared volume.
    except FileNotFoundError:
        pass
    return InspectorServer(path, tesseract=tesseract, pdftoppm=pdftoppm)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--tesseract", default="/usr/bin/tesseract")
    parser.add_argument("--pdftoppm", default="/usr/bin/pdftoppm")
    arguments = parser.parse_args()
    # As container PID 1 the default SIGTERM action is ignored; stop promptly on docker stop.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with make_server(
        arguments.socket, tesseract=arguments.tesseract, pdftoppm=arguments.pdftoppm
    ) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
