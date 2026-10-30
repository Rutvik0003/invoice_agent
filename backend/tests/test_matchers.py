"""Tests for the Stage 3 matchers with tricky real-world inputs."""

from datetime import date
from decimal import Decimal

import pytest

from app.verification.matchers import (
    match_amount,
    match_code,
    match_date,
    match_identifier,
    match_name,
    normalise_identifier,
    parse_amount,
    parse_date,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1,18,000.00", "118000.00"), ("Rs.118000/-", "118000"), ("Rs. 1,18,000/-", "118000"), ("₹1,18,000.00", "118000.00"),
        ("INR 118000.00", "118000.00"), ("118000", "118000"), ("-0.16", "-0.16"), ("1,227.15", "1227.15"),
        ("12,34,567.5", "1234567.5"),
    ],
)
def test_parse_amount_formats(text, expected):
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["Total", "18%", "PO-2026-1050", "27AAPFU0939F1ZV", "1,2,3", "", "Rs.", "1 Job"])
def test_parse_amount_rejects_non_amounts(text):
    assert parse_amount(text) is None


def test_amount_tolerance_is_one_rupee():
    assert match_amount(118000.0, "Rs. 1,18,000/-") == 100
    assert match_amount(118000.0, "1,18,001.00") == 100
    assert match_amount(118000.0, "1,18,000.99") == 100
    assert match_amount(118000.0, "1,18,002.00") is None
    assert match_amount(118000.0, "1,81,000.00") is None


@pytest.mark.parametrize(
    "value, text",
    [("INV/0881", "INV / 0881"), ("SIT/26-27/0881", "SIT-26-27-0881"), ("KOS-0457", "KOS/457"), ("inv-00457", "INV/457"),
     ("PO-2026-1050", "PO/2026/1050"), ("VE0393", "VE0393")],
)
def test_identifiers_match_across_styling(value, text):
    assert match_identifier(value, text, 90) == 100


def test_identifier_ocr_confusions():
    assert match_identifier("SO/2026/0881", "S0/2026/0881", 90) == 95  # O read as zero
    assert match_identifier("INV-1104", "lNV-1104", 90) == 95  # I read as l


@pytest.mark.parametrize("wrong", ["INV/0818", "INV/0882", "INV/0891", "INV/0981"])
def test_identifier_rejects_changed_or_swapped_digits(wrong):
    assert match_identifier("INV/0881", wrong, 90) is None


def test_letter_noise_with_identical_digits_is_tolerated():
    assert match_identifier("INV/0881", "INV/881X", 90) is not None


def test_long_identifier_swap_is_not_rescued_by_fuzzy():
    # 13 characters with two digits swapped scores > 90 on plain fuzzy ratio; the digit guard rejects it
    assert match_identifier("SIT/26-27/000881", "SIT/26-27/000818", 90) is None


def test_normalise_identifier():
    assert normalise_identifier(" kos-0457 ") == "KOS457"
    assert normalise_identifier("2026/KOS/57") == "2026KOS57"


def test_gstin_with_spaces_and_one_ocr_error():
    assert match_code("27AABCD1234F1Z5", "27AAB CD1234 F1Z5", allow_one_difference=False) == 100
    assert match_code("27AABCD1234F1Z5", "27 AABCD 1234 F1Z5", allow_one_difference=False) == 100
    assert match_code("27AABCD1234F1Z5", "27AABCD1234FIZ5", allow_one_difference=True) == 90
    assert match_code("27AABCD1234F1Z5", "27AABCD1234FIZ5", allow_one_difference=False) is None
    assert match_code("27AABCD1234F1Z5", "27AABCD1243FIZ5", allow_one_difference=True) is None


@pytest.mark.parametrize(
    "text", ["05-Mar-26", "05/03/2026", "5 Mar 2026", "March 5, 2026", "2026-03-05", "05.03.2026", "05-03-2026", "5-March-2026"]
)
def test_dates_in_every_printed_format(text):
    assert parse_date(text) == date(2026, 3, 5)
    assert match_date("2026-03-05", text) == 100


def test_dates_are_day_first_and_reject_other_days():
    assert parse_date("03/05/2026") == date(2026, 5, 3)
    assert match_date("2026-03-05", "06-Mar-26") is None
    assert parse_date("Mar") is None


def test_names_need_most_of_the_name():
    assert match_name("Sharma IT Solutions Pvt. Ltd.", "Sharma IT Solutions Pvt Ltd") >= 90
    assert match_name("Ramesh Packaging", "Ramesh Packaging") == 100
    assert match_name("Ramesh Packaging", "Packaging") is None  # a single shared word is not enough
    assert match_name("Ramesh Packaging", "Suresh Plastics") is None


def test_bare_small_numbers_do_not_verify_amounts():
    assert match_amount(5.0, "4") is None
    assert match_amount(12.0, "12") is None
    assert match_amount(0.0, "0.00") == 100
    assert match_amount(450.0, "450") == 100
