"""Synthetic PDF dates must not exempt aliases or arbitrary card-bearing strings."""

import importlib.util
import io
import re
import time
from pathlib import Path

import pytest
from PIL import ImageFont, PdfImagePlugin
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    TextStringObject,
)

from sallimbook.documents import _validation_worker as worker

LUHN_DATE = "D:20261018051908Z"


def pdf(change):
    with PdfWriter() as writer:
        writer.add_blank_page(300, 300)
        change(writer)
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()


def info(writer):
    return writer._info.get_object()


def reject_card(data):
    with pytest.raises(worker.Rejected) as error:
        worker._pdf(data)
    assert error.value.code == "DOCUMENT_CARD_DATA"


def info_first(data):
    trailer = data.index(b"trailer\n")
    before, after = data[:trailer], data[trailer:]
    root = re.search(rb"/Root [0-9]+ 0 R", after)[0]
    meta = re.search(rb"/Info [0-9]+ 0 R", after)[0]
    after = after.replace(root, b"PLACEHOLDER").replace(meta, root).replace(b"PLACEHOLDER", meta)
    return before + after


@pytest.mark.parametrize(
    "value",
    [
        "D:2026",
        "D:202610",
        "D:20261018",
        "D:2026101805",
        "D:202610180519",
        LUHN_DATE,
        "D:20261018051908",
        "D:20000229000000Z",
        "D:20261018051908+09",
        "D:20261018051908+09'",
        "D:20261018051908+09'30",
        "D:20261018051908-08'00'",
        "D:99991231235959+23'59",
    ],
)
def test_exact_calendar_dates_are_recognized_only_as_typed_metadata(value):
    assert worker._pdf_date(value)
    data = pdf(lambda writer: writer.add_metadata({"/CreationDate": value, "/ModDate": value}))
    with worker._pdf(data) as reader:
        assert len(reader.pages) == 1


@pytest.mark.parametrize(
    "value",
    [
        "",
        "20261018051908",
        "d:20261018051908Z",
        "D:20261",
        "D:2026101",
        "D:00000101000000Z",
        "D:19000229000000Z",
        "D:20260230000000Z",
        "D:20260001",
        "D:20261301",
        "D:20261000",
        "D:20261032",
        "D:20261018240000Z",
        "D:20261018236000Z",
        "D:20261018235960Z",
        LUHN_DATE + "+00'00",
        "D:20261018051908+24'00",
        "D:20261018051908+09'60",
        "D:20261018051908+0900",
        "D:20261018051908+09''",
        "D:20261018051908+09'00''",
        "D:20261018051908+",
        "D:２０２６１０１８０５１９０８Z",
        " " + LUHN_DATE,
        LUHN_DATE + "\n",
        LUHN_DATE + " CVC",
        LUHN_DATE + "\x00",
        "D:20261018\u200b051908Z",
    ],
)
def test_malformed_dates_receive_no_semantic_exception(value):
    assert not worker._pdf_date(value)


@pytest.mark.parametrize("key", ["/CreationDate", "/ModDate"])
@pytest.mark.parametrize(
    "value",
    [
        LUHN_DATE + " CVC SECURITY CODE",
        "CVC " + LUHN_DATE,
        LUHN_DATE + " extra text",
        " " + LUHN_DATE,
        LUHN_DATE + "\n",
        "D:２０２６１０１８０５１９０８Z",
    ],
)
def test_date_fields_with_extra_or_non_ascii_card_text_still_fail(key, value):
    reject_card(pdf(lambda writer: writer.add_metadata({key: value})))


@pytest.mark.parametrize("indirect", [False, True])
def test_reproducing_luhn_date_is_accepted_in_both_canonical_date_fields(indirect):
    with pytest.raises(worker.Rejected) as error:
        worker._card_text(LUHN_DATE)
    assert error.value.code == "DOCUMENT_CARD_DATA"

    def change(writer):
        value = TextStringObject(LUHN_DATE)
        if indirect:
            value = writer._add_object(value)
        info(writer)[NameObject("/CreationDate")] = value
        info(writer)[NameObject("/ModDate")] = value

    with worker._pdf(pdf(change)) as reader:
        assert len(reader.pages) == 1


@pytest.mark.parametrize("date_first", [False, True])
@pytest.mark.parametrize("alias", ["title", "page", "array", "orphan"])
def test_shared_indirect_date_is_rescanned_outside_typed_edge(date_first, alias):
    def change(writer):
        value = writer._add_object(TextStringObject(LUHN_DATE))
        metadata = info(writer)
        if date_first:
            metadata[NameObject("/CreationDate")] = value
        if alias == "title":
            metadata[NameObject("/Title")] = value
        elif alias == "page":
            writer.pages[0][NameObject("/SyntheticText")] = value
        elif alias == "array":
            metadata[NameObject("/SyntheticArray")] = ArrayObject([value])
        else:
            writer._add_object(DictionaryObject({NameObject("/SyntheticText"): value}))
        if not date_first:
            metadata[NameObject("/CreationDate")] = value

    data = pdf(change)
    reject_card(info_first(data) if date_first else data)


@pytest.mark.parametrize("location", ["nested_info", "catalog", "orphan", "direct_info"])
def test_same_key_outside_canonical_info_is_not_a_date_exception(location):
    def change(writer):
        dictionary = DictionaryObject({NameObject("/CreationDate"): TextStringObject(LUHN_DATE)})
        if location == "nested_info":
            info(writer)[NameObject("/SyntheticNested")] = dictionary
        elif location == "catalog":
            writer._root_object[NameObject("/CreationDate")] = TextStringObject(LUHN_DATE)
        elif location == "orphan":
            writer._add_object(dictionary)

    data = pdf(change)
    if location == "direct_info":
        data = re.sub(
            rb"/Info [0-9]+ 0 R", b"/Info << /CreationDate (" + LUHN_DATE.encode() + b") >>", data
        )
    reject_card(data)


@pytest.mark.parametrize("alias_first", [False, True])
def test_info_dictionary_alias_does_not_share_its_typed_privilege(alias_first):
    def change(writer):
        writer.add_metadata({"/CreationDate": LUHN_DATE})
        writer._root_object[NameObject("/SyntheticAlias")] = writer._info

    data = pdf(change)
    if alias_first:
        # Move /Info before /Root in the trailer to exercise the opposite visit order.
        data = info_first(data)
    reject_card(data)


@pytest.mark.parametrize(
    "wrapper", [ArrayObject, lambda value: DictionaryObject({NameObject("/Value"): value[0]})]
)
def test_container_in_date_field_does_not_grant_context_to_its_children(wrapper):
    def change(writer):
        info(writer)[NameObject("/CreationDate")] = wrapper([TextStringObject(LUHN_DATE)])

    reject_card(pdf(change))


def test_calendar_invalid_luhn_date_keeps_card_detection():
    value = "D:20260230000008Z"
    assert not worker._pdf_date(value)
    reject_card(pdf(lambda writer: writer.add_metadata({"/CreationDate": value})))


@pytest.mark.parametrize("typed_first", [False, True])
def test_visible_page_date_is_still_scanned_even_with_identical_info_date(typed_first):
    def change(writer):
        writer.add_metadata({"/CreationDate": LUHN_DATE})
        font = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
        )
        page = writer.pages[0]
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 10 10 Td (" + LUHN_DATE.encode() + b") Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)

    data = pdf(change)
    reject_card(info_first(data) if typed_first else data)


@pytest.fixture
def document_checks(monkeypatch):
    path = Path(__file__).resolve().parents[3] / "infra/documents/run_checks.py"
    spec = importlib.util.spec_from_file_location("synthetic_document_checks", path)
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    # Host unit tests need no system font. Real CJK OCR is covered by the image suite.
    font = ImageFont.load_default(size=52)
    monkeypatch.setattr(checks.ImageFont, "truetype", lambda *_args, **_kwargs: font)
    return checks


def test_fixture_pdf_bytes_are_identical_across_the_two_reproduction_clocks(
    monkeypatch, document_checks
):
    outputs = []
    for second in (0, 8):
        clock = time.struct_time((2026, 10, 18, 5, 19, second, 6, 291, 0))
        monkeypatch.setattr(PdfImagePlugin.time, "gmtime", lambda clock=clock: clock)
        data = document_checks.receipt("PDF", korean=True)
        outputs.append(data)
        with worker._pdf(data) as reader:
            metadata = reader.metadata or {}
            assert "/CreationDate" not in metadata and "/ModDate" not in metadata
    assert outputs[0] == outputs[1]


def test_dated_integration_fixture_preserves_its_real_receipt_page(document_checks):
    data = document_checks.metadata_pdf({"/CreationDate": LUHN_DATE, "/ModDate": LUHN_DATE})
    with worker._pdf(data) as reader:
        assert len(reader.pages) == 1
        assert reader.metadata["/CreationDate"] == LUHN_DATE
        assert reader.metadata["/ModDate"] == LUHN_DATE
