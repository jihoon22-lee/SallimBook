"""Bounded, fail-closed document inspection. No plaintext file is written here.

Only static server configuration may supply scanner/binary paths. OCR is a conservative
screen for readable documents, not proof that every possible card photograph is detected.
The original bytes are neither normalized nor returned by the inspection worker.
"""

import hashlib
import json
import os
import re
import socket
import stat
import struct
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sallimbook.core.errors import DomainError
from sallimbook.documents._validation_worker import (
    DEADLINE_SECONDS,
    MAX_PAGES,
    ProcessFailure,
    ProcessTimeout,
    bounded_process,
)

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
ALLOWED_MIME_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png"})
SCAN_SECONDS = 15.0
# The worker stops itself at DEADLINE_SECONDS; the extra ten seconds cover start-up and exit.
WORKER_SECONDS = DEADLINE_SECONDS + 10
MAX_SCANNER_REPLY = 1024
PING = 0
INSPECT_KINDS = {"application/pdf": 1, "image/jpeg": 2, "image/png": 3}
MAX_INSPECTOR_REPLY = 1024
# The inspector answers its own worker deadline first; this only bounds a stuck transport.
INSPECTOR_MARGIN_SECONDS = 10.0
_INSPECTION_SLOT = threading.BoundedSemaphore(1)

_ERRORS = {
    "DOCUMENT_TOO_LARGE": (413, "첨부파일은 20MiB 이하로 선택해 주세요."),
    "DOCUMENT_UNSAFE": (422, "지원하는 안전한 PDF·JPEG·PNG 문서를 선택해 주세요."),
    "DOCUMENT_IMAGE_UNSUPPORTED": (
        422,
        "사진·이미지에 지원하지 않는 부가 정보가 있어요. "
        "JPEG로 다시 저장하거나 앱에서 다시 선택해 주세요.",
    ),
    "DOCUMENT_TOO_COMPLEX": (
        422,
        "쪽수나 해상도가 커서 검사 시간 안에 확인하지 못했어요. "
        "필요한 쪽만 나누거나 해상도를 낮춰 첨부해 주세요.",
    ),
    "DOCUMENT_MALWARE": (422, "보안 검사에서 허용하지 않은 파일입니다."),
    "DOCUMENT_CARD_DATA": (422, "카드번호·보안코드 또는 카드 사진은 첨부할 수 없습니다."),
    "DOCUMENT_UNREADABLE": (422, "글자를 명확히 읽을 수 있는 영수증·문서를 선택해 주세요."),
    "DOCUMENT_SCAN_UNAVAILABLE": (503, "파일 보안 검사를 준비하고 있습니다."),
    "DOCUMENT_OCR_UNAVAILABLE": (503, "문서 내용 검사를 준비하고 있습니다."),
}


@dataclass(frozen=True)
class ValidatedDocument:
    content_type: str
    size_bytes: int
    sha256: str
    page_count: int


def _fail(code: str) -> None:
    status, message = _ERRORS[code]
    raise DomainError(code, message, status) from None


def _socket_path(value: str | None) -> str:
    try:
        if (
            not isinstance(value, str)
            or not value.startswith("/")
            or len(os.fsencode(value)) >= 108
            or any(ord(char) < 32 for char in value)
        ):
            raise ValueError
        info = os.lstat(value)
        if not stat.S_ISSOCK(info.st_mode):
            raise ValueError
        # A private local socket is required; no network endpoint or symlink fallback.
        if info.st_mode & stat.S_IWOTH:
            raise ValueError
        return value
    except OSError, ValueError, TypeError:
        _fail("DOCUMENT_SCAN_UNAVAILABLE")


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining


def _scanner_command(path: str, command: bytes, data: bytes | None = None) -> bytes:
    deadline = time.monotonic() + SCAN_SECONDS
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as scanner:
            scanner.settimeout(_remaining(deadline))
            scanner.connect(path)
            scanner.settimeout(_remaining(deadline))
            scanner.sendall(command)
            if data is not None:
                view = memoryview(data)
                for start in range(0, len(data), 64 * 1024):
                    chunk = view[start : start + 64 * 1024]
                    scanner.settimeout(_remaining(deadline))
                    scanner.sendall(struct.pack("!I", len(chunk)))
                    scanner.settimeout(_remaining(deadline))
                    scanner.sendall(chunk)
                scanner.settimeout(_remaining(deadline))
                scanner.sendall(b"\0\0\0\0")
            reply = bytearray()
            while b"\0" not in reply:
                scanner.settimeout(_remaining(deadline))
                chunk = scanner.recv(MAX_SCANNER_REPLY + 1 - len(reply))
                if not chunk:
                    raise ValueError
                reply.extend(chunk)
                if len(reply) > MAX_SCANNER_REPLY:
                    raise ValueError
            if reply.count(b"\0") != 1 or reply[-1] != 0:
                raise ValueError
            return bytes(reply[:-1])
    except OSError, ValueError, TimeoutError:
        _fail("DOCUMENT_SCAN_UNAVAILABLE")


def _inspector_command(
    path: str, kind: int, data: bytes = b"", *, seconds: float | None = None
) -> bytes:
    """One framed request to the isolated inspector; the reply is the worker's fixed JSON."""
    if seconds is None:
        seconds = WORKER_SECONDS + INSPECTOR_MARGIN_SECONDS
    deadline = time.monotonic() + seconds
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as inspector:
            inspector.settimeout(_remaining(deadline))
            inspector.connect(path)
            inspector.settimeout(_remaining(deadline))
            inspector.sendall(struct.pack("!BI", kind, len(data)))
            view = memoryview(data)
            for start in range(0, len(data), 64 * 1024):
                inspector.settimeout(_remaining(deadline))
                inspector.sendall(view[start : start + 64 * 1024])
            inspector.shutdown(socket.SHUT_WR)
            reply = bytearray()
            while True:
                inspector.settimeout(_remaining(deadline))
                chunk = inspector.recv(MAX_INSPECTOR_REPLY + 1 - len(reply))
                if not chunk:
                    break
                reply.extend(chunk)
                if len(reply) > MAX_INSPECTOR_REPLY:
                    raise ValueError
            if not reply:
                raise ValueError
            return bytes(reply)
    except OSError, ValueError, TimeoutError:
        raise ProcessFailure from None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def check_scanner_availability(scanner_socket: str | None) -> None:
    """Check the private daemon protocol, without sending any document or filename.

    Official protocol: docs.clamav.net/manual/Usage/ClamdProtocol.html.
    This is readiness evidence, not a substitute for scanning every submitted byte.
    """
    path = _socket_path(scanner_socket)
    if _scanner_command(path, b"zPING\0") != b"PONG":
        _fail("DOCUMENT_SCAN_UNAVAILABLE")
    version = _scanner_command(path, b"zVERSIONCOMMANDS\0")
    # The dedicated daemon runs with TZ=Etc/UTC. VERSION reports its CVD build
    # timestamp in local ctime format, so treating an arbitrary timezone as UTC
    # is unsupported. Pin the engine tested with this protocol and parser profile.
    prefix, separator, commands = version.partition(b"| COMMANDS:")
    matched = re.fullmatch(
        rb"ClamAV ([0-9]+\.[0-9]+\.[0-9]+)/([1-9][0-9]{0,9})/([^|\r\n]+)",
        prefix.strip(),
    )
    if (
        not matched
        or matched[1] != b"1.4.6"
        or not separator
        or b"INSTREAM" not in commands.split()
    ):
        _fail("DOCUMENT_SCAN_UNAVAILABLE")
    try:
        built_at = datetime.strptime(matched[3].strip().decode("ascii"), "%a %b %d %H:%M:%S %Y")
        age = _utc_now() - built_at.replace(tzinfo=UTC)
    except ValueError, UnicodeError, OverflowError:
        _fail("DOCUMENT_SCAN_UNAVAILABLE")
    if age > timedelta(days=7) or age < -timedelta(minutes=5):
        _fail("DOCUMENT_SCAN_UNAVAILABLE")


def check_inspector_availability(inspector_socket: str | None) -> None:
    """Readiness only: a ping never carries document bytes."""
    try:
        reply = _inspector_command(_socket_path(inspector_socket), PING, seconds=2.0)
    except ProcessFailure:
        _fail("DOCUMENT_SCAN_UNAVAILABLE")
    if reply != b'{"status":"ok"}':
        _fail("DOCUMENT_SCAN_UNAVAILABLE")


def _scan(data: bytes, scanner_socket: str | None) -> None:
    check_scanner_availability(scanner_socket)
    reply = _scanner_command(_socket_path(scanner_socket), b"zINSTREAM\0", data)
    if reply == b"stream: OK":
        return
    if re.fullmatch(rb"stream: [ -~]{1,900} FOUND", reply):
        _fail("DOCUMENT_MALWARE")
    _fail("DOCUMENT_SCAN_UNAVAILABLE")


def _binary_path(value: str | None) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or len(value) > 4096
        or any(ord(char) < 32 for char in value)
    ):
        _fail("DOCUMENT_OCR_UNAVAILABLE")
    # Existence/execute permission is checked inside the limited worker too.
    return value


def _validate_document(
    data: bytes,
    declared_mime: str,
    *,
    scanner_socket: str | None,
    tesseract_path: str | None = "/usr/bin/tesseract",
    pdftoppm_path: str | None = "/usr/bin/pdftoppm",
) -> ValidatedDocument:
    """Inspect the exact immutable bytes before encryption; no permissive fallback."""
    if type(data) is not bytes or not data or declared_mime not in ALLOWED_MIME_TYPES:
        _fail("DOCUMENT_UNSAFE")
    if len(data) > MAX_DOCUMENT_BYTES:
        _fail("DOCUMENT_TOO_LARGE")
    _scan(data, scanner_socket)
    tesseract = _binary_path(tesseract_path)
    pdftoppm = _binary_path(pdftoppm_path) if declared_mime == "application/pdf" else "-"
    worker = Path(__file__).with_name("_validation_worker.py").resolve()
    try:
        output = bounded_process(
            [sys.executable, "-I", "-B", str(worker), declared_mime, tesseract, pdftoppm],
            data,
            timeout=WORKER_SECONDS,
            output_limit=1024,
            new_session=True,
        )
        result = json.loads(output)
    except ProcessTimeout:
        _fail("DOCUMENT_TOO_COMPLEX")
    except ProcessFailure, ValueError, TypeError, UnicodeError:
        _fail("DOCUMENT_SCAN_UNAVAILABLE")
    if not isinstance(result, dict):
        _fail("DOCUMENT_SCAN_UNAVAILABLE")
    if set(result) == {"error"} and isinstance(result["error"], str) and result["error"] in _ERRORS:
        _fail(result["error"])
    if (
        set(result) != {"content_type", "page_count"}
        or result["content_type"] != declared_mime
        or type(result["page_count"]) is not int
        or not 1 <= result["page_count"] <= MAX_PAGES
        or declared_mime != "application/pdf"
        and result["page_count"] != 1
    ):
        _fail("DOCUMENT_SCAN_UNAVAILABLE")
    return ValidatedDocument(
        declared_mime, len(data), hashlib.sha256(data).hexdigest(), result["page_count"]
    )


def validate_document(
    data: bytes,
    declared_mime: str,
    *,
    scanner_socket: str | None,
    tesseract_path: str | None = "/usr/bin/tesseract",
    pdftoppm_path: str | None = "/usr/bin/pdftoppm",
) -> ValidatedDocument:
    """One expensive inspection per API process; busy callers fail without queuing bytes."""
    if not _INSPECTION_SLOT.acquire(blocking=False):
        _fail("DOCUMENT_SCAN_UNAVAILABLE")
    try:
        return _validate_document(
            data,
            declared_mime,
            scanner_socket=scanner_socket,
            tesseract_path=tesseract_path,
            pdftoppm_path=pdftoppm_path,
        )
    finally:
        _INSPECTION_SLOT.release()
