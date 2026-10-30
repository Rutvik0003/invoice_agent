"""Helpers shared by the API routers: database access, labels for the sample picker, run serialisation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import HTTPException, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.models import Run

INVOICE_DIR = REPO_ROOT / "data" / "invoices"


def engine_of(request: Request) -> Engine:
    return request.app.state.engine


def get_run_or_404(session: Session, run_id: str) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@lru_cache
def sample_labels() -> dict[str, dict]:
    """Every generated invoice's label, keyed by invoice id (golden first)."""
    out: dict[str, dict] = {}
    for set_name in ("golden", "stress"):
        for path in sorted((INVOICE_DIR / set_name / "labels").glob("*.json")):
            label = json.loads(path.read_text(encoding="utf-8"))
            if (INVOICE_DIR / set_name / label["file_name"]).exists():
                out[label["invoice_id"]] = label
    return out


def sample_file(sample_id: str) -> tuple[str, bytes]:
    label = sample_labels().get(sample_id)
    if label is None:
        raise HTTPException(status_code=404, detail=f"Unknown sample {sample_id}")
    path = INVOICE_DIR / label["set_name"] / label["file_name"]
    return label["file_name"], path.read_bytes()


def iso_utc(moment: datetime | None) -> str | None:
    """ISO timestamp that always says UTC (SQLite hands datetimes back without a timezone)."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.isoformat()


def _extracted_value(run: Run, field: str) -> object:
    data = run.extracted_json or {}
    return (data.get(field) or {}).get("value")


def run_summary(run: Run) -> dict:
    """The row shown in tables and lists."""
    return {
        "id": run.id,
        "created_at": iso_utc(run.created_at),
        "file_name": run.file_name,
        "model": run.model,
        "model_name": run.model_name,
        "status": run.status,
        "decision": run.decision,
        "total_amount": float(run.total_amount) if run.total_amount is not None else _extracted_value(run, "total_amount"),
        "vendor_id": run.vendor_id,
        "vendor_name": _extracted_value(run, "vendor_name"),
        "invoice_number": _extracted_value(run, "invoice_number"),
        "po_number": run.po_number,
        "duration_ms": run.duration_ms,
        "used_cache": run.used_cache,
        "is_test_run": run.is_test_run,
        "retry_of": run.retry_of,
        "sample_id": run.sample_id,
        "page_count": run.page_count,
        "error": run.error_json and {k: run.error_json.get(k) for k in ("type", "message")},
    }
