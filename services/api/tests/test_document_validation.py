"""Synthetic inspection tests. Fake ClamAV/OCR prove protocol boundaries, not detection."""

import hashlib
import io
import json
import os
import random
import re
import socket
import struct
import sys
import tempfile
import threading
import time
import zlib
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from sallimbook.core.errors import DomainError
from sallimbook.documents import _validation_worker as worker
from sallimbook.documents import inspector, validation

VERSION = b"ClamAV 1.4.6/28000/Sat Oct 17 00:00:00 2026 | COMMANDS: PING VERSION INSTREAM END\0"
TSV_HEADER = (
    b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
    b"left\ttop\twidth\theight\tconf\ttext\n"
)


@pytest.fixture(autouse=True)
def controlled_scanner_clock(monkeypatch):
    monkeypatch.setattr(validation, "_utc_now", lambda: datetime(2026, 10, 18, tzinfo=UTC))


def image_bytes(kind="PNG", size=(400, 200)):
    result = io.BytesIO()
    with Image.new("RGB", size, "white") as image:
        image.save(result, format=kind)
    return result.getvalue()


def pdf_bytes(change=None, pages=1, encrypted=False):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(300, 300)
    if change:
        change(writer)
    if encrypted:
        writer.encrypt("synthetic-only")
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


def assert_domain(code, action, status=None):
    with pytest.raises(DomainError) as error:
        action()
    assert error.value.code == code
    if status:
        assert error.value.status == status
    assert str(error.value) == code
    assert error.value.__cause__ is None


def assert_rejected(action, code="DOCUMENT_UNSAFE"):
    with pytest.raises(worker.Rejected) as error:
        action()
    assert error.value.code == code
    assert str(error.value) == code


def receive(connection, count):
    result = bytearray()
    while len(result) < count:
        part = connection.recv(count - len(result))
        if not part:
            raise RuntimeError("synthetic stream ended")
        result.extend(part)
    return bytes(result)


@contextmanager
def scanner(tmp_path, responses=None, *, stream_reply=b"stream: OK\0", slow=False):
    # AF_UNIX has a fixed path limit; pytest's configured TMPDIR/test names may exceed it.
    # This directory contains a synthetic socket only, never document bytes.
    with tempfile.TemporaryDirectory(prefix="sbd-", dir="/tmp") as directory:
        with _scanner(Path(directory), responses, stream_reply=stream_reply, slow=slow) as result:
            yield result


@contextmanager
def _scanner(tmp_path, responses=None, *, stream_reply=b"stream: OK\0", slow=False):
    """Private synthetic Unix daemon; it never represents actual malware scanning."""
    path = tmp_path / "scanner.sock"
    received = []
    errors = []
    stop = threading.Event()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        os.chmod(path, 0o600)
        server.listen()
        server.settimeout(0.05)

        def run():
            while not stop.is_set():
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
                with connection:
                    connection.settimeout(2)
                    try:
                        command = bytearray()
                        while not command.endswith(b"\0"):
                            command.extend(receive(connection, 1))
                        if slow:
                            stop.wait(0.2)
                            continue
                        if command == b"zINSTREAM\0":
                            data = bytearray()
                            while True:
                                length = struct.unpack("!I", receive(connection, 4))[0]
                                if length == 0:
                                    break
                                assert length <= 64 * 1024
                                data.extend(receive(connection, length))
                            received.append(bytes(data))
                            reply = stream_reply
                        else:
                            replies = responses or {
                                b"zPING\0": b"PONG\0",
                                b"zVERSIONCOMMANDS\0": VERSION,
                            }
                            reply = replies.get(bytes(command), b"UNKNOWN COMMAND\0")
                        connection.sendall(reply)
                    except (OSError, RuntimeError) as error:
                        if not stop.is_set():
                            errors.append(type(error).__name__)

        thread = threading.Thread(target=run)
        thread.start()
        try:
            yield str(path), received
        finally:
            stop.set()
            thread.join(timeout=3)
            assert not thread.is_alive()
            assert not errors


def fake_worker(monkeypatch, result=None):
    calls = []

    def run(command, data, **options):
        calls.append((command, data, options))
        return json.dumps(result or {"content_type": "image/png", "page_count": 1}).encode()

    monkeypatch.setattr(validation, "bounded_process", run)
    return calls


def test_validation_preserves_exact_bytes_checksum_and_only_four_metadata_fields(
    tmp_path, monkeypatch
):
    data = image_bytes()
    calls = fake_worker(monkeypatch)
    with scanner(tmp_path) as (path, received):
        result = validation.validate_document(data, "image/png", scanner_socket=path)
    assert result == validation.ValidatedDocument(
        "image/png", len(data), hashlib.sha256(data).hexdigest(), 1
    )
    assert received == [data]
    command, stdin, options = calls[0]
    assert stdin is data
    assert command[:3] == [sys.executable, "-I", "-B"]
    assert command[-3:] == ["image/png", "/usr/bin/tesseract", "-"]
    assert options == {
        "timeout": validation.WORKER_SECONDS,
        "output_limit": 1024,
        "new_session": True,
    }
    assert set(result.__dataclass_fields__) == {
        "content_type",
        "size_bytes",
        "sha256",
        "page_count",
    }


@pytest.mark.parametrize(
    "mime",
    ["text/html", "image/svg+xml", "image/webp", "application/zip", "image/png; charset=utf-8"],
)
def test_mime_allowlist_rejects_before_scanner_or_process(mime, monkeypatch):
    calls = fake_worker(monkeypatch)
    assert_domain(
        "DOCUMENT_UNSAFE",
        lambda: validation.validate_document(b"synthetic", mime, scanner_socket=None),
        422,
    )
    assert not calls


def test_empty_nonbytes_and_size_limit_are_enforced_before_inspection(monkeypatch):
    for value in (b"", bytearray(b"synthetic"), "synthetic"):
        assert_domain(
            "DOCUMENT_UNSAFE",
            lambda value=value: validation.validate_document(
                value, "image/png", scanner_socket=None
            ),
        )
    monkeypatch.setattr(validation, "MAX_DOCUMENT_BYTES", 5)
    assert_domain(
        "DOCUMENT_TOO_LARGE",
        lambda: validation.validate_document(b"123456", "image/png", scanner_socket=None),
        413,
    )


@pytest.mark.parametrize(
    "path",
    [None, "https://scanner.invalid", "relative.sock", "/missing/scanner.sock", "/bad\0path"],
)
def test_scanner_unconfigured_or_wrong_path_fails_closed(path):
    assert_domain(
        "DOCUMENT_SCAN_UNAVAILABLE", lambda: validation.check_scanner_availability(path), 503
    )


def test_scanner_refuses_regular_files_symlinks_and_world_writable_socket(tmp_path):
    file = tmp_path / "not-a-socket"
    file.write_text("synthetic configuration only")
    assert_domain(
        "DOCUMENT_SCAN_UNAVAILABLE", lambda: validation.check_scanner_availability(str(file))
    )
    with scanner(tmp_path) as (path, _):
        alias = Path(path).parent / "alias"
        alias.symlink_to(path)
        assert_domain(
            "DOCUMENT_SCAN_UNAVAILABLE", lambda: validation.check_scanner_availability(str(alias))
        )
        os.chmod(path, 0o666)
        assert_domain(
            "DOCUMENT_SCAN_UNAVAILABLE", lambda: validation.check_scanner_availability(path)
        )


@pytest.mark.parametrize(
    "response",
    [
        b"ClamAV 1.4.6\0",
        b"ClamAV 1.4.6/28000/date | COMMANDS: PING\0",
        b"untrusted\0",
        b"x" * 1025,
        b"PONG\0extra",
    ],
)
def test_scanner_protocol_unknown_truncated_or_overlong_version_fails_closed(tmp_path, response):
    with scanner(tmp_path, {b"zPING\0": b"PONG\0", b"zVERSIONCOMMANDS\0": response}) as (path, _):
        assert_domain(
            "DOCUMENT_SCAN_UNAVAILABLE", lambda: validation.check_scanner_availability(path), 503
        )


@pytest.mark.parametrize(
    "reply,code",
    [
        (b"stream: synthetic-signature FOUND\0", "DOCUMENT_MALWARE"),
        (b"stream: parser ERROR\0", "DOCUMENT_SCAN_UNAVAILABLE"),
        (b"INSTREAM size limit exceeded. ERROR\0", "DOCUMENT_SCAN_UNAVAILABLE"),
        (b"other: OK\0", "DOCUMENT_SCAN_UNAVAILABLE"),
    ],
)
def test_scan_verdict_is_exact_and_never_echoes_signature_or_error(
    tmp_path, monkeypatch, reply, code
):
    calls = fake_worker(monkeypatch)
    with scanner(tmp_path, stream_reply=reply) as (path, _):
        assert_domain(
            code,
            lambda: validation.validate_document(image_bytes(), "image/png", scanner_socket=path),
        )
    assert not calls


def test_scanner_timeout_is_bounded_and_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(validation, "SCAN_SECONDS", 0.05)
    with scanner(tmp_path, slow=True) as (path, _):
        assert_domain(
            "DOCUMENT_SCAN_UNAVAILABLE", lambda: validation.check_scanner_availability(path), 503
        )


@pytest.mark.parametrize(
    "result",
    [
        {"content_type": "application/pdf", "page_count": 1},
        {"content_type": "image/png", "page_count": True},
        {"content_type": "image/png", "page_count": 2},
        {"content_type": "image/png", "page_count": 1, "text": "synthetic"},
        {"error": "UNKNOWN"},
        [],
    ],
)
def test_worker_result_rejects_extra_fields_wrong_shape_mime_or_count(
    tmp_path, monkeypatch, result
):
    monkeypatch.setattr(
        validation, "bounded_process", lambda *args, **kwargs: json.dumps(result).encode()
    )
    with scanner(tmp_path) as (path, _):
        assert_domain(
            "DOCUMENT_SCAN_UNAVAILABLE",
            lambda: validation.validate_document(image_bytes(), "image/png", scanner_socket=path),
        )


@pytest.mark.parametrize(
    "code",
    [
        "DOCUMENT_UNSAFE",
        "DOCUMENT_CARD_DATA",
        "DOCUMENT_UNREADABLE",
        "DOCUMENT_OCR_UNAVAILABLE",
        "DOCUMENT_IMAGE_UNSUPPORTED",
        "DOCUMENT_TOO_COMPLEX",
    ],
)
def test_worker_returns_only_fixed_errors(tmp_path, monkeypatch, code):
    fake_worker(monkeypatch, {"error": code})
    with scanner(tmp_path) as (path, _):
        assert_domain(
            code,
            lambda: validation.validate_document(image_bytes(), "image/png", scanner_socket=path),
        )


def test_unsupported_image_is_422(tmp_path, monkeypatch):
    fake_worker(monkeypatch, {"error": "DOCUMENT_IMAGE_UNSUPPORTED"})
    with scanner(tmp_path) as (path, _):
        assert_domain(
            "DOCUMENT_IMAGE_UNSUPPORTED",
            lambda: validation.validate_document(image_bytes(), "image/png", scanner_socket=path),
            422,
        )


@pytest.mark.parametrize("mime,kind", [("image/png", "PNG"), ("image/jpeg", "JPEG")])
def test_actual_image_verify_and_load_and_declared_mime_agree(mime, kind):
    with worker._image(image_bytes(kind), mime) as image:
        assert image.size == (400, 200)
    other = "image/jpeg" if mime == "image/png" else "image/png"
    assert_rejected(lambda: worker._image(image_bytes(kind), other))
    assert_rejected(
        lambda: worker._image(image_bytes(kind) + b"synthetic trailing body", mime),
        "DOCUMENT_IMAGE_UNSUPPORTED",
    )
    assert_rejected(lambda: worker._image(image_bytes(kind)[:-5], mime))


def test_png_crc_animation_unknown_chunks_and_pixel_bombs_fail_before_load():
    data = image_bytes()
    broken = data[:29] + bytes([data[29] ^ 1]) + data[30:]
    assert_rejected(lambda: worker._png_structure(broken))
    for name in (b"acTL", b"tEXt", b"zzZZ"):
        payload = b"synthetic"
        chunk = (
            struct.pack("!I", len(payload))
            + name
            + payload
            + struct.pack("!I", zlib.crc32(name + payload))
        )
        assert_rejected(
            lambda chunk=chunk: worker._png_structure(data[:-12] + chunk + data[-12:]),
            "DOCUMENT_IMAGE_UNSUPPORTED",
        )
    for dimensions, code in (
        ((8193, 1), "DOCUMENT_TOO_COMPLEX"),
        ((4001, 4000), "DOCUMENT_TOO_COMPLEX"),
        ((0, 100), "DOCUMENT_UNSAFE"),
    ):
        header = struct.pack("!II", *dimensions) + data[24:29]
        huge = data[:16] + header + struct.pack("!I", zlib.crc32(b"IHDR" + header)) + data[33:]
        assert_rejected(lambda huge=huge: worker._png_structure(huge), code)


def test_jpeg_comments_unknown_app_and_append_containers_are_rejected():
    data = image_bytes("JPEG")
    for marker in (b"\xff\xfe", b"\xff\xe5"):
        inserted = data[:2] + marker + b"\x00\x0bsynthetic" + data[2:]
        assert_rejected(
            lambda inserted=inserted: worker._jpeg_structure(inserted), "DOCUMENT_IMAGE_UNSUPPORTED"
        )
    for marker in (b"PK\x03\x04", b"PK\x05\x06", b"\x7fELF", b"MZ\x90\x00", b"%PDF-1.7"):
        assert_rejected(lambda marker=marker: worker._polyglot(data + marker, "image/jpeg"))


def test_pdf_strict_parsing_encryption_header_and_end_are_checked():
    with worker._pdf(pdf_bytes()) as reader:
        assert len(reader.pages) == 1
    for data in (
        b"prefix" + pdf_bytes(),
        pdf_bytes() + b"trailing",
        pdf_bytes(encrypted=True),
    ):
        assert_rejected(lambda data=data: worker._pdf(data))


@pytest.mark.parametrize(
    "name",
    [
        "/JavaScript",
        "/OpenAction",
        "/AA",
        "/Launch",
        "/EmbeddedFiles",
        "/XFA",
        "/RichMedia",
        "/AcroForm",
        "/URI",
        "/AF",
    ],
)
def test_pdf_rejects_active_content_in_even_unreachable_objects(name):
    def change(writer):
        writer._add_object(DictionaryObject({NameObject(name): TextStringObject("synthetic")}))

    assert_rejected(lambda: worker._pdf(pdf_bytes(change)))


def test_pdf_active_action_name_and_escaped_names_are_not_raw_string_only_checks():
    def change(writer):
        writer._root_object[NameObject("/Synthetic")] = DictionaryObject(
            {NameObject("/S"): NameObject("/Launch")}
        )

    assert_rejected(lambda: worker._pdf(pdf_bytes(change)))
    data = pdf_bytes(
        lambda writer: writer._root_object.update({NameObject("/AA"): DictionaryObject()})
    )
    # Same-length escaped key can also be produced directly as a parsed NameObject.
    assert_rejected(lambda data=data: worker._pdf(data))


def test_pdf_depth_node_count_stream_and_page_geometry_bounds(monkeypatch):
    def deep(writer):
        value = ArrayObject([NumberObject(1)])
        for _ in range(70):
            value = ArrayObject([value])
        writer._root_object[NameObject("/Synthetic")] = value

    assert_rejected(lambda: worker._pdf(pdf_bytes(deep)))
    monkeypatch.setattr(worker, "MAX_OBJECTS", 2)
    assert_rejected(lambda: worker._pdf(pdf_bytes()))
    monkeypatch.setattr(worker, "MAX_OBJECTS", 10_000)

    def large(writer):
        stream = DecodedStreamObject()
        stream.set_data(b"x" * 1000)
        writer._add_object(stream)

    monkeypatch.setattr(worker, "MAX_STREAM", 100)
    assert_rejected(lambda: worker._pdf(pdf_bytes(large)))


def test_pdf_compressed_stream_bomb_unknown_filters_and_oversized_images_are_rejected():
    def compressed(writer):
        stream = DecodedStreamObject()
        stream.set_data(b"x" * (worker.MAX_STREAM + 1))
        writer._add_object(stream.flate_encode())

    assert_rejected(lambda: worker._pdf(pdf_bytes(compressed)))

    def image(writer):
        stream = DecodedStreamObject()
        stream.set_data(b"synthetic")
        stream.update(
            {
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(8193),
                NameObject("/Height"): NumberObject(1),
            }
        )
        writer._add_object(stream)

    assert_rejected(lambda: worker._pdf(pdf_bytes(image)), "DOCUMENT_TOO_COMPLEX")


def a4_scan_pdf(pixels, size=(1654, 2339)):
    # One A4 page holding a lossless (Flate) RGB scan at 200 dpi, as scanner apps export it.
    writer = PdfWriter()
    page = writer.add_blank_page(595, 842)
    image = DecodedStreamObject()
    image.set_data(pixels)
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(size[0]),
            NameObject("/Height"): NumberObject(size[1]),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    reference = writer._add_object(image.flate_encode())
    content = DecodedStreamObject()
    content.set_data(b"q 595 0 0 842 0 0 cm /Scan Do Q")
    page[NameObject("/Contents")] = writer._add_object(content)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/XObject"): DictionaryObject({NameObject("/Scan"): reference})}
    )
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


@pytest.mark.parametrize("scan", ["clean", "noisy"])
def test_lossless_a4_scan_pdf_is_accepted(scan):
    # 1654 x 2339 x 3 bytes decode to 11.6 MB; a noisy scan also stays over 8 MiB compressed.
    length = 1654 * 2339 * 3
    pixels = b"\xff" * length if scan == "clean" else random.Random(2026).randbytes(length)
    worker._pdf(a4_scan_pdf(pixels)).close()


def test_an_image_stream_over_the_image_bound_is_still_rejected(monkeypatch):
    length = 1654 * 2339 * 3
    monkeypatch.setattr(worker, "MAX_IMAGE_STREAM", length - 1)
    assert_rejected(lambda: worker._pdf(a4_scan_pdf(b"\xff" * length)))


def synthetic_pan():
    prefix = "4" + "12345678901234"
    for check in range(10):
        candidate = prefix + str(check)
        total = sum(
            (digit * 2 - 9 if digit * 2 > 9 else digit * 2) if n % 2 else digit
            for n, digit in enumerate(map(int, reversed(candidate)))
        )
        if total % 10 == 0:
            return candidate
    raise AssertionError


def test_card_luhn_and_labelled_values_are_rejected_without_returning_the_input():
    pan = synthetic_pan()
    for text in (
        pan,
        " ".join(pan[n : n + 4] for n in range(0, 16, 4)),
        "CVV 123",
        "CVC2 4321",
        "card security code: 321",
        "카드 보안코드 123",
        "VALID THRU 12/28",
        "VALID THRU",
    ):
        assert_rejected(lambda text=text: worker._card_text(text), "DOCUMENT_CARD_DATA")
    # A label with nothing but masked characters next to it is an ordinary receipt.
    for text in ("CVV synthetic", "CVC2", "card security code", "카드 보안코드"):
        worker._card_text(text)
    worker._card_text("합성 진료비 영수증 2026-10-17 금액 25000")
    invalid = pan[:-1] + str((int(pan[-1]) + 1) % 10)
    worker._card_text(invalid)


def tsv(words, confidence=95):
    return TSV_HEADER + b"".join(
        f"5\t1\t1\t1\t1\t{i}\t0\t0\t20\t20\t{confidence}\t{word}\n".encode()
        for i, word in enumerate(words, 1)
    )


def test_ocr_requires_real_tsv_readability_and_scans_low_confidence_card_candidates():
    assert worker._ocr_words(tsv(["SYNTHETIC", "MEDICAL", "RECEIPT"]))
    assert not worker._ocr_words(TSV_HEADER)
    assert not worker._ocr_words(tsv(["SYNTHETIC", "MEDICAL", "RECEIPT"], 20))
    assert_rejected(lambda: worker._ocr_words(tsv([synthetic_pan()], 30)), "DOCUMENT_CARD_DATA")
    grouped = [synthetic_pan()[n : n + 4] for n in range(0, 16, 4)]
    assert_rejected(lambda: worker._ocr_words(tsv(grouped, 10)), "DOCUMENT_CARD_DATA")
    for output in (b"unstructured synthetic", tsv(["synthetic"], "nan"), b"\xff"):
        assert_rejected(lambda output=output: worker._ocr_words(output), "DOCUMENT_OCR_UNAVAILABLE")


def test_ocr_all_four_orientations_are_inspected_and_no_temp_file_is_used(monkeypatch):
    calls = []

    def run(command, data, **kwargs):
        calls.append((command, data[:2], kwargs))
        return tsv(["SYNTHETIC", "MEDICAL", "RECEIPT"])

    monkeypatch.setattr(worker, "bounded_process", run)
    with Image.new("RGB", (120, 60), "white") as image:
        worker._ocr(image, "/static/tesseract", time.monotonic() + 60)
    assert len(calls) == 4
    assert all(
        command[1:3] == ["stdin", "stdout"] and prefix == b"P6" for command, prefix, _ in calls
    )
    assert all(
        set(options) == {"timeout", "output_limit"}
        and 0 < options["timeout"] <= worker.TOOL_SECONDS
        and options["output_limit"] == worker.MAX_OCR_OUTPUT
        for _, _, options in calls
    )


def test_ocr_missing_binary_language_failure_and_blank_text_never_allow(monkeypatch):
    assert_rejected(
        lambda: worker._ocr_setup("/missing/tesseract", "-", False), "DOCUMENT_OCR_UNAVAILABLE"
    )
    monkeypatch.setattr(worker, "_tool", lambda value: value)
    monkeypatch.setattr(
        worker,
        "bounded_process",
        lambda *args, **kwargs: b"List of available languages (1):\neng\n",
    )
    assert_rejected(
        lambda: worker._ocr_setup("/static/tesseract", "-", False), "DOCUMENT_OCR_UNAVAILABLE"
    )
    monkeypatch.setattr(worker, "bounded_process", lambda *args, **kwargs: TSV_HEADER)
    with Image.new("RGB", (120, 60), "white") as image:
        assert_rejected(
            lambda: worker._ocr(image, "/static/tesseract", time.monotonic() + 60),
            "DOCUMENT_UNREADABLE",
        )


def test_bounded_process_drains_concurrent_stdin_stdout_and_discards_stderr():
    script = (
        "import sys; sys.stderr.write('synthetic private detail'); "
        "sys.stdout.buffer.write(sys.stdin.buffer.read()[::-1])"
    )
    data = b"synthetic" * 20_000
    result = worker.bounded_process(
        [sys.executable, "-I", "-c", script],
        data,
        timeout=5,
        output_limit=len(data),
        new_session=True,
    )
    assert result == data[::-1]


@pytest.mark.parametrize(
    "script",
    [
        "import sys; sys.stdout.buffer.write(b'x'*10000)",
        "import time; time.sleep(10)",
        "raise RuntimeError('synthetic private text')",
    ],
)
def test_bounded_process_output_timeout_and_exception_are_redacted(script):
    with pytest.raises(worker.ProcessFailure) as error:
        worker.bounded_process(
            [sys.executable, "-I", "-c", script],
            b"",
            timeout=0.15,
            output_limit=1024,
            new_session=True,
        )
    assert str(error.value) == "DOCUMENT_PROCESS_FAILED"
    assert error.value.__cause__ is None


def test_real_isolated_worker_rejects_invalid_files_without_echoing_data():
    path = Path(worker.__file__)
    output = worker.bounded_process(
        [
            sys.executable,
            "-I",
            "-B",
            str(path),
            "application/pdf",
            "/missing/tesseract",
            "/missing/pdftoppm",
        ],
        b"synthetic private invalid PDF",
        timeout=5,
        output_limit=1024,
        new_session=True,
    )
    assert json.loads(output) == {"error": "DOCUMENT_UNSAFE"}


def test_real_isolated_worker_valid_image_with_missing_ocr_fails_closed():
    path = Path(worker.__file__)
    output = worker.bounded_process(
        [sys.executable, "-I", "-B", str(path), "image/png", "/missing/tesseract", "-"],
        image_bytes(),
        timeout=5,
        output_limit=1024,
        new_session=True,
    )
    assert json.loads(output) == {"error": "DOCUMENT_OCR_UNAVAILABLE"}


def test_expensive_inspection_has_one_slot_and_releases_it_after_failure(monkeypatch):
    called = []
    monkeypatch.setattr(validation, "_scan", lambda *args: called.append(True))
    fake_worker(monkeypatch)
    assert validation._INSPECTION_SLOT.acquire(blocking=False)
    try:
        assert_domain(
            "DOCUMENT_SCAN_UNAVAILABLE",
            lambda: validation.validate_document(
                image_bytes(), "image/png", scanner_socket="/static/scanner.sock"
            ),
        )
        assert not called
    finally:
        validation._INSPECTION_SLOT.release()
    assert_domain(
        "DOCUMENT_UNSAFE",
        lambda: validation.validate_document(b"", "image/png", scanner_socket=None),
    )
    assert (
        validation.validate_document(
            image_bytes(), "image/png", scanner_socket="/static/scanner.sock"
        ).page_count
        == 1
    )


def test_real_isolated_worker_valid_pdf_reaches_missing_ocr_instead_of_warning_failure():
    path = Path(worker.__file__)
    output = worker.bounded_process(
        [
            sys.executable,
            "-I",
            "-B",
            str(path),
            "application/pdf",
            "/missing/tesseract",
            "/missing/pdftoppm",
        ],
        pdf_bytes(),
        timeout=5,
        output_limit=1024,
        new_session=True,
    )
    assert json.loads(output) == {"error": "DOCUMENT_OCR_UNAVAILABLE"}


def test_pdf_escaped_active_key_is_decoded_before_policy_check():
    data = pdf_bytes(
        lambda writer: writer._root_object.update({NameObject("/ZZZZ"): DictionaryObject()})
    )
    # Equal-length replacement leaves cross-reference offsets valid.
    data = data.replace(b"/ZZZZ", b"/#41A")
    assert_rejected(lambda: worker._pdf(data))


def test_worker_limits_disable_core_and_plaintext_disk_writes():
    code = (
        "import importlib.util,json,resource; "
        "s=importlib.util.spec_from_file_location('w'," + repr(worker.__file__) + "); "
        "w=importlib.util.module_from_spec(s); s.loader.exec_module(w); w._limits(); "
        "print(json.dumps([resource.getrlimit(resource.RLIMIT_AS),"
        "resource.getrlimit(resource.RLIMIT_CPU),resource.getrlimit(resource.RLIMIT_FSIZE),"
        "resource.getrlimit(resource.RLIMIT_CORE)]))"
    )
    result = worker.bounded_process(
        [sys.executable, "-I", "-c", code], b"", timeout=5, output_limit=1024, new_session=True
    )
    assert json.loads(result) == [[768 * 1024 * 1024] * 2, [45, 46], [0, 0], [0, 0]]


def object_stream_pdf(active=False):
    """Synthetic PDF 1.5 with a real compressed page-tree object stream and xref stream."""
    body = bytearray(b"%PDF-1.5\n")
    offsets = {}

    def add(number, value):
        offsets[number] = len(body)
        body.extend(f"{number} 0 obj\n".encode() + value + b"\nendobj\n")

    add(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    pages = b"<< /Type /Pages /Count 1 /Kids [3 0 R] >> "
    page = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300]"
    page += b" /AA << >> >>" if active else b" >>"
    header = f"2 0 3 {len(pages)} ".encode()
    content = zlib.compress(header + pages + page)
    add(
        5,
        (
            f"<< /Type /ObjStm /N 2 /First {len(header)} /Filter /FlateDecode "
            f"/Length {len(content)} >>\nstream\n"
        ).encode()
        + content
        + b"\nendstream",
    )
    offsets[4] = len(body)
    entries = [
        (0, 0, 65535),
        (1, offsets[1], 0),
        (2, 5, 0),
        (2, 5, 1),
        (1, offsets[4], 0),
        (1, offsets[5], 0),
    ]
    content = zlib.compress(b"".join(struct.pack("!BIH", *entry) for entry in entries))
    add(
        4,
        (
            f"<< /Type /XRef /Size 6 /Root 1 0 R /W [1 4 2] /Filter /FlateDecode "
            f"/Length {len(content)} >>\nstream\n"
        ).encode()
        + content
        + b"\nendstream",
    )
    body.extend(f"startxref\n{offsets[4]}\n%%EOF\n".encode())
    return bytes(body)


def test_normal_pdf_object_stream_is_supported_under_same_object_budget():
    with worker._pdf(object_stream_pdf()) as reader:
        assert len(reader.pages) == 1
        assert set(reader.xref_objStm) == {2, 3}


def test_active_content_inside_compressed_pdf_object_stream_is_rejected():
    assert_rejected(lambda: worker._pdf(object_stream_pdf(active=True)))


@pytest.mark.parametrize(
    "marker", [b"<?php", b"<?=", b"<SCRIPT", b"<!doctype html", b"<svg", b"javascript:"]
)
def test_executable_markup_polyglots_are_rejected_inside_valid_container_metadata(marker):
    assert_rejected(lambda: worker._polyglot(image_bytes() + marker, "image/png"))


@pytest.mark.parametrize(
    "version",
    [
        b"ClamAV 1.4.3/28000/Sat Oct 17 00:00:00 2026 | COMMANDS: PING INSTREAM\0",
        b"ClamAV 1.5.0/28000/Sat Oct 17 00:00:00 2026 | COMMANDS: PING INSTREAM\0",
        b"ClamAV 1.4.6/28000/Sat Oct 10 23:59:59 2026 | COMMANDS: PING INSTREAM\0",
        b"ClamAV 1.4.6/28000/Sun Oct 18 00:05:01 2026 | COMMANDS: PING INSTREAM\0",
        b"ClamAV 1.4.6/28000/invalid-date | COMMANDS: PING INSTREAM\0",
        b"ClamAV 1.4.6/0/Sat Oct 17 00:00:00 2026 | COMMANDS: PING INSTREAM\0",
    ],
)
def test_scanner_engine_and_signature_age_fail_closed_with_controlled_utc_clock(tmp_path, version):
    with scanner(tmp_path, {b"zPING\0": b"PONG\0", b"zVERSIONCOMMANDS\0": version}) as (path, _):
        assert_domain(
            "DOCUMENT_SCAN_UNAVAILABLE", lambda: validation.check_scanner_availability(path), 503
        )


@pytest.mark.parametrize("date", [b"Sun Oct 11 00:00:00 2026", b"Sun Oct 18 00:05:00 2026"])
def test_scanner_signature_exact_age_and_small_clock_skew_boundaries(tmp_path, date):
    version = b"ClamAV 1.4.6/28000/" + date + b" | COMMANDS: PING INSTREAM\0"
    with scanner(tmp_path, {b"zPING\0": b"PONG\0", b"zVERSIONCOMMANDS\0": version}) as (path, _):
        validation.check_scanner_availability(path)


def test_bounded_process_timeout_is_distinct_and_redacted():
    with pytest.raises(worker.ProcessTimeout) as error:
        worker.bounded_process(
            [sys.executable, "-I", "-c", "import time; time.sleep(10)"],
            b"",
            timeout=0.15,
            output_limit=1024,
            new_session=True,
        )
    assert str(error.value) == "DOCUMENT_PROCESS_FAILED" and error.value.__cause__ is None
    with pytest.raises(worker.ProcessFailure) as failure:
        worker.bounded_process(
            [sys.executable, "-I", "-c", "raise SystemExit(3)"], b"", timeout=5, output_limit=1024
        )
    assert type(failure.value) is worker.ProcessFailure


def test_tool_timeout_is_too_complex_but_tool_failure_stays_unavailable(monkeypatch):
    for error, code in (
        (worker.ProcessTimeout, "DOCUMENT_TOO_COMPLEX"),
        (worker.ProcessFailure, "DOCUMENT_OCR_UNAVAILABLE"),
    ):

        def fail(*args, error=error, **kwargs):
            raise error

        monkeypatch.setattr(worker, "bounded_process", fail)
        with Image.new("RGB", (120, 60), "white") as image:
            assert_rejected(
                lambda: worker._ocr(image, "/static/tesseract", time.monotonic() + 30), code
            )
        assert_rejected(
            lambda: worker._render(pdf_bytes(), 1, "/static/pdftoppm", time.monotonic() + 30),
            code,
        )


def test_deadline_bounds_every_tool_call_and_stops_when_spent(monkeypatch):
    calls = []

    def run(command, data, **options):
        calls.append(options["timeout"])
        return tsv(["SYNTHETIC", "MEDICAL", "RECEIPT"])

    monkeypatch.setattr(worker, "bounded_process", run)
    with Image.new("RGB", (120, 60), "white") as image:
        assert_rejected(
            lambda: worker._ocr(image, "/static/tesseract", time.monotonic() - 1),
            "DOCUMENT_TOO_COMPLEX",
        )
        assert calls == []
        worker._ocr(image, "/static/tesseract", time.monotonic() + 3)
    assert len(calls) == 4 and all(0 < value <= 3 for value in calls)


def test_ocr_runs_two_orientations_at_a_time(monkeypatch):
    # User decision 2026-10-20: keep all four orientations, halve the wall time on two CPUs.
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    def run(command, data, **options):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.2)
        with lock:
            state["active"] -= 1
        return tsv(["SYNTHETIC", "MEDICAL", "RECEIPT"])

    monkeypatch.setattr(worker, "bounded_process", run)
    with Image.new("RGB", (120, 60), "white") as image:
        started = time.monotonic()
        worker._ocr(image, "/static/tesseract", time.monotonic() + 30)
    assert state["peak"] == worker.OCR_PARALLEL == 2
    assert time.monotonic() - started < 0.7


def test_ocr_card_data_in_any_parallel_orientation_is_rejected(monkeypatch):
    outputs = iter([tsv(["SYNTHETIC", "MEDICAL", "RECEIPT"])] * 3 + [tsv([synthetic_pan()], 95)])
    lock = threading.Lock()

    def run(command, data, **options):
        with lock:
            return next(outputs)

    monkeypatch.setattr(worker, "bounded_process", run)
    with Image.new("RGB", (120, 60), "white") as image:
        assert_rejected(
            lambda: worker._ocr(image, "/static/tesseract", time.monotonic() + 30),
            "DOCUMENT_CARD_DATA",
        )


def test_page_limit_is_too_complex_and_zero_pages_unsafe():
    assert_rejected(
        lambda: worker._pdf(pdf_bytes(pages=worker.MAX_PAGES + 1)), "DOCUMENT_TOO_COMPLEX"
    )
    assert_rejected(lambda: worker._pdf(pdf_bytes(pages=0)))
    with worker._pdf(pdf_bytes(pages=worker.MAX_PAGES)) as reader:
        assert len(reader.pages) == worker.MAX_PAGES


def test_pixel_limits_are_too_complex_but_empty_dimensions_unsafe():
    for dims in ((8193, 1), (4001, 4000)):
        assert_rejected(lambda d=dims: worker._size(*d), "DOCUMENT_TOO_COMPLEX")
    for dims in ((0, 100), (100, 0)):
        assert_rejected(lambda d=dims: worker._size(*d))
    data = image_bytes("JPEG")
    at = data.index(b"\xff\xc0") + 5  # marker 2 + length 2 + precision 1 → 높이·너비
    assert_rejected(
        lambda: worker._jpeg_structure(data[:at] + struct.pack("!HH", 1, 8193) + data[at + 4 :]),
        "DOCUMENT_TOO_COMPLEX",
    )


def test_worker_timeout_maps_to_too_complex_and_crash_to_scan_unavailable(tmp_path, monkeypatch):
    for error, code, status in (
        (worker.ProcessTimeout, "DOCUMENT_TOO_COMPLEX", 422),
        (worker.ProcessFailure, "DOCUMENT_SCAN_UNAVAILABLE", 503),
    ):

        def run(*args, error=error, **kwargs):
            raise error

        monkeypatch.setattr(validation, "bounded_process", run)
        with scanner(tmp_path) as (path, _):
            assert_domain(
                code,
                lambda: validation.validate_document(
                    image_bytes(), "image/png", scanner_socket=path
                ),
                status,
            )


def test_worker_budget_fits_inside_api_and_android_timeouts():
    assert worker.DEADLINE_SECONDS == validation.WORKER_SECONDS - 10
    assert validation.WORKER_SECONDS <= 90 and 1 <= worker.MAX_PAGES <= 20
    assert worker.TOOL_SECONDS <= worker.DEADLINE_SECONDS / 2


def test_worker_result_page_count_is_bounded_by_max_pages(tmp_path, monkeypatch):
    fake_worker(
        monkeypatch, {"content_type": "application/pdf", "page_count": worker.MAX_PAGES + 1}
    )
    with scanner(tmp_path) as (path, _):
        assert_domain(
            "DOCUMENT_SCAN_UNAVAILABLE",
            lambda: validation.validate_document(
                pdf_bytes(), "application/pdf", scanner_socket=path
            ),
        )


def test_client_page_limit_constants_match_worker():
    root = Path(__file__).resolve().parents[3]
    for path in (
        "apps/client/src/features/documents/model.ts",
        "apps/client/android/app/src/main/java/io/github/jihoon22lee/sallimbook/auth/NativeDocumentPolicy.kt",
    ):
        assert re.search(r"MAX_PDF_PAGES = (\d+)", (root / path).read_text())[1] == str(
            worker.MAX_PAGES
        )


@contextmanager
def remote_inspector(monkeypatch, reply=b'{"content_type":"image/png","page_count":1}'):
    calls = []

    def run(command, data, **options):
        calls.append((command, data))
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def local(*args, **kwargs):
        raise AssertionError("The API process must not start the parser worker")

    monkeypatch.setattr(inspector, "bounded_process", run)
    monkeypatch.setattr(validation, "bounded_process", local)
    with tempfile.TemporaryDirectory(prefix="sbr-", dir="/tmp") as directory:
        path = str(Path(directory) / "inspector.sock")
        server = inspector.make_server(path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield path, calls
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def test_remote_inspection_matches_the_local_result_without_a_local_worker(tmp_path, monkeypatch):
    data = image_bytes()
    with scanner(tmp_path) as (scan_path, received), remote_inspector(monkeypatch) as (path, calls):
        result = validation.validate_document(
            data, "image/png", scanner_socket=scan_path, inspector_socket=path
        )
    assert result == validation.ValidatedDocument(
        "image/png", len(data), hashlib.sha256(data).hexdigest(), 1
    )
    assert received == [data] and calls[0][1] == data
    assert calls[0][0][-3:] == ["image/png", "/usr/bin/tesseract", "-"]


@pytest.mark.parametrize(
    ("reply", "code", "status"),
    [
        (worker.ProcessTimeout(), "DOCUMENT_TOO_COMPLEX", 422),
        (worker.ProcessFailure(), "DOCUMENT_SCAN_UNAVAILABLE", 503),
        (b'{"error":"DOCUMENT_CARD_DATA"}', "DOCUMENT_CARD_DATA", 422),
        (
            b'{"content_type":"image/png","page_count":1,"text":"x"}',
            "DOCUMENT_SCAN_UNAVAILABLE",
            503,
        ),
        (b"not-json", "DOCUMENT_SCAN_UNAVAILABLE", 503),
    ],
)
def test_remote_inspection_keeps_api_side_result_validation(
    tmp_path, monkeypatch, reply, code, status
):
    with scanner(tmp_path) as (scan_path, _), remote_inspector(monkeypatch, reply) as (path, _):
        assert_domain(
            code,
            lambda: validation.validate_document(
                image_bytes(), "image/png", scanner_socket=scan_path, inspector_socket=path
            ),
            status,
        )


def test_missing_world_writable_or_silent_inspector_fails_closed(tmp_path, monkeypatch):
    def local(*args, **kwargs):
        raise AssertionError("The API process must not start the parser worker")

    data = image_bytes()
    monkeypatch.setattr(validation, "bounded_process", local)
    # The silent peer accepts nothing; a short transport deadline keeps the test fast.
    monkeypatch.setattr(validation, "WORKER_SECONDS", 0.2)
    monkeypatch.setattr(validation, "INSPECTOR_MARGIN_SECONDS", 0.2)
    with (
        tempfile.TemporaryDirectory(prefix="sbs-", dir="/tmp") as directory,
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as silent,
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as shared,
        scanner(tmp_path) as (scan_path, _),
    ):
        silent_path, shared_path = Path(directory) / "silent.sock", Path(directory) / "open.sock"
        silent.bind(str(silent_path))
        silent.listen()
        shared.bind(str(shared_path))
        os.chmod(shared_path, 0o666)
        for path in (Path(directory) / "missing.sock", shared_path, silent_path):
            assert_domain(
                "DOCUMENT_SCAN_UNAVAILABLE",
                lambda p=str(path): validation.validate_document(
                    data, "image/png", scanner_socket=scan_path, inspector_socket=p
                ),
                503,
            )
