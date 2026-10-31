"""The email to a vendor about a held or rejected invoice: what is wrong, what to change, the invoice attached.

The reasons come from the decision (fixed reason codes); this module only words them for the vendor. Internal
wording ("possible fraud", "AI read ...") never reaches the vendor: every code has its own vendor-facing text.
Demo: nothing is delivered. "Sending" logs the email (to the vendor's address on file) and the UI confirms it.
"""

from __future__ import annotations

import string
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app.pipeline.reason_codes import ReasonCode, inr

FIELD_LABELS = {
    "vendor_gstin": "GSTIN", "buyer_gstin": "buyer GSTIN", "vendor_name": "supplier name", "invoice_number": "invoice number",
    "invoice_date": "invoice date", "total_amount": "invoice total", "po_reference": "purchase order number",
    "subtotal": "subtotal", "cgst": "CGST amount", "sgst": "SGST amount", "igst": "IGST amount",
    "bank_account": "bank account number", "line_items": "line items",
}


@dataclass(frozen=True)
class VendorText:
    title: str  # short problem name, used in the subject
    problem: str  # what is wrong (str.format with the check's details)
    change: str  # what the vendor should do


VENDOR_TEXT: dict[ReasonCode, VendorText] = {
    ReasonCode.NOT_A_TAX_INVOICE: VendorText(
        "Not a tax invoice", "The document we received is a {doc_type}, not a tax invoice.",
        "Please send a tax invoice for this supply."),
    ReasonCode.DUPLICATE_FILE: VendorText(
        "Duplicate submission", "This exact file has already been received and processed.",
        "No action is needed unless this is a different invoice; if it is, please send that invoice instead."),
    ReasonCode.DUPLICATE_INVOICE_NUMBER: VendorText(
        "Duplicate invoice number", "Invoice number {number} was already received from you as {original} on "
                                    "{original_date} (₹{original_total}, {original_status}).",
        "Please do not resend invoice {original}. If this is a new supply, issue an invoice with a new number."),
    ReasonCode.GST_TYPE_INVALID: VendorText(
        "Wrong GST type", "{charged} was charged, but a supplier in state {vendor_state} billing us in state "
                          "{buyer_state} must charge {required}.",
        "Please reissue the invoice charging {required} instead of {charged}."),
    ReasonCode.ARITHMETIC_MISMATCH: VendorText(
        "Totals do not add up", "The figures on the invoice do not add up: {detail}.",
        "Please correct the totals and reissue the invoice."),
    ReasonCode.PO_CLOSED: VendorText(
        "Purchase order closed", "{po} is closed: it has already been fully billed.",
        "Please check which purchase order this supply belongs to and reissue the invoice against it."),
    ReasonCode.ARITHMETIC_UNCERTAIN: VendorText(
        "Totals could not be confirmed", "The figures on the copy we received do not appear to add up ({detail}).",
        "Please confirm the correct subtotal, tax and total, or send a corrected invoice."),
    ReasonCode.FIELD_NOT_VERIFIED: VendorText(
        "Unclear {field_label}", "We could not clearly read the {field_label} on the copy we received "
                                 "(we read: {value}).",
        "Please confirm the {field_label}, or send a clearer copy of the invoice."),
    ReasonCode.LOW_CONFIDENCE_FIELD: VendorText(
        "Unclear {field_label}", "We could not clearly read the {field_label} on the copy we received "
                                 "(we read: {value}).",
        "Please confirm the {field_label}, or send a clearer copy of the invoice."),
    ReasonCode.POSSIBLE_DUPLICATE: VendorText(
        "Possible duplicate", "This invoice looks very similar to {original} dated {original_date} "
                              "(₹{original_total}), which we have already received.",
        "Please confirm whether this is a new invoice or a copy of {original}."),
    ReasonCode.VENDOR_UNKNOWN: VendorText(
        "Supplier not registered", "We could not find {name} (GSTIN {gstin}) in our list of registered suppliers.",
        "Please complete supplier registration with our procurement team, or check the GSTIN on the invoice."),
    ReasonCode.VENDOR_NOT_APPROVED: VendorText(
        "Supplier registration pending", "Your supplier registration with us is not yet approved.",
        "Please complete any pending registration steps with our procurement team."),
    ReasonCode.VENDOR_BLOCKED: VendorText(
        "Supplier account inactive", "Your supplier account with us is currently inactive.",
        "Please contact our procurement team before sending further invoices."),
    ReasonCode.VENDOR_MATCHED_BY_NAME_ONLY: VendorText(
        "GSTIN missing or different", "The GSTIN on the invoice ({gstin}) is missing or differs from the GSTIN we "
                                      "have on file for your company.",
        "Please reissue the invoice with your registered GSTIN, or tell us if your GSTIN has changed."),
    ReasonCode.BANK_DETAILS_MISMATCH: VendorText(
        "Bank details differ from our records", "The bank details printed on the invoice ({invoice_bank}) differ "
                                                "from the details we hold on file.",
        "For your security we will confirm any change through your registered contact. Please do not send new bank "
        "details by email; if your account has changed, contact our finance team through your usual channel."),
    ReasonCode.BUYER_MISMATCH: VendorText(
        "Invoice not addressed to us", "The invoice is addressed to {buyer} ({gstin}), not to {expected}.",
        "Please reissue the invoice to {expected}."),
    ReasonCode.GST_RATE_UNUSUAL: VendorText(
        "GST rate not valid", "GST rate {rate}% on '{item}' is not a valid rate on {date} (valid: {valid}).",
        "Please check the GST rate for '{item}' and reissue the invoice with the correct rate."),
    ReasonCode.MISSING_REQUIRED_FIELD: VendorText(
        "Required details missing", "The invoice does not show: {fields_label}.",
        "Please reissue the invoice including: {fields_label}."),
    ReasonCode.PO_NOT_FOUND: VendorText(
        "Purchase order not found", "{detail}",
        "Please quote the correct purchase order number on the invoice."),
    ReasonCode.PO_AMBIGUOUS: VendorText(
        "Purchase order number missing", "The invoice does not quote a purchase order number.",
        "Please tell us which purchase order this invoice is for, or reissue it with the PO number."),
    ReasonCode.PO_INFERRED: VendorText(
        "Purchase order number missing", "The invoice does not quote a purchase order number; it appears to "
                                         "relate to {po}.",
        "Please confirm that this invoice is for {po}, and quote the PO number on future invoices."),
    ReasonCode.PO_VENDOR_MISMATCH: VendorText(
        "Purchase order belongs to another supplier", "{po} quoted on the invoice is not one of your purchase orders.",
        "Please check the PO number and reissue the invoice."),
    ReasonCode.ITEM_NOT_ON_PO: VendorText(
        "Item not on the purchase order", "'{item}' (₹{amount}) is not on {po}.",
        "Please confirm the item against the purchase order, or remove it and reissue the invoice."),
    ReasonCode.QTY_EXCEEDS_PO: VendorText(
        "Quantity above the purchase order", "'{item}': {billed} {unit} billed, but only {remaining} remain on {po} "
                                             "(ordered {ordered}).",
        "Please bill only the remaining {remaining} {unit}, or ask our buyer to amend the purchase order."),
    ReasonCode.PRICE_VARIANCE_OVER_TOLERANCE: VendorText(
        "Price above the purchase order", "The unit price ₹{billed} for '{item}' is {pct}% above the agreed PO "
                                          "price ₹{po_price}.",
        "Please reissue the invoice at the PO price ₹{po_price}, or share the approval for the new price."),
    ReasonCode.PO_OVERRUN: VendorText(
        "Purchase order value exceeded", "{po} has ₹{remaining} left to bill, but this invoice bills ₹{this_invoice}.",
        "Please bill only the remaining ₹{remaining}, or ask our buyer to amend the purchase order."),
}
# INFO codes are notes for us, not problems for the vendor
assert set(VENDOR_TEXT) == {c for c in ReasonCode if c.severity != "INFO"}, "every Hold/Reject code needs vendor text"


class _Blank(defaultdict):
    def __missing__(self, key: str) -> str:
        return "-"


def _fill(template: str, details: dict) -> str:
    return string.Formatter().vformat(template, (), _Blank(str, details))


def _details(reason: dict) -> dict:
    """The check's values, plus readable labels for field names."""
    details = dict(reason.get("details") or {})
    field = details.get("field") or (reason.get("evidence") or {}).get("invoice_field") or ""
    details["field_label"] = FIELD_LABELS.get(field, field.replace("_", " ") or "value")
    if "fields" in details:
        details["fields_label"] = ", ".join(FIELD_LABELS.get(f.strip(), f.strip()) for f in details["fields"].split(","))
    return details


@dataclass(frozen=True)
class Problem:
    code: str
    title: str
    problem: str
    change: str


def vendor_problems(reasons: list[dict], outcome: str) -> list[Problem]:
    """Reject codes for a rejected invoice (that is why it was rejected), Hold codes for a held one; no duplicates."""
    wanted = "REJECT" if outcome == "REJECT" else "HOLD"
    out: list[Problem] = []
    for reason in reasons:
        code = reason.get("code")
        if not code or reason.get("severity") != wanted:
            continue
        text = VENDOR_TEXT[ReasonCode(code)]
        details = _details(reason)
        problem = Problem(code, _fill(text.title, details), _fill(text.problem, details), _fill(text.change, details))
        if problem not in out:
            out.append(problem)
    return out


@dataclass(frozen=True)
class VendorEmail:
    sender: str
    recipient: str
    subject: str
    body: str
    attachment_name: str
    attachment_mime: str


def compose(*, vendor_name: str, invoice_number: str | None, invoice_date: date | None, total: float | None,
            outcome: str, reasons: list[dict], buyer_name: str, recipient: str | None, file_name: str,
            mime: str) -> VendorEmail:
    """Subject: '<vendor> - <problem> - Invoice <number>'; body: each problem and the change needed."""
    problems = vendor_problems(reasons, outcome)
    number = invoice_number or "(no number)"
    headline = problems[0].title if problems else ("Invoice rejected" if outcome == "REJECT" else "Invoice on hold")
    if len(problems) > 1:
        headline += f" (+{len(problems) - 1} more)"
    subject = f"{vendor_name} - {headline} - Invoice {number}"
    about = f"invoice {number}" + (f" dated {invoice_date:%d %b %Y}" if invoice_date else "") + (
        f" for ₹{inr(total)}" if total is not None else "")
    status = ("we are unable to accept it" if outcome == "REJECT"
              else "it is on hold and cannot be paid until the points below are resolved")
    items = "\n\n".join(f"{i}. {p.title}\n   Problem: {p.problem}\n   Change needed: {p.change}"
                        for i, p in enumerate(problems, 1))
    body = (f"Dear {vendor_name},\n\nThank you for your {about}. After review, {status}.\n\n{items}\n\n"
            f"The invoice we received is attached for reference. Please reply to this email with the corrected invoice "
            f"or the confirmation requested above.\n\nRegards,\nAccounts Payable\n{buyer_name}\n")
    return VendorEmail(f"Accounts Payable, {buyer_name}", recipient or "(no email on file)", subject, body,
                       file_name, mime)
