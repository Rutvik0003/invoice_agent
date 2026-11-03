"""Run endpoints: create (upload or sample), list, detail, live events (SSE), page images, retry, samples."""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from datetime import datetime

import pymupdf
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.common import engine_of, get_run_or_404, iso_utc, run_summary, sample_file, sample_labels
from app.config import get_settings
from app.demo.mode import check_demo_quota, require_real_mode
from app.extraction.pdf_utils import PDF
from app.models import HoldAction, Run, RunEvent
from app.pipeline.intake import IntakeError
from app.pipeline.orchestrator import create_run_record, process_run
from app.runtime_settings import effective_settings

router = APIRouter(prefix="/api", tags=["runs"])
PAGE_DPI = 110
_page_cache: OrderedDict[tuple[str, int], bytes] = OrderedDict()


def create_run(request: Request, background: BackgroundTasks, file_name: str, data: bytes, model: str,
               use_cache: bool, retry_of: str | None = None, sample_id: str | None = None,
               model_name: str | None = None, source: dict | None = None) -> str:
    """Validate the file (Stage 1 checks happen up front so bad files get an immediate, clear error),
    store the run, and process it in the background."""
    engine = engine_of(request)
    try:
        run_id = create_run_record(engine, file_name, data, model, retry_of, sample_id, model_name=model_name,
                                   source=source)
    except (IntakeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background.add_task(process_run, run_id, engine, effective_settings(engine), use_cache, request.app.state.extract_fn)
    return run_id


@router.post("/runs")
async def post_run(request: Request, background: BackgroundTasks, file: UploadFile | None = File(None),
                   sample_id: str | None = Form(None), model: str | None = Form(None),
                   model_name: str | None = Form(None), use_cache: bool = Form(False)) -> dict:
    """Start a run from an uploaded file OR a sample id. Returns the run id immediately.
    Demo: samples only (their vendors and POs are in the demo data), within the visitor's hourly run limit."""
    if file is not None and file.filename:
        require_real_mode(request, "Uploading files")
    engine = engine_of(request)
    check_demo_quota(request, engine, 1, effective_settings(engine).demo_max_runs_per_hour)
    model = model or get_settings().default_model
    if file is not None and file.filename:
        data = await file.read()
        run_id = create_run(request, background, file.filename, data, model, use_cache, model_name=model_name)
    elif sample_id:
        name, data = sample_file(sample_id)
        run_id = create_run(request, background, name, data, model, use_cache, sample_id=sample_id,
                            model_name=model_name)
    else:
        raise HTTPException(status_code=400, detail="Upload a file or choose a sample.")
    return {"run_id": run_id}


@router.post("/runs/{run_id}/retry")
def retry_run(run_id: str, request: Request, background: BackgroundTasks, model: str = Query(...),
              model_name: str | None = Query(None), use_cache: bool = Query(False)) -> dict:
    """A new run with the same file and another (or the same) model, linked to the original.
    Retrying with the same provider keeps the model picked for the original run unless another is given."""
    engine = engine_of(request)
    settings = effective_settings(engine)
    check_demo_quota(request, engine, 1, settings.demo_max_runs_per_hour)
    with Session(engine) as session:
        run = get_run_or_404(session, run_id)
        name, data, sample_id, source = run.file_name, run.file_bytes, run.sample_id, run.source_json
        if model_name is None and model == run.model and run.model_name in settings.model_choices(model):
            model_name = run.model_name
    return {"run_id": create_run(request, background, name, data, model, use_cache, retry_of=run_id,
                                 sample_id=sample_id, model_name=model_name, source=source)}


@router.get("/runs")
def list_runs(request: Request, decision: str | None = None, outcome: str | None = None, status: str | None = None, vendor: str | None = None,
              model: str | None = None, date_from: str | None = None, date_to: str | None = None,
              search: str | None = None, include_test: bool = False, page: int = Query(1, ge=1),
              page_size: int = Query(20, ge=1, le=200)) -> dict:
    """Runs, newest first, with filters and pagination."""
    query = select(Run).order_by(Run.created_at.desc())
    if not include_test:
        query = query.where(Run.is_test_run.is_(False))
    if decision:
        query = query.where(Run.decision == decision.upper())
    if status:
        query = query.where(Run.status == status)
    if vendor:
        query = query.where(Run.vendor_id == vendor)
    if model:
        query = query.where(Run.model == model)
    if date_from:
        query = query.where(Run.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.where(Run.created_at < datetime.fromisoformat(date_to))
    with Session(engine_of(request)) as session:
        rows = [run_summary(r) for r in session.scalars(query)]
    if outcome:
        rows = [r for r in rows if r["outcome"] == outcome.upper()]
    if search:
        needle = search.lower()
        rows = [r for r in rows if any(needle in str(r.get(k) or "").lower()
                                       for k in ("file_name", "vendor_name", "invoice_number", "po_number", "vendor_id"))]
    start = (page - 1) * page_size
    return {"total": len(rows), "page": page, "page_size": page_size, "items": rows[start:start + page_size]}


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict:
    """Everything about one run: extraction, verification (with boxes), decision, events, human actions, retries."""
    with Session(engine_of(request)) as session:
        run = get_run_or_404(session, run_id)
        events = session.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.id)).all()
        actions = session.scalars(select(HoldAction).where(HoldAction.run_id == run_id).order_by(HoldAction.id)).all()
        retries = session.scalars(select(Run.id).where(Run.retry_of == run_id)).all()
        return {
            **run_summary(run),
            "mime_type": run.mime_type,
            "file_hash": run.file_hash,
            "extracted": run.extracted_json,
            "verification": run.verification_json,
            "rules": run.decision_json,
            "reasons": run.reasons_json or [],
            "error_detail": run.error_json,
            "events": [_event_dict(e) for e in events],
            "hold_actions": [{"actor_role": a.actor_role, "action": a.action, "comment": a.comment, "payload": a.payload,
                              "created_at": iso_utc(a.created_at)} for a in actions],
            "retries": list(retries),
            "sample": _sample_hint(run.sample_id),
        }


def _sample_hint(sample_id: str | None) -> dict | None:
    label = sample_labels().get(sample_id) if sample_id else None
    if not label:
        return None
    return {"id": sample_id, "scenario": label["scenario"], "expected_decision": label["expected_decision"],
            "expected_reason_codes": label["expected_reason_codes"]}


def _event_dict(event: RunEvent) -> dict:
    return {"id": event.id, "stage": event.stage, "type": event.event_type, "payload": event.payload,
            "created_at": iso_utc(event.created_at)}


def _events_after(engine, run_id: str, last_id: int) -> tuple[list[dict], bool]:
    """(new events, finished?) - finished means the run is over and there is nothing more to send."""
    with Session(engine) as session:
        run = session.get(Run, run_id)
        if run is None:
            return [], True
        rows = session.scalars(select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.id > last_id)
                               .order_by(RunEvent.id)).all()
        finished = run.status not in ("queued", "running") and not rows
        return [_event_dict(e) for e in rows], finished


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request) -> EventSourceResponse:
    """Server-Sent Events: replays every past event, then streams new ones until the run completes."""
    engine = engine_of(request)
    with Session(engine) as session:
        get_run_or_404(session, run_id)
    # resume point: the browser's automatic Last-Event-ID header, or ?after= on a manual reconnect
    last_id = int(request.headers.get("last-event-id") or request.query_params.get("after") or 0)

    async def stream():
        nonlocal last_id
        while True:
            events, gone = await run_in_threadpool(_events_after, engine, run_id, last_id)
            for event in events:
                last_id = event["id"]
                yield {"id": str(event["id"]), "event": event["type"], "data": json.dumps(event)}
                if event["type"] == "run_completed":
                    return
            if gone or await request.is_disconnected():
                return
            await asyncio.sleep(0.3)

    return EventSourceResponse(stream(), ping=15)


def clear_page_images() -> None:
    """Drop rendered page images (demo reset deletes the runs they belong to)."""
    _page_cache.clear()


@router.get("/runs/{run_id}/pages/{page:int}.png")
def page_image(run_id: str, page: int, request: Request) -> Response:
    """A page as PNG: the same page the verification boxes (normalised 0-1) refer to."""
    key = (run_id, page)
    if key not in _page_cache:
        with Session(engine_of(request)) as session:
            run = get_run_or_404(session, run_id)
            data, mime = run.file_bytes, run.mime_type
        if mime == PDF:
            doc = pymupdf.open(stream=data, filetype="pdf")
            if not 1 <= page <= len(doc):
                raise HTTPException(status_code=404, detail="No such page")
            png = doc[page - 1].get_pixmap(dpi=PAGE_DPI).tobytes("png")
        else:
            if page != 1:
                raise HTTPException(status_code=404, detail="No such page")
            import io

            image = Image.open(io.BytesIO(data)).convert("RGB")
            buf = io.BytesIO()
            image.save(buf, "PNG")
            png = buf.getvalue()
        _page_cache[key] = png
        while len(_page_cache) > 64:
            _page_cache.popitem(last=False)
    return Response(_page_cache[key], media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@router.get("/samples")
def list_samples() -> list[dict]:
    """Golden + stress invoices for the sample picker (golden first)."""
    return [{"id": l["invoice_id"], "set": l["set_name"], "scenario": l["scenario"], "template": l["template"],
             "scan_level": l["scan_level"], "file_name": l["file_name"], "expected_decision": l["expected_decision"],
             "expected_reason_codes": l["expected_reason_codes"], "notes": l["notes"]}
            for l in sample_labels().values()]
