"""Real, network-isolated ClamAV/Poppler/Tesseract checks using only synthetic memory data."""

import hashlib
import io
import json
import os
import random
import resource
import struct
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)
from sallimbook.core.errors import DomainError
from sallimbook.documents import _validation_worker as worker
from sallimbook.documents.validation import (
    WORKER_SECONDS,
    check_scanner_availability,
    validate_document,
)

SOCKET = "/run/sallimbook/clamd.sock"
SPOOL = Path("/run/sallimbook/spool")
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
MEASURE_CASES = (
    "pdf-text-a4-1",
    "pdf-text-a4-2",
    "pdf-text-a4-4",
    "pdf-text-a4-8",
    "pdf-image-a4-1",
    "pdf-image-a4-4",
    "jpeg-photo-3072x2304",
    "jpeg-photo-4000x3000",
    "jpeg-photo-4608x3456",
)
# A4 rendered by the worker's pdftoppm at 200 dpi.
A4_PIXELS = (1654, 2339)


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


def receipt(
    kind="PNG",
    *,
    korean=False,
    card=False,
    pan=False,
    dates=False,
    masked=False,
    noise_seed=None,
):
    image = receipt_image(
        korean=korean, card=card, pan=pan, dates=dates, masked=masked, noise_seed=noise_seed
    )
    buffer = io.BytesIO()
    # Fixtures are clock-independent; dated PDF acceptance uses explicit metadata.
    metadata = {"creationDate": None, "modDate": None} if kind == "PDF" else {}
    image.save(buffer, format=kind, resolution=200, **metadata)
    image.close()
    return buffer.getvalue()


def receipt_image(
    *, korean=False, card=False, pan=False, dates=False, masked=False, noise_seed=None
):
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
    if dates:
        # Date pairs once matched as Luhn-valid card numbers (L12 regression).
        lines = [
            "합성 진료비 영수증",
            "2026.10.01 2026.10.08",
            "2026-09-30 2026-10-07",
            "합성 병원",
        ]
    if masked:
        # A card receipt prints a masked number and bare field labels; it is not card data.
        lines = [
            "합성 카드 영수증",
            "CARD NO ****-****-****-2349",
            "카드번호 4123-45**-****-2349",
            "TOTAL PAID 25000 KRW",
        ]
    for number, line in enumerate(lines):
        draw.text((40, 45 + 125 * number), line, font=font, fill="black")
    if noise_seed is not None:
        # A random band makes entropy-coded JPEG data that can contain marker bytes.
        band = random.Random(noise_seed).randbytes(1200 * 120 * 3)
        with Image.frombytes("RGB", (1200, 120), band) as noise:
            image.paste(noise, (0, 570))
    return image


def receipt_pdf(pages):
    """An image-only PDF (OCR path) with one synthetic Korean receipt per page."""
    images = [receipt_image(korean=True) for _ in range(pages)]
    buffer = io.BytesIO()
    images[0].save(
        buffer,
        format="PDF",
        resolution=200,
        save_all=True,
        append_images=images[1:],
        creationDate=None,
        modDate=None,
    )
    for image in images:
        image.close()
    return buffer.getvalue()


def _app_segment(marker, payload):
    return bytes([0xFF, marker]) + struct.pack("!H", len(payload) + 2) + payload


def phone_like_jpeg():
    """A receipt stored sideways with EXIF orientation 6, an XMP packet and a camera trailer."""
    with (
        receipt_image(korean=True) as upright,
        upright.rotate(90, expand=True) as stored,
    ):
        exif = Image.Exif()
        exif[0x0112] = 6
        buffer = io.BytesIO()
        stored.save(buffer, format="JPEG", quality=92, exif=exif.tobytes())
    data = buffer.getvalue()
    xmp = _app_segment(
        0xE1, b'http://ns.adobe.com/xap/1.0/\0<x:xmpmeta xmlns:x="adobe:ns:meta/"/>'
    )
    trailer = (
        b"\0\0\0\x18ftypmp42\0\0\0\0mp42isom" + b"SEFHsynthetic camera trailerSEFT"
    )
    return data[:2] + xmp + data[2:] + trailer


def reencoded_phone_jpeg():
    """What the clients upload: orientation applied, metadata and trailer dropped."""
    with Image.open(io.BytesIO(phone_like_jpeg()), formats=["JPEG"]) as image:
        upright = ImageOps.exif_transpose(image)
        buffer = io.BytesIO()
        upright.save(buffer, format="JPEG", quality=90)
        upright.close()
    return buffer.getvalue()


def marker_in_scan_jpeg():
    """A noisy receipt JPEG whose only marker bytes sit in excluded entropy-coded data."""
    for seed in range(1000):
        data = receipt("JPEG", noise_seed=seed)
        try:
            worker._polyglot(data, "image/jpeg", ((0, len(data)),))
            continue
        except worker.Rejected:
            pass
        try:
            worker._polyglot(data, "image/jpeg")
        except worker.Rejected:
            continue
        return data
    require(False, "jpeg_marker_in_scan")


def lossless_scan_pdf():
    # A Korean receipt on a lossless (Flate) A4 200 dpi RGB page; it decodes to 11.6 MB.
    page_image = Image.new("RGB", (1654, 2339), "white")
    with receipt_image(korean=True) as image:
        page_image.paste(image, (200, 300))
    writer = PdfWriter()
    page = writer.add_blank_page(595, 842)
    scan = DecodedStreamObject()
    scan.set_data(page_image.tobytes())
    scan.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(page_image.width),
            NameObject("/Height"): NumberObject(page_image.height),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    page_image.close()
    reference = writer._add_object(scan.flate_encode())
    content = DecodedStreamObject()
    content.set_data(b"q 595 0 0 842 0 0 cm /Scan Do Q")
    page[NameObject("/Contents")] = writer._add_object(content)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/XObject"): DictionaryObject({NameObject("/Scan"): reference})}
    )
    buffer = io.BytesIO()
    writer.write(buffer)
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
    text = b"CARD NUMBER CVC SECURITY CODE 123" if card else b"SYNTHETIC MEDICAL RECEIPT"
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


def dense_pdf(pages, kind):
    """A4 pages filled edge to edge with synthetic text; no digit group longer than two."""
    if kind == "text":
        writer = PdfWriter()
        font = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
        )
        for _page in range(pages):
            page = writer.add_blank_page(595, 842)
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
            )
            lines = b"".join(
                b"(SYNTHETIC CLINIC LINE %02d CONSULTATION AND PHARMACY ITEMS) Tj 0 -12 Td "
                % line
                for line in range(64)
            )
            content = DecodedStreamObject()
            content.set_data(b"BT /F1 9 Tf 36 800 Td " + lines + b"ET")
            page[NameObject("/Contents")] = writer._add_object(content)
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()
    if kind == "image":
        font = ImageFont.truetype(FONT, 30)
        images = []
        for _page in range(pages):
            image = Image.new("L", A4_PIXELS, 255)
            draw = ImageDraw.Draw(image)
            for line in range(48):
                text = (
                    f"합성 진료비 영수증 항목 {line:02d} 진찰료 약제비 검사료 확인"
                    if line % 2
                    else f"SYNTHETIC CLINIC LINE {line:02d} CONSULTATION AND PHARMACY ITEMS"
                )
                draw.text((80, 80 + 46 * line), text, font=font, fill=0)
            images.append(image)
        buffer = io.BytesIO()
        images[0].save(
            buffer,
            format="PDF",
            resolution=200,
            save_all=True,
            append_images=images[1:],
            creationDate=None,
            modDate=None,
        )
        for image in images:
            image.close()
        return buffer.getvalue()
    raise ValueError(kind)


def photo_jpeg(width, height):
    """A camera-sized plain JPEG: block noise around a synthetic receipt, no EXIF."""
    rng = random.Random(width * height)
    blocks = (width // 8, height // 8)
    noise = bytes(128 + rng.randint(-20, 20) for _ in range(blocks[0] * blocks[1]))
    with Image.frombytes("L", blocks, noise) as small:
        image = small.resize((width, height), Image.Resampling.NEAREST).convert("RGB")
    draw = ImageDraw.Draw(image)
    left, top = width // 4, height // 8
    draw.rectangle((left, top, width - left, height - top), fill="white")
    font = ImageFont.truetype(FONT, max(16, height // 60))
    step = (height - 2 * top) // 38
    for line in range(36):
        text = (
            f"합성 영수증 항목 {line:02d} 진찰료 약제비"
            if line % 2
            else f"SYNTHETIC RECEIPT LINE {line:02d} CONSULTATION"
        )
        draw.text((left + step, top + step * (line + 1)), text, font=font, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    image.close()
    return buffer.getvalue()


def _measure_input(case):
    if case not in MEASURE_CASES:
        raise ValueError(case)
    kind, _, size = case.rpartition("-")
    if case.startswith("pdf-"):
        pages = int(size)
        data = dense_pdf(pages, "text" if kind == "pdf-text-a4" else "image")
        return data, "application/pdf", pages, pages * A4_PIXELS[0] * A4_PIXELS[1]
    width, height = map(int, size.split("x"))
    return photo_jpeg(width, height), "image/jpeg", 1, width * height


def _executable(path):
    return os.path.isabs(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def _timed(command, data, output_limit):
    started = time.monotonic()
    output = worker.bounded_process(
        command, data, timeout=300, output_limit=output_limit
    )
    return output, round(time.monotonic() - started, 3)


def _ocr_seconds(image, tesseract):
    """Production OCR orientations, each timed without the production per-call limit."""
    seconds = []
    for angle in (0, 90, 180, 270):
        rotated = image if angle == 0 else image.rotate(angle, expand=True)
        try:
            buffer = io.BytesIO()
            rotated.save(buffer, format="PPM")
            seconds.append(
                _timed(
                    worker._ocr_command(tesseract),
                    buffer.getvalue(),
                    worker.MAX_OCR_OUTPUT,
                )[1]
            )
        finally:
            if rotated is not image:
                rotated.close()
    return seconds


def measure(case, *, tesseract="/usr/bin/tesseract", pdftoppm="/usr/bin/pdftoppm"):
    """One synthetic case through the production worker; only fixed numeric fields leave."""
    data, mime, pages, pixels = _measure_input(case)
    script = Path(worker.__file__).resolve()
    command = [
        sys.executable,
        "-I",
        "-B",
        str(script),
        mime,
        tesseract,
        pdftoppm if mime == "application/pdf" else "-",
    ]
    started = time.monotonic()
    try:
        output = worker.bounded_process(
            command, data, timeout=600, output_limit=1024, new_session=True
        )
        answer = json.loads(output)
        result = "accepted" if "page_count" in answer else str(answer.get("error"))
    except worker.ProcessFailure, ValueError:
        result = "WORKER_FAILED"
    seconds = round(time.monotonic() - started, 3)
    render_seconds, ocr_seconds = [], []
    tools = [tesseract] + ([pdftoppm] if mime == "application/pdf" else [])
    if all(_executable(tool) for tool in tools):
        if mime == "application/pdf":
            for page_number in range(1, pages + 1):
                output, elapsed = _timed(
                    worker._render_command(pdftoppm, page_number),
                    data,
                    worker.MAX_PIXELS * 3 + 1024,
                )
                render_seconds.append(elapsed)
                with Image.open(io.BytesIO(output), formats=["PPM"]) as image:
                    ocr_seconds.extend(_ocr_seconds(image, tesseract))
        else:
            with Image.open(io.BytesIO(data), formats=["JPEG"]) as image:
                image.load()
                ocr_seconds.extend(_ocr_seconds(image, tesseract))
    try:
        peak = int(Path("/sys/fs/cgroup/memory.peak").read_text())
    except OSError, ValueError:
        peak = None
    return {
        "case": case,
        "pages": pages,
        "pixels": pixels,
        "seconds": seconds,
        "result": result,
        "render_seconds": render_seconds,
        "ocr_seconds": ocr_seconds,
        "memory_peak_bytes": peak,
        "max_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
    }


def accepted(data, mime, stage, pages=1):
    started = time.monotonic()
    result = validate_document(data, mime, scanner_socket=SOCKET)
    seconds = time.monotonic() - started
    require(result.content_type == mime and result.size_bytes == len(data), stage)
    require(
        result.sha256 == hashlib.sha256(data).hexdigest()
        and result.page_count == pages,
        stage,
    )
    return seconds


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
    if sys.argv[1:2] == ["--measure"]:
        check_isolation()
        print(json.dumps(measure(sys.argv[2])))
        return 0
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
            ("pdf_lossless_a4_scan", lossless_scan_pdf(), "application/pdf"),
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
        for stage, data in [
            ("jpeg_marker_in_scan", marker_in_scan_jpeg()),
            ("jpeg_reencoded_phone", reencoded_phone_jpeg()),
        ]:
            accepted(data, "image/jpeg", stage)
            results.append(stage)
        stage = "png_dates_korean"
        accepted(receipt(korean=True, dates=True), "image/png", stage)
        results.append(stage)
        stage = "png_masked_card_receipt"
        accepted(receipt(masked=True), "image/png", stage)
        results.append(stage)
        stage = "pdf_max_pages"
        max_pages_seconds = accepted(
            receipt_pdf(worker.MAX_PAGES),
            "application/pdf",
            stage,
            pages=worker.MAX_PAGES,
        )
        require(max_pages_seconds < WORKER_SECONDS, stage)
        results.append(stage)
        # The public EICAR string is assembled only in memory; no .com file is written.
        eicar = (
            b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$"
            + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        )
        blank = io.BytesIO()
        with Image.new("RGB", (400, 200), "white") as image:
            image.save(blank, format="PNG")
        jpeg = receipt("JPEG")
        comment = b"<?php synthetic"
        cases = [
            (
                "jpeg_phone_original",
                phone_like_jpeg(),
                "image/jpeg",
                {"DOCUMENT_IMAGE_UNSUPPORTED"},
                {},
            ),
            (
                "jpeg_comment_marker",
                jpeg[:2] + _app_segment(0xFE, comment) + jpeg[2:],
                "image/jpeg",
                {"DOCUMENT_UNSAFE", "DOCUMENT_IMAGE_UNSUPPORTED"},
                {},
            ),
            (
                "jpeg_trailer_zip",
                jpeg + b"PK\x03\x04synthetic archive bytes",
                "image/jpeg",
                {"DOCUMENT_UNSAFE", "DOCUMENT_IMAGE_UNSUPPORTED"},
                {},
            ),
            (
                "pdf_too_many_pages",
                receipt_pdf(worker.MAX_PAGES + 1),
                "application/pdf",
                {"DOCUMENT_TOO_COMPLEX"},
                {},
            ),
            (
                "card_pdf_metadata",
                metadata_pdf({"/Title": synthetic_pan()}),
                "application/pdf",
                {"DOCUMENT_CARD_DATA"},
                {},
            ),
            (
                "card_pdf_date_suffix",
                metadata_pdf({"/CreationDate": "D:20261018051908Z CVC SECURITY CODE 123"}),
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
                    "max_pages_seconds": round(max_pages_seconds, 3),
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
