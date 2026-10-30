"""How values are printed on invoices: Indian number grouping, amount and date styles, amount in words."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

AMOUNT_STYLES = ("rupee_symbol", "rs_slash", "inr_plain", "no_symbol")
DATE_STYLES = ("dd/mm/yyyy", "dd-mm-yyyy", "d Mon yyyy", "dd-Mon-yy", "Month d, yyyy", "yyyy-mm-dd")


def indian_grouping(value: Decimal, decimals: bool = True) -> str:
    """1234567.5 -> '12,34,567.50' (lakh/crore grouping)."""
    value = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if value < 0 else ""
    rupees, paise = f"{abs(value):.2f}".split(".")
    head, tail = rupees[:-3], rupees[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    grouped = ",".join(groups + [tail]) if groups else tail
    return f"{sign}{grouped}.{paise}" if decimals else f"{sign}{grouped}"


def format_amount(value: Decimal, style: str) -> str:
    """Print a summary amount in one of the styles seen on Indian invoices."""
    value = Decimal(value)
    whole = value == value.to_integral_value()
    if style == "rupee_symbol":
        return f"₹{indian_grouping(value)}"
    if style == "rs_slash":
        return f"Rs. {indian_grouping(value, decimals=False)}/-" if whole else f"Rs. {indian_grouping(value)}"
    if style == "inr_plain":
        return f"INR {value:.2f}"
    if style == "no_symbol":
        return indian_grouping(value, decimals=False) if whole else indian_grouping(value)
    raise ValueError(f"Unknown amount style {style!r}")


def format_number(value: Decimal) -> str:
    """Table figures: Indian grouping, always two decimals."""
    return indian_grouping(Decimal(value))


def format_date(value: date, style: str) -> str:
    if style == "dd/mm/yyyy":
        return value.strftime("%d/%m/%Y")
    if style == "dd-mm-yyyy":
        return value.strftime("%d-%m-%Y")
    if style == "d Mon yyyy":
        return f"{value.day} {value.strftime('%b %Y')}"
    if style == "dd-Mon-yy":
        return value.strftime("%d-%b-%y")
    if style == "Month d, yyyy":
        return f"{value.strftime('%B')} {value.day}, {value.year}"
    if style == "yyyy-mm-dd":
        return value.isoformat()
    raise ValueError(f"Unknown date style {style!r}")


def spaced_gstin(gstin: str) -> str:
    """27AAPFU0939F1ZV -> '27 AAPFU 0939 F1ZV' (how some vendors print it)."""
    return f"{gstin[:2]} {gstin[2:7]} {gstin[7:11]} {gstin[11:]}"


_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
    "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen",
]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _below_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + " " + _ONES[n % 10]).strip()


def _below_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = [f"{_ONES[hundreds]} Hundred"] if hundreds else []
    if rest:
        parts.append(_below_hundred(rest))
    return " ".join(parts)


def number_to_indian_words(n: int) -> str:
    """1234567 -> 'Twelve Lakh Thirty Four Thousand Five Hundred Sixty Seven'."""
    if n == 0:
        return "Zero"
    parts = []
    for size, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1_000, "Thousand")):
        count, n = divmod(n, size)
        if count:
            parts.append(f"{number_to_indian_words(count) if count >= 100 else _below_hundred(count)} {name}")
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def amount_in_words(value: Decimal) -> str:
    """'Rupees One Lakh Twenty Three Thousand Four Hundred Fifty Six and Fifty Paise Only'."""
    value = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rupees = int(value)
    paise = int((value - rupees) * 100)
    words = f"Rupees {number_to_indian_words(rupees)}"
    if paise:
        words += f" and {_below_hundred(paise)} Paise"
    return words + " Only"


ABBREVIATIONS = {
    "Private": "Pvt.", "Limited": "Ltd.", "Solutions": "Solns", "Technologies": "Tech.", "Services": "Servs.",
    "Industries": "Inds.", "Enterprises": "Ent.", "Systems": "Sys.", "Management": "Mgmt.", "Engineering": "Engg.",
    "Electricals": "Elec.", "Infotech": "Infotech", "Logistics": "Logistics", "Company": "Co.",
}


def abbreviate_name(name: str) -> str:
    """Sharma IT Solutions Private Limited -> Sharma IT Solns Pvt. Ltd."""
    return " ".join(ABBREVIATIONS.get(word, word) for word in name.split())
