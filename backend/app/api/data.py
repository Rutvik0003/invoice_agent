"""Read-only views of master data (vendors, POs with balances, invoice history) and run statistics."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import engine_of
from app.config import get_settings
from app.models import InvoiceHistory, POHeader, Run, Vendor
from app.verification.ocr import tesseract_status
from app.verification.verify import CRITICAL_FIELDS

router = APIRouter(prefix="/api", tags=["data"])
MANUAL_MINUTES_PER_INVOICE = 8


@router.get("/config")
def config() -> dict:
    """Read-only settings for the UI: which models can be used, and the business-rule thresholds."""
    s = get_settings()
    return {
        "default_model": s.default_model,
        "models": [
            {"id": "gemini", "label": "Google Gemini", "model_name": s.gemini_model, "configured": s.gemini_configured,
             "description": "Reads the PDF directly. Most accurate; about 15-20 s per invoice on the free tier."},
            {"id": "groq", "label": "Groq", "model_name": s.groq_model, "configured": s.groq_configured,
             "description": "Reads page images. Very fast (about 4 s); the free tier fits single-page invoices only."},
        ],
        "confidence_threshold": s.confidence_threshold,
        "tolerance_pct": s.tolerance_pct,
        "tolerance_abs_inr": s.tolerance_abs_inr,
        "po_infer_min_score": s.po_infer_min_score,
        "po_infer_min_gap": s.po_infer_min_gap,
        "po_infer_floor": s.po_infer_floor,
        "possible_dup_days": s.possible_dup_days,
        "verify_enabled": s.verify_enabled,
        "ocr_dpi": s.ocr_dpi,
        "ocr_min_word_conf": s.ocr_min_word_conf,
        "verify_fuzzy_min": s.verify_fuzzy_min,
        "ocr": tesseract_status(s).model_dump(),
        "max_upload_mb": 10,
    }


@router.get("/data/vendors")
def vendors(request: Request) -> list[dict]:
    with Session(engine_of(request)) as session:
        return [{c: getattr(v, c) for c in ("vendor_id", "legal_name", "trade_name", "gstin", "state", "state_code",
                                             "status", "category", "bank_name", "bank_account", "ifsc", "payment_terms_days")}
                for v in session.scalars(select(Vendor).order_by(Vendor.vendor_id))]


@router.get("/data/pos")
def purchase_orders(request: Request, vendor: str | None = None, status: str | None = None) -> list[dict]:
    """POs with value, billed and remaining balance, their lines, and the invoices billed against them."""
    with Session(engine_of(request)) as session:
        query = select(POHeader).order_by(POHeader.po_number.desc())
        if vendor:
            query = query.where(POHeader.vendor_id == vendor)
        if status:
            query = query.where(POHeader.status == status)
        invoices: dict[str, list[dict]] = {}
        for h in session.scalars(select(InvoiceHistory)):
            invoices.setdefault(h.po_number, []).append(
                {"history_id": h.history_id, "invoice_number": h.invoice_number, "invoice_date": h.invoice_date.isoformat(),
                 "taxable_value": float(h.taxable_value), "total_amount": float(h.total_amount), "status": h.status})
        out = []
        for po in session.scalars(query):
            out.append({
                "po_number": po.po_number, "vendor_id": po.vendor_id, "po_date": po.po_date.isoformat(), "status": po.status,
                "taxable_value": float(po.taxable_value), "billed_value": float(po.billed_value),
                "remaining_value": float(po.remaining_value), "total_value": float(po.total_value),
                "billed_pct": round(100 * float(po.billed_value) / float(po.taxable_value), 1) if po.taxable_value else 0.0,
                "lines": [{"line_no": l.line_no, "description": l.description, "hsn_sac": l.hsn_sac, "unit": l.unit,
                           "qty_ordered": float(l.qty_ordered), "qty_billed": float(l.qty_billed),
                           "qty_remaining": float(l.qty_remaining), "unit_price": float(l.unit_price),
                           "gst_rate": float(l.gst_rate)} for l in po.lines],
                "invoices": sorted(invoices.get(po.po_number, []), key=lambda i: i["invoice_date"]),
            })
        return out


@router.get("/data/history")
def history(request: Request, vendor: str | None = None, limit: int = 500) -> list[dict]:
    with Session(engine_of(request)) as session:
        query = select(InvoiceHistory).order_by(InvoiceHistory.invoice_date.desc()).limit(limit)
        if vendor:
            query = query.where(InvoiceHistory.vendor_id == vendor)
        return [{"history_id": h.history_id, "vendor_id": h.vendor_id, "invoice_number": h.invoice_number,
                 "invoice_date": h.invoice_date.isoformat(), "po_number": h.po_number,
                 "taxable_value": float(h.taxable_value), "total_amount": float(h.total_amount), "status": h.status,
                 "from_run": h.history_id.startswith("R-")} for h in session.scalars(query)]


@router.get("/stats")
def stats(request: Request, include_test: bool = False, tz_offset_minutes: int = 0) -> dict:
    """Dashboard numbers. AP time saved assumes MANUAL_MINUTES_PER_INVOICE for every invoice decided automatically."""
    with Session(engine_of(request)) as session:
        query = select(Run)
        if not include_test:
            query = query.where(Run.is_test_run.is_(False))
        runs = session.scalars(query).all()
    decisions = Counter(r.decision for r in runs if r.decision)
    statuses = Counter(r.status for r in runs)
    durations = [r.duration_ms for r in runs if r.duration_ms and r.status in ("completed", "resolved_by_human")]
    reasons = Counter(reason["code"] for r in runs for reason in (r.reasons_json or []) if reason.get("code"))
    verified = printed = critical_verified = critical_printed = 0
    for r in runs:
        for name, field in ((r.verification_json or {}).get("fields") or {}).items():
            if field.get("status") == "not_applicable":
                continue
            ok = field.get("status") == "verified"
            printed, verified = printed + 1, verified + ok
            if name in CRITICAL_FIELDS:
                critical_printed, critical_verified = critical_printed + 1, critical_verified + ok
    auto = sum(1 for r in runs if r.status == "completed" and r.decision in ("APPROVE", "REJECT"))
    by_day = Counter()
    shift = timedelta(minutes=-tz_offset_minutes)  # the browser's offset (JS getTimezoneOffset), so days match the viewer
    for r in runs:
        if r.decision and r.created_at:
            by_day[((r.created_at + shift).date().isoformat(), r.decision)] += 1
    return {
        "total_runs": len(runs),
        "by_decision": dict(decisions),
        "by_status": dict(statuses),
        "avg_duration_ms": int(sum(durations) / len(durations)) if durations else None,
        "runs_by_model": dict(Counter(r.model for r in runs)),
        "top_reason_codes": reasons.most_common(8),
        "fields_verified_pct": round(100 * verified / printed, 1) if printed else None,
        "critical_fields_verified_pct": round(100 * critical_verified / critical_printed, 1) if critical_printed else None,
        "decided_automatically": auto,
        "ap_minutes_saved": auto * MANUAL_MINUTES_PER_INVOICE,
        "ap_minutes_assumption": f"{MANUAL_MINUTES_PER_INVOICE} minutes of manual AP work per invoice that was approved "
                                 "or rejected without a person (holds still need a person, so they count as 0).",
        "decisions_by_day": [{"date": d, "decision": k, "count": n} for (d, k), n in sorted(by_day.items())],
    }
