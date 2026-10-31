"""Label files (labels/<invoice_id>.json): schema, and ground truth built from exactly what is printed."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from datagen.invoice_spec import InvoiceSpec

Decision = Literal["APPROVE", "HOLD", "REJECT"]
VerificationStatus = Literal["verified", "not_found", "not_applicable", "unavailable"]

# The ReasonCode names from CLAUDE.md §6 (a plain list: the generator never imports the engine)
REASON_CODES = frozenset({
    "NOT_A_TAX_INVOICE", "DUPLICATE_FILE", "DUPLICATE_INVOICE_NUMBER", "GST_TYPE_INVALID", "ARITHMETIC_MISMATCH",
    "PO_CLOSED", "ARITHMETIC_UNCERTAIN", "FIELD_NOT_VERIFIED", "LOW_CONFIDENCE_FIELD", "POSSIBLE_DUPLICATE",
    "VENDOR_UNKNOWN", "VENDOR_NOT_APPROVED", "VENDOR_BLOCKED", "VENDOR_MATCHED_BY_NAME_ONLY", "BANK_DETAILS_MISMATCH",
    "BUYER_MISMATCH", "GST_RATE_UNUSUAL", "MISSING_REQUIRED_FIELD", "PO_NOT_FOUND", "PO_AMBIGUOUS", "PO_INFERRED",
    "PO_VENDOR_MISMATCH", "ITEM_NOT_ON_PO", "QTY_EXCEEDS_PO", "PRICE_VARIANCE_OVER_TOLERANCE", "PO_OVERRUN",
    "PRICE_VARIANCE_WITHIN_TOLERANCE", "OCR_UNAVAILABLE", "FIELD_CROSS_CHECKED",
})


class FieldBox(BaseModel):
    page: int = Field(ge=1)
    bbox: list[float]  # [x0, y0, x1, y1], normalised 0-1, origin top-left
    approximate: bool

    @field_validator("bbox")
    @classmethod
    def _valid_bbox(cls, v: list[float]) -> list[float]:
        if len(v) != 4 or not all(0 <= c <= 1 for c in v) or v[0] >= v[2] or v[1] >= v[3]:
            raise ValueError(f"bad bbox {v}")
        return v


class Signal(BaseModel):
    confidence: float = Field(ge=0, le=1)
    verification_status: VerificationStatus


class Label(BaseModel):
    invoice_id: str
    file_name: str
    set_name: Literal["golden", "stress", "holdout"]
    scenario: str
    template: str
    is_scanned: bool
    scan_level: Literal["none", "mild", "heavy", "photo", "web"]
    file_format: Literal["pdf", "png", "jpg"]
    degradations: list[str]
    ground_truth: dict
    field_boxes: dict[str, FieldBox]
    obscured_fields: list[str]
    rules_eval_signals: dict[str, Signal]
    expected_decision: Decision
    acceptable_decisions: list[Decision]
    expected_reason_codes: list[str]
    expected_reason_codes_any_of: list[list[str]] = []
    true_po_number: str | None
    knobs: dict
    notes: str

    @field_validator("expected_reason_codes")
    @classmethod
    def _known_codes(cls, v: list[str]) -> list[str]:
        unknown = set(v) - REASON_CODES
        if unknown:
            raise ValueError(f"unknown reason codes {unknown}")
        return v


def _scalar(value, printed: str | None) -> dict:
    return {"value": value, "printed": printed}


def _num(value) -> float | None:
    return None if value is None else float(value)


def ground_truth(spec: InvoiceSpec, page_count: int) -> dict:
    """ExtractedInvoice-shaped truth: 'value' is the clean value, 'printed' the exact text on the page."""
    printed = spec.printed_values()
    has = lambda name: printed.get(name) is not None  # noqa: E731
    return {
        "document_type": _scalar(spec.document_type, spec.title),
        "vendor_name": _scalar(spec.vendor_name_printed, spec.vendor_name_printed),
        "vendor_gstin": _scalar(spec.vendor.gstin, printed["vendor_gstin"]),
        "vendor_address": _scalar(spec.vendor.address, spec.vendor.address),
        "vendor_state": _scalar(spec.vendor.state, spec.vendor.state),
        "buyer_name": _scalar(spec.buyer.name, spec.buyer.name),
        "buyer_gstin": _scalar(spec.buyer.gstin, printed["buyer_gstin"]),
        "invoice_number": _scalar(spec.invoice_number, spec.invoice_number),
        "invoice_date": _scalar(spec.invoice_date.isoformat(), printed["invoice_date"]),
        "po_reference": _scalar(spec.po_reference, spec.po_reference),
        "line_items": [
            {
                "description": line.description,
                "hsn_sac": line.hsn_sac,
                "quantity": line.quantity,
                "unit": line.unit,
                "unit_price": float(line.unit_price),
                "amount": float(line.amount),
                "tax_rate": line.gst_rate,
            }
            for line in spec.lines
        ],
        "subtotal": _scalar(_num(spec.subtotal), printed["subtotal"]),
        "discount": _scalar(_num(spec.discount) if spec.discount else None, spec.amount_text(spec.discount) if spec.discount else None),
        "other_charges": _scalar(_num(spec.other_charges) if spec.other_charges else None,
                                 spec.amount_text(spec.other_charges) if spec.other_charges else None),
        "cgst": _scalar(_num(spec.cgst) if has("cgst") else None, printed["cgst"]),
        "sgst": _scalar(_num(spec.sgst) if has("sgst") else None, printed["sgst"]),
        "igst": _scalar(_num(spec.igst) if has("igst") else None, printed["igst"]),
        "round_off": _scalar(_num(spec.round_off), None if spec.round_off is None else str(spec.round_off)),
        "total_amount": _scalar(_num(spec.total_amount), printed["total_amount"]),
        "amount_in_words": _scalar(spec.words_text, spec.words_text),
        "bank_account": _scalar(spec.bank_account, spec.bank_account),
        "bank_ifsc": _scalar(spec.bank_ifsc, spec.bank_ifsc),
        "page_count": _scalar(page_count, None),
    }
