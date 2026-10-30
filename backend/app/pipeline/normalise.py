"""Turn printed values into comparable ones: dates, amounts, invoice numbers, GSTINs, names.

Shared by Stage 3 (finding values on the page) and Stages 4-8 (the rules), so both always agree on
what, say, 'KOS-0457' or 'Rs. 1,18,000/-' means.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

# ---------------------------------------------------------------- amounts

_CURRENCY = re.compile(r"(₹|rs\.?|inr|/-|\s)", re.IGNORECASE)
_AMOUNT = re.compile(r"-?\d{1,3}(,\d{2})*,\d{3}(\.\d+)?|-?\d+(\.\d+)?")


def parse_amount(text: str) -> Decimal | None:
    """'₹1,18,000.00', 'Rs.118000/-', 'INR 118000.00', '1,18,000' -> Decimal; anything else -> None."""
    cleaned = _CURRENCY.sub("", text or "").strip(":")
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
    cleaned = re.sub(r"\s+", " ", text.strip().strip(":,;")).replace("Sept", "Sep")
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


# ---------------------------------------------------------------- names

_NAME_WORDS = {"private": "pvt", "limited": "ltd", "and": "&", "company": "co"}


def normalise_name(text: str) -> str:
    """'M/s Sharma IT Solutions Private Limited' -> 'sharma it solutions pvt ltd' (for fuzzy comparison)."""
    lowered = re.sub(r"^\s*m/?s\.?\s+", "", (text or "").lower())
    words = re.sub(r"[^a-z0-9& ]", " ", lowered).split()
    return " ".join(_NAME_WORDS.get(w, w) for w in words)
