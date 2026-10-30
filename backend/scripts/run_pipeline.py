"""Run the full 8-stage pipeline on one invoice and print the live event stream in colour.

Usage: python backend/scripts/run_pipeline.py <file | sample id> --model gemini|groq [--use-cache]
Uses the same database as the server, so an approval here really updates the PO ledger
(run it twice and the second run is rejected as a duplicate; POST /api/admin/reset-demo to start over).
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

from eval_common import BACKEND_DIR  # noqa: F401  (sets up sys.path)

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import sample_file, sample_labels
from app.config import get_settings
from app.db import get_engine
from app.main import prepare_database
from app.models import RunEvent
from app.pipeline.intake import IntakeError
from app.pipeline.orchestrator import STAGE_ORDER, create_run_record, process_run

os.system("")  # enables ANSI colours in the Windows console
COLOUR = {"passed": "\033[32m", "warning": "\033[33m", "failed": "\033[31m", "info": "\033[36m", "dim": "\033[90m",
          "APPROVE": "\033[42;30m", "HOLD": "\033[43;30m", "REJECT": "\033[41;97m", "bold": "\033[1m"}
RESET = "\033[0m"
STAGE_NO = {key: i + 1 for i, (key, _) in enumerate(STAGE_ORDER)}
STAGE_TITLE = dict(STAGE_ORDER)


def c(text: str, colour: str) -> str:
    return f"{COLOUR.get(colour, '')}{text}{RESET}"


def show(event: RunEvent) -> None:
    """Print one event as a coloured line."""
    p = event.payload
    kind = event.event_type
    if kind == "stage_started":
        print(c(f"[{STAGE_NO.get(event.stage, '-')}] {STAGE_TITLE.get(event.stage, event.stage)} ...", "bold"))
    elif kind == "check_result" and event.stage == "verification":
        status = p.get("status")
        colour = {"verified": "passed", "not_found": "failed", "unavailable": "warning"}.get(status, "dim")
        where = f"{p.get('source')} p{p.get('page')}" if status == "verified" else ""
        print(f"      {c(f'{status:14}', colour)} {p['field']:15} {str(p.get('value'))[:30]:30} {c(where, 'dim')}")
    elif kind == "check_result":
        colour = {"REJECT": "failed", "HOLD": "warning", "INFO": "info"}.get(p.get("severity"), "passed")
        mark = p.get("code") or "ok"
        print(f"      {c(mark.ljust(30), colour)} {p.get('message', '')}")
    elif kind == "stage_completed":
        status = p.get("status", "passed")
        extra = ""
        if event.stage == "extraction":
            extra = f"  {p.get('provider')} / {p.get('model_name')}" + ("  [cached extraction]" if p.get("cached") else "")
        elif event.stage == "verification":
            extra = f"  {p.get('verified')}/{p.get('printed')} fields found on the page ({p.get('engine_used')})"
        print(c(f"    -> {status} ({p.get('duration_ms', 0)} ms){extra}", status))
    elif kind == "stage_failed":
        error = p.get("error") or {}
        print(c(f"    -> FAILED [{error.get('type')}] {error.get('message')}", "failed"))
    elif kind == "run_completed":
        decision = p.get("decision")
        if decision:
            print("\n" + c(f"  {decision}  ", decision) + f"  {p.get('summary', '')}")
            if p.get("ledger_applied"):
                print(c("  PO ledger and invoice history updated.", "info"))
        else:
            print("\n" + c(f"  Run ended: {p.get('status')}", "failed"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="path to a PDF/PNG/JPG, or a sample id such as 01_happy_clean")
    parser.add_argument("--model", choices=["gemini", "groq"], default=None)
    parser.add_argument("--use-cache", action="store_true", help="reuse a cached extraction (saves free-tier quota)")
    args = parser.parse_args()
    settings = get_settings()
    engine = get_engine()
    prepare_database(engine)
    if Path(args.source).is_file():
        name, data, sample_id = Path(args.source).name, Path(args.source).read_bytes(), None
    elif args.source in sample_labels():
        (name, data), sample_id = sample_file(args.source), args.source
    else:
        sys.exit(f"{args.source} is neither a file nor a sample id")
    try:
        run_id = create_run_record(engine, name, data, args.model or settings.default_model, sample_id=sample_id)
    except IntakeError as exc:
        sys.exit(f"Rejected at intake: {exc}")
    print(c(f"Run {run_id}  {name}", "dim"))
    worker = threading.Thread(target=process_run, args=(run_id, engine, settings, args.use_cache))
    worker.start()
    last_id, done = 0, False
    while not done:
        with Session(engine) as session:
            events = session.scalars(select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.id > last_id)
                                     .order_by(RunEvent.id)).all()
            for event in events:
                last_id = event.id
                show(event)
                done = done or event.event_type == "run_completed"
        if not done:
            time.sleep(0.2)
    worker.join()


if __name__ == "__main__":
    main()
