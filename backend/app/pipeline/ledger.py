"""Apply an approved invoice to the PO ledger and the invoice history (the only place runs change master data).

Demo assumption: approving an invoice pays it, so it is recorded as paid (dated today).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import InvoiceHistory, POHeader
from app.schemas import LedgerUpdate


def po_status(lines) -> str:
    """open (nothing billed), closed (everything billed) or partially_billed - the same rule as the seed data."""
    if all(Decimal(l.qty_billed) == 0 for l in lines):
        return "open"
    if all(Decimal(l.qty_billed) >= Decimal(l.qty_ordered) for l in lines):
        return "closed"
    return "partially_billed"


def apply_ledger_update(session: Session, update: LedgerUpdate, run_id: str) -> dict:
    """Add billed quantities to the PO lines, refresh the PO header, and append the invoice to history.
    Returns a before -> after snapshot of what changed (shown on the Approve card)."""
    po = session.get(POHeader, update.po_number)
    if po is None:
        raise ValueError(f"PO {update.po_number} not found")
    by_line = {line.line_no: line for line in po.lines}
    change = {"po_number": po.po_number, "po_value": float(po.taxable_value), "billed_before": float(po.billed_value),
              "status_before": po.status, "lines": []}
    for item in update.lines:
        line = by_line[item.po_line_no]
        before = Decimal(line.qty_billed)
        line.qty_billed = before + Decimal(str(item.quantity))
        line.qty_remaining = Decimal(line.qty_ordered) - Decimal(line.qty_billed)
        change["lines"].append({"line_no": line.line_no, "description": line.description, "unit": line.unit,
                                "ordered": float(line.qty_ordered), "billed_before": float(before),
                                "billed_after": float(line.qty_billed), "remaining_after": float(line.qty_remaining)})
    po.billed_value = Decimal(po.billed_value) + Decimal(str(update.taxable_value))
    po.remaining_value = Decimal(po.taxable_value) - Decimal(po.billed_value)
    po.status = po_status(po.lines)
    change.update(billed_after=float(po.billed_value), remaining_after=float(po.remaining_value), status_after=po.status,
                  history_id=f"R-{run_id[:8]}")
    row = update.history_row
    session.add(InvoiceHistory(
        history_id=f"R-{run_id[:8]}",
        vendor_id=row["vendor_id"],
        invoice_number=row["invoice_number"],
        invoice_date=date.fromisoformat(row["invoice_date"]),
        po_number=row["po_number"],
        taxable_value=Decimal(row["taxable_value"]),
        cgst=Decimal(row["cgst"]),
        sgst=Decimal(row["sgst"]),
        igst=Decimal(row["igst"]),
        round_off=Decimal(row["round_off"]),
        total_amount=Decimal(row["total_amount"]),
        status=row["status"],
        payment_date=date.today() if row["status"] == "paid" else None,
        lines_json=row["lines_json"],
    ))
    return change
