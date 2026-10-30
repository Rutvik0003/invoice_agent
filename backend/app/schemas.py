"""Pydantic models at the system boundaries (CLAUDE.md §7).

ExtractedInvoice is what the AI returns in Stage 2. Every scalar field carries the clean value, the
exact printed text, the model's confidence and a short evidence snippet. VerificationResult is what
Stage 3 (text layer / OCR) found on the page for those values.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocumentType = Literal["tax_invoice", "quotation", "proforma", "credit_note", "delivery_challan", "purchase_order", "other"]

_NUMBER_JUNK = re.compile(r"(₹|rs\.?|inr|/-|,|\s)", re.IGNORECASE)


def lenient_number(value: object) -> object:
    """Accept '1,18,000.00', '₹118000', 'Rs. 118000/-' as numbers (models sometimes return printed strings)."""
    if isinstance(value, str):
        cleaned = _NUMBER_JUNK.sub("", value)
        if cleaned in ("", "-", "null", "None"):
            return None
        try:
            return float(cleaned)
        except ValueError:
            return value  # let validation report it
    return value


class _Field(BaseModel):
    model_config = ConfigDict(extra="ignore")

    printed: str | None = Field(None, description="Exact text as printed on the document, or null")
    confidence: float = Field(0.0, ge=0, le=1, description="0-1: how sure the model is that value is what is printed")
    evidence: str | None = Field(None, description="Short snippet of surrounding document text, or null")


class TextField(_Field):
    value: str | None = None


class NumberField(_Field):
    value: float | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _number(cls, v: object) -> object:
        return lenient_number(v)


class DateField(_Field):
    value: str | None = Field(None, description="ISO date YYYY-MM-DD, or null")


class DocumentTypeField(_Field):
    value: DocumentType | None = None


class LineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str | None = None
    hsn_sac: str | None = None
    quantity: float | None = None
    unit: str | None = None
    unit_price: float | None = None
    amount: float | None = None
    tax_rate: float | None = Field(None, description="GST rate in percent, e.g. 18")
    confidence: float = Field(0.0, ge=0, le=1)

    @field_validator("quantity", "unit_price", "amount", "tax_rate", mode="before")
    @classmethod
    def _number(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.rstrip("%")
        return lenient_number(v)

    @field_validator("hsn_sac", mode="before")
    @classmethod
    def _code(cls, v: object) -> object:
        return str(int(v)) if isinstance(v, (int, float)) else v


class ExtractedInvoice(BaseModel):
    """Stage 2 output: only what is printed; null for anything absent."""

    model_config = ConfigDict(extra="ignore")

    document_type: DocumentTypeField = DocumentTypeField()
    vendor_name: TextField = TextField()
    vendor_gstin: TextField = TextField()
    vendor_address: TextField = TextField()
    vendor_state: TextField = TextField()
    buyer_name: TextField = TextField()
    buyer_gstin: TextField = TextField()
    invoice_number: TextField = TextField()
    invoice_date: DateField = DateField()
    po_reference: TextField = TextField()
    line_items: list[LineItem] = []
    subtotal: NumberField = NumberField()
    discount: NumberField = NumberField()
    other_charges: NumberField = NumberField()
    cgst: NumberField = NumberField()
    sgst: NumberField = NumberField()
    igst: NumberField = NumberField()
    round_off: NumberField = NumberField()
    total_amount: NumberField = NumberField()
    amount_in_words: TextField = TextField()
    bank_account: TextField = TextField()
    bank_ifsc: TextField = TextField()
    page_count: NumberField = NumberField()


ErrorType = Literal["rate_limited", "timeout", "invalid_response", "provider_error", "auth_error", "unsupported_file"]


class ExtractionError(BaseModel):
    type: ErrorType
    message: str  # shown to the user
    detail: str | None = None  # technical detail for logs (never contains keys)


class ExtractionResult(BaseModel):
    invoice: ExtractedInvoice | None = None
    error: ExtractionError | None = None
    model_name: str
    provider: str
    latency_ms: int = 0
    raw_response: str | None = None
    repaired: bool = False
    cached: bool = False


# ---------------------------------------------------------------- Stage 3

VerificationStatus = Literal["verified", "not_found", "not_applicable", "unavailable"]
WordSource = Literal["text_layer", "ocr"]


class FieldVerification(BaseModel):
    status: VerificationStatus
    source: WordSource | None = None
    page: int | None = None
    bbox: list[float] | None = None  # [x0, y0, x1, y1] normalised 0-1, origin top-left
    matched_text: str | None = None
    ocr_word_conf: float | None = None


class PageVerificationInfo(BaseModel):
    page: int
    source: WordSource | Literal["unavailable"]
    word_count: int
    mean_ocr_conf: float | None = None


class VerificationResult(BaseModel):
    engine_used: Literal["text_layer", "ocr", "mixed", "unavailable"]
    pages: list[PageVerificationInfo] = []
    fields: dict[str, FieldVerification] = {}
    duration_ms: int = 0
