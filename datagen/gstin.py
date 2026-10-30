"""PAN, GSTIN (with checksum), IFSC and bank account generators, plus GSTIN validation."""

import random
import re
import string

ALPHABET = string.digits + string.ascii_uppercase  # GSTIN checksum alphabet: 0-9 then A-Z (base 36)

# GST state codes used in this project (code -> state name)
STATES: dict[str, str] = {
    "03": "Punjab",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "19": "West Bengal",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "27": "Maharashtra",
    "29": "Karnataka",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "36": "Telangana",
}

# PAN 4th character = holder type
PAN_ENTITY_TYPES = {"C": "company", "F": "firm / LLP", "P": "individual / proprietor"}

GSTIN_PATTERN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def gstin_checksum(first14: str) -> str:
    """Mod-36 check character for the first 14 GSTIN characters."""
    total = 0
    for index, char in enumerate(first14):
        factor = 1 if index % 2 == 0 else 2
        product = ALPHABET.index(char) * factor
        total += product // 36 + product % 36
    return ALPHABET[(36 - total % 36) % 36]


def make_pan(entity_type: str, rng: random.Random | None = None, name_initial: str | None = None) -> str:
    """PAN: 3 letters + holder type + name initial + 4 digits + 1 letter."""
    if entity_type not in PAN_ENTITY_TYPES:
        raise ValueError(f"Unknown PAN entity type {entity_type!r}")
    rng = rng or random.Random()
    letters = string.ascii_uppercase
    initial = (name_initial or rng.choice(letters)).upper()
    return (
        "".join(rng.choice(letters) for _ in range(3))
        + entity_type
        + initial
        + f"{rng.randint(1, 9999):04d}"
        + rng.choice(letters)
    )


def make_gstin(state_code: str, pan: str, entity_no: int = 1) -> str:
    """GSTIN: state code + PAN + entity number (1-9, A-Z) + 'Z' + check character."""
    if state_code not in STATES:
        raise ValueError(f"Unknown state code {state_code!r}")
    if not 1 <= entity_no <= 35:
        raise ValueError("entity_no must be 1-35")
    first14 = state_code + pan + ALPHABET[entity_no] + "Z"
    return first14 + gstin_checksum(first14)


def validate_gstin(gstin: str) -> bool:
    """A GSTIN is valid if it has the right shape and its last character matches the checksum."""
    if not isinstance(gstin, str) or not GSTIN_PATTERN.match(gstin):
        return False
    return gstin_checksum(gstin[:14]) == gstin[14]


def make_ifsc(bank_code: str, rng: random.Random | None = None) -> str:
    """IFSC: 4-letter bank code + '0' + 6-character branch code (mostly digits, like real IFSCs)."""
    rng = rng or random.Random()
    return bank_code + "0" + "".join(rng.choice(string.digits) for _ in range(6))


def make_bank_account(rng: random.Random | None = None) -> str:
    """Bank account number of 9-18 digits, never starting with 0."""
    rng = rng or random.Random()
    length = rng.randint(9, 18)
    return str(rng.randint(1, 9)) + "".join(rng.choice(string.digits) for _ in range(length - 1))


def validate_ifsc(ifsc: str) -> bool:
    """IFSC format check: 4 letters, a zero, 6 alphanumerics."""
    return bool(IFSC_PATTERN.match(ifsc or ""))


def validate_bank_account(account: str) -> bool:
    """Bank account format check: 9-18 digits."""
    return bool(re.fullmatch(r"\d{9,18}", account or ""))
