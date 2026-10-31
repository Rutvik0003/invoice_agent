"""The fixed ReasonCode list (CLAUDE.md §6): severity, who it is routed to, and a plain-English message template."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from app.schemas import CheckEvidence, CheckResult

AP_CLERK = "AP clerk"
PROCUREMENT = "Procurement"
FINANCE_CONTROLLER = "Finance controller"
TAX_TEAM = "Tax team"
BUYER = "Buyer"
VENDOR = "Vendor"


@dataclass(frozen=True)
class CodeInfo:
    severity: str  # REJECT | HOLD | INFO
    role: str  # who acts on it (Reject -> the vendor gets a note)
    template: str  # str.format placeholders
    fix: str = ""  # Reject only: what the vendor must do (goes into the vendor note)


class ReasonCode(str, Enum):
    NOT_A_TAX_INVOICE = "NOT_A_TAX_INVOICE"
    DUPLICATE_FILE = "DUPLICATE_FILE"
    DUPLICATE_INVOICE_NUMBER = "DUPLICATE_INVOICE_NUMBER"
    GST_TYPE_INVALID = "GST_TYPE_INVALID"
    ARITHMETIC_MISMATCH = "ARITHMETIC_MISMATCH"
    PO_CLOSED = "PO_CLOSED"
    ARITHMETIC_UNCERTAIN = "ARITHMETIC_UNCERTAIN"
    FIELD_NOT_VERIFIED = "FIELD_NOT_VERIFIED"
    LOW_CONFIDENCE_FIELD = "LOW_CONFIDENCE_FIELD"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    VENDOR_UNKNOWN = "VENDOR_UNKNOWN"
    VENDOR_NOT_APPROVED = "VENDOR_NOT_APPROVED"
    VENDOR_BLOCKED = "VENDOR_BLOCKED"
    VENDOR_MATCHED_BY_NAME_ONLY = "VENDOR_MATCHED_BY_NAME_ONLY"
    BANK_DETAILS_MISMATCH = "BANK_DETAILS_MISMATCH"
    BUYER_MISMATCH = "BUYER_MISMATCH"
    GST_RATE_UNUSUAL = "GST_RATE_UNUSUAL"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    PO_NOT_FOUND = "PO_NOT_FOUND"
    PO_AMBIGUOUS = "PO_AMBIGUOUS"
    PO_INFERRED = "PO_INFERRED"
    PO_VENDOR_MISMATCH = "PO_VENDOR_MISMATCH"
    ITEM_NOT_ON_PO = "ITEM_NOT_ON_PO"
    QTY_EXCEEDS_PO = "QTY_EXCEEDS_PO"
    PRICE_VARIANCE_OVER_TOLERANCE = "PRICE_VARIANCE_OVER_TOLERANCE"
    PO_OVERRUN = "PO_OVERRUN"
    PRICE_VARIANCE_WITHIN_TOLERANCE = "PRICE_VARIANCE_WITHIN_TOLERANCE"
    OCR_UNAVAILABLE = "OCR_UNAVAILABLE"
    FIELD_CROSS_CHECKED = "FIELD_CROSS_CHECKED"

    @property
    def info(self) -> CodeInfo:
        return CODES[self]

    @property
    def severity(self) -> str:
        return CODES[self].severity

    @property
    def role(self) -> str:
        return CODES[self].role

    def message(self, **values: object) -> str:
        return CODES[self].template.format(**values)


CODES: dict[ReasonCode, CodeInfo] = {
    ReasonCode.NOT_A_TAX_INVOICE: CodeInfo(
        "REJECT", VENDOR, "The document is a {doc_type}, not a tax invoice.",
        "send a tax invoice for this supply (a {doc_type} cannot be paid against)."),
    ReasonCode.DUPLICATE_FILE: CodeInfo(
        "REJECT", VENDOR, "This exact file was already processed in run {run_id}.",
        "note that this file has already been received; no action is needed unless it is a different invoice."),
    ReasonCode.DUPLICATE_INVOICE_NUMBER: CodeInfo(
        "REJECT", VENDOR, "Invoice number {number} was already received from this vendor as {original} "
                          "on {original_date} (₹{original_total}, {original_status}).",
        "do not resend invoice {original} dated {original_date}: it has already been received ({original_status}). "
        "If this is a new supply, issue an invoice with a new number."),
    ReasonCode.GST_TYPE_INVALID: CodeInfo(
        "REJECT", VENDOR, "{charged} was charged, but a supplier in state {vendor_state} billing a buyer in state "
                          "{buyer_state} must charge {required}.",
        "reissue the invoice charging {required} instead of {charged}."),
    ReasonCode.ARITHMETIC_MISMATCH: CodeInfo(
        "REJECT", VENDOR, "The figures do not add up: {detail}.",
        "correct the totals ({detail}) and reissue the invoice."),
    ReasonCode.PO_CLOSED: CodeInfo(
        "REJECT", VENDOR, "{po} is closed: it has already been fully billed.",
        "check which purchase order this supply belongs to: {po} is fully billed and closed."),
    ReasonCode.ARITHMETIC_UNCERTAIN: CodeInfo(
        "HOLD", AP_CLERK, "The figures do not add up ({detail}), but {fields} could not be confirmed on the page, "
                          "so this may be a reading error."),
    ReasonCode.FIELD_NOT_VERIFIED: CodeInfo(
        "HOLD", AP_CLERK, "AI read {field} = {value}, but this value could not be found on the document. "
                          "Please confirm it."),
    ReasonCode.LOW_CONFIDENCE_FIELD: CodeInfo(
        "HOLD", AP_CLERK, "{field} was read with low confidence ({confidence:.0%}): {value}. Please confirm it."),
    ReasonCode.POSSIBLE_DUPLICATE: CodeInfo(
        "HOLD", AP_CLERK, "{reason} Compare with {original} dated {original_date} (₹{original_total})."),
    ReasonCode.VENDOR_UNKNOWN: CodeInfo(
        "HOLD", PROCUREMENT, "Vendor '{name}' (GSTIN {gstin}) is not in the vendor master."),
    ReasonCode.VENDOR_NOT_APPROVED: CodeInfo(
        "HOLD", PROCUREMENT, "Vendor {vendor} ({vendor_id}) is not yet approved (status: pending)."),
    ReasonCode.VENDOR_BLOCKED: CodeInfo(
        "HOLD", PROCUREMENT, "Vendor {vendor} ({vendor_id}) is blocked in the vendor master."),
    ReasonCode.VENDOR_MATCHED_BY_NAME_ONLY: CodeInfo(
        "HOLD", AP_CLERK, "Vendor matched by name only ('{name}' ~ {vendor}, {score}%): the GSTIN on the invoice "
                          "({gstin}) is missing or different from the master ({master_gstin})."),
    ReasonCode.BANK_DETAILS_MISMATCH: CodeInfo(
        "HOLD", FINANCE_CONTROLLER, "Bank details on the invoice ({invoice_bank}) differ from the vendor master "
                                   "({master_bank}). Possible fraud: verify through a known contact, not the "
                                   "contact details on this invoice."),
    ReasonCode.BUYER_MISMATCH: CodeInfo(
        "HOLD", AP_CLERK, "The invoice is addressed to {buyer} ({gstin}), not to {expected}."),
    ReasonCode.GST_RATE_UNUSUAL: CodeInfo(
        "HOLD", TAX_TEAM, "GST rate {rate}% on '{item}' is not a valid slab on {date} (valid: {valid})."),
    ReasonCode.MISSING_REQUIRED_FIELD: CodeInfo(
        "HOLD", AP_CLERK, "Required information is missing from the invoice: {fields}."),
    ReasonCode.PO_NOT_FOUND: CodeInfo(
        "HOLD", BUYER, "{detail}"),
    ReasonCode.PO_AMBIGUOUS: CodeInfo(
        "HOLD", BUYER, "No PO quoted, and several open POs fit equally well: {candidates}. Please assign the right one."),
    ReasonCode.PO_INFERRED: CodeInfo(
        "HOLD", BUYER, "No PO quoted. {po} matches this invoice (score {score:.2f}, next best {second:.2f}). "
                       "Please confirm the PO."),
    ReasonCode.PO_VENDOR_MISMATCH: CodeInfo(
        "HOLD", BUYER, "{po} belongs to vendor {po_vendor}, not to the vendor on this invoice ({vendor})."),
    ReasonCode.ITEM_NOT_ON_PO: CodeInfo(
        "HOLD", BUYER, "'{item}' (₹{amount}) is not on {po}."),
    ReasonCode.QTY_EXCEEDS_PO: CodeInfo(
        "HOLD", BUYER, "'{item}': {billed} {unit} billed, but only {remaining} remain on {po} line {line} "
                       "(ordered {ordered})."),
    ReasonCode.PRICE_VARIANCE_OVER_TOLERANCE: CodeInfo(
        "HOLD", BUYER, "Unit price ₹{billed} for '{item}' is {pct}% above the PO price ₹{po_price} "
                       "(₹{line_diff} on this line; tolerance ₹{tolerance}). Accept or dispute."),
    ReasonCode.PO_OVERRUN: CodeInfo(
        "HOLD", BUYER, "{po} value is ₹{po_value}; ₹{billed_before} was already billed, and this invoice adds "
                       "₹{this_invoice} (total ₹{total_billed}, ₹{over} over; tolerance ₹{tolerance}). Amend the PO "
                       "or approve only the remaining ₹{remaining}."),
    ReasonCode.PRICE_VARIANCE_WITHIN_TOLERANCE: CodeInfo(
        "INFO", BUYER, "Unit price ₹{billed} for '{item}' is {pct}% above the PO price ₹{po_price} "
                       "(₹{line_diff} on this line), within tolerance (₹{tolerance})."),
    ReasonCode.OCR_UNAVAILABLE: CodeInfo(
        "INFO", AP_CLERK, "Page verification was not possible ({detail}); the decision relied on the model's "
                          "confidence for {fields}."),
    ReasonCode.FIELD_CROSS_CHECKED: CodeInfo(
        "INFO", AP_CLERK, "Not found on the page, but confirmed independently: {details}."),
}

assert set(CODES) == set(ReasonCode), "every ReasonCode needs severity, role and template"


def inr(value: object) -> str:
    """Indian-grouped rupee amount for messages: 118000 -> '1,18,000.00'."""
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    rupees, paise = f"{abs(amount):.2f}".split(".")
    head, tail = rupees[:-3], rupees[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}{','.join(groups + [tail])}.{paise}"


def show(value: object) -> str:
    """A value for a message: amounts as ₹ with Indian grouping, whole numbers without '.0'."""
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, float):
        return f"₹{inr(value)}"
    if isinstance(value, Decimal):
        return f"{value.normalize():f}"
    return str(value)


def raised(stage: str, check: str, code: ReasonCode, evidence: CheckEvidence | None = None, **values: object) -> CheckResult:
    """A check that produced a reason code (INFO codes count as passed, with a note)."""
    return CheckResult(stage=stage, check=check, passed=code.severity == "INFO", code=code.value, severity=code.severity,
                       message=code.message(**values), evidence=evidence or CheckEvidence(),
                       details={k: str(v) for k, v in values.items()})


def passed(stage: str, check: str, message: str, evidence: CheckEvidence | None = None) -> CheckResult:
    """A check that found nothing wrong (or could not apply, with the reason in the message)."""
    return CheckResult(stage=stage, check=check, passed=True, message=message, evidence=evidence or CheckEvidence())
