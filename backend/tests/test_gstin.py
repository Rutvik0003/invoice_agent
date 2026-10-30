"""Tests for datagen.gstin: PAN, GSTIN checksum, IFSC and bank account generators."""

import random
import string

import pytest

from datagen.gstin import (
    STATES,
    gstin_checksum,
    make_bank_account,
    make_gstin,
    make_ifsc,
    make_pan,
    validate_bank_account,
    validate_gstin,
    validate_ifsc,
)

# Publicly documented example with a worked checksum calculation (taxclue.in GSTIN validator;
# also the standard example for python-stdnum's GSTIN module).
PUBLIC_VALID_GSTIN = "27AAPFU0939F1ZV"


def test_public_example_gstin_is_valid():
    assert validate_gstin(PUBLIC_VALID_GSTIN)
    assert gstin_checksum(PUBLIC_VALID_GSTIN[:14]) == "V"


def test_round_trip_1000_generated_gstins():
    rng = random.Random(1)
    for _ in range(1000):
        pan = make_pan(rng.choice("CFP"), rng)
        gstin = make_gstin(rng.choice(list(STATES)), pan, rng.randint(1, 9))
        assert len(gstin) == 15
        assert validate_gstin(gstin), gstin


def _same_class_substitute(char: str, rng: random.Random) -> str:
    pool = string.digits if char.isdigit() else string.ascii_uppercase
    return rng.choice([c for c in pool if c != char])


def test_any_single_character_change_is_rejected():
    rng = random.Random(2)
    gstin = make_gstin("27", make_pan("C", rng), 1)
    for position in range(15):
        tampered = gstin[:position] + _same_class_substitute(gstin[position], rng) + gstin[position + 1:]
        assert not validate_gstin(tampered), f"change at position {position} not detected: {tampered}"


@pytest.mark.parametrize(
    "bad",
    ["", "27AAPFU0939F1Z", "27AAPFU0939F1ZVX", "27aapfu0939f1zv", "27AAPFU0939F1YV", "2AAAPFU0939F1ZV", None],
)
def test_malformed_gstins_are_rejected(bad):
    assert not validate_gstin(bad)


def test_pan_format_and_entity_type():
    rng = random.Random(3)
    for entity in "CFP":
        pan = make_pan(entity, rng, name_initial="s")
        assert len(pan) == 10
        assert pan[:5].isalpha() and pan[5:9].isdigit() and pan[9].isalpha()
        assert pan[3] == entity
        assert pan[4] == "S"


def test_unknown_entity_type_or_state_is_an_error():
    with pytest.raises(ValueError):
        make_pan("X")
    with pytest.raises(ValueError):
        make_gstin("99", "AAAPA1234A")


def test_gstin_embeds_state_pan_and_entity_number():
    gstin = make_gstin("29", "ABCPD1234E", 2)
    assert gstin.startswith("29ABCPD1234E2Z")


def test_ifsc_and_account_formats():
    rng = random.Random(4)
    for _ in range(200):
        ifsc = make_ifsc("HDFC", rng)
        account = make_bank_account(rng)
        assert validate_ifsc(ifsc) and ifsc.startswith("HDFC0")
        assert validate_bank_account(account) and 9 <= len(account) <= 18 and account[0] != "0"
    assert not validate_ifsc("HDFC1234567")
    assert not validate_bank_account("12345678")
