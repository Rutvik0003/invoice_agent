"""Stage 7: match invoice lines to PO lines and check items, quantities, prices and the PO total (2-way match)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.config import Settings
from app.pipeline.normalise import to_decimal
from app.pipeline.po_match import description_score, invoice_taxable
from app.pipeline.reason_codes import ReasonCode, inr, passed, raised, show
from app.pipeline.repository import PORecord, POLineRecord
from app.schemas import CheckEvidence, CheckResult, ExtractedInvoice

STAGE = "amount_match"
LINE_MATCH_MIN = 85  # description similarity for an invoice line to map onto a PO line
PAISA = Decimal("0.005")


@dataclass
class LineMatch:
    """An invoice line mapped onto a PO line (or not found on the PO)."""

    index: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    po_line: POLineRecord | None


def tolerance(value: Decimal, settings: Settings) -> Decimal:
    """A variance is acceptable up to min(TOLERANCE_PCT % of the value, TOLERANCE_ABS_INR)."""
    pct = (value * Decimal(str(settings.tolerance_pct)) / 100).quantize(Decimal("0.01"))
    return min(pct, Decimal(str(settings.tolerance_abs_inr)))


def map_lines(inv: ExtractedInvoice, po: PORecord) -> list[LineMatch]:
    """Greedy best-first mapping on description similarity, unit price as tie-break; each PO line used once."""
    pairs = []
    for i, line in enumerate(inv.line_items):
        price = to_decimal(line.unit_price) or Decimal("0")
        for po_line in po.lines:
            score = description_score(line.description, po_line.description)
            if score >= LINE_MATCH_MIN:
                pairs.append((score, -abs(price - po_line.unit_price), i, po_line))
    pairs.sort(key=lambda p: (p[0], p[1]), reverse=True)
    used_lines, used_po_lines, mapping = set(), set(), {}
    for _, _, i, po_line in pairs:
        if i not in used_lines and po_line.line_no not in used_po_lines:
            mapping[i] = po_line
            used_lines.add(i)
            used_po_lines.add(po_line.line_no)
    matches = []
    for i, line in enumerate(inv.line_items):
        qty = Decimal(str(line.quantity)) if line.quantity is not None else Decimal("0")
        price = to_decimal(line.unit_price) or Decimal("0")
        amount = to_decimal(line.amount) if line.amount is not None else (qty * price).quantize(Decimal("0.01"))
        matches.append(LineMatch(i, line.description or f"line {i + 1}", qty, price, amount, mapping.get(i)))
    return matches


def check_items(matches: list[LineMatch], po: PORecord) -> list[CheckResult]:
    """Every invoice line must be an item on the PO."""
    out = [raised(STAGE, "item_on_po", ReasonCode.ITEM_NOT_ON_PO,
                  CheckEvidence(invoice_field=f"line_items[{m.index}]", invoice_value=m.description,
                                reference_source=po.po_number, reference_value=[l.description for l in po.lines]),
                  item=m.description, amount=inr(m.amount), po=po.po_number)
           for m in matches if m.po_line is None]
    return out or [passed(STAGE, "item_on_po", f"Every line is an item on {po.po_number}.")]


def check_quantities(matches: list[LineMatch], po: PORecord) -> list[CheckResult]:
    """Quantity billed on each line must not exceed what is still open on the PO line."""
    out = []
    for m in matches:
        if m.po_line is None or m.quantity <= m.po_line.qty_remaining:
            continue
        out.append(raised(STAGE, "quantity", ReasonCode.QTY_EXCEEDS_PO,
                          CheckEvidence(invoice_field=f"line_items[{m.index}].quantity", invoice_value=float(m.quantity),
                                        reference_source=f"{po.po_number} line {m.po_line.line_no}",
                                        reference_value=float(m.po_line.qty_remaining)),
                          item=m.description, billed=show(m.quantity), unit=m.po_line.unit,
                          remaining=show(m.po_line.qty_remaining), ordered=show(m.po_line.qty_ordered),
                          po=po.po_number, line=m.po_line.line_no))
    return out or [passed(STAGE, "quantity", "Quantities are within what is still open on the PO.")]


def check_prices(matches: list[LineMatch], po: PORecord, settings: Settings) -> list[CheckResult]:
    """Unit price may exceed the PO price by at most min(1% of the line value, ₹500); a small excess is noted."""
    out = []
    for m in matches:
        if m.po_line is None:
            continue
        diff = m.unit_price - m.po_line.unit_price
        if diff <= PAISA:  # same price, or cheaper than the PO
            continue
        line_diff = (diff * m.quantity).quantize(Decimal("0.01"))
        allowed = tolerance(m.po_line.unit_price * m.quantity, settings)
        pct = (diff / m.po_line.unit_price * 100).quantize(Decimal("0.01"))
        code = ReasonCode.PRICE_VARIANCE_WITHIN_TOLERANCE if line_diff <= allowed else ReasonCode.PRICE_VARIANCE_OVER_TOLERANCE
        out.append(raised(STAGE, "unit_price", code,
                          CheckEvidence(invoice_field=f"line_items[{m.index}].unit_price", invoice_value=float(m.unit_price),
                                        reference_source=f"{po.po_number} line {m.po_line.line_no}",
                                        reference_value=float(m.po_line.unit_price)),
                          billed=inr(m.unit_price), item=m.description, pct=f"{pct:g}", po_price=inr(m.po_line.unit_price),
                          line_diff=inr(line_diff), tolerance=inr(allowed)))
    return out or [passed(STAGE, "unit_price", "Unit prices match the PO.")]


def check_po_total(inv: ExtractedInvoice, po: PORecord, settings: Settings) -> CheckResult:
    """Already billed on the PO plus this invoice (before tax) must not exceed the PO value + tolerance."""
    this_invoice = invoice_taxable(inv)
    total_billed = po.billed_value + this_invoice
    allowed = tolerance(po.taxable_value, settings)
    evidence = CheckEvidence(invoice_field="subtotal", invoice_value=float(this_invoice),
                             reference_source=f"{po.po_number} value and billing history",
                             reference_value=f"value {inr(po.taxable_value)}, billed {inr(po.billed_value)}")
    if total_billed <= po.taxable_value + allowed:
        return passed(STAGE, "po_total", f"Billed so far ₹{inr(po.billed_value)} + this invoice ₹{inr(this_invoice)} "
                                         f"is within the PO value ₹{inr(po.taxable_value)}.", evidence)
    return raised(STAGE, "po_total", ReasonCode.PO_OVERRUN, evidence, po=po.po_number, po_value=inr(po.taxable_value),
                  billed_before=inr(po.billed_value), this_invoice=inr(this_invoice), total_billed=inr(total_billed),
                  over=inr(total_billed - po.taxable_value), tolerance=inr(allowed),
                  remaining=inr(max(po.remaining_value, Decimal("0"))))


def run_amount_match(inv: ExtractedInvoice, po: PORecord, settings: Settings) -> tuple[list[LineMatch], list[CheckResult]]:
    matches = map_lines(inv, po)
    checks = check_items(matches, po) + check_quantities(matches, po) + check_prices(matches, po, settings)
    checks.append(check_po_total(inv, po, settings))
    return matches, checks
