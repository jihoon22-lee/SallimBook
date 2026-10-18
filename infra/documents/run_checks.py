"""Real, network-isolated ClamAV/Poppler/Tesseract checks using only synthetic memory data."""

import hashlib
import io
import json
import os
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    TextStringObject,
)
from sallimbook.core.errors import DomainError
from sallimbook.documents.validation import (
    check_scanner_availability,
    validate_document,
)

SOCKET = "/run/sallimbook/clamd.sock"
SPOOL = Path("/run/sallimbook/spool")
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def require(condition, stage):
    if not condition:
        raise RuntimeError(stage)


def check_isolation():
    require(os.getuid() == 10001, "nonroot")
    status = Path("/proc/self/status").read_text()
    require("NoNewPrivs:\t1" in status, "no_new_privileges")
    require("CapEff:\t0000000000000000" in status, "no_capabilities")
    mounts = Path("/proc/self/mountinfo").read_text().splitlines()
    spool_mount = next(line for line in mounts if line.split()[4] == "/run/sallimbook")
    require(" - tmpfs " in spool_mount, "ram_spool")
    require(
        all(flag in spool_mount for flag in ("noexec", "nosuid", "nodev")),
        "spool_flags",
    )
    require(
        Path("/sys/fs/cgroup/memory.swap.max").read_text().strip() == "0",
        "swap_disabled",
    )
    root_mount = next(line for line in mounts if line.split()[4] == "/")
    require("ro" in root_mount.split()[5].split(","), "readonly_root")


def synthetic_pan():
    prefix = "4" + "12345678901234"
    for check in range(10):
        value = prefix + str(check)
        total = 0
        for index, digit in enumerate(map(int, reversed(value))):
            doubled = digit * 2 if index % 2 else digit
            total += doubled - 9 if doubled > 9 else doubled
        if total % 10 == 0:
            return value
    raise RuntimeError("synthetic_fixture")


def receipt(kind="PNG", *, korean=False, card=False, pan=False):
    image = Image.new("RGB", (1200, 700), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(FONT, 52)
    lines = (
        [
            "합성 진료비 영수증",
            "합성 병원 검사 진료",
            "합성 환자 진료 날짜",
            "납부 금액 확인 문서",
        ]
        if korean
        else [
            "SYNTHETIC MEDICAL RECEIPT",
            "TEST HOSPITAL VISIT SUMMARY",
            "DATE 2026 10 17",
            "TOTAL PAID 25000 KRW",
        ]
    )
    if card:
        lines = ["SYNTHETIC CARD TEST", "CARD NUMBER", "CVC SECURITY CODE", "123"]
    if pan:
        number = synthetic_pan()
        lines = [
            "SYNTHETIC TEST DOCUMENT",
            " ".join(number[n : n + 4] for n in range(0, 16, 4)),
            "SYNTHETIC REFERENCE",
            "TEST ONLY",
        ]
    for number, line in enumerate(lines):
        draw.text((40, 45 + 125 * number), line, font=font, fill="black")
    buffer = io.BytesIO()
    # Fixtures are clock-independent; dated PDF acceptance uses explicit metadata.
    metadata = {"creationDate": None, "modDate": None} if kind == "PDF" else {}
    image.save(buffer, format=kind, resolution=200, **metadata)
    image.close()
    return buffer.getvalue()


def text_pdf(*, card=False, active=False, pan=False):
    writer = PdfWriter()
    page = writer.add_blank_page(600, 400)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    text = b"CARD NUMBER CVC SECURITY CODE" if card else b"SYNTHETIC MEDICAL RECEIPT"
    if pan:
        text = synthetic_pan().encode()
    content = DecodedStreamObject()
    content.set_data(
        b"BT /F1 24 Tf 30 330 Td ("
        + text
        + b") Tj 0 -60 Td (TEST HOSPITAL VISIT SUMMARY) Tj 0 -60 Td (TOTAL PAID 25000 KRW) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    if active:
        writer._root_object[NameObject("/OpenAction")] = DictionaryObject(
            {
                NameObject("/S"): NameObject("/JavaScript"),
                NameObject("/JS"): TextStringObject("synthetic"),
            }
        )
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def metadata_pdf(metadata):
    """A real image PDF with deliberate synthetic /Info values, never wall-clock dates."""
    # PdfWriter.__enter__ reinitializes the writer, discarding constructor clones.
    writer = PdfWriter(clone_from=io.BytesIO(receipt("PDF", korean=True)))
    try:
        writer.add_metadata(metadata)
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()
    finally:
        writer.close()


def accepted(data, mime, stage):
    result = validate_document(data, mime, scanner_socket=SOCKET)
    require(result.content_type == mime and result.size_bytes == len(data), stage)
    require(
        result.sha256 == hashlib.sha256(data).hexdigest() and result.page_count == 1,
        stage,
    )


def rejected(data, mime, expected, stage, **options):
    try:
        validate_document(
            data, mime, scanner_socket=options.pop("scanner_socket", SOCKET), **options
        )
    except DomainError as error:
        require(error.code in expected, stage)
    else:
        raise RuntimeError(stage)


def main():
    stage = "isolation"
    daemon = None
    results = []
    try:
        check_isolation()
        SPOOL.mkdir(mode=0o700)
        stage = "scanner_start"
        daemon = subprocess.Popen(
            ["/usr/local/sbin/clamd", "--config-file=/etc/sallimbook/clamd.conf"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 90
        while True:
            require(daemon.poll() is None and time.monotonic() < deadline, stage)
            try:
                check_scanner_availability(SOCKET)
                break
            except DomainError:
                time.sleep(0.2)
        results.append(stage)
        for stage, data, mime in [
            ("png_english", receipt(), "image/png"),
            ("jpeg_english", receipt("JPEG"), "image/jpeg"),
            ("png_korean", receipt(korean=True), "image/png"),
            ("pdf_text", text_pdf(), "application/pdf"),
            ("pdf_image_korean", receipt("PDF", korean=True), "application/pdf"),
            (
                "pdf_dated_korean",
                metadata_pdf(
                    {
                        "/CreationDate": "D:20261018051908Z",
                        "/ModDate": "D:20261018051908Z",
                    }
                ),
                "application/pdf",
            ),
        ]:
            accepted(data, mime, stage)
            results.append(stage)
        # The public EICAR string is assembled only in memory; no .com file is written.
        eicar = (
            b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$"
            + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        )
        blank = io.BytesIO()
        with Image.new("RGB", (400, 200), "white") as image:
            image.save(blank, format="PNG")
        cases = [
            (
                "card_pdf_metadata",
                metadata_pdf({"/Title": synthetic_pan()}),
                "application/pdf",
                {"DOCUMENT_CARD_DATA"},
                {},
            ),
            (
                "card_pdf_date_suffix",
                metadata_pdf({"/CreationDate": "D:20261018051908Z CVC SECURITY CODE"}),
                "application/pdf",
                {"DOCUMENT_CARD_DATA"},
                {},
            ),
            (
                "luhn_pdf_text",
                text_pdf(pan=True),
                "application/pdf",
                {"DOCUMENT_CARD_DATA"},
                {},
            ),
            ("luhn_png", receipt(pan=True), "image/png", {"DOCUMENT_CARD_DATA"}, {}),
            (
                "unreadable_image",
                blank.getvalue(),
                "image/png",
                {"DOCUMENT_UNREADABLE"},
                {},
            ),
            (
                "size_limit",
                b"x" * (20 * 1024 * 1024 + 1),
                "image/png",
                {"DOCUMENT_TOO_LARGE"},
                {},
            ),
            ("eicar", eicar, "application/pdf", {"DOCUMENT_MALWARE"}, {}),
            (
                "active_pdf",
                text_pdf(active=True),
                "application/pdf",
                {"DOCUMENT_UNSAFE", "DOCUMENT_MALWARE"},
                {},
            ),
            (
                "card_pdf_text",
                text_pdf(card=True),
                "application/pdf",
                {"DOCUMENT_CARD_DATA"},
                {},
            ),
            ("card_png", receipt(card=True), "image/png", {"DOCUMENT_CARD_DATA"}, {}),
            (
                "card_image_pdf",
                receipt("PDF", card=True),
                "application/pdf",
                {"DOCUMENT_CARD_DATA"},
                {},
            ),
            ("wrong_mime", receipt(), "image/jpeg", {"DOCUMENT_UNSAFE"}, {}),
            (
                "missing_ocr",
                receipt(),
                "image/png",
                {"DOCUMENT_OCR_UNAVAILABLE"},
                {"tesseract_path": "/missing/tesseract"},
            ),
            (
                "scanner_unconfigured",
                receipt(),
                "image/png",
                {"DOCUMENT_SCAN_UNAVAILABLE"},
                {"scanner_socket": None},
            ),
        ]
        for stage, data, mime, expected, options in cases:
            rejected(data, mime, expected, stage, **options)
            results.append(stage)
        stage = "spool_cleanup"
        deadline = time.monotonic() + 3
        while list(SPOOL.iterdir()) and time.monotonic() < deadline:
            time.sleep(0.05)
        require(not list(SPOOL.iterdir()), stage)
        results.append(stage)
        daemon.terminate()
        daemon.wait(timeout=10)
        daemon = None
        stage = "scanner_stopped"
        rejected(receipt(), "image/png", {"DOCUMENT_SCAN_UNAVAILABLE"}, stage)
        results.append(stage)
        # Only fixed test names and versions are reported; no input/text/daemon logs.
        print(
            json.dumps(
                {
                    "ok": True,
                    "checks": results,
                    "python": __import__("platform").python_version(),
                    "pillow": Image.__version__,
                    "pypdf": __import__("pypdf").__version__,
                }
            )
        )
        return 0
    except BaseException:  # noqa: BLE001 - Never print input-derived parser/OCR exceptions.
        print(
            json.dumps(
                {"ok": False, "failed_check": stage, "completed_checks": results}
            )
        )
        return 1
    finally:
        if daemon is not None:
            daemon.terminate()
            try:
                daemon.wait(timeout=10)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait()


if __name__ == "__main__":
    raise SystemExit(main())
