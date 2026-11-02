"""Running processes: every invoice and batch still being processed, plus what finished recently.

Processing happens on the server, so it continues when the person leaves the live screen; this is where they find
it again.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.batches import _batch_dict, _runs_of
from app.api.common import engine_of, run_summary
from app.models import Batch, Run, RunEvent
from app.pipeline.orchestrator import STAGE_ORDER

router = APIRouter(prefix="/api", tags=["running"])
ACTIVE = ("queued", "running")
RECENT_MINUTES = 30
STAGE_TITLES = dict(STAGE_ORDER)


def _current_stage(session: Session, run_id: str) -> dict | None:
    """The stage a running invoice is in (the last one started), with its position in the 8 stages."""
    started = session.scalars(select(RunEvent.stage).where(RunEvent.run_id == run_id, RunEvent.event_type == "stage_started")
                              .order_by(RunEvent.id.desc())).first()
    if started not in STAGE_TITLES:
        return None
    keys = list(STAGE_TITLES)
    return {"key": started, "title": STAGE_TITLES[started], "number": keys.index(started) + 1, "of": len(keys)}


@router.get("/running")
def running(request: Request) -> dict:
    """Single runs and batches in progress (oldest first), then those started in the last 30 minutes that finished."""
    since = datetime.now(timezone.utc) - timedelta(minutes=RECENT_MINUTES)
    single = select(Run).where(Run.batch_id.is_(None), Run.is_test_run.is_(False))
    with Session(engine_of(request)) as session:
        active_runs = [{**run_summary(r), "stage": _current_stage(session, r.id)}
                       for r in session.scalars(single.where(Run.status.in_(ACTIVE)).order_by(Run.created_at))]
        recent_runs = [run_summary(r) for r in session.scalars(
            single.where(Run.status.not_in(ACTIVE), Run.created_at >= since).order_by(Run.created_at.desc()).limit(10))]
        batches = [_batch_dict(b, _runs_of(session, b.id))
                   for b in session.scalars(select(Batch).order_by(Batch.created_at.desc()).limit(50))]
    active_batches = [b for b in reversed(batches) if not b["finished"]]
    recent_batches = [b for b in batches if b["finished"] and b["created_at"] >= since.isoformat()][:5]
    return {"active": len(active_runs) + len(active_batches), "runs": active_runs, "batches": active_batches,
            "recent_runs": recent_runs, "recent_batches": recent_batches}
