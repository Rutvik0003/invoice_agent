"""Demo sandboxes: every demo visitor gets their own copy of the freshly seeded database (CLAUDE.md §12).

The first demo visit of a server process builds a template database (tables + seeded master data); each new
visitor gets a copy of that file. A visitor's runs, approvals, holds and settings therefore never reach another
visitor or the real database. Sandboxes not used for `ttl_hours` are deleted.
"""

from __future__ import annotations

import re
import shutil
import threading
import time
import weakref
from pathlib import Path
from typing import Callable

from sqlalchemy import Engine

from app.config import get_settings
from app.db import BACKEND_DIR, init_db, make_engine
from app.logging_setup import get_logger

logger = get_logger("demo")
VISITOR_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")  # also keeps file names safe
SWEEP_EVERY_S = 600
TEMPLATE = "_template.db"

# engines that belong to a demo sandbox (runtime_settings uses this to pick the demo AI key)
_demo_engines: "weakref.WeakSet[Engine]" = weakref.WeakSet()


def is_demo_engine(engine: Engine) -> bool:
    return engine in _demo_engines


def sandbox_dir(configured: str) -> Path:
    path = Path(configured)
    return path if path.is_absolute() else BACKEND_DIR / path


class SandboxPool:
    """Opens (and creates on first use) one SQLite database per demo visitor."""

    def __init__(self, prepare: Callable[[Engine], None], on_open: Callable[[Engine], None] | None = None,
                 directory: Path | None = None, ttl_hours: float | None = None) -> None:
        self._directory = directory  # default: DEMO_SANDBOX_DIR / DEMO_SANDBOX_TTL_HOURS, read on first use
        self._ttl_hours = ttl_hours
        self._prepare = prepare  # tables + seeded master data (used once, for the template)
        self._on_open = on_open  # e.g. mark runs a restart interrupted
        self._engines: dict[str, Engine] = {}
        self._last_used: dict[str, float] = {}
        self._template_ready = False
        self._last_sweep = 0.0
        self._lock = threading.RLock()

    @property
    def directory(self) -> Path:
        if self._directory is None:
            self._directory = sandbox_dir(get_settings().demo_sandbox_dir)
        return self._directory

    @property
    def ttl_s(self) -> float:
        if self._ttl_hours is None:
            self._ttl_hours = get_settings().demo_sandbox_ttl_hours
        return self._ttl_hours * 3600

    def _path(self, visitor_id: str) -> Path:
        if not VISITOR_ID.match(visitor_id):
            raise ValueError("invalid visitor id")
        return self.directory / f"{visitor_id}.db"

    def _template(self) -> Path:
        """The seeded database new visitors start from (rebuilt once per server process, so it follows data/master)."""
        path = self.directory / TEMPLATE
        if not self._template_ready:
            self.directory.mkdir(parents=True, exist_ok=True)
            path.unlink(missing_ok=True)
            engine = make_engine(f"sqlite:///{path.as_posix()}")
            self._prepare(engine)
            engine.dispose()
            self._template_ready = True
        return path

    def engine_for(self, visitor_id: str) -> Engine:
        """The visitor's database, created from the template on their first visit."""
        with self._lock:
            self._last_used[visitor_id] = time.time()
            engine = self._engines.get(visitor_id)
            if engine is None:
                path = self._path(visitor_id)
                fresh = not path.exists()
                if fresh:
                    shutil.copyfile(self._template(), path)
                engine = make_engine(f"sqlite:///{path.as_posix()}")
                if not fresh:
                    init_db(engine)  # a sandbox from an earlier server version: add new columns
                    if self._on_open is not None:
                        self._on_open(engine)
                _demo_engines.add(engine)
                self._engines[visitor_id] = engine
                logger.info("demo sandbox opened", extra={"fresh": fresh})
            self._sweep()
            return engine

    def engines(self) -> list[Engine]:
        """Every open sandbox (the batch worker serves their queues too)."""
        with self._lock:
            return list(self._engines.values())

    def _sweep(self) -> None:
        """Delete sandboxes nobody used for ttl_hours (at most every few minutes)."""
        now = time.time()
        if now - self._last_sweep < SWEEP_EVERY_S:
            return
        self._last_sweep = now
        for path in self.directory.glob("*.db"):
            visitor_id = path.stem
            if path.name == TEMPLATE or not VISITOR_ID.match(visitor_id):
                continue
            last = self._last_used.get(visitor_id, path.stat().st_mtime)
            if now - last < self.ttl_s:
                continue
            engine = self._engines.pop(visitor_id, None)
            if engine is not None:
                engine.dispose()
            self._last_used.pop(visitor_id, None)
            try:
                path.unlink()
                logger.info("demo sandbox expired")
            except OSError:  # still in use on Windows: try again at the next sweep
                pass
