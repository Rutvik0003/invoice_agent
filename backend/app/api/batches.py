"""Bulk upload: many invoices at once, queued and processed one by one, with a combined result."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from collections import Counter
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import engine_of, iso_utc, run_summary, shown_outcome
from app.config import get_settings
from app.demo.mode import check_demo_quota, require_real_mode
from app.runtime_settings import effective_settings
from app.logging_setup import get_logger
from app.models import Batch, Run
from app.pipeline.intake import IntakeError
from app.pipeline.orchestrator import create_run_record

router = APIRouter(prefix="/api", tags=["batches"])
logger = get_logger("batches")
MAX_FILES = 50
FINISHED = ("completed", "extraction_failed", "failed", "interrupted", "resolved_by_human")


@router.post("/batches")
async def create_batch(request: Request, files: list[UploadFile] = File(...), model: str | None = Form(None),
                       model_name: str | None = Form(None), use_cache: bool = Form(False)) -> dict:
    """Queue every valid file as a run of one batch. Files that fail the intake checks are listed, not queued."""
    require_real_mode(request, "Uploading files")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"At most {MAX_FILES} files per batch ({len(files)} sent).")
    items = [BatchFile(upload.filename or "invoice", await upload.read()) for upload in files]
    return queue_batch(request, items, model or get_settings().default_model, model_name, use_cache)


@dataclass
class BatchFile:
    file_name: str
    data: bytes
    sample_id: str | None = None
    source: dict | None = None  # the email it came from (inbox)


def queue_batch(request: Request, items: list[BatchFile], model: str, model_name: str | None,
                use_cache: bool) -> dict:
    """Store a batch and queue its files as runs (in this order); the batch worker processes them one by one."""
    engine = engine_of(request)
    batch_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(Batch(id=batch_id, model=model, model_name=model_name or None, file_errors=[]))
        session.commit()
    run_ids, errors = [], []
    for item in items:
        try:
            run_ids.append(create_run_record(engine, item.file_name, item.data, model, model_name=model_name,
                                             batch_id=batch_id, use_cache=use_cache, sample_id=item.sample_id,
                                             source=item.source))
        except IntakeError as exc:
            errors.append({"file_name": item.file_name, "error": str(exc)})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    with Session(engine) as session:
        batch = session.get(Batch, batch_id)
        if not run_ids:
            session.delete(batch)
            session.commit()
            raise HTTPException(status_code=400, detail="None of the files can be processed: " +
                                "; ".join(f"{e['file_name']}: {e['error']}" for e in errors))
        batch.file_errors = errors
        session.commit()
    request.app.state.batch_worker.notify()
    logger.info("batch queued", extra={"batch_id": batch_id, "runs": len(run_ids), "rejected_files": len(errors)})
    return {"batch_id": batch_id, "run_ids": run_ids, "file_errors": errors}


FAILED = ("extraction_failed", "failed", "interrupted")


def latest_attempts(runs: list[Run]) -> list[Run]:
    """One row per uploaded file: a run retried inside the batch is replaced by its newest retry, in the original's
    place (upload order)."""
    by_id = {r.id: r for r in runs}
    retried = {r.retry_of for r in runs if r.retry_of in by_id}

    def first_upload(run: Run) -> Run:
        while run.retry_of in by_id:
            run = by_id[run.retry_of]
        return run

    order = {r.id: i for i, r in enumerate(runs)}
    latest = [r for r in runs if r.id not in retried]
    return sorted(latest, key=lambda r: order[first_upload(r).id])


def _batch_dict(batch: Batch, all_runs: list[Run], queue: list[str] | None = None) -> dict:
    """Progress and combined result of one batch."""
    runs = latest_attempts(all_runs)
    by_id = {r.id: r for r in all_runs}
    attempts = {r.id: 1 + len(list(_chain(r, by_id))) for r in runs}
    statuses = Counter(r.status for r in runs)
    decisions = Counter(r.decision for r in runs if r.decision)
    outcomes = Counter(shown_outcome(r) for r in runs if r.decision)
    done = sum(statuses[s] for s in FINISHED)
    out = {
        "id": batch.id, "created_at": iso_utc(batch.created_at), "model": batch.model, "model_name": batch.model_name,
        "total": len(runs), "done": done, "finished": done == len(runs), "by_status": dict(statuses),
        "by_decision": dict(decisions), "by_outcome": dict(outcomes), "file_errors": batch.file_errors or [],
        "total_amount": sum(float(r.total_amount) for r in runs if r.total_amount is not None),
        "failed": sum(statuses[s] for s in FAILED),
    }
    if queue is not None:
        out["items"] = [{**run_summary(r), "queue_position": queue.index(r.id) + 1 if r.id in queue else None,
                         "attempt": attempts[r.id],
                         "reasons": [{"code": c.get("code"), "severity": c.get("severity"), "message": c.get("message")}
                                     for c in (r.reasons_json or []) if c.get("code")]}
                        for r in runs]
    return out


def _chain(run: Run, by_id: dict[str, Run]):
    """Earlier attempts of this run inside the batch (newest first)."""
    while run.retry_of in by_id:
        run = by_id[run.retry_of]
        yield run


def _runs_of(session: Session, batch_id: str) -> list[Run]:
    return list(session.scalars(select(Run).where(Run.batch_id == batch_id).order_by(Run.created_at, Run.id)))


@router.get("/batches")
def list_batches(request: Request, limit: int = 20) -> list[dict]:
    """Recent batches, newest first, with their progress."""
    with Session(engine_of(request)) as session:
        batches = session.scalars(select(Batch).order_by(Batch.created_at.desc()).limit(limit)).all()
        return [_batch_dict(b, _runs_of(session, b.id)) for b in batches]


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, request: Request) -> dict:
    """One batch: every invoice with its status, decision and reasons, plus its place in the queue."""
    with Session(engine_of(request)) as session:
        batch = session.get(Batch, batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        queue = list(session.scalars(select(Run.id).where(Run.status == "queued", Run.batch_id.is_not(None))
                                     .order_by(Run.created_at, Run.id)))
        return _batch_dict(batch, _runs_of(session, batch_id), queue)


class BatchRetry(BaseModel):
    model: Literal["gemini", "groq"]
    model_name: str | None = None
    run_ids: list[str] | None = None  # default: every invoice of the batch that could not be read


@router.post("/batches/{batch_id}/retry")
def retry_batch(batch_id: str, body: BatchRetry, request: Request) -> dict:
    """Queue failed invoices again (with another model, typically), inside the same batch. Each retry is a new run
    linked to the failed one; the batch shows the newest attempt in the original's place."""
    engine = engine_of(request)
    with Session(engine) as session:
        if session.get(Batch, batch_id) is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        latest = latest_attempts(_runs_of(session, batch_id))
        wanted = [r for r in latest if r.status in FAILED and (body.run_ids is None or r.id in body.run_ids)]
        if not wanted:
            raise HTTPException(status_code=409, detail="Nothing to retry: no failed invoice in this batch matches.")
        settings = effective_settings(engine)
        # no model named: the same provider keeps the model each invoice was read with (as a single retry does)
        originals = [(r.id, r.file_name, r.file_bytes, bool(r.use_cache), r.sample_id, r.source_json,
                      body.model_name or (r.model_name if r.model == body.model
                                          and r.model_name in settings.model_choices(body.model) else None))
                     for r in wanted]
    check_demo_quota(request, engine, len(originals), settings.demo_max_runs_per_hour)
    try:
        new_ids = [create_run_record(engine, name, data, body.model, retry_of=run_id, model_name=model_name,
                                     batch_id=batch_id, use_cache=use_cache, sample_id=sample_id, source=source)
                   for run_id, name, data, use_cache, sample_id, source, model_name in originals]
    except (IntakeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.app.state.batch_worker.notify()
    logger.info("batch retry queued", extra={"batch_id": batch_id, "runs": len(new_ids), "model": body.model})
    return {"run_ids": new_ids}
