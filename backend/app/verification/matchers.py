"""Type-aware matchers: does a printed word (or a run of up to 6 words on one line) show this value?

Pure functions. Each returns a score 0-100 (None = no match). Higher scores win; exact beats fuzzy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from rapidfuzz import fuzz

from app.pipeline.normalise import normalise_code, normalise_identifier, parse_amount, parse_date
from app.verification.page_text import PageWords

MAX_RUN = 6
AMOUNT_TOLERANCE = Decimal("1.00")  # ± ₹1


@dataclass
class Candidate:
    """A single word or a run of adjacent words on the same printed line."""

    text: str
    page: int
    source: str
    bbox: tuple[float, float, float, float]
    n_words: int
    conf: float | None


def candidates(pages: list[PageWords], max_run: int = MAX_RUN) -> list[Candidate]:
    """Every word and every run of up to max_run adjacent words on the same line."""
    out = []
    for page in pages:
        lines: dict[tuple, list] = {}
        for word in page.words:
            lines.setdefault(word.line, []).append(word)
        for words in lines.values():
            words.sort(key=lambda w: w.bbox[0])
            for start in range(len(words)):
                for end in range(start + 1, min(start + max_run, len(words)) + 1):
                    run = words[start:end]
                    confs = [w.conf for w in run if w.conf is not None]
                    out.append(Candidate(
                        text=" ".join(w.text for w in run),
                        page=page.page,
                        source=page.source,
                        bbox=(min(w.bbox[0] for w in run), min(w.bbox[1] for w in run),
                              max(w.bbox[2] for w in run), max(w.bbox[3] for w in run)),
                        n_words=len(run),
                        conf=round(sum(confs) / len(confs), 1) if confs else None,
                    ))
    return out


# ---------------------------------------------------------------- amounts

RUPEE_MISREADS = "2%?Z€¥"  # how OCR commonly renders a printed ₹


def match_amount(value: float, text: str, ocr: bool = False) -> int | None:
    """Same amount within ± ₹1. For OCR text, a leading character that is a misread ₹ ('₹13,266' -> '213,266')
    is also tried without it, but only when what remains is a comma-formatted amount."""
    target = Decimal(str(value))
    digits = sum(ch.isdigit() for ch in text)
    if "." not in text and "," not in text and digits < 3:
        return None  # a bare '4' or '12' (a quantity, a line number) is not evidence for an amount
    parsed = parse_amount(text)
    if parsed is not None and abs(parsed - target) <= AMOUNT_TOLERANCE:
        return 100
    stripped = text.strip()
    if ocr and len(stripped) > 1 and stripped[0] in RUPEE_MISREADS and "," in stripped:
        rest = parse_amount(stripped[1:])
        if rest is not None and abs(rest - target) <= AMOUNT_TOLERANCE:
            return 90
    return None


# ---------------------------------------------------------------- identifiers (invoice number, PO ref)

OCR_CONFUSIONS = str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"})


def _confusion_forms(text: str) -> set[str]:
    """The identifier with OCR confusions mapped, both before and after normalising
    ('SO/0881' vs 'S0/0881' only line up one way, 'INV-0881' vs 'INV/881' only the other)."""
    return {normalise_identifier(text).translate(OCR_CONFUSIONS),
            normalise_identifier(text.upper().translate(OCR_CONFUSIONS))}


def match_identifier(value: str, text: str, fuzzy_min: int) -> int | None:
    """Exact after normalising; else equal after mapping OCR confusions (O/0, I/1, S/5, B/8, Z/2);
    else fuzzy >= fuzzy_min but only if every digit is identical (a changed or swapped digit never matches)."""
    a, b = normalise_identifier(value), normalise_identifier(text)
    if not a or not b:
        return None
    if a == b:
        return 100
    if _confusion_forms(value) & _confusion_forms(text):
        return 95
    ma, mb = a.translate(OCR_CONFUSIONS), b.translate(OCR_CONFUSIONS)
    digits = lambda s: re.sub(r"\D", "", s)  # noqa: E731
    if digits(ma) and digits(ma) == digits(mb):
        score = fuzz.ratio(ma, mb)
        if score >= fuzzy_min:
            return int(score)
    return None


# ---------------------------------------------------------------- codes (GSTIN, bank account)


def match_code(value: str, text: str, allow_one_difference: bool) -> int | None:
    """Exact (ignoring spaces); or at most one differing character when the text came from OCR."""
    a, b = normalise_code(value), normalise_code(text)
    if not a or not b:
        return None
    if a == b:
        return 100
    if allow_one_difference and len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1:
        return 90
    return None


# ---------------------------------------------------------------- dates

def match_date(value: str, text: str) -> int | None:
    """Same calendar date, however it is printed (value is ISO YYYY-MM-DD)."""
    try:
        target = date.fromisoformat(value)
    except (TypeError, ValueError):
        target = parse_date(value or "")
    parsed = parse_date(text)
    return 100 if target is not None and parsed == target else None


# ---------------------------------------------------------------- names


def _name_tokens(text: str) -> str:
    return re.sub(r"[^a-z0-9& ]", " ", text.lower()).strip()


def match_name(value: str, text: str, minimum: int = 90) -> int | None:
    """RapidFuzz token_set_ratio >= 90, and the printed run must be about as long as the name
    (otherwise a single shared word like 'Packaging' would match)."""
    a, b = _name_tokens(value), _name_tokens(text)
    if not a or not b or len(b) < 0.7 * len(a):
        return None
    score = fuzz.token_set_ratio(a, b)
    return int(score) if score >= minimum else None


# ---------------------------------------------------------------- amounts in words ("Rupees One Lakh ... Only")

_UNIT_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen".split())}
_TENS_WORDS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
_SCALE_WORDS = {"hundred": 100, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
                "million": 1_000_000, "crore": 10_000_000, "crores": 10_000_000}
_NUMBER_WORDS = set(_UNIT_WORDS) | set(_TENS_WORDS) | set(_SCALE_WORDS)


def _words_value(tokens: list[str]) -> int:
    """['one', 'lakh', 'eighteen', 'thousand'] -> 118000 (Indian lakh/crore and international scales)."""
    total, current = 0, 0
    for token in tokens:
        if token in _UNIT_WORDS:
            current += _UNIT_WORDS[token]
        elif token in _TENS_WORDS:
            current += _TENS_WORDS[token]
        elif token == "hundred":
            current = max(current, 1) * 100
        else:
            scale = _SCALE_WORDS[token]
            # 'twelve crore three lakh': everything so far below this scale is multiplied by it
            below = total % scale
            total = total - below + (below + max(current, 1)) * scale
            current = 0
    return total + current


def words_to_amount(text: str) -> Decimal | None:
    """An amount written in words -> Decimal ('Rupees One Lakh Eighteen Thousand and Fifty Paise Only' -> 118000.50);
    None if the text holds no number words. Paise are the number words just before 'paise' (always < 100)."""
    tokens = re.findall(r"[a-z]+", (text or "").lower())
    numbers = [t for t in tokens if t in _NUMBER_WORDS]
    if not numbers or not any(t in _SCALE_WORDS or t in ("rupees", "rupee", "rs", "inr", "only") for t in tokens):
        return None
    paise = 0
    if "paise" in tokens or "paisa" in tokens:
        end = tokens.index("paise" if "paise" in tokens else "paisa")
        start = end
        while start > 0 and (tokens[start - 1] in _UNIT_WORDS or tokens[start - 1] in _TENS_WORDS):
            start -= 1
        paise = _words_value(tokens[start:end]) if start < end else 0
        tokens = tokens[:start]
    rupee_tokens = [t for t in tokens if t in _NUMBER_WORDS]
    if not rupee_tokens and not paise:
        return None
    return Decimal(_words_value(rupee_tokens)) + Decimal(paise) / 100


def amount_in_words_candidates(pages: list[PageWords]) -> list[Candidate]:
    """Each printed line (and each line joined with the next, for wrapped text) as one candidate: amounts in
    words are long phrases, beyond the 6-word runs used for other values."""
    out = []
    for page in pages:
        lines: dict[tuple, list] = {}
        for word in page.words:
            lines.setdefault(word.line, []).append(word)
        ordered = sorted((sorted(ws, key=lambda w: w.bbox[0]) for ws in lines.values()),
                         key=lambda ws: (min(w.bbox[1] for w in ws), ws[0].bbox[0]))
        for words in ordered + [a + b for a, b in zip(ordered, ordered[1:])]:
            confs = [w.conf for w in words if w.conf is not None]
            out.append(Candidate(" ".join(w.text for w in words), page.page, page.source,
                                 (min(w.bbox[0] for w in words), min(w.bbox[1] for w in words),
                                  max(w.bbox[2] for w in words), max(w.bbox[3] for w in words)),
                                 len(words), round(sum(confs) / len(confs), 1) if confs else None))
    return out


def match_amount_in_words(value: float, text: str) -> int | None:
    """The phrase, read as an amount in words, equals the value within ± ₹1 (scores below a printed figure)."""
    parsed = words_to_amount(text)
    if parsed is None or abs(parsed - Decimal(str(value))) > AMOUNT_TOLERANCE:
        return None
    return 85
