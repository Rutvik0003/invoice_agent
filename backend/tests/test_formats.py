"""Tests for datagen.formats: how amounts, dates and names are printed."""

from datetime import date
from decimal import Decimal

import pytest

from datagen.formats import (
    abbreviate_name,
    amount_in_words,
    format_amount,
    format_date,
    indian_grouping,
    number_to_indian_words,
    spaced_gstin,
)


@pytest.mark.parametrize(
    "value, expected",
    [("0", "0.00"), ("999", "999.00"), ("1000", "1,000.00"), ("123456", "1,23,456.00"),
     ("12345678.5", "1,23,45,678.50"), ("-4500.25", "-4,500.25")],
)
def test_indian_grouping(value, expected):
    assert indian_grouping(Decimal(value)) == expected


@pytest.mark.parametrize(
    "style, value, expected",
    [
        ("rupee_symbol", "123456", "₹1,23,456.00"),
        ("rs_slash", "123456", "Rs. 1,23,456/-"),
        ("rs_slash", "123456.50", "Rs. 1,23,456.50"),
        ("inr_plain", "123456", "INR 123456.00"),
        ("no_symbol", "123456", "1,23,456"),
        ("no_symbol", "123456.75", "1,23,456.75"),
    ],
)
def test_amount_styles(style, value, expected):
    assert format_amount(Decimal(value), style) == expected


@pytest.mark.parametrize(
    "style, expected",
    [("dd/mm/yyyy", "05/03/2026"), ("dd-mm-yyyy", "05-03-2026"), ("d Mon yyyy", "5 Mar 2026"),
     ("dd-Mon-yy", "05-Mar-26"), ("Month d, yyyy", "March 5, 2026"), ("yyyy-mm-dd", "2026-03-05")],
)
def test_date_styles(style, expected):
    assert format_date(date(2026, 3, 5), style) == expected


def test_amount_in_words_uses_lakh_and_crore():
    assert number_to_indian_words(123456) == "One Lakh Twenty Three Thousand Four Hundred Fifty Six"
    assert number_to_indian_words(10_000_000) == "One Crore"
    assert amount_in_words(Decimal("1001.50")) == "Rupees One Thousand One and Fifty Paise Only"


def test_spaced_gstin_and_abbreviation():
    assert spaced_gstin("27AAPFU0939F1ZV") == "27 AAPFU 0939 F1ZV"
    assert abbreviate_name("Sharma IT Solutions Private Limited") == "Sharma IT Solns Pvt. Ltd."
