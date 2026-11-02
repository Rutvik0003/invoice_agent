"""Runs stages 1-8 for one Run, saving every event so the UI can follow along live (and replay later).

Event types: stage_started, check_result, stage_completed, stage_failed, run_completed.
"""

from __future__ import annotations

import json
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import REPO_ROOT, Settings
from app.extraction import extract_document
from app.logging_setup import get_logger
from app.models import Run, RunEvent
from app.pipeline.engine import TITLES, RulesResult, StageResult, run_rules
from app.pipeline.intake import intake
from app.pipeline.ledger import apply_ledger_update
from app.pipeline.repository import BuyerRecord, DbRepository, InMemoryRepository, MasterRepository
from app.runtime_settings import effective_settings
from app.schemas import ExtractionResult
from app.verification.cross_check import cross_check
from app.verification.verify import collect_page_words, unavailable_result, verify

MASTER_DIR = REPO_ROOT / "data" / "master"
STAGE_ORDER = (
    ("intake", "Intake"),
    ("extraction", "Read & extract (AI)"),
    ("verification", "Verify on page"),
    *((key, title) for key, title in TITLES.items()),
)
ExtractFn = Callable[..., ExtractionResult]
logger = get_logger("pipeline")


def load_buyer(master_dir: Path = MASTER_DIR) -> BuyerRecord:
    data = json.loads((master_dir / "buyer.json").read_text(encoding="utf-8"))
    return BuyerRecord(data["legal_name"], tuple(data["name_variants"]), data["gstin"], data["state_code"])


class EventLog:
    """Writes RunEvents for one run (each in its own short transaction, so streams see them immediately)."""

    def __init__(self, engine: Engine, run_id: str) -> None:
        self.engine = engine
        self.run_id = run_id
        self._started: dict[str, float] = {}

    def emit(self, stage: str, event_type: str, /, **payload: object) -> None:
        payload = {"at": datetime.now(timezone.utc).isoformat(), **payload}
        with Session(self.engine) as session:
            session.add(RunEvent(run_id=self.run_id, stage=stage, event_type=event_type, payload=payload))
            session.commit()

    def start(self, stage: str) -> None:
        self._started[stage] = time.monotonic()
        self.emit(stage, "stage_started", title=dict(STAGE_ORDER)[stage])

    def complete(self, stage: str, status: str = "passed", duration_ms: int | None = None, **payload: object) -> None:
        if duration_ms is None:
            duration_ms = int((time.monotonic() - self._started.get(stage, time.monotonic())) * 1000)
        self.emit(stage, "stage_completed", status=status, duration_ms=duration_ms, **payload)
        logger.info("stage completed", extra={"run_id": self.run_id, "stage": stage, "status": status,
                                              "duration_ms": duration_ms})

    def fail(self, stage: str, **payload: object) -> None:
        duration_ms = int((time.monotonic() - self._started.get(stage, time.monotonic())) * 1000)
        self.emit(stage, "stage_failed", duration_ms=duration_ms, **payload)
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        logger.warning("stage failed", extra={"run_id": self.run_id, "stage": stage, "duration_ms": duration_ms,
                                              "error_type": error.get("type"), "error": error.get("message")})


def stage_status(stage: StageResult) -> str:
    """failed if any Reject code, warning if any Hold code, else passed (INFO notes keep it passed)."""
    severities = {c.severity for c in stage.checks if c.code}
    return "failed" if "REJECT" in severities else "warning" if "HOLD" in severities else "passed"


def _update_run(engine: Engine, run_id: str, **values: object) -> None:
    with Session(engine) as session:
        run = session.get(Run, run_id)
        for key, value in values.items():
            setattr(run, key, value)
        session.commit()


def process_run(run_id: str, engine: Engine, settings: Settings, use_cache: bool = False,
                extract_fn: ExtractFn = extract_document, repository: MasterRepository | None = None) -> None:
    """Stages 1-8 for one run. Never raises: any unexpected error marks the run 'failed' with an event."""
    log = EventLog(engine, run_id)
    started = time.monotonic()
    stage = "intake"
    repo_session: Session | None = None
    try:
        with Session(engine) as session:
            run = session.get(Run, run_id)
            data, file_name, provider, is_test = run.file_bytes, run.file_name, run.model, run.is_test_run
            chosen_model = run.model_name
        if chosen_model:  # the model picked for this run (e.g. one of several Gemini models)
            settings = settings.model_copy(update={f"{provider}_model": chosen_model})
        _update_run(engine, run_id, status="running")
        logger.info("run started", extra={"run_id": run_id, "model": provider, "size_bytes": len(data),
                                          "test_run": is_test, "cached_allowed": use_cache})

        # 1. intake
        log.start("intake")
        info = intake(file_name, data)
        pages = [{"page": i + 1, "text_layer": has_text} for i, has_text in enumerate(info.text_layer)]
        log.complete("intake", file_hash=info.file_hash, mime=info.mime, page_count=info.page_count,
                     size_bytes=info.size_bytes, pages=pages)
        _update_run(engine, run_id, page_count=info.page_count, mime_type=info.mime)

        # 2. read & extract (the only AI call)
        stage = "extraction"
        log.start("extraction")
        extraction = extract_fn(data, info.mime, provider, settings, engine, use_cache=use_cache)
        _update_run(engine, run_id, model_name=extraction.model_name, used_cache=extraction.cached)
        if extraction.error is not None:
            log.fail("extraction", error=extraction.error.model_dump(), model_name=extraction.model_name)
            _update_run(engine, run_id, status="extraction_failed", error_json=extraction.error.model_dump(),
                        duration_ms=int((time.monotonic() - started) * 1000))
            log.emit("run", "run_completed", status="extraction_failed", decision=None)
            logger.info("run completed", extra={"run_id": run_id, "status": "extraction_failed",
                                                "duration_ms": int((time.monotonic() - started) * 1000)})
            return
        invoice = extraction.invoice
        log.complete("extraction", model_name=extraction.model_name, provider=extraction.provider,
                     cached=extraction.cached, repaired=extraction.repaired, latency_ms=extraction.latency_ms,
                     invoice=invoice.model_dump(mode="json"))
        _update_run(engine, run_id, extracted_json=invoice.model_dump(mode="json"))

        # master data for stage 3b (cross-check) and stages 4-8
        if repository is None:
            repo_session = Session(engine)
            repo: MasterRepository = DbRepository(repo_session, load_buyer(), exclude_run_id=run_id)
        else:
            repo = repository

        # 3. verify on page (no AI), then confirm what the page could not show from our records / arithmetic
        stage = "verification"
        log.start("verification")
        words = []
        if settings.verify_enabled:
            words = collect_page_words(data, info.mime, settings, engine, info.file_hash)
            verification = verify(invoice, words, settings)
        else:
            verification = unavailable_result(invoice, info.page_count)
        verification = cross_check(invoice, verification, repo, settings.confidence_threshold, words)
        for name, field in verification.fields.items():
            log.emit("verification", "check_result", field=name, value=getattr(invoice, name).value,
                     confidence=getattr(invoice, name).confidence, **field.model_dump())
        for index, line in enumerate(verification.line_items):
            log.emit("verification", "check_result", field=f"line_items[{index}].amount",
                     value=invoice.line_items[index].amount, confidence=invoice.line_items[index].confidence,
                     **line.model_dump())
        found = sum(f.status == "verified" for f in verification.fields.values())
        confirmed = sum(f.status == "cross_checked" for f in verification.fields.values())
        printed = sum(f.status != "not_applicable" for f in verification.fields.values())
        missing = any(f.status == "not_found" for f in verification.fields.values())
        log.complete("verification", status="warning" if missing or verification.engine_used == "unavailable" else "passed",
                     engine_used=verification.engine_used, verified=found, cross_checked=confirmed, printed=printed,
                     pages=[p.model_dump() for p in verification.pages])
        _update_run(engine, run_id, verification_json=verification.model_dump(mode="json"))

        # 4-8. rules (pure Python): events are emitted as each stage finishes
        stage = "self_check"

        def on_stage(result: StageResult) -> None:
            nonlocal stage
            stage = result.stage
            log.emit(result.stage, "stage_started", title=result.title)
            for check in result.checks:
                log.emit(result.stage, "check_result", **check.model_dump(mode="json"))
            log.complete(result.stage, status=stage_status(result), duration_ms=result.duration_ms)

        rules: RulesResult = run_rules(invoice, verification, repo, settings, info.file_hash, on_stage)
        decision = rules.decision

        # apply the ledger update for a real (non-test) approval
        ledger_applied, ledger_change = False, None
        if decision.outcome == "APPROVE" and decision.ledger_update and not is_test:
            with Session(engine) as session:
                ledger_change = apply_ledger_update(session, decision.ledger_update, run_id)
                session.commit()
            ledger_applied = True
        duration = int((time.monotonic() - started) * 1000)
        _update_run(engine, run_id, status="completed", decision=decision.outcome,
                    total_amount=invoice.total_amount.value, vendor_id=rules.vendor_id, po_number=rules.po_number,
                    duration_ms=duration, reasons_json=[r.model_dump(mode="json") for r in decision.reasons],
                    decision_json={**rules.model_dump(mode="json"), "ledger_applied": ledger_applied,
                                   "ledger_change": ledger_change})
        log.emit("run", "run_completed", status="completed", decision=decision.outcome, summary=decision.summary,
                 duration_ms=duration, ledger_applied=ledger_applied, ledger_change=ledger_change)
        logger.info("run completed", extra={"run_id": run_id, "status": "completed", "decision": decision.outcome,
                                            "codes": rules.codes, "duration_ms": duration,
                                            "verification": verification.engine_used, "ledger_applied": ledger_applied})
    except Exception as exc:  # noqa: BLE001 - a run must always end in a final state
        logger.exception("run failed with an internal error", extra={"run_id": run_id, "stage": stage})
        detail = f"{type(exc).__name__}: {exc}"
        log.fail(stage, error={"type": "internal_error", "message": "Processing stopped because of an internal error.",
                               "detail": detail[:500]})
        _update_run(engine, run_id, status="failed", error_json={"type": "internal_error", "message": detail[:500],
                                                                 "trace": traceback.format_exc()[-2000:]},
                    duration_ms=int((time.monotonic() - started) * 1000))
        log.emit("run", "run_completed", status="failed", decision=None)
    finally:
        if repo_session is not None:
            repo_session.close()


INTERRUPTED_MESSAGE = "The server restarted while this invoice was being processed. Retry to process it again."


def mark_interrupted_runs(engine: Engine) -> list[str]:
    """At startup: runs left 'queued' or 'running' by a previous server process will never finish, so mark them
    'interrupted' (closing the open stage and the event stream) instead of leaving them spinning forever.
    Queued runs of a batch are not touched: the batch worker processes them after the restart."""
    with Session(engine) as session:
        unfinished = (Run.status == "running") | ((Run.status == "queued") & Run.batch_id.is_(None))
        run_ids = list(session.scalars(select(Run.id).where(unfinished)))
    for run_id in run_ids:
        log = EventLog(engine, run_id)
        with Session(engine) as session:
            events = session.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.id)).all()
            open_stages = {e.stage for e in events if e.event_type == "stage_started"} - {
                e.stage for e in events if e.event_type in ("stage_completed", "stage_failed")}
        error = {"type": "interrupted", "message": INTERRUPTED_MESSAGE}
        for stage in open_stages:
            log.emit(stage, "stage_failed", error=error)
        _update_run(engine, run_id, status="interrupted", error_json=error)
        log.emit("run", "run_completed", status="interrupted", decision=None)
        logger.warning("run interrupted by a server restart", extra={"run_id": run_id})
    return run_ids


def create_run_record(engine: Engine, file_name: str, data: bytes, model: str, retry_of: str | None = None,
                      sample_id: str | None = None, is_test_run: bool = False, model_name: str | None = None,
                      batch_id: str | None = None, use_cache: bool | None = None, source: dict | None = None) -> str:
    """Stage 1 checks up front (raises IntakeError with a user-facing reason), then store a queued run.
    model is the provider ('gemini' | 'groq'); model_name optionally picks one of its configured models."""
    if model not in ("gemini", "groq"):
        raise ValueError("model must be 'gemini' or 'groq'")
    if model_name and model_name not in effective_settings(engine).model_choices(model):
        raise ValueError(f"{model_name} is not one of the configured {model} models")
    info = intake(file_name, data)
    run_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(Run(id=run_id, file_name=file_name, file_hash=info.file_hash, file_bytes=data, model=model,
                        status="queued", mime_type=info.mime, page_count=info.page_count, retry_of=retry_of,
                        sample_id=sample_id, is_test_run=is_test_run, model_name=model_name or None,
                        batch_id=batch_id, use_cache=use_cache, source_json=source))
        session.commit()
    return run_id


def seeded_repository(buyer: BuyerRecord | None = None) -> InMemoryRepository:
    """The untouched seeded state from data/master (used by the sandboxed Test Suite)."""
    repo = InMemoryRepository.from_master_dir(MASTER_DIR)
    if buyer is not None:
        repo.buyer = buyer
    return repo
