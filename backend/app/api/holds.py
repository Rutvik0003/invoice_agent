"""Hold queue: held invoices grouped by who must act, and the human actions that resolve them."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import engine_of, get_run_or_404, iso_utc, run_summary
from app.logging_setup import get_logger
from app.models import HoldAction, Run
from app.pipeline.amount_match import map_lines
from app.pipeline.decision import ledger_update
from app.pipeline.ledger import apply_ledger_update
from app.pipeline.normalise import normalise_invoice_number
from app.pipeline.orchestrator import load_buyer
from app.pipeline.po_compare import compare
from app.pipeline.repository import DbRepository
from app.pipeline.self_check import invoice_date
from app.runtime_settings import effective_settings
from app.schemas import ExtractedInvoice

logger = get_logger("holds")
router = APIRouter(prefix="/api", tags=["holds"])
CONFIRMABLE = set(ExtractedInvoice.model_fields) - {"line_items"}


class HoldActionIn(BaseModel):
    action: Literal["approve", "reject", "assign_po", "confirm_field"]
    role: str = Field(min_length=1)
    comment: str = Field(min_length=1, description="Required: why the person decided this")
    payload: dict = {}


def _hold_item(run: Run, actions: list[HoldAction]) -> dict:
    decision = (run.decision_json or {}).get("decision", {})
    return {
        **run_summary(run),
        "routed_questions": decision.get("routed_questions", []),
        "reasons": run.reasons_json or [],
        "po_candidates": (run.decision_json or {}).get("po_candidates", []),
        "verification_fields": (run.verification_json or {}).get("fields", {}),
        "extracted": run.extracted_json,
        "resolved": run.status == "resolved_by_human",
        "hold_actions": [{"actor_role": a.actor_role, "action": a.action, "comment": a.comment, "payload": a.payload,
                          "created_at": iso_utc(a.created_at)} for a in actions],
    }


@router.get("/holds")
def list_holds(request: Request, state: Literal["open", "resolved", "all"] = "open", include_test: bool = False) -> dict:
    """Held invoices, newest first, grouped by the role each routed question goes to."""
    with Session(engine_of(request)) as session:
        query = select(Run).where(Run.decision_json.is_not(None)).order_by(Run.created_at.desc())
        if not include_test:
            query = query.where(Run.is_test_run.is_(False))
        items = []
        for run in session.scalars(query):
            was_held = (run.decision_json or {}).get("decision", {}).get("outcome") == "HOLD"
            if not was_held:
                continue
            resolved = run.status == "resolved_by_human"
            if (state == "open" and resolved) or (state == "resolved" and not resolved):
                continue
            actions = session.scalars(select(HoldAction).where(HoldAction.run_id == run.id).order_by(HoldAction.id)).all()
            items.append(_hold_item(run, list(actions)))
    by_role: dict[str, list[str]] = {}
    for item in items:
        for question in item["routed_questions"]:
            by_role.setdefault(question["role"], []).append(item["id"])
    return {"items": items, "by_role": by_role}


@router.get("/runs/{run_id}/po-compare")
def po_compare(run_id: str, request: Request, po: str | None = None) -> dict:
    """The invoice next to a PO, line by line. Default PO: the run's (quoted, inferred or assigned), else the best
    candidate. `options` lists every PO of this vendor (and the candidates) so another one can be compared."""
    engine = engine_of(request)
    with Session(engine) as session:
        run = get_run_or_404(session, run_id)
        if run.extracted_json is None:
            raise HTTPException(status_code=409, detail="Nothing was extracted from this invoice.")
        repo = DbRepository(session, load_buyer())
        invoice = ExtractedInvoice.model_validate(run.extracted_json)
        quoted_po = repo.po(invoice.po_reference.value) if invoice.po_reference.value else None
        candidates = [c["po_number"] for c in (run.decision_json or {}).get("po_candidates", [])]
        # why each PO is offered, most relevant first: the run's PO, the one printed on the invoice, the suggestions,
        # then every other open PO of this vendor
        reasons: dict[str, str] = {}
        if run.po_number:
            reasons[run.po_number] = "matched"
        if quoted_po is not None:
            reasons.setdefault(quoted_po.po_number, "quoted")
        for number in candidates:
            reasons.setdefault(number, "suggested")
        if run.vendor_id:
            for p in sorted(repo.open_pos_for_vendor(run.vendor_id), key=lambda p: p.po_number):
                reasons.setdefault(p.po_number, "other")
        options = list(reasons)
        chosen = po or (options[0] if options else None)
        record = repo.po(chosen) if chosen else None
        if chosen and record is None:
            raise HTTPException(status_code=404, detail=f"PO {chosen} not found.")
        result = compare(invoice, record, run.vendor_id, effective_settings(engine)) if record else None
        return {"options": options, "option_reasons": reasons, "candidates": candidates,
                "selected": record.po_number if record else None, "comparison": result}


@router.post("/holds/{run_id}/action")
def hold_action(run_id: str, body: HoldActionIn, request: Request) -> dict:
    """Record a person's action on a held invoice. Approve/Reject resolve it ('resolved_by_human');
    assign_po and confirm_field correct the inputs and keep it open. Every action is logged with its comment."""
    engine = engine_of(request)
    with Session(engine) as session:
        run = get_run_or_404(session, run_id)
        held = (run.decision_json or {}).get("decision", {}).get("outcome") == "HOLD"
        if not held:
            raise HTTPException(status_code=409, detail="This run is not on hold.")
        if run.status == "resolved_by_human":
            raise HTTPException(status_code=409, detail="This hold was already resolved.")
        result: dict = {}
        if body.action == "assign_po":
            result = _assign_po(session, run, body.payload)
        elif body.action == "confirm_field":
            result = _confirm_field(run, body.payload)
        elif body.action == "approve":
            result = _approve(session, run)
        else:
            run.decision, run.status = "REJECT", "resolved_by_human"
            result = {"decision": "REJECT"}
        session.add(HoldAction(run_id=run_id, actor_role=body.role, action=body.action, comment=body.comment,
                               payload={**body.payload, **result}))
        session.commit()
        logger.info("hold action", extra={"run_id": run_id, "action": body.action, "role": body.role,
                                          "status": run.status})
        return {"run": run_summary(run), "result": result}


def _assign_po(session: Session, run: Run, payload: dict) -> dict:
    po_number = str(payload.get("po_number") or "").strip()
    repo = DbRepository(session, load_buyer())
    po = repo.po(po_number) if po_number else None
    if po is None:
        raise HTTPException(status_code=400, detail=f"PO {po_number or '(none)'} not found.")
    if run.vendor_id and po.vendor_id != run.vendor_id:
        raise HTTPException(status_code=400, detail=f"{po.po_number} belongs to vendor {po.vendor_id}, not {run.vendor_id}.")
    if po.status == "closed":
        raise HTTPException(status_code=400, detail=f"{po.po_number} is closed.")
    run.po_number = po.po_number
    return {"po_number": po.po_number}


def _confirm_field(run: Run, payload: dict) -> dict:
    field = payload.get("field")
    if field not in CONFIRMABLE:
        raise HTTPException(status_code=400, detail=f"Unknown field {field!r}.")
    extracted = dict(run.extracted_json or {})
    entry = dict(extracted.get(field) or {})
    old = entry.get("value")
    entry.update(value=payload.get("value", old), confidence=1.0, evidence="confirmed by a person")
    extracted[field] = entry
    ExtractedInvoice.model_validate(extracted)  # reject values that do not fit the field type
    run.extracted_json = extracted
    return {"field": field, "old_value": old, "new_value": entry["value"]}


def already_paid(repo: DbRepository, run: Run, invoice: ExtractedInvoice) -> None:
    """A person must not pay an invoice twice: refuse if this file was approved in another run since, or the
    vendor's history already has this invoice number (for example a re-run of the same invoice was approved)."""
    earlier = repo.processed_file(run.file_hash)
    if earlier is not None and earlier.decision == "APPROVE":
        raise HTTPException(status_code=409, detail=f"This file was already approved and paid in run {earlier.run_id[:8]}. "
                                                    "Reject this hold instead.")
    number = normalise_invoice_number(str(invoice.invoice_number.value))
    paid = next((h for h in repo.history_for_vendor(run.vendor_id)
                 if normalise_invoice_number(h.invoice_number) == number), None)
    if paid is not None:
        raise HTTPException(status_code=409, detail=f"Invoice {paid.invoice_number} from this vendor is already in the "
                                                    f"invoice history ({paid.status}, {paid.invoice_date:%d %b %Y}). "
                                                    "Reject this hold instead.")


def _approve(session: Session, run: Run) -> dict:
    """Human approval: bill the PO (inferred, or assigned by a person) and record the invoice in history."""
    if not run.po_number:
        raise HTTPException(status_code=400, detail="Assign a PO before approving.")
    if not run.vendor_id:
        raise HTTPException(status_code=400, detail="The vendor is not in the vendor master; it cannot be paid yet.")
    invoice = ExtractedInvoice.model_validate(run.extracted_json)
    missing = []
    if not invoice.invoice_number.value:
        missing.append("invoice number")
    if invoice_date(invoice) is None:
        missing.append("invoice date")
    if missing:  # the invoice history (duplicate checks, payment) cannot record an invoice without them
        raise HTTPException(status_code=400, detail=f"The {' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} "
                                                    "missing. Enter it with 'Confirm value' first, then approve.")
    repo = DbRepository(session, load_buyer(), exclude_run_id=run.id)
    already_paid(repo, run, invoice)
    po = repo.po(run.po_number)
    vendor = next((v for v in repo.vendors() if v.vendor_id == run.vendor_id), None)
    update = ledger_update(invoice, vendor, po, map_lines(invoice, po))
    if not run.is_test_run:
        change = apply_ledger_update(session, update, run.id)
        run.decision_json = {**(run.decision_json or {}), "ledger_change": change, "ledger_applied": True}
    run.decision, run.status = "APPROVE", "resolved_by_human"
    return {"decision": "APPROVE", "po_number": po.po_number, "ledger_lines": len(update.lines),
            "ledger_applied": not run.is_test_run}
