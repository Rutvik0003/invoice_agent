"""Turn printed values into comparable ones: dates, amounts, invoice numbers, GSTINs, names.

Shared by Stage 3 (finding values on the page) and Stages 4-8 (the rules), so both always agree on
what, say, 'KOS-0457' or 'Rs. 1,18,000/-' means.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

# ---------------------------------------------------------------- amounts

_CURRENCY = re.compile(r"(₹|rs\.?|inr|रु\.?|रू\.?|\$|usd|/-|\s)", re.IGNORECASE)
# Hindi invoices may print Devanagari digits (१,१८,०००); they mean exactly the same numbers
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_AMOUNT = re.compile(r"-?\d{1,3}(,\d{2})*,\d{3}(\.\d+)?|-?\d+(\.\d+)?")


def parse_amount(text: str) -> Decimal | None:
    """'₹1,18,000.00', 'Rs.118000/-', 'INR 118000.00', '1,18,000' -> Decimal; anything else -> None."""
    cleaned = _CURRENCY.sub("", (text or "").translate(_DEVANAGARI_DIGITS)).strip(":")
    if not cleaned or not _AMOUNT.fullmatch(cleaned):
        return None
    try:
        return Decimal(cleaned.replace(",", ""))
    except InvalidOperation:
        return None


def to_decimal(value: object) -> Decimal | None:
    """A model value (float, int or printed string) as Decimal rounded to paise; None stays None."""
    if value is None:
        return None
    if isinstance(value, str):
        parsed = parse_amount(value)
        return None if parsed is None else parsed.quantize(Decimal("0.01"))
    return Decimal(str(value)).quantize(Decimal("0.01"))


# ---------------------------------------------------------------- dates

DATE_FORMATS = (
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
    "%d %b %Y", "%d-%b-%Y", "%d-%b-%y", "%d %b %y", "%d %B %Y", "%d-%B-%Y",
    "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%Y-%m-%d", "%Y/%m/%d",
)


def parse_date(text: str | None) -> date | None:
    """Day-first Indian dates in the common printed formats (and ISO) -> date."""
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text.translate(_DEVANAGARI_DIGITS).strip().strip(":,;")).replace("Sept", "Sep")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- invoice numbers / PO numbers

_ID_SEPARATORS = re.compile(r"[\s\-/_.]")


def normalise_identifier(text: str) -> str:
    """Uppercase, drop spaces / - / _ . and strip leading zeros of a trailing number (KOS-0457 == KOS/457)."""
    compact = _ID_SEPARATORS.sub("", (text or "").upper())
    match = re.fullmatch(r"([A-Z]*)0*(\d+)", compact)
    return f"{match.group(1)}{match.group(2)}" if match else compact


normalise_invoice_number = normalise_identifier


# ---------------------------------------------------------------- GSTIN, bank account, IFSC


def normalise_code(text: str) -> str:
    """GSTIN / account / IFSC: uppercase, no spaces, dashes, dots or colons."""
    return re.sub(r"[\s\-.:]", "", (text or "").upper())


def gstin_state(gstin: str | None) -> str | None:
    """First two digits of a GSTIN = the supplier's state code."""
    code = normalise_code(gstin or "")[:2]
    return code if len(code) == 2 and code.isdigit() else None


# GSTIN = 2-digit state + PAN (5 letters, 4 digits, 1 letter) + entity (1-9 / A-Z) + 'Z' + check character
GSTIN_PATTERN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_GSTIN_SLOTS = "DDLLLLLDDDDLEZC"  # D digit, L letter, E entity, Z the letter Z, C check character
_AS_LETTER = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}
_AS_DIGIT = {"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "G": "6", "B": "8"}
_BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_char(first14: str) -> str:
    """The GSTIN's 15th character: a mod-36 checksum of the first 14."""
    total = 0
    for index, char in enumerate(first14):
        product = _BASE36.index(char) * (1 if index % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _BASE36[(36 - total % 36) % 36]


def gstin_valid(gstin: str) -> bool:
    """Right shape and a correct check character."""
    return bool(GSTIN_PATTERN.match(gstin)) and gstin_check_char(gstin[:14]) == gstin[14]


def repair_gstin(text: str | None) -> str | None:
    """A misread GSTIN corrected, or None. A look-alike character is swapped only where the GSTIN format forbids
    what was read (a digit in a letter-only place: 0 -> O, 1 -> I, ...; a letter in a digit-only place: O -> 0),
    and the result is kept only if its check character is then correct. A GSTIN already valid is not changed."""
    code = normalise_code(text or "")
    if len(code) != 15 or gstin_valid(code):
        return None
    fixed = []
    for char, slot in zip(code, _GSTIN_SLOTS):
        if slot == "D" and not char.isdigit():
            char = _AS_DIGIT.get(char, char)
        elif slot in "LZ" and not char.isalpha():
            char = _AS_LETTER.get(char, char)
        elif slot == "E" and char == "0":
            char = "O"
        fixed.append(char)
    repaired = "".join(fixed)
    return repaired if repaired != code and gstin_valid(repaired) else None


# ---------------------------------------------------------------- names

_NAME_WORDS = {"private": "pvt", "limited": "ltd", "and": "&", "company": "co"}


def normalise_name(text: str) -> str:
    """'M/s Sharma IT Solutions Private Limited' -> 'sharma it solutions pvt ltd' (for fuzzy comparison)."""
    lowered = re.sub(r"^\s*m/?s\.?\s+", "", (text or "").lower())
    words = re.sub(r"[^a-z0-9& ]", " ", lowered).split()
    return " ".join(_NAME_WORDS.get(w, w) for w in words)
