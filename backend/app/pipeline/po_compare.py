"""Side-by-side view of an invoice and a purchase order, for the person resolving a hold.

Same rules as Stage 7 (line mapping, quantity, price tolerance, PO balance), laid out line by line so the
differences can be read at a glance. Pure function: reads the PO, decides nothing, changes nothing.
"""

from __future__ import annotations

from decimal import Decimal

from app.config import Settings
from app.pipeline.amount_match import PAISA, map_lines, tolerance
from app.pipeline.po_match import invoice_taxable
from app.pipeline.repository import PORecord
from app.schemas import ExtractedInvoice


def _f(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def price_status(unit_price: Decimal, po_price: Decimal, quantity: Decimal, settings: Settings) -> tuple[str, Decimal]:
    """(match | below_po | within_tolerance | over_tolerance, extra billed on the line)."""
    diff = unit_price - po_price
    if abs(diff) <= PAISA:
        return "match", Decimal("0.00")
    if diff < 0:
        return "below_po", (diff * quantity).quantize(Decimal("0.01"))
    line_diff = (diff * quantity).quantize(Decimal("0.01"))
    return ("within_tolerance" if line_diff <= tolerance(po_price * quantity, settings) else "over_tolerance"), line_diff


def compare(inv: ExtractedInvoice, po: PORecord, vendor_id: str | None, settings: Settings) -> dict:
    """Invoice lines against PO lines, the PO balance before and after this invoice, and what does not match."""
    matches = map_lines(inv, po)
    lines = []
    for m in matches:
        row = {"index": m.index, "description": m.description, "quantity": _f(m.quantity), "unit_price": _f(m.unit_price),
               "amount": _f(m.amount), "adjustment": m.adjustment, "po_line": None, "issues": []}
        if m.po_line is None:
            if not m.adjustment:
                row["issues"].append("not_on_po")
        else:
            pl = m.po_line
            status, line_diff = price_status(m.unit_price, pl.unit_price, m.quantity, settings)
            row["po_line"] = {"line_no": pl.line_no, "description": pl.description, "unit": pl.unit,
                              "qty_ordered": _f(pl.qty_ordered), "qty_billed": _f(pl.qty_billed),
                              "qty_remaining": _f(pl.qty_remaining), "unit_price": _f(pl.unit_price)}
            row["price_status"], row["price_diff_on_line"] = status, _f(line_diff)
            if m.quantity > pl.qty_remaining:
                row["issues"].append("qty_exceeds_po")
            if status == "over_tolerance":
                row["issues"].append("price_over_tolerance")
        lines.append(row)
    used = {m.po_line.line_no for m in matches if m.po_line is not None}
    this_invoice = invoice_taxable(inv)
    allowed = tolerance(po.taxable_value, settings)
    return {
        "po": {"po_number": po.po_number, "vendor_id": po.vendor_id, "po_date": po.po_date.isoformat(),
               "status": po.status, "taxable_value": _f(po.taxable_value), "billed_value": _f(po.billed_value),
               "remaining_value": _f(po.remaining_value)},
        "belongs_to_vendor": vendor_id is None or po.vendor_id == vendor_id,
        "closed": po.status == "closed",
        "lines": lines,
        "po_lines_not_billed": [{"line_no": l.line_no, "description": l.description, "unit": l.unit,
                                 "qty_remaining": _f(l.qty_remaining), "unit_price": _f(l.unit_price)}
                                for l in po.lines if l.line_no not in used],
        "totals": {"this_invoice": _f(this_invoice), "remaining_before": _f(po.remaining_value),
                   "remaining_after": _f(po.remaining_value - this_invoice), "tolerance": _f(allowed),
                   "overrun": po.billed_value + this_invoice > po.taxable_value + allowed},
    }
