"""A tiny hand-made master-data world and invoice builders for the rules-engine tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.config import Settings
from app.pipeline.repository import BuyerRecord, HistoryRecord, InMemoryRepository, POLineRecord, PORecord, VendorRecord
from app.schemas import ExtractedInvoice, FieldVerification, VerificationResult
from app.verification.verify import VERIFIED_FIELDS

SETTINGS = Settings(_env_file=None)
D = Decimal

BUYER = BuyerRecord("Zenith Retail Pvt Ltd", ("Zenith Retail Pvt Ltd", "Zenith Retail Private Limited"),
                    "27RHRCZ5469N1Z7", "27")
INTRA = VendorRecord("V1", "Sharma IT Solutions Private Limited", "Sharma IT Solutions", "27AABCS1234F1Z5", "27",
                     "approved", "HDFC Bank", "50100123456789", "HDFC0001234")
INTER = VendorRecord("V2", "Kosmic Cartons Private Limited", "Kosmic Cartons", "29AABCK1234F1Z9", "29",
                     "approved", "ICICI Bank", "000401234567", "ICIC0000004")
PENDING = VendorRecord("V3", "Nova Supplies LLP", "Nova Supplies", "07AAFFN1234F1Z1", "07", "pending",
                       "SBI", "30001234567", "SBIN0001234")
BLOCKED = VendorRecord("V4", "Orbit Logistics LLP", "Orbit Logistics", "27AAFFO1234F1Z3", "27", "blocked",
                       "Axis Bank", "912010012345678", "UTIB0000123")


def line(no: int, desc: str, ordered: str, billed: str, price: str, rate: str = "18") -> POLineRecord:
    return POLineRecord(no, desc, "Nos", D(ordered), D(billed), D(price), D(rate))


PO_OPEN = PORecord("PO-2026-1001", "V1", date(2026, 9, 1), "open", D("100000.00"), D("0.00"), (
    line(1, "Laptop - Intel Core i5, 16GB RAM, 512GB SSD", "1", "0", "60000.00"),
    line(2, "LED Monitor 24\" Full HD", "4", "0", "10000.00"),
))
PO_PARTIAL = PORecord("PO-2026-1002", "V2", date(2026, 8, 1), "partially_billed", D("50000.00"), D("44000.00"), (
    line(1, "Corrugated Box 5-Ply 18x12x12 in", "1000", "880", "50.00", "5"),
))
PO_CLOSED = PORecord("PO-2026-1003", "V1", date(2026, 6, 1), "closed", D("20000.00"), D("20000.00"), (
    line(1, "Network Switch - 24 Port Gigabit", "1", "1", "20000.00"),
))
PO_PENDING = PORecord("PO-2026-1004", "V3", date(2026, 9, 1), "open", D("5000.00"), D("0.00"), (
    line(1, "A4 Copier Paper 75 GSM (500 sheets)", "20", "0", "250.00"),
))
HISTORY = [
    HistoryRecord("H0001", "V2", "KOS-0457", date(2026, 9, 10), "PO-2026-1002", D("44000.00"), D("46200.00"), "paid"),
    HistoryRecord("H0002", "V1", "SIT/26-27/0881", date(2026, 6, 5), "PO-2026-1003", D("20000.00"), D("23600.00"), "paid"),
]


def repo(pos: list[PORecord] | None = None, history: list[HistoryRecord] | None = None,
         hashes: dict[str, str] | None = None) -> InMemoryRepository:
    return InMemoryRepository(BUYER, [INTRA, INTER, PENDING, BLOCKED],
                              pos if pos is not None else [PO_OPEN, PO_PARTIAL, PO_CLOSED, PO_PENDING],
                              history if history is not None else list(HISTORY), hashes)


def invoice(vendor: VendorRecord = INTRA, lines: list[dict] | None = None, intra: bool | None = None,
            confidence: float = 0.95, **fields) -> ExtractedInvoice:
    """An honest invoice for `lines` (default: one laptop on PO_OPEN), totals computed, GST by state rule."""
    lines = lines if lines is not None else [
        {"description": "Laptop - Intel Core i5, 16GB RAM, 512GB SSD", "quantity": 1, "unit_price": 60000.0, "tax_rate": 18}]
    for item in lines:
        item.setdefault("amount", round(item["quantity"] * item["unit_price"], 2))
        item.setdefault("confidence", 0.95)
    subtotal = round(sum(i["amount"] for i in lines), 2)
    tax = round(sum(i["amount"] * i["tax_rate"] / 100 for i in lines), 2)
    intra = vendor.state_code == "27" if intra is None else intra
    values = {
        "document_type": "tax_invoice", "vendor_name": vendor.legal_name, "vendor_gstin": vendor.gstin,
        "buyer_name": BUYER.legal_name, "buyer_gstin": BUYER.gstin, "invoice_number": "INV-2001",
        "invoice_date": "2026-10-20", "po_reference": "PO-2026-1001" if vendor is INTRA else None,
        "subtotal": subtotal, "cgst": round(tax / 2, 2) if intra else None, "sgst": round(tax / 2, 2) if intra else None,
        "igst": None if intra else tax, "total_amount": round(subtotal + tax, 2),
        "bank_account": vendor.bank_account, "bank_ifsc": vendor.ifsc,
    }
    values.update(fields)
    data = {k: {"value": v, "confidence": confidence} for k, v in values.items()}
    data["line_items"] = lines
    return ExtractedInvoice.model_validate(data)


def verification(inv: ExtractedInvoice, status: str = "verified", **overrides: str) -> VerificationResult:
    """Every printed verified field gets `status` (absent ones: not_applicable); overrides per field."""
    fields = {}
    for name in VERIFIED_FIELDS:
        value = getattr(inv, name).value
        fields[name] = FieldVerification(status=overrides.get(name, "not_applicable" if value in (None, "") else status))
    engine = {"verified": "text_layer", "unavailable": "unavailable"}.get(status, "ocr")
    return VerificationResult(engine_used=engine, fields=fields)
