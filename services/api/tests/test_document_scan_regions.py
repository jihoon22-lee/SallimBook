"""Polyglot markers are searched outside compressed image/PDF data, never less than that."""

import io
import random
import struct
import time
import zlib

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from sallimbook.documents import _validation_worker as worker

MARKERS = (b"<?=", b"<svg", b"PK\x03\x04")
# 마커를 스트림 경계에서 13바이트 넘게 띄운다(경계 중첩 검사 구간 밖).
MARKER_LINE = b"q Q % synthetic padding <?= <svg PK\x03\x04 javascript: synthetic padding\n"


def image_bytes(kind="PNG", size=(400, 200)):
    result = io.BytesIO()
    with Image.new("RGB", size, "white") as image:
        image.save(result, format=kind)
    return result.getvalue()


def noise_jpeg():
    rng = random.Random(7)
    result = io.BytesIO()
    with Image.frombytes("RGB", (64, 64), rng.randbytes(64 * 64 * 3)) as image:
        image.save(result, format="JPEG", quality=95)
    return result.getvalue()


def entropy_start(data):
    at = data.index(b"\xff\xda")
    return at + 2 + struct.unpack("!H", data[at + 2 : at + 4])[0]


def chunk(name, payload):
    return (
        struct.pack("!I", len(payload))
        + name
        + payload
        + struct.pack("!I", zlib.crc32(name + payload) & 0xFFFFFFFF)
    )


def stored_png(markers):
    row = b"\x00" + b"\x80" * 40 + markers + b"\x80" * (88 - len(markers))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!IIBBBBB", 128, 1, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row, 0))
        + chunk(b"IEND", b"")
    )


def assert_rejected(action, code="DOCUMENT_UNSAFE"):
    with pytest.raises(worker.Rejected) as error:
        action()
    assert error.value.code == code
    assert str(error.value) == code


def test_jpeg_ranges_exclude_only_entropy_coded_data():
    data = image_bytes("JPEG")
    assert worker._scannable_ranges(data, "image/jpeg") == (
        (0, entropy_start(data)),
        (len(data) - 2, len(data)),
    )


@pytest.mark.parametrize("marker", MARKERS)
def test_jpeg_entropy_data_markers_no_longer_reject(marker):
    data = noise_jpeg()
    start, end = entropy_start(data), len(data) - 2
    middle = (start + end) // 2
    assert middle - start > 32 and end - middle > 32
    patched = data[:middle] + marker + data[middle:]  # 0xFF 없는 bytes라 구조는 유지된다
    worker._jpeg_structure(patched)
    worker._polyglot(patched, "image/jpeg")


def test_seeded_noise_photos_with_coincidental_markers_pass_polyglot():
    rng, coincidental = random.Random(20261019), 0
    for _ in range(40):
        with Image.frombytes("RGB", (1400, 1000), rng.randbytes(1400 * 1000 * 3)) as image:
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=95)
        data = buffer.getvalue()
        coincidental += any(m in data.lower() for m in (b"<?=", b"<svg")) or any(
            m in data for m in (b"PK\x03\x04", b"PK\x05\x06", b"\x7fELF", b"MZ\x90\x00")
        )
        worker._polyglot(data, "image/jpeg")
    assert coincidental >= 1  # 같은 조건에서 기존 규칙은 10/40개를 거부했다


def test_png_idat_markers_no_longer_reject_and_image_still_decodes():
    data = stored_png(b"<?=<svg PK\x03\x04")
    start = data.index(b"IDAT") + 4
    end = start + struct.unpack("!I", data[start - 8 : start - 4])[0]
    assert worker._scannable_ranges(data, "image/png") == ((0, start), (end, len(data)))
    worker._polyglot(data, "image/png")
    with worker._image(data, "image/png") as image:
        assert image.size == (128, 1)


@pytest.mark.parametrize("marker", [b"<?php", b"<?=", b"<svg", b"javascript:", b"PK\x03\x04"])
def test_markers_in_metadata_comment_and_trailer_are_still_rejected(marker):
    jpeg = image_bytes("JPEG")
    app1 = b"\xff\xe1" + struct.pack("!H", 8 + len(marker)) + b"Exif\0\0" + marker
    com = b"\xff\xfe" + struct.pack("!H", 2 + len(marker)) + marker
    for candidate in (jpeg[:2] + app1 + jpeg[2:], jpeg[:2] + com + jpeg[2:], jpeg + marker):
        assert_rejected(lambda c=candidate: worker._polyglot(c, "image/jpeg"))
    png = image_bytes("PNG")
    for name in (b"tEXt", b"iTXt", b"zTXt"):
        text = png[:-12] + chunk(name, b"Comment\0" + marker) + png[-12:]
        assert_rejected(lambda t=text: worker._polyglot(t, "image/png"))
    assert_rejected(lambda: worker._polyglot(png + marker, "image/png"))


def test_marker_straddling_an_excluded_boundary_is_rejected():
    png = image_bytes("PNG")
    at = png.index(b"IDAT")
    length = struct.unpack("!I", png[at - 4 : at])[0]
    payload = png[at + 4 : at + 4 + length] + b"<scr"
    forged = (
        png[: at - 4]
        + struct.pack("!I", len(payload))
        + b"IDAT"
        + payload
        + b"ipt>"
        + png[at + 8 + length :]
    )
    assert_rejected(lambda: worker._polyglot(forged, "image/png"))  # CRC 자리로 이어지는 "<script"


def test_unparseable_image_structure_scans_whole_file():
    jpeg = noise_jpeg()
    cut = jpeg[: entropy_start(jpeg) + 40]
    assert worker._scannable_ranges(cut, "image/jpeg") == ((0, len(cut)),)
    assert worker._scannable_ranges(image_bytes("PNG")[:20], "image/png") == ((0, 20),)
    assert worker._scannable_ranges(b"synthetic", "image/jpeg") == ((0, 9),)
    assert worker._scannable_ranges(b"%PDF-synthetic", "application/pdf") == ((0, 14),)


def pdf_bytes(change):
    writer = PdfWriter()
    writer.add_blank_page(300, 300)
    change(writer)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def contents(raw, *, filtered):
    def change(writer):
        stream = DecodedStreamObject()
        stream._data = zlib.compress(raw, 0) if filtered else raw
        if filtered:
            stream[NameObject("/Filter")] = NameObject("/FlateDecode")
        writer.pages[0][NameObject("/Contents")] = writer._add_object(stream)

    return change


def manual_pdf(extra, payload):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R >>",
        b"<< /Length %d %s >>\nstream\n%s\nendstream" % (len(payload), extra, payload),
    ]
    output = b"%PDF-1.7\n"
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(output))
        output += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(output)
    output += b"xref\n0 5\n0000000000 65535 f\r\n" + b"".join(
        b"%010d 00000 n\r\n" % offset for offset in offsets
    )
    return output + b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % xref


@pytest.mark.parametrize("filtered", [False, True])
def test_pdf_ranges_cover_everything_except_stream_data(filtered):
    raw = zlib.compress(MARKER_LINE, 0) if filtered else MARKER_LINE
    data = pdf_bytes(contents(MARKER_LINE, filtered=filtered))
    start = data.index(b"stream\n") + len(b"stream\n")
    with worker._pdf(data) as reader:  # 스트림 안 마커는 더 이상 거부 사유가 아니다
        assert reader.pages[0]["/Contents"].get_object()._data == raw  # pypdf 원시 bytes 계약
        assert worker._scannable_ranges(data, "application/pdf", reader) == (
            (0, start),
            (start + len(raw), len(data)),
        )


def test_pdf_object_syntax_and_comment_markers_are_still_rejected():
    titled = pdf_bytes(lambda writer: writer.add_metadata({"/Title": "SYNTHETICZZ"}))
    assert_rejected(lambda: worker._pdf(titled.replace(b"SYNTHETICZZ", b"<svg onload")))
    plain = pdf_bytes(contents(b"q Q\n", filtered=False))
    assert_rejected(
        lambda: worker._pdf(plain.replace(b"%\xe2\xe3\xcf\xd3", b"%<?= "))
    )  # 같은 길이: xref 유지


def test_pdf_stream_copy_inside_dictionary_cannot_hide_markers():
    payload = b"q Q % <svg onload\n"
    assert_rejected(
        lambda: worker._pdf(manual_pdf(b"/SyntheticCopy (stream\n" + payload + b")", payload))
    )
    with worker._pdf(manual_pdf(b"/SyntheticCopy (stream\nq Q\n)", b"q Q\n")) as reader:
        assert len(reader.pages) == 1


def test_pdf_stream_location_mismatch_scans_whole_file():
    data = pdf_bytes(contents(b"q Q\n", filtered=False))
    with worker._pdf(data) as reader:
        reader.pages[0]["/Contents"].get_object()._data = b"synthetic bytes absent from file"
        assert worker._scannable_ranges(data, "application/pdf", reader) == ((0, len(data)),)


def test_inspect_document_reaches_ocr_for_pdf_with_stream_markers():
    data = pdf_bytes(contents(MARKER_LINE, filtered=True))
    assert_rejected(
        lambda: worker.inspect_document(
            data,
            "application/pdf",
            "/missing/tesseract",
            "/missing/pdftoppm",
            deadline=time.monotonic() + 30,
        ),
        "DOCUMENT_OCR_UNAVAILABLE",
    )


def test_zip_end_of_directory_hidden_in_excluded_tail_data_is_rejected():
    # ZIP/JAR readers locate the end-of-central-directory record in the last 64 KiB, so it
    # must stay visible even inside an IDAT payload or JPEG scan data near the end.
    eocd = b"PK\x05\x06" + b"\x00" * 16 + struct.pack("<H", 16)
    png = stored_png(b"\x80" * 8)
    at = png.index(b"IDAT")
    length = struct.unpack("!I", png[at - 4 : at])[0]
    payload = png[at + 4 : at + 4 + length] + b"\x80" * 32 + eocd
    forged = png[: at - 4] + chunk(b"IDAT", payload) + png[at + 8 + length :]
    assert_rejected(lambda: worker._polyglot(forged, "image/png"))
    jpeg = noise_jpeg()
    hidden = jpeg[:-2] + b"\x00" * 32 + eocd[:-2] + struct.pack("<H", 2) + jpeg[-2:]
    assert_rejected(lambda: worker._polyglot(hidden, "image/jpeg"))


def segment(marker, payload):
    return marker + struct.pack("!H", len(payload) + 2) + payload


@pytest.mark.parametrize(
    "segment_bytes",
    [
        segment(b"\xff\xe1", b"http://ns.adobe.com/xap/1.0/\0<x:xmpmeta/>"),
        segment(b"\xff\xe1", b"http://ns.adobe.com/xmp/extension/\0synthetic"),
        segment(b"\xff\xe2", b"MPF\0MM\0*\0\0\0\x08"),
        segment(b"\xff\xe5", b"synthetic"),
        segment(b"\xff\xfe", b"synthetic comment"),
    ],
)
def test_jpeg_segments_outside_profile_are_unsupported_not_unsafe(segment_bytes):
    data = image_bytes("JPEG")
    assert_rejected(
        lambda: worker._jpeg_structure(data[:2] + segment_bytes + data[2:]),
        "DOCUMENT_IMAGE_UNSUPPORTED",
    )


@pytest.mark.parametrize("kind", ["samsung_seft", "motion_mp4", "gain_map_jpeg"])
def test_data_after_jpeg_eoi_is_unsupported(kind):
    trailer = {
        "samsung_seft": b"SEFH\0\0\0\x01synthetic SEFT",
        "motion_mp4": b"\0\0\0\x18ftypmp42synthetic",
        "gain_map_jpeg": image_bytes("JPEG"),
    }[kind]
    assert_rejected(
        lambda: worker._jpeg_structure(image_bytes("JPEG") + trailer),
        "DOCUMENT_IMAGE_UNSUPPORTED",
    )


def test_malformed_jpeg_stays_unsafe():
    data = image_bytes("JPEG")
    for broken in (
        data[:-2],
        b"\xff\xd8\xff\xd9",
        data[:2] + b"\xff\xe1\x00\x01" + data[2:],
        b"\x00" + data,
    ):
        assert_rejected(lambda b=broken: worker._jpeg_structure(b))


@pytest.mark.parametrize("name", [b"tEXt", b"iTXt", b"zTXt", b"acTL", b"iDOT", b"zzZZ"])
def test_png_chunks_outside_profile_are_unsupported(name):
    data = image_bytes("PNG")
    assert_rejected(
        lambda: worker._png_structure(data[:-12] + chunk(name, b"synthetic") + data[-12:]),
        "DOCUMENT_IMAGE_UNSUPPORTED",
    )


def test_data_after_png_iend_is_unsupported_but_broken_png_stays_unsafe():
    data = image_bytes("PNG")
    assert_rejected(
        lambda: worker._png_structure(data + b"synthetic trailing body"),
        "DOCUMENT_IMAGE_UNSUPPORTED",
    )
    crc = data[:29] + bytes([data[29] ^ 1]) + data[30:]
    for bad in (crc, data[:-5], data[:8] + chunk(b"IDAT", b"x") + data[8:]):
        assert_rejected(lambda b=bad: worker._png_structure(b))


def test_image_checks_structure_then_markers_then_decode():
    data = image_bytes("JPEG")
    assert_rejected(
        lambda: worker._image(data + b"<?php synthetic", "image/jpeg"),
        "DOCUMENT_IMAGE_UNSUPPORTED",
    )
    exif = data[:2] + segment(b"\xff\xe1", b"Exif\0\0" + b"<?php synthetic") + data[2:]
    assert_rejected(
        lambda: worker._image(exif, "image/jpeg")
    )  # 허용 APP1 안 마커는 DOCUMENT_UNSAFE
