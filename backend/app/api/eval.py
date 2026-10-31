"""Test Suite: run the 12 golden invoices as sandboxed test runs and compare with their expected outcomes.

Test runs are judged against the seeded master data held in memory (so earlier demo approvals cannot
affect them) and never change the ledger (CLAUDE.md §9).
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.common import engine_of, sample_file, sample_labels
from app.config import REPO_ROOT
from app.config import get_settings
from app.models import Run
from app.pipeline.evaluation import judge
from app.pipeline.orchestrator import create_run_record, process_run, seeded_repository
from app.runtime_settings import effective_settings

router = APIRouter(prefix="/api", tags=["eval"])
_lock = threading.Lock()
_latest: dict = {}


class SuiteRequest(BaseModel):
    model: str | None = None
    use_cache: bool = True
    delay_s: float = 13.0  # pause after each live model call (free-tier pacing)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_suite(suite: dict, engine, extract_fn, model: str, use_cache: bool, delay_s: float) -> None:
    settings = effective_settings(engine)
    for index, item in enumerate(suite["items"]):
        label = sample_labels()[item["sample_id"]]
        name, data = sample_file(item["sample_id"])
        run_id = create_run_record(engine, name, data, model, sample_id=item["sample_id"], is_test_run=True)
        item.update(run_id=run_id, status="running")
        process_run(run_id, engine, settings, use_cache, extract_fn, repository=seeded_repository())
        with Session(engine) as session:
            run = session.get(Run, run_id)
            codes = [r["code"] for r in (run.reasons_json or []) if r.get("code")]
            outcome, status, cached = run.decision, run.status, run.used_cache
            error = run.error_json
        passed, problems = judge(label, outcome, codes) if status == "completed" else (False, [f"run {status}"])
        item.update(status=status, actual=outcome, codes=sorted(set(codes)), passed=passed, problems=problems,
                    cached=cached, error=error and error.get("message"))
        suite["done"] = index + 1
        suite["passed"] = sum(1 for i in suite["items"] if i.get("passed"))
        if not cached and index < len(suite["items"]) - 1 and delay_s > 0:
            suite["next_call_at"] = time.time() + delay_s
            time.sleep(delay_s)
            suite["next_call_at"] = None
    suite.update(status="done", finished_at=_now())


@router.post("/eval/golden")
def start_suite(body: SuiteRequest, request: Request, background: BackgroundTasks) -> dict:
    """Start the golden Test Suite in the background (one at a time)."""
    global _latest
    with _lock:
        if _latest.get("status") == "running":
            raise HTTPException(status_code=409, detail="The test suite is already running.")
        model = body.model or get_settings().default_model
        golden = [l for l in sample_labels().values() if l["set_name"] == "golden"]
        _latest = {
            "id": str(uuid.uuid4()), "status": "running", "model": model, "use_cache": body.use_cache,
            "started_at": _now(), "finished_at": None, "done": 0, "passed": 0, "total": len(golden), "next_call_at": None,
            "items": [{"sample_id": l["invoice_id"], "scenario": l["scenario"], "expected": l["expected_decision"],
                       "acceptable": l["acceptable_decisions"], "expected_codes": l["expected_reason_codes"],
                       "status": "pending"} for l in golden],
        }
    background.add_task(run_suite, _latest, engine_of(request), request.app.state.extract_fn, model, body.use_cache,
                        body.delay_s)
    return {"suite_id": _latest["id"], "total": _latest["total"]}


REPORT_DIR = REPO_ROOT / "data" / "eval_reports"
REPORT_KINDS = {
    "rules": ["rules_eval_all_", "rules_eval_golden_", "rules_eval_stress_"],
    "extraction_gemini": ["extraction_eval_golden_gemini_", "extraction_eval_golden_both_"],
    "extraction_groq": ["extraction_eval_golden_groq_"],
    "verification": ["verification_eval_all_minconf40_", "verification_eval_all_"],
}


@router.get("/eval/reports")
def latest_reports() -> dict:
    """The newest saved evaluation report of each kind (markdown), for the Test Suite screen."""
    out = {}
    for kind, prefixes in REPORT_KINDS.items():
        for prefix in prefixes:
            files = sorted(REPORT_DIR.glob(f"{prefix}*.md"), key=lambda p: p.name, reverse=True)
            if files:
                out[kind] = {"file": files[0].name, "markdown": files[0].read_text(encoding="utf-8")}
                break
    return out


@router.get("/eval/latest")
def latest_suite() -> dict:
    """The latest Test Suite: progress, and expected vs actual per golden invoice."""
    if not _latest:
        return {"status": "never_run", "items": []}
    data = {**_latest, "items": [dict(i) for i in _latest["items"]]}
    if data.get("next_call_at"):
        data["next_call_in_s"] = max(0, round(data["next_call_at"] - time.time()))
    return data
