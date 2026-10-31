"""One-tap vendor email for held and rejected invoices: preview, and "send" (demo: logged, not delivered)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import engine_of, get_run_or_404, iso_utc
from app.logging_setup import get_logger
from app.models import EmailLog, Run, Vendor
from app.pipeline.orchestrator import load_buyer
from app.pipeline.self_check import invoice_date
from app.schemas import ExtractedInvoice
from app.vendor_email import VendorEmail, compose, vendor_problems

router = APIRouter(prefix="/api", tags=["email"])
logger = get_logger("email")


def original_outcome(run: Run) -> str | None:
    """The engine's decision (a person may have resolved a hold since; the email explains the original problem)."""
    return (run.decision_json or {}).get("decision", {}).get("outcome")


def _compose(session: Session, run: Run, engine) -> VendorEmail:
    outcome = original_outcome(run)
    if outcome not in ("HOLD", "REJECT") or run.extracted_json is None:
        raise HTTPException(status_code=409, detail="Only held or rejected invoices can be emailed to the vendor.")
    if not vendor_problems(run.reasons_json or [], outcome):
        raise HTTPException(status_code=409, detail="There is nothing the vendor needs to change on this invoice.")
    invoice = ExtractedInvoice.model_validate(run.extracted_json)
    vendor = session.get(Vendor, run.vendor_id) if run.vendor_id else None
    total = run.total_amount if run.total_amount is not None else invoice.total_amount.value
    return compose(
        vendor_name=vendor.legal_name if vendor else (invoice.vendor_name.value or "Supplier"),
        invoice_number=invoice.invoice_number.value, invoice_date=invoice_date(invoice),
        total=float(total) if total is not None else None, outcome=outcome, reasons=run.reasons_json or [],
        buyer_name=load_buyer().legal_name, recipient=vendor.email if vendor else None, file_name=run.file_name,
        mime=run.mime_type,
    )


def _log_rows(session: Session, run_id: str) -> list[dict]:
    rows = session.scalars(select(EmailLog).where(EmailLog.run_id == run_id).order_by(EmailLog.id)).all()
    return [{"created_at": iso_utc(r.created_at), "recipient": r.recipient, "subject": r.subject, "sent": r.sent,
             "error": r.error} for r in rows]


@router.get("/runs/{run_id}/email")
def preview_email(run_id: str, request: Request) -> dict:
    """The email one tap would send, and every earlier send."""
    engine = engine_of(request)
    with Session(engine) as session:
        run = get_run_or_404(session, run_id)
        mail = _compose(session, run, engine)
        return {**mail.__dict__, "history": _log_rows(session, run_id)}


@router.post("/runs/{run_id}/email")
def send_email(run_id: str, request: Request) -> dict:
    """Demo send: the email is logged against the run (nothing leaves the app) and the UI shows "Mail sent"."""
    engine = engine_of(request)
    with Session(engine) as session:
        run = get_run_or_404(session, run_id)
        mail = _compose(session, run, engine)
        session.add(EmailLog(run_id=run_id, sender=mail.sender, recipient=mail.recipient, subject=mail.subject,
                             sent=True, error=None))
        session.commit()
        logger.info("vendor email logged (demo, not delivered)", extra={"run_id": run_id})
        return {"sent": True, "recipient": mail.recipient, "subject": mail.subject, "history": _log_rows(session, run_id)}
