"""The isolated measurement harness reports only fixed numeric fields for synthetic inputs."""

import importlib.util
from pathlib import Path

import pytest
from PIL import ImageFont

from sallimbook.documents import _validation_worker as worker

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def checks(monkeypatch):
    path = ROOT / "infra/documents/run_checks.py"
    spec = importlib.util.spec_from_file_location("synthetic_document_checks", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Host unit tests need no system font. Real CJK OCR is covered by the image suite.
    font = ImageFont.load_default(size=52)
    monkeypatch.setattr(module.ImageFont, "truetype", lambda *_args, **_kwargs: font)
    return module


def harness():
    spec = importlib.util.spec_from_file_location(
        "synthetic_document_harness", ROOT / "scripts/test_document_tools.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_measure_case_names_match_harness(checks):
    assert (
        checks.MEASURE_CASES
        == harness().MEASURE_CASES
        == (
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
    )


@pytest.mark.parametrize("kind", ["text", "image"])
@pytest.mark.parametrize("pages", [1, 4])
def test_dense_pdf_is_a4_with_exact_pages_and_no_card_like_text(checks, kind, pages):
    with worker._pdf(checks.dense_pdf(pages, kind)) as reader:  # _card_text도 통과해야 한다
        assert len(reader.pages) == pages
        assert [round(float(v)) for v in reader.pages[0].mediabox[2:]] == [595, 842]


def test_photo_fixture_is_plain_jpeg_within_pixel_limit(checks):
    data = checks.photo_jpeg(4608, 3456)
    worker._jpeg_structure(data)
    assert b"Exif" not in data[:4096] and 4608 * 3456 <= worker.MAX_PIXELS


def test_measure_reports_only_fixed_numeric_fields(checks):
    row = checks.measure("jpeg-photo-3072x2304", tesseract="/missing/tesseract")
    assert set(row) == {
        "case",
        "pages",
        "pixels",
        "seconds",
        "result",
        "render_seconds",
        "ocr_seconds",
        "memory_peak_bytes",
        "max_rss_kib",
    }
    assert (row["case"], row["pages"], row["pixels"]) == ("jpeg-photo-3072x2304", 1, 3072 * 2304)
    assert row["result"] == "DOCUMENT_OCR_UNAVAILABLE" and row["ocr_seconds"] == []
    with pytest.raises(ValueError):
        checks.measure("unknown-case")


def test_tool_commands_are_unchanged_by_refactor():
    assert worker.TOOL_SECONDS == 10
    assert worker._ocr_command("/static/tesseract") == [
        "/static/tesseract",
        "stdin",
        "stdout",
        "-l",
        "eng+kor",
        "--psm",
        "11",
        "--dpi",
        "200",
        "tsv",
    ]
    assert worker._render_command("/static/pdftoppm", 3) == [
        "/static/pdftoppm",
        "-f",
        "3",
        "-l",
        "3",
        "-r",
        "200",
        "-singlefile",
        "-",
    ]
