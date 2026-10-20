"""Synthetic inspector protocol tests. The worker is replaced; no document is parsed here."""

import errno
import json
import os
import socket
import stat
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from sallimbook.documents import _validation_worker as worker
from sallimbook.documents import inspector, validation


@pytest.fixture
def served(monkeypatch):
    servers = []
    # AF_UNIX paths are short; this directory only ever holds a synthetic socket.
    directory = tempfile.TemporaryDirectory(prefix="sbi-", dir="/tmp")

    def start(run):
        monkeypatch.setattr(inspector, "bounded_process", run)
        path = str(Path(directory.name) / f"inspector-{len(servers)}.sock")
        server = inspector.make_server(path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return path

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    directory.cleanup()


def request(path, frame):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(path)
        client.sendall(frame)
        client.shutdown(socket.SHUT_WR)
        reply = bytearray()
        try:
            while chunk := client.recv(4096):
                reply.extend(chunk)
        except ConnectionResetError:
            # Closing with unread request bytes resets the peer; it is still "no reply".
            pass
        return bytes(reply)


def test_inspection_runs_the_unchanged_worker_command_on_exact_bytes(served):
    calls = []

    def run(command, data, **options):
        calls.append((command, data, options))
        return b'{"content_type":"image/png","page_count":1}'

    path = served(run)
    data = os.urandom(70_000)
    reply = validation._inspector_command(path, validation.INSPECT_KINDS["image/png"], data)
    assert reply == b'{"content_type":"image/png","page_count":1}'
    command, stdin, options = calls[0]
    assert stdin == data
    assert command == inspector.worker_command(
        "image/png", "/usr/bin/tesseract", "/usr/bin/pdftoppm"
    )
    assert command[:3] == [sys.executable, "-I", "-B"] and command[-3:] == [
        "image/png",
        "/usr/bin/tesseract",
        "-",
    ]
    assert options == {
        "timeout": validation.WORKER_SECONDS,
        "output_limit": validation.MAX_INSPECTOR_REPLY,
        "new_session": True,
    }
    assert stat.S_IMODE(os.lstat(path).st_mode) == 0o660


def test_worker_timeout_and_failure_keep_their_classification(served):
    def timeout(*args, **kwargs):
        raise worker.ProcessTimeout

    def crash(*args, **kwargs):
        raise worker.ProcessFailure

    for run, code in ((timeout, "DOCUMENT_TOO_COMPLEX"), (crash, "DOCUMENT_SCAN_UNAVAILABLE")):
        path = served(run)
        kind = validation.INSPECT_KINDS["application/pdf"]
        reply = validation._inspector_command(path, kind, b"x")
        assert json.loads(reply) == {"error": code}


def test_ping_answers_while_an_inspection_is_running(served):
    started, release = threading.Event(), threading.Event()

    def slow(*args, **kwargs):
        started.set()
        release.wait(10)
        return b'{"content_type":"image/png","page_count":1}'

    path = served(slow)
    kind = validation.INSPECT_KINDS["image/png"]
    first = threading.Thread(target=validation._inspector_command, args=(path, kind, b"x"))
    first.start()
    try:
        assert started.wait(5)
        began = time.monotonic()
        validation.check_inspector_availability(path)
        assert time.monotonic() - began < 1
        busy = validation._inspector_command(path, kind, b"y")
        assert json.loads(busy) == {"error": "DOCUMENT_SCAN_UNAVAILABLE"}
    finally:
        release.set()
        first.join(timeout=10)


@pytest.mark.parametrize(
    "frame",
    [
        struct.pack("!BI", 9, 1) + b"x",
        struct.pack("!BI", 0, 1) + b"x",
        struct.pack("!BI", 3, validation.MAX_DOCUMENT_BYTES + 1),
        struct.pack("!BI", 3, 0),
        struct.pack("!BI", 3, 5) + b"abc",
        struct.pack("!BI", 3, 1) + b"xy",
        b"\x03",
    ],
)
def test_malformed_requests_close_without_running_the_worker(served, frame):
    calls = []
    path = served(lambda *args, **kwargs: calls.append(args) or b"{}")
    assert request(path, frame) == b""
    assert calls == []


def test_existing_non_socket_path_is_never_replaced():
    with tempfile.TemporaryDirectory(prefix="sbn-", dir="/tmp") as directory:
        target = Path(directory) / "inspector.sock"
        target.write_text("synthetic")
        with pytest.raises(OSError) as error:
            inspector.make_server(str(target))
        assert error.value.errno == errno.EADDRINUSE
        assert target.read_text() == "synthetic"
