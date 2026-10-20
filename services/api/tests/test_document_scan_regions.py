"""Polyglot markers are searched outside compressed image/PDF data, never less than that."""

import io
import random
import struct
import zlib

import pytest
from PIL import Image

from sallimbook.documents import _validation_worker as worker

MARKERS = (b"<?=", b"<svg", b"PK\x03\x04")


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
