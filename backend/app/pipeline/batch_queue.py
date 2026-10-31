"""Bulk uploads: every invoice of a batch is queued, then processed one at a time in upload order.

One background thread per server process takes the oldest queued batch run, processes it (stages 1-8, the same
as a single run) and moves on. The queue lives in the database, so a server restart simply carries on with the
runs still queued. AI requests are spaced by the pacing in app.extraction, so a big batch stays under the
free-tier rate limits.
"""

from __future__ import annotations

import threading
from typing import Callable

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.logging_setup import get_logger
from app.models import Run
from app.pipeline.orchestrator import ExtractFn, process_run
from app.runtime_settings import effective_settings

logger = get_logger("batch")
IDLE_POLL_S = 5.0


def next_queued_run(engine: Engine) -> tuple[str, bool] | None:
    """(run id, use cache) of the oldest queued run that belongs to a batch, or None."""
    with Session(engine) as session:
        run = session.scalars(select(Run).where(Run.status == "queued", Run.batch_id.is_not(None))
                              .order_by(Run.created_at, Run.id)).first()
        return (run.id, bool(run.use_cache)) if run else None


def process_next(engine: Engine, extract_fn: ExtractFn) -> str | None:
    """Process one queued batch run; returns its id (None when the queue is empty)."""
    queued = next_queued_run(engine)
    if queued is None:
        return None
    run_id, use_cache = queued
    process_run(run_id, engine, effective_settings(engine), use_cache, extract_fn)
    return run_id


class BatchWorker:
    """The single thread that works through queued batch runs."""

    def __init__(self, engine: Engine, extract_fn: Callable[..., object]) -> None:
        self.engine = engine
        self.extract_fn = extract_fn
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="batch-worker", daemon=True)
        self._thread.start()

    def notify(self) -> None:
        """A new batch was queued: start now instead of at the next poll."""
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                done = process_next(self.engine, self.extract_fn)
            except Exception:  # noqa: BLE001 - the worker must survive anything (process_run already never raises)
                logger.exception("batch worker error")
                done = None
            if done is None:
                self._wake.wait(IDLE_POLL_S)
                self._wake.clear()
