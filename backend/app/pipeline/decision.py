"""Stage 8: turn every check result into one decision. Pure function: no AI, no database writes.

Any REJECT-severity code -> Reject; else any HOLD -> Hold; else Approve (with a note if INFO codes exist).
Every reason is listed. Hold -> one routed question per role. Reject -> a draft note to the vendor.
Approve -> the PO-ledger update and invoice-history row to record.
"""

from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal

from app.pipeline.amount_match import LineMatch
from app.pipeline.normalise import to_decimal
from app.pipeline.reason_codes import (
    AP_CLERK,
    BUYER,
    CODES,
    FINANCE_CONTROLLER,
    PROCUREMENT,
    TAX_TEAM,
    ReasonCode,
    inr,
)
from app.pipeline.repository import BuyerRecord, PORecord, VendorRecord
from app.pipeline.self_check import invoice_date
from app.schemas import CheckResult, Decision, ExtractedInvoice, LedgerLine, LedgerUpdate, RoutedQuestion

ROLE_ASK = {
    AP_CLERK: "Please confirm or correct the values against the original document, then approve or reject.",
    BUYER: "Please confirm or assign the PO and accept or dispute the differences.",
    PROCUREMENT: "Please confirm whether we may buy from and pay this vendor.",
    FINANCE_CONTROLLER: "Please verify the bank details with the vendor through a known contact before any payment.",
    TAX_TEAM: "Please confirm the correct GST rate for this item.",
}
SEVERITY_ORDER = {"REJECT": 0, "HOLD": 1, "INFO": 2}


def _invoice_label(inv: ExtractedInvoice, vendor: VendorRecord | None) -> str:
    number = inv.invoice_number.value or "(no number)"
    who = vendor.legal_name if vendor else (inv.vendor_name.value or "an unknown vendor")
    total = to_decimal(inv.total_amount.value)
    return f"Invoice {number} from {who}" + (f" for ₹{inr(total)}" if total is not None else "")


def routed_questions(holds: list[CheckResult], inv: ExtractedInvoice, vendor: VendorRecord | None) -> list[RoutedQuestion]:
    """One question per role, listing exactly what that person must look at."""
    by_role: OrderedDict[str, list[CheckResult]] = OrderedDict()
    for check in holds:
        by_role.setdefault(ReasonCode(check.code).role, []).append(check)
    questions = []
    for role, checks in by_role.items():
        bullets = "\n".join(f"- {c.message}" for c in checks)
        text = f"{_invoice_label(inv, vendor)} is on hold.\n{bullets}\n{ROLE_ASK.get(role, '')}".strip()
        questions.append(RoutedQuestion(role=role, question=text, codes=sorted({c.code for c in checks})))
    return questions


def vendor_note(rejects: list[CheckResult], inv: ExtractedInvoice, vendor: VendorRecord | None, buyer: BuyerRecord) -> str:
    """A polite note to the vendor that says exactly what is wrong and what to do."""
    name = vendor.legal_name if vendor else (inv.vendor_name.value or "Sir/Madam")
    number = inv.invoice_number.value or "(no number)"
    on = invoice_date(inv)
    total = to_decimal(inv.total_amount.value)
    intro = (f"Thank you for your invoice {number}" + (f" dated {on:%d %b %Y}" if on else "")
             + (f" for ₹{inr(total)}" if total is not None else "") + ".")
    problems = "\n".join(f"- {c.message}" for c in rejects)
    fixes = []
    for c in rejects:
        fix = CODES[ReasonCode(c.code)].fix
        line = fix.format(**c.details) if fix else c.message
        if line not in fixes:
            fixes.append(line)
    actions = "\n".join(f"- {f}" for f in fixes)
    return (f"Dear {name},\n\n{intro} We are unable to process it because:\n{problems}\n\n"
            f"To resolve this, please:\n{actions}\n\nIf you have any questions, reply to this email.\n\n"
            f"Regards,\nAccounts Payable\n{buyer.legal_name}")


def ledger_update(inv: ExtractedInvoice, vendor: VendorRecord, po: PORecord, matches: list[LineMatch]) -> LedgerUpdate:
    """Approve: add each billed quantity to its PO line, and append the invoice to the history."""
    lines = [LedgerLine(po_number=po.po_number, po_line_no=m.po_line.line_no, description=m.description,
                        quantity=float(m.quantity), unit_price=float(m.unit_price), amount=float(m.amount))
             for m in matches if m.po_line is not None]
    taxable = sum((Decimal(str(l.amount)) for l in lines), Decimal("0.00"))
    total = to_decimal(inv.total_amount.value) or Decimal("0.00")
    on = invoice_date(inv)
    history_row = {
        "vendor_id": vendor.vendor_id, "invoice_number": inv.invoice_number.value,
        "invoice_date": on.isoformat() if on else None, "po_number": po.po_number,
        "taxable_value": str(taxable), "cgst": str(to_decimal(inv.cgst.value) or Decimal("0.00")),
        "sgst": str(to_decimal(inv.sgst.value) or Decimal("0.00")), "igst": str(to_decimal(inv.igst.value) or Decimal("0.00")),
        "round_off": str(to_decimal(inv.round_off.value) or Decimal("0.00")), "total_amount": str(total),
        "status": "approved",
        "lines_json": [{"po_line_no": l.po_line_no, "description": l.description, "quantity": l.quantity,
                        "unit_price": l.unit_price, "amount": l.amount} for l in lines],
    }
    return LedgerUpdate(po_number=po.po_number, lines=lines, taxable_value=float(taxable), total_amount=float(total),
                        history_row=history_row)


def decide(checks: list[CheckResult], inv: ExtractedInvoice, buyer: BuyerRecord, vendor: VendorRecord | None,
           po: PORecord | None, matches: list[LineMatch]) -> Decision:
    """Severity precedence: Reject > Hold > Approve (with note if there are INFO codes)."""
    reasons = sorted((c for c in checks if c.code), key=lambda c: SEVERITY_ORDER[c.severity])
    rejects = [c for c in reasons if c.severity == "REJECT"]
    holds = [c for c in reasons if c.severity == "HOLD"]
    infos = [c for c in reasons if c.severity == "INFO"]
    label = _invoice_label(inv, vendor)
    if rejects:
        return Decision(outcome="REJECT", summary=f"Reject: {label}. " + " ".join(c.message for c in rejects),
                        reasons=reasons, vendor_note=vendor_note(rejects, inv, vendor, buyer))
    if holds:
        roles = list(OrderedDict.fromkeys(ReasonCode(c.code).role for c in holds))
        return Decision(outcome="HOLD", summary=f"Hold: {label}. {len(holds)} issue(s) for {', '.join(roles)}.",
                        reasons=reasons, routed_questions=routed_questions(holds, inv, vendor))
    if vendor is None or po is None:  # cannot happen without a Hold code; never approve without both
        raise ValueError("Approve requires a known vendor and a PO")
    note = (" With note: " + " ".join(c.message for c in infos)) if infos else ""
    return Decision(outcome="APPROVE", approve_with_note=bool(infos),
                    summary=f"Approve: {label} matches {po.po_number}.{note}", reasons=reasons,
                    ledger_update=ledger_update(inv, vendor, po, matches))
