"""The one extraction prompt and JSON schema shared by every provider."""

from __future__ import annotations

import json
from functools import lru_cache

from app.schemas import ExtractedInvoice

SCALAR_FIELDS = [
    ("document_type", "tax_invoice | quotation | proforma | credit_note | delivery_challan | purchase_order | other"),
    ("vendor_name", "seller / supplier name as printed"),
    ("vendor_gstin", "seller's 15-character GSTIN, value without spaces"),
    ("vendor_address", "seller's address"),
    ("vendor_state", "seller's state"),
    ("buyer_name", "buyer / bill-to party name"),
    ("buyer_gstin", "buyer's GSTIN, value without spaces"),
    ("invoice_number", "invoice / bill number exactly as printed (keep slashes, dashes, leading zeros)"),
    ("invoice_date", "invoice date; value as YYYY-MM-DD (dates are day-first in India)"),
    ("po_reference", "purchase order number if printed anywhere (header, 'Your Order No', notes)"),
    ("subtotal", "sum of line amounts before tax (number)"),
    ("discount", "invoice-level discount (positive number)"),
    ("other_charges", "freight / packing / other charges (number)"),
    ("cgst", "total CGST amount (number)"),
    ("sgst", "total SGST amount (number)"),
    ("igst", "total IGST amount (number)"),
    ("round_off", "round-off adjustment, negative if subtracted (number)"),
    ("total_amount", "grand total payable (number)"),
    ("amount_in_words", "amount in words, as printed"),
    ("bank_account", "seller's bank account number, digits only"),
    ("bank_ifsc", "seller's bank IFSC code"),
    ("page_count", "number of pages in the document (number)"),
]

SYSTEM_PROMPT = """You read Indian GST invoices for an accounts-payable team. You only READ the document;
you never judge, approve, correct or explain it.

Rules:
1. Extract only what is printed. If a field is not on the document, return null for value and printed.
2. Never compute, infer or guess a missing value (do not add up a missing total, do not invent a PO number).
3. For every field return:
   - "value": the clean value (numbers as plain numbers like 118000.5, dates as YYYY-MM-DD, GSTIN without spaces),
   - "printed": the exact text as printed (e.g. "Rs. 1,18,000/-", "05-Mar-26", "INV/0881"),
   - "confidence": 0-1, how sure you are the value is exactly what is printed. Use a LOW confidence (< 0.5)
     when the text is blurred, smudged, covered, cut off or you are unsure,
   - "evidence": a short snippet of the surrounding printed text (label + value), or null.
4. A GSTIN has 15 characters: 2 digits (state code), 5 letters, 4 digits, 1 letter, 1 digit or letter, the
   letter Z, 1 check character. Read each character carefully ("1" vs "I", "0" vs "O", "5" vs "S", "8" vs "B").
5. Indian formats: amounts use lakh grouping (1,18,000.00), may carry ₹ / Rs. / INR / "/-".
   Dates are day-first (05/03/2026 is 5 March 2026).
6. Multi-page documents: line items may continue across pages; totals are usually on the last page.
7. document_type: "tax_invoice" for a Tax Invoice / GST Invoice / Invoice / Bill; otherwise the kind of
   document it is (quotation, proforma, credit_note, delivery_challan, purchase_order, other).
8. line_items: one entry per printed line with description, hsn_sac, quantity, unit, unit_price, amount,
   tax_rate (percent) and a confidence. Do not include tax, freight or round-off rows as line items.
9. Return ONLY a JSON object matching the schema. No commentary."""


def _schema_outline() -> dict:
    field = {"value": "...", "printed": "string|null", "confidence": "0-1", "evidence": "string|null"}
    outline: dict = {name: {**field, "value": hint} for name, hint in SCALAR_FIELDS}
    outline["line_items"] = [{"description": "string", "hsn_sac": "string|null", "quantity": "number|null",
                              "unit": "string|null", "unit_price": "number|null", "amount": "number|null",
                              "tax_rate": "number|null", "confidence": "0-1"}]
    return outline


@lru_cache
def user_prompt() -> str:
    """Instruction plus the JSON shape (spelled out, because not every provider enforces a schema)."""
    return ("Extract this invoice. Respond with one JSON object with exactly these keys:\n"
            + json.dumps(_schema_outline(), indent=1, ensure_ascii=False))


def _require_everything(node: object) -> None:
    """Make every object property required and drop defaults, so a model cannot silently skip a key
    (a skipped 'confidence' would otherwise default to 0)."""
    if isinstance(node, dict):
        node.pop("default", None)
        if node.get("type") == "object" and "properties" in node:
            node["required"] = list(node["properties"])
        for child in node.values():
            _require_everything(child)
    elif isinstance(node, list):
        for child in node:
            _require_everything(child)


@lru_cache
def json_schema() -> dict:
    """JSON Schema of ExtractedInvoice, for providers that enforce structured output (all keys required)."""
    schema = ExtractedInvoice.model_json_schema()
    _require_everything(schema)
    return schema


KEY_FIELDS = ("vendor_name", "vendor_gstin", "buyer_gstin", "invoice_number", "invoice_date", "po_reference",
              "subtotal", "cgst", "sgst", "igst", "total_amount", "bank_account")

COMPACT_NOTE = ("Keep the answer short: give \"evidence\" only for " + ", ".join(KEY_FIELDS)
                + "; set \"evidence\" to null for every other field. Use no spaces or line breaks between JSON tokens.")


def repair_prompt(previous_output: str, error: str) -> str:
    """The single repair retry: show the model its own output and what was wrong with it."""
    return (f"Your previous answer could not be used.\nProblem: {error[:1500]}\n"
            f"Previous answer (start):\n{previous_output[:4000]}\n\n"
            "Return the corrected JSON object only, following the same rules and schema.")
