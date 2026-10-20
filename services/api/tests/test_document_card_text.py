"""Card-number candidates follow card digit groupings, not every long run of digits."""

import time

import pytest

from sallimbook.documents import _validation_worker as worker

PAN = "4123456789012349"  # 기존 synthetic_pan()과 같은 합성 번호
TSV_HEADER = (
    b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
    b"left\ttop\twidth\theight\tconf\ttext\n"
)


def tsv(words, confidence=95):
    return TSV_HEADER + b"".join(
        f"5\t1\t1\t1\t1\t{i}\t0\t0\t20\t20\t{confidence}\t{word}\n".encode()
        for i, word in enumerate(words, 1)
    )


def assert_rejected(action, code="DOCUMENT_UNSAFE"):
    with pytest.raises(worker.Rejected) as error:
        action()
    assert error.value.code == code
    assert str(error.value) == code


@pytest.mark.parametrize(
    "text",
    [
        PAN,
        "4123 4567 8901 2349",
        "4123-4567-8901-2349",
        "4123 - 4567 - 8901 - 2349",
        "3712 345678 90120",
        "3012 345678 9019",
        "6212 3456 7890 1234 569",
        "４１２３ ４５６７ ８９０１ ２３４９",
        "No 1 4123 4567 8901 2349",
        "4 1 2 3 4 5 6 7 8 9 0 1 2 3 4 9",
    ],
)
def test_real_pan_layouts_are_still_card_data(text):
    assert_rejected(lambda: worker._card_text(text), "DOCUMENT_CARD_DATA")


@pytest.mark.parametrize(
    "text",
    [
        "2026.02.22 2026.03.01",
        "2026-02-22 2026-03-01",
        "20260222 20260301",
        "2026 02 22 2026 03 01",
        "1002-006-456789",
        "합성 진료비 영수증 2026-10-17 금액 25000",
        "4123 4567 8901 2340",
        "0000 0000 0000 0000",
    ],
)
def test_dates_accounts_and_invalid_numbers_are_not_card_data(text):
    worker._card_text(text)


def test_ocr_word_join_does_not_turn_a_date_pair_into_a_card_number():
    assert worker._ocr_words(tsv(["진료기간", "2026.02.22", "2026.03.01", "SYNTHETIC", "RECEIPT"]))


def test_card_group_scan_stays_linear_on_long_digit_runs():
    started = time.monotonic()
    for text in ("1 " * 100_000, "1234 " * 50_000, "12 " * 300_000):
        worker._card_text(text)
    assert time.monotonic() - started < 2.0


# User decision 2026-10-20: sideways text OCRs as long digit blobs with confidence 4–22 and
# ~10% pass Luhn by chance, while real card numbers read at 95+ in their upright orientation.
@pytest.mark.parametrize("confidence", [0, 10, 29])
def test_low_confidence_unbroken_digit_word_is_not_a_card_candidate(confidence):
    assert not worker._ocr_words(tsv(["SYNTHETIC", PAN, "RECEIPT"], confidence))


@pytest.mark.parametrize("confidence", [30, 95])
def test_confident_unbroken_digit_word_is_card_data(confidence):
    assert_rejected(lambda: worker._ocr_words(tsv([PAN], confidence)), "DOCUMENT_CARD_DATA")


def test_grouped_low_confidence_card_number_is_still_card_data():
    assert_rejected(
        lambda: worker._ocr_words(tsv(["4123", "4567", "8901", "2349"], 5)), "DOCUMENT_CARD_DATA"
    )


def test_low_confidence_blob_cannot_join_neighbouring_digit_words():
    # The ignored blob ends the digit run instead of vanishing between its neighbours.
    words = ["4123", "4567", "2452424446244", "8901", "2349"]
    worker._ocr_words(tsv(words, 10))
