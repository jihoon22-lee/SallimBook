"""Private isolated parser/OCR worker. stdin bytes; fixed, bounded JSON status only.

This module's imports are standard-library only. The API may import bounded_process;
Pillow/pypdf are imported exclusively inside the limited worker's parse functions.
No user filename, URL, arbitrary command, temporary file, or document text is emitted.
"""

import csv
import io
import json
import logging
import math
import os
import re
import resource
import selectors
import signal
import struct
import subprocess
import sys
import threading
import time
import unicodedata
import warnings
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_DIMENSION = 8192
# Measured 2026-10-20 with parallel OCR: s = 9.04 s/page, floor((90 - 10) / (1.5 × 9.04)) = 5.
# Clients pin the same value.
MAX_PAGES = 5
# The API waits WORKER_SECONDS = DEADLINE_SECONDS + 10 for the whole worker.
DEADLINE_SECONDS = 80
MAX_OBJECTS = 10_000
MAX_DEPTH = 64
MAX_NODES = 100_000
MAX_STREAM = 8 * 1024 * 1024
MAX_DECOMPRESSED = 64 * 1024 * 1024
MAX_OCR_OUTPUT = 2 * 1024 * 1024
# Per render/OCR tool call; every call is further bounded by the worker deadline.
TOOL_SECONDS = 10
# Unbroken 13+ digit OCR words below this confidence are not card candidates (user decision
# 2026-10-20: sideways-text blobs score 4–22, upright card numbers 95+).
OCR_BLOB_CONFIDENCE = 30
# Orientations OCRed at once (user decision 2026-10-20: same coverage, about half the time).
OCR_PARALLEL = 2
PROCESS_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "OMP_THREAD_LIMIT": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
}


class ProcessFailure(Exception):
    def __init__(self):
        super().__init__("DOCUMENT_PROCESS_FAILED")


class ProcessTimeout(ProcessFailure):
    """The process outlived its time budget; other process failures stay ProcessFailure."""


class Rejected(Exception):
    def __init__(self, code: str = "DOCUMENT_UNSAFE"):
        super().__init__(code)
        self.code = code


def bounded_process(
    command: list[str],
    data: bytes,
    *,
    timeout: float,
    output_limit: int,
    new_session: bool = False,
) -> bytes:
    """Drain stdout while writing stdin; never retain unbounded output or stderr."""
    process = None
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=PROCESS_ENV,
            cwd="/",
            close_fds=True,
            start_new_session=new_session,
        )
        deadline = time.monotonic() + timeout
        output = bytearray()
        sent = 0
        view = memoryview(data)
        with selectors.DefaultSelector() as poll:
            os.set_blocking(process.stdout.fileno(), False)
            os.set_blocking(process.stdin.fileno(), False)
            poll.register(process.stdout, selectors.EVENT_READ)
            if data:
                poll.register(process.stdin, selectors.EVENT_WRITE)
            else:
                process.stdin.close()
            while poll.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProcessTimeout
                for key, event in poll.select(min(remaining, 0.25)):
                    if event & selectors.EVENT_WRITE:
                        try:
                            sent += os.write(key.fd, view[sent : sent + 64 * 1024])
                        except BrokenPipeError:
                            raise ProcessFailure from None
                        if sent == len(data):
                            poll.unregister(key.fileobj)
                            key.fileobj.close()
                    else:
                        chunk = os.read(key.fd, min(64 * 1024, output_limit + 1 - len(output)))
                        if not chunk:
                            poll.unregister(key.fileobj)
                            key.fileobj.close()
                        else:
                            output.extend(chunk)
                            if len(output) > output_limit:
                                raise ProcessFailure
            if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
                raise ProcessFailure
            return bytes(output)
    except ProcessTimeout, subprocess.TimeoutExpired:
        raise ProcessTimeout from None
    except OSError, ValueError, subprocess.SubprocessError, ProcessFailure:
        raise ProcessFailure from None
    finally:
        if process is not None:
            if new_session:
                # Also kill grandchildren if a compromised worker exited before its tools.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.kill()
            process.wait()
            for stream in (process.stdin, process.stdout):
                if stream is not None and not stream.closed:
                    stream.close()


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (45, 46))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    logging.disable(logging.CRITICAL)
    warnings.simplefilter("error")


def _size(width: int, height: int) -> None:
    if width < 1 or height < 1:
        raise Rejected
    # Legitimate but beyond the inspection budget: a retry cannot help, so say so.
    if width > MAX_DIMENSION or height > MAX_DIMENSION or width * height > MAX_PIXELS:
        raise Rejected("DOCUMENT_TOO_COMPLEX")


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Rejected("DOCUMENT_TOO_COMPLEX")
    return remaining


# Digit groups joined by one space or a dash (optionally spaced); dots, commas, colons and
# tildes end a run, so dates such as 2026.02.22 2026.03.01 never form one candidate.
# _card_text collapses every whitespace run (tabs, repeated spaces, line breaks) first.
_PAN_SEPARATOR = r"(?: ?[-–—] ?| )"
_PAN_RUN = re.compile(r"(?<!\d)\d+(?:" + _PAN_SEPARATOR + r"\d+)*")
_PAN_LAYOUTS = frozenset(
    {(length,) for length in range(13, 20)}
    | {(4, 4, 4, 4)}
    | {(4, 4, 4, 4, tail) for tail in (1, 2, 3)}
    | {(4, 6, 5), (4, 6, 4)}
)
# OCR and PDF text can lose any separators of a printed grid (4111 1111 11111111,
# 41111111 11111111, 6212 3456 7890 1234569). A window whose group boundaries all fall on
# a printed card grid is still a candidate: (boundaries allowed, total digits).
_PAN_GRIDS = (
    (frozenset({4, 8, 12, 16}), frozenset({16, 17, 18, 19})),
    (frozenset({4, 10}), frozenset({14, 15})),
)
_PAN_DATE = re.compile(r"(?:19|20)\d\d(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])")


def _on_grid(lengths: tuple[int, ...]) -> bool:
    boundaries = set()
    total = 0
    for length in lengths[:-1]:
        total += length
        boundaries.add(total)
    total += lengths[-1]
    return any(total in totals and boundaries <= allowed for allowed, totals in _PAN_GRIDS)


def _pan_candidates(text: str):
    """Card-like digit strings (13–19 digits) from NFKC text, in linear time."""
    for run in _PAN_RUN.finditer(text):
        groups = re.findall(r"\d+", run[0])
        lengths = [len(group) for group in groups]
        for start in range(len(groups)):
            # Every grid starts with a group of at least four digits, which also keeps
            # this loop short on long runs of one- to three-digit groups.
            if lengths[start] < 4:
                continue
            total = 0
            for end in range(start, len(groups)):
                total += lengths[end]
                if total > 19:
                    break
                window = tuple(lengths[start : end + 1])
                if window in _PAN_LAYOUTS:
                    yield "".join(groups[start : end + 1])
                elif len(window) > 1 and _on_grid(window):
                    digits = "".join(groups[start : end + 1])
                    # No card number starts with a 19xx/20xx date; date pairs such as
                    # 20260222 20260301 on a receipt fit the 8-8 grid otherwise.
                    if not _PAN_DATE.match(digits):
                        yield digits
        # A maximal stretch of single digits (spaced-out OCR) is one candidate as a whole.
        opened = None
        for index, length in enumerate([*lengths, 0]):
            if length == 1:
                opened = index if opened is None else opened
                continue
            if opened is not None and 13 <= index - opened <= 19:
                yield "".join(groups[opened:index])
            opened = None


# Receipts print masked card numbers and the bare labels of card fields; neither is card data.
# A security code or an expiry date is, so a label counts when the first number after it is
# such a value, and a masked number only with an expiry date right after it. The gap before
# a value holds no digits or masking characters, so "CVC *** 1234원" is not a code. A full
# date (2026.10.31) is not an expiry, so coupon and point expiry lines pass.
_VALUE_GAP = r"[^\d*•●#]{0,24}"
_EXPIRY_DATE = (
    r"(?<!\d)(?<!\d[./-])(?<!\d [./-])(?<!\d[./-] )(?<!\d [./-] )"
    r"(?:(?:0[1-9]|1[0-2]) ?[./-] ?(?:20\d\d|\d\d)|20\d\d ?[./-] ?(?:0[1-9]|1[0-2]))"
    r"(?!\d)(?! ?[./-] ?\d)"
)
_SECURITY_CODE = re.compile(
    r"(?i)(?:(?<![a-z])(?:cvc|cvv|cvn|csc|cid)2?(?![a-z])|"
    r"card ?(?:security|verification) ?(?:code|number|value)|security ?code|"
    r"카드 ?(?:보안|인증) ?(?:코드|번호)|보안 ?(?:코드|번호))"
    + _VALUE_GAP
    + r"(?<!\d)\d{3,4}(?!\d)"
)
_EXPIRY = re.compile(
    r"(?i)(?:valid ?(?:thru|through)|(?<![a-z])exp(?:iry|iration|ires)?(?![a-z])|"
    r"유효 ?기간|만료)" + _VALUE_GAP + _EXPIRY_DATE
)
_MASK = re.compile(r"(?i)[*x•●#]")
_MASKED_NUMBER_DATE = re.compile(
    r"(?i)(?<![\d*x•●#])((?:[\d*x•●#]{4}[ -]?){3}[\d*x•●#]{1,7}|[\d*x•●#]{13,19})"
    r"[^\d*x•●#]{0,3}" + _EXPIRY_DATE
)


def _card_text(value: str) -> None:
    # NFKC makes full-width digits and punctuation equivalent. Do not log candidates.
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKC", value)
        if char.isspace() or unicodedata.category(char) not in {"Cc", "Cf"}
    )
    if len(normalized) > MAX_OCR_OUTPUT:
        raise Rejected
    normalized = re.sub(r"\s+", " ", normalized)
    if (
        _SECURITY_CODE.search(normalized)
        or _EXPIRY.search(normalized)
        or any(_MASK.search(found[1]) for found in _MASKED_NUMBER_DATE.finditer(normalized))
    ):
        raise Rejected("DOCUMENT_CARD_DATA")
    for candidate in _pan_candidates(normalized):
        digits = [int(char) for char in candidate]
        if len(set(digits)) == 1:
            continue
        total = 0
        for index, digit in enumerate(reversed(digits)):
            value = digit * 2 if index % 2 else digit
            total += value - 9 if value > 9 else value
        if total % 10 == 0:
            raise Rejected("DOCUMENT_CARD_DATA")


# Each scanned range widens by the longest marker minus one so a marker that continues into
# attacker-chosen bytes next to an excluded range (e.g. a PNG CRC) is still found.
_MARKER_OVERLAP = 13
# ZIP/JAR readers search the last 64 KiB plus the 22-byte record for the end of the central
# directory, so that tail is always scanned for it, excluded ranges or not.
_ZIP_TAIL = 65_557


def _merge(ranges: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _jpeg_ranges(data: bytes) -> tuple[tuple[int, int], ...] | None:
    """Everything except entropy-coded scan data; None when the layout cannot be followed."""
    if not data.startswith(b"\xff\xd8"):
        return None
    ranges: list[tuple[int, int]] = []
    opened = 0
    position = 2
    while position < len(data):
        if data[position] != 0xFF:
            return None
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            return None
        marker = data[position]
        position += 1
        if marker == 0xD9:
            ranges.append((opened, len(data)))
            return _merge(ranges)
        if marker in {0x00, 0x01} or 0xD0 <= marker <= 0xD8 or position + 2 > len(data):
            return None
        length = struct.unpack("!H", data[position : position + 2])[0]
        if length < 2 or position + length > len(data):
            return None
        position += length
        if marker == 0xDA:
            ranges.append((opened, position))
            while True:
                if position + 1 >= len(data):
                    return None
                if data[position] != 0xFF:
                    position += 1
                    continue
                following = data[position + 1]
                if following == 0x00 or 0xD0 <= following <= 0xD7:
                    position += 2
                elif following == 0xFF:
                    position += 1
                else:
                    opened = position
                    break
    return None


def _png_ranges(data: bytes) -> tuple[tuple[int, int], ...] | None:
    """Everything except IDAT payloads; None when the chunk layout cannot be followed."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    ranges: list[tuple[int, int]] = []
    opened = 0
    position = 8
    while position < len(data):
        if position + 12 > len(data):
            return None
        length = struct.unpack("!I", data[position : position + 4])[0]
        name = data[position + 4 : position + 8]
        end = position + 12 + length
        if end > len(data):
            return None
        if name == b"IDAT":
            ranges.append((opened, position + 8))
            opened = end - 4
        position = end
        if name == b"IEND":
            ranges.append((opened, len(data)))
            return _merge(ranges)
    return None


_STREAM_KEYWORD = re.compile(rb"stream *(?:\r\n|\r|\n)")
_MAX_STREAM_CANDIDATES = 64


def _pdf_ranges(data: bytes, reader) -> tuple[tuple[int, int], ...] | None:
    """Everything except raw stream data located after a parsed object's `stream` keyword."""
    from pypdf.generic import IndirectObject, StreamObject

    located = sorted(
        (offset, generation, object_id)
        for generation, rows in reader.xref.items()
        for object_id, offset in rows.items()
        if object_id != 0 and generation != 65535 and object_id not in reader.xref_objStm
    )
    excluded: list[tuple[int, int]] = []
    # Search windows end at the next object's offset, so total work stays linear in file size.
    for index, (offset, generation, object_id) in enumerate(located):
        window_end = located[index + 1][0] if index + 1 < len(located) else len(data)
        value = IndirectObject(object_id, generation, reader).get_object()
        if not isinstance(value, StreamObject) or not value._data:
            continue
        raw = value._data
        for candidates, match in enumerate(_STREAM_KEYWORD.finditer(data, offset, window_end), 1):
            if candidates > _MAX_STREAM_CANDIDATES:
                return None
            if match.end() + len(raw) <= window_end and data.startswith(raw, match.end()):
                excluded.append((match.end(), match.end() + len(raw)))
                break
        else:
            return None
    ranges: list[tuple[int, int]] = []
    opened = 0
    for start, end in sorted(excluded):
        if start < opened:
            return None
        ranges.append((opened, start))
        opened = end
    ranges.append((opened, len(data)))
    return _merge([(start, end) for start, end in ranges if start < end] or [(0, 0)])


def _scannable_ranges(data: bytes, mime: str, reader=None) -> tuple[tuple[int, int], ...]:
    """Sorted half-open ranges that the marker scan covers; the whole file if unparseable."""
    ranges = None
    if mime == "image/jpeg":
        ranges = _jpeg_ranges(data)
    elif mime == "image/png":
        ranges = _png_ranges(data)
    elif mime == "application/pdf" and reader is not None:
        ranges = _pdf_ranges(data, reader)
    return ranges if ranges is not None else ((0, len(data)),)


def _polyglot(data: bytes, mime: str, ranges: tuple[tuple[int, int], ...] | None = None) -> None:
    # Reject append/prepend containers and executable signatures. Structural parsing
    # below additionally requires exact format termination and known container chunks.
    # Compressed image/stream data is excluded: random bytes there are not interpretable.
    if b"PK\x05\x06" in data[-_ZIP_TAIL:]:
        raise Rejected
    for start, end in _scannable_ranges(data, mime) if ranges is None else ranges:
        part = data[max(0, start - _MARKER_OVERLAP) : min(len(data), end + _MARKER_OVERLAP)]
        if any(
            marker in part for marker in (b"PK\x03\x04", b"PK\x05\x06", b"\x7fELF", b"MZ\x90\x00")
        ):
            raise Rejected
        if mime != "application/pdf" and b"%PDF-" in part:
            raise Rejected
        # HTML/PHP interpreters can ignore an image/PDF prefix. Raw executable markup
        # is excluded even when stored in otherwise legal container metadata.
        lower = part.lower()
        if any(
            marker in lower
            for marker in (
                b"<?php",
                b"<?=",
                b"<script",
                b"<!doctype html",
                b"<html",
                b"<svg",
                b"<iframe",
                b"<object",
                b"javascript:",
            )
        ):
            raise Rejected


def _png_structure(data: bytes) -> None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise Rejected
    position = 8
    seen = []
    allowed = {
        b"IHDR",
        b"PLTE",
        b"IDAT",
        b"IEND",
        b"tRNS",
        b"gAMA",
        b"cHRM",
        b"sRGB",
        b"pHYs",
        b"sBIT",
        b"bKGD",
        b"tIME",
        b"eXIf",
        b"iCCP",
    }
    while position < len(data):
        if position + 12 > len(data) or len(seen) > 10_000:
            raise Rejected
        length = struct.unpack("!I", data[position : position + 4])[0]
        name = data[position + 4 : position + 8]
        end = position + 12 + length
        if end > len(data):
            raise Rejected
        body = data[position + 8 : end - 4]
        expected = struct.unpack("!I", data[end - 4 : end])[0]
        if zlib.crc32(name + body) & 0xFFFFFFFF != expected:
            raise Rejected
        # Well-formed but outside this profile (text, animation, editor chunks).
        if name not in allowed:
            raise Rejected("DOCUMENT_IMAGE_UNSUPPORTED")
        if not seen and (name != b"IHDR" or length != 13):
            raise Rejected
        if name != b"IDAT" and name in seen:
            raise Rejected
        if name == b"IHDR":
            _size(*struct.unpack("!II", body[:8]))
        seen.append(name)
        if name == b"IEND":
            if length != 0 or b"IDAT" not in seen:
                raise Rejected
            if end != len(data):
                raise Rejected("DOCUMENT_IMAGE_UNSUPPORTED")
            return
        position = end
    raise Rejected


_JPEG_SOF = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def _jpeg_structure(data: bytes) -> None:
    # Broken structure is DOCUMENT_UNSAFE; well-formed segments or trailers outside this
    # profile (XMP, MPF, comments, camera trailers after EOI) are DOCUMENT_IMAGE_UNSUPPORTED.
    if not data.startswith(b"\xff\xd8"):
        raise Rejected
    position = 2
    scans = 0
    while position < len(data):
        if data[position] != 0xFF:
            raise Rejected
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            raise Rejected
        marker = data[position]
        position += 1
        if marker == 0xD9:
            if scans == 0:
                raise Rejected
            if position != len(data):
                raise Rejected("DOCUMENT_IMAGE_UNSUPPORTED")
            return
        if marker in {0x00, 0xD8, 0x01} or 0xD0 <= marker <= 0xD7:
            raise Rejected
        if position + 2 > len(data):
            raise Rejected
        length = struct.unpack("!H", data[position : position + 2])[0]
        if length < 2 or position + length > len(data):
            raise Rejected
        payload = data[position + 2 : position + length]
        if marker in _JPEG_SOF:
            if len(payload) < 5:
                raise Rejected
            # SOFn payload: precision, height, width.
            height, width = struct.unpack("!HH", payload[1:5])
            _size(width, height)
        if 0xE0 <= marker <= 0xEF:
            prefixes = {
                0xE0: (b"JFIF\0", b"JFXX\0"),
                0xE1: (b"Exif\0\0",),
                0xE2: (b"ICC_PROFILE\0",),
                0xEE: (b"Adobe",),
            }
            if marker not in prefixes or not payload.startswith(prefixes[marker]):
                raise Rejected("DOCUMENT_IMAGE_UNSUPPORTED")
        elif marker == 0xFE:
            # Uninterpreted comments are not part of this readable-document profile.
            raise Rejected("DOCUMENT_IMAGE_UNSUPPORTED")
        position += length
        if marker == 0xDA:
            scans += 1
            if scans > 100:
                raise Rejected
            while position < len(data):
                if data[position] != 0xFF:
                    position += 1
                    continue
                if position + 1 >= len(data):
                    raise Rejected
                next_marker = data[position + 1]
                if next_marker == 0x00 or 0xD0 <= next_marker <= 0xD7:
                    position += 2
                elif next_marker == 0xFF:
                    position += 1
                else:
                    break
    raise Rejected


def _pillow():
    from PIL import Image, ImageFile, PngImagePlugin

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    PngImagePlugin.MAX_TEXT_CHUNK = 64 * 1024
    PngImagePlugin.MAX_TEXT_MEMORY = 256 * 1024
    return Image


def _image(data: bytes, mime: str):
    Image = _pillow()
    if mime == "image/png":
        _png_structure(data)
        expected = "PNG"
    elif mime == "image/jpeg":
        _jpeg_structure(data)
        expected = "JPEG"
    else:
        raise Rejected
    # Structure first so camera trailers get the unsupported-image answer, then markers.
    _polyglot(data, mime)
    with Image.open(io.BytesIO(data), formats=[expected]) as image:
        _size(*image.size)
        if image.format != expected or getattr(image, "n_frames", 1) != 1:
            raise Rejected
        image.verify()
    # verify() invalidates the decoder; a separate load actually decodes every pixel.
    with Image.open(io.BytesIO(data), formats=[expected]) as image:
        image.load()
        if "exif" in image.info:
            _card_text(bytes(image.info["exif"]).decode("utf-8", errors="ignore"))
        # Flatten transparent pixels for OCR; the original file remains untouched.
        if "A" in image.getbands() or "transparency" in image.info:
            result = Image.new("RGB", image.size, "white")
            rgba = image.convert("RGBA")
            result.paste(rgba, mask=rgba.getchannel("A"))
            rgba.close()
            return result
        return image.convert("RGB")


def _tool(path: str) -> str:
    if not path.startswith("/") or not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise Rejected("DOCUMENT_OCR_UNAVAILABLE")
    return path


def _ocr_setup(tesseract: str, pdftoppm: str, pdf: bool) -> None:
    _tool(tesseract)
    if pdf:
        _tool(pdftoppm)
    try:
        output = bounded_process([tesseract, "--list-langs"], b"", timeout=5, output_limit=8192)
    except ProcessFailure:
        raise Rejected("DOCUMENT_OCR_UNAVAILABLE") from None
    languages = {line.strip() for line in output.splitlines()}
    if not {b"eng", b"kor"}.issubset(languages):
        raise Rejected("DOCUMENT_OCR_UNAVAILABLE")


def _ocr_words(output: bytes) -> bool:
    try:
        # Tesseract writes words verbatim: a quote is text, never a CSV quoting character.
        table = csv.DictReader(
            io.StringIO(output.decode("utf-8", errors="strict")),
            delimiter="\t",
            quoting=csv.QUOTE_NONE,
        )
        expected = [
            "level",
            "page_num",
            "block_num",
            "par_num",
            "line_num",
            "word_num",
            "left",
            "top",
            "width",
            "height",
            "conf",
            "text",
        ]
        if table.fieldnames != expected:
            raise ValueError
        words = []
        confidence = []
        for index, row in enumerate(table):
            if index > 50_000 or None in row or any(value is None for value in row.values()):
                raise ValueError
            if row["level"] != "5":
                continue
            word = row["text"].strip()
            if word:
                score = float(row["conf"])
                if not math.isfinite(score) or not -1 <= score <= 100:
                    raise ValueError
                # Sideways text reads as long low-confidence digit blobs that pass Luhn by
                # chance; such a blob ends the digit run instead of becoming a candidate.
                # Grouped numbers (4-4-4-4) still count at any confidence.
                blob = re.search(r"\d{13,}", unicodedata.normalize("NFKC", word))
                words.append("|" if blob and score < OCR_BLOB_CONFIDENCE else word)
                if any(char.isalnum() for char in word):
                    confidence.append(score)
        _card_text(" ".join(words))
        return (
            len(confidence) >= 3
            and sum(confidence) / len(confidence) >= 65
            and sum(score < 40 for score in confidence) <= len(confidence) * 0.2
        )
    except ValueError, KeyError, UnicodeError, csv.Error:
        raise Rejected("DOCUMENT_OCR_UNAVAILABLE") from None


def _ocr_command(tesseract: str) -> list[str]:
    return [tesseract, "stdin", "stdout", "-l", "eng+kor", "--psm", "11", "--dpi", "200", "tsv"]


def _ocr(image, tesseract: str, deadline: float) -> None:
    # Check every right-angle orientation, including low-confidence recognized words.
    # OCR still cannot prove absence of all visual card data; unreadable input is refused.
    _remaining(deadline)
    encode = threading.Lock()

    def recognize(angle: int) -> bytes:
        # One rotation is serialized at a time so at most OCR_PARALLEL PPM copies are alive.
        with encode:
            rotated = image if angle == 0 else image.rotate(angle, expand=True)
            try:
                buffer = io.BytesIO()
                rotated.save(buffer, format="PPM")
                data = buffer.getvalue()
                buffer.close()
            finally:
                if rotated is not image:
                    rotated.close()
        try:
            return bounded_process(
                _ocr_command(tesseract),
                data,
                timeout=min(TOOL_SECONDS, _remaining(deadline)),
                output_limit=MAX_OCR_OUTPUT,
            )
        except ProcessTimeout:
            raise Rejected("DOCUMENT_TOO_COMPLEX") from None
        except ProcessFailure:
            raise Rejected("DOCUMENT_OCR_UNAVAILABLE") from None

    pool = ThreadPoolExecutor(max_workers=OCR_PARALLEL)
    try:
        futures = [pool.submit(recognize, angle) for angle in (0, 90, 180, 270)]
        outputs = [future.result() for future in futures]
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    readable = False
    for output in outputs:
        readable = _ocr_words(output) or readable
    if not readable:
        raise Rejected("DOCUMENT_UNREADABLE")


_ACTIVE_KEYS = {
    "/JavaScript",
    "/JS",
    "/OpenAction",
    "/AA",
    "/Launch",
    "/EmbeddedFiles",
    "/EmbeddedFile",
    "/EF",
    "/AF",
    "/XFA",
    "/RichMedia",
    "/RichMediaContent",
    "/RichMediaSettings",
    "/Movie",
    "/Sound",
    "/Rendition",
    "/GoToR",
    "/GoToE",
    "/SubmitForm",
    "/ImportData",
    "/URI",
    "/AcroForm",
    "/Collection",
    "/3D",
    "/3DD",
    "/3DA",
    "/FileAttachment",
}
_ACTIVE_NAMES = _ACTIVE_KEYS | {"/Action", "/Filespec", "/PS", "/PostScript", "/Crypt"}
_FILTERS = {
    "/FlateDecode",
    "/ASCIIHexDecode",
    "/ASCII85Decode",
    "/DCTDecode",
    "/RunLengthDecode",
    "/LZWDecode",
    "/CCITTFaxDecode",
}


def _pdf_date(value: str) -> bool:
    # ISO 32000-1:2008, 7.9.4 and Table 317: only /Info date fields have this type.
    # https://opensource.adobe.com/dc-acrobat-sdk-docs/standards/pdfstandards/pdf/PDF32000_2008.pdf
    match = re.fullmatch(
        r"D:([0-9]{4}(?:[0-9]{2}){0,5})"
        r"(?:Z|[+-]([0-9]{2})(?:'(?:([0-9]{2})'?)?)?)?",
        value,
    )
    if match is None:
        return False
    digits, offset_hour, offset_minute = match.groups()
    fields = [int(digits[:4])]
    fields.extend(int(digits[index : index + 2]) for index in range(4, len(digits), 2))
    defaults = [1, 1, 0, 0, 0]
    fields.extend(defaults[len(fields) - 1 :])
    try:
        datetime(*fields)
    except ValueError:
        return False
    return (offset_hour is None or int(offset_hour) <= 23) and (
        offset_minute is None or int(offset_minute) <= 59
    )


def _pdf(data: bytes):
    from pypdf import apply_configuration
    from pypdf.errors import PyPdfError

    try:
        with apply_configuration(
            maximum_declared_stream_length=MAX_STREAM,
            array_based_stream_maximum_output_length=MAX_STREAM,
            array_maximum_element_count=MAX_OBJECTS,
            dictionary_maximum_element_count=MAX_OBJECTS,
            jbig2_maximum_output_length=MAX_STREAM,
            jbig2dec_binary=None,
            lzw_maximum_output_length=MAX_STREAM,
            run_length_maximum_output_length=MAX_STREAM,
            zlib_maximum_output_length=MAX_STREAM,
            zlib_maximum_recovery_input_length=0,
            brotli_maximum_output_length=MAX_STREAM,
            flate_maximum_columns=MAX_DIMENSION,
            flate_maximum_row_length=1024 * 1024,
            image_maximum_buffer_size=MAX_STREAM,
            stream_filters_maximum_length=4,
            stream_decoding_work_maximum_length=MAX_DECOMPRESSED,
            stream_parsing_work_maximum_count=MAX_NODES,
            xmp_maximum_input_length=MAX_STREAM,
            xmp_maximum_element_count=MAX_OBJECTS,
            outline_maximum_entries=MAX_OBJECTS,
            outline_maximum_depth=MAX_DEPTH,
            page_tree_maximum_entries=MAX_OBJECTS,
            page_tree_maximum_depth=MAX_DEPTH,
            form_fields_maximum_entries=MAX_OBJECTS,
            form_fields_maximum_depth=MAX_DEPTH,
            xform_maximum_invocations_per_extraction=1000,
        ):
            reader = _read_pdf(data)
            try:
                # Stream locations are known only after the strict parse.
                _polyglot(
                    data, "application/pdf", _scannable_ranges(data, "application/pdf", reader)
                )
            except BaseException:
                reader.close()
                raise
            return reader
    except PyPdfError, ValueError, TypeError, OSError, RecursionError:
        raise Rejected from None


def _read_pdf(data: bytes):
    from pypdf import PdfReader
    from pypdf.generic import (
        ArrayObject,
        ByteStringObject,
        DictionaryObject,
        IndirectObject,
        NameObject,
        StreamObject,
        TextStringObject,
    )

    if not re.match(rb"%PDF-(?:1\.[0-7]|2\.0)(?:\r\n|\r|\n)", data):
        raise Rejected
    if not re.search(rb"%%EOF[\x00\x09\x0a\x0c\x0d\x20]*\Z", data):
        raise Rejected
    # Incremental updates and embedded second documents are outside this profile.
    if data.count(b"%PDF-") != 1 or data.count(b"%%EOF") != 1:
        raise Rejected
    reader = PdfReader(io.BytesIO(data), strict=True, root_object_recovery_limit=MAX_OBJECTS)
    if reader.is_encrypted or "/Encrypt" in reader.trailer:
        raise Rejected
    references = [
        (generation, object_id)
        for generation, rows in reader.xref.items()
        for object_id in rows
        if object_id != 0 and generation != 65535
    ]
    references.extend((0, object_id) for object_id in reader.xref_objStm)
    if len(references) > MAX_OBJECTS or int(reader.trailer.get("/Size", 0)) > MAX_OBJECTS + 1:
        raise Rejected
    visited_refs = set()
    traversed_refs = set()
    visited_objects = set()
    nodes = 0
    decompressed = 0

    def visit(value, depth=0, *, context="ordinary", inventory=False):
        nonlocal nodes, decompressed
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise Rejected
        if isinstance(value, IndirectObject):
            reference = (value.generation, value.idnum)
            # Sweep unreachable objects without retyping an already visited
            # /Info date as an untyped standalone string.
            if inventory and reference in traversed_refs:
                return
            identity = (*reference, context)
            if identity in visited_refs:
                return
            visited_refs.add(identity)
            traversed_refs.add(reference)
            if len(visited_refs) > MAX_OBJECTS:
                raise Rejected
            visit(value.get_object(), depth + 1, context=context)
            return
        if isinstance(value, (DictionaryObject, ArrayObject)):
            identity = (id(value), context)
            if identity in visited_objects:
                return
            visited_objects.add(identity)
        if isinstance(value, DictionaryObject):
            if len(value) > MAX_OBJECTS or _ACTIVE_KEYS.intersection(value):
                raise Rejected
            if isinstance(value, StreamObject):
                filters = value.get("/Filter", [])
                if isinstance(filters, IndirectObject):
                    filters = filters.get_object()
                if isinstance(filters, NameObject):
                    filters = [filters]
                if (
                    not isinstance(filters, (ArrayObject, list))
                    or len(filters) > 4
                    or any(item not in _FILTERS for item in filters)
                ):
                    raise Rejected
                if value.get("/Subtype") == "/Image":
                    _size(int(value.get("/Width", 0)), int(value.get("/Height", 0)))
                decoded = value.get_data()
                decompressed += len(decoded)
                if len(decoded) > MAX_STREAM or decompressed > MAX_DECOMPRESSED:
                    raise Rejected
            for key, child in value.items():
                if not isinstance(key, NameObject) or len(str(key)) > 256:
                    raise Rejected
                child_context = "ordinary"
                if value is reader.trailer and key == "/Info" and isinstance(child, IndirectObject):
                    child_context = "info"
                elif (
                    context == "info"
                    and not isinstance(value, StreamObject)
                    and key in {"/CreationDate", "/ModDate"}
                ):
                    child_context = "date"
                visit(child, depth + 1, context=child_context)
        elif isinstance(value, ArrayObject):
            if len(value) > MAX_OBJECTS:
                raise Rejected
            for child in value:
                visit(child, depth + 1)
        elif isinstance(value, NameObject):
            if str(value) in _ACTIVE_NAMES or len(str(value)) > 256:
                raise Rejected
        elif isinstance(value, TextStringObject):
            # The exception belongs to this typed edge, never a shared object.
            # Aliases in titles, pages or orphan dictionaries are still scanned.
            if context != "date" or not _pdf_date(str(value)):
                _card_text(str(value))
        elif isinstance(value, ByteStringObject):
            if len(value) > MAX_STREAM:
                raise Rejected
            _card_text(bytes(value).decode("utf-8", errors="ignore"))

    visit(reader.trailer)
    for generation, object_id in references:
        visit(IndirectObject(object_id, generation, reader), inventory=True)
    pages = reader.pages
    if not pages:
        raise Rejected
    if len(pages) > MAX_PAGES:
        raise Rejected("DOCUMENT_TOO_COMPLEX")
    for page in pages:
        # Float is used only for page geometry, never for financial data.
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
            raise Rejected
        if page.get("/UserUnit", 1) != 1:
            raise Rejected
        _size(math.ceil(width * 200 / 72), math.ceil(height * 200 / 72))
        content = page.get_contents()
        if content is not None and len(content.get_data()) > MAX_STREAM:
            raise Rejected
        _card_text(page.extract_text() or "")
    return reader


def _render_command(pdftoppm: str, page_number: int) -> list[str]:
    return [
        pdftoppm,
        "-f",
        str(page_number),
        "-l",
        str(page_number),
        "-r",
        "200",
        "-singlefile",
        "-",
    ]


def _render(data: bytes, page_number: int, pdftoppm: str, deadline: float):
    try:
        output = bounded_process(
            _render_command(pdftoppm, page_number),
            data,
            timeout=min(TOOL_SECONDS, _remaining(deadline)),
            output_limit=MAX_PIXELS * 3 + 1024,
        )
    except ProcessTimeout:
        raise Rejected("DOCUMENT_TOO_COMPLEX") from None
    except ProcessFailure:
        raise Rejected("DOCUMENT_OCR_UNAVAILABLE") from None
    Image = _pillow()
    if not output.startswith(b"P6"):
        raise Rejected("DOCUMENT_OCR_UNAVAILABLE")
    with Image.open(io.BytesIO(output), formats=["PPM"]) as image:
        _size(*image.size)
        image.load()
        return image.convert("RGB")


def inspect_document(
    data: bytes, mime: str, tesseract: str, pdftoppm: str, *, deadline: float
) -> dict:
    if not data or len(data) > MAX_BYTES:
        raise Rejected
    if mime == "application/pdf":
        reader = _pdf(data)
        try:
            _ocr_setup(tesseract, pdftoppm, True)
            page_count = len(reader.pages)
            for page_number in range(1, page_count + 1):
                _remaining(deadline)
                with _render(data, page_number, pdftoppm, deadline) as image:
                    _ocr(image, tesseract, deadline)
        finally:
            reader.close()
    else:
        with _image(data, mime) as image:
            _ocr_setup(tesseract, pdftoppm, False)
            _ocr(image, tesseract, deadline)
        page_count = 1
    return {"content_type": mime, "page_count": page_count}


def main() -> None:
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        _limits()
        if len(sys.argv) != 4 or sys.argv[1] not in {"application/pdf", "image/png", "image/jpeg"}:
            raise Rejected
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        result = inspect_document(data, sys.argv[1], sys.argv[2], sys.argv[3], deadline=deadline)
    except Rejected as failure:
        result = {"error": failure.code}
    except BaseException:
        # Parser text, OCR output, metadata, and exception messages never cross the pipe.
        result = {"error": "DOCUMENT_UNSAFE"}
    sys.stdout.write(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
