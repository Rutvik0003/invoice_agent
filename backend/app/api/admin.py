"""Admin: reset the demo to the seeded state (CLAUDE.md §9)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.common import engine_of
from app.db import Base
from app.models import RUN_TABLES
from app.seed import seed_master

router = APIRouter(prefix="/api", tags=["admin"])


def reset_demo(engine) -> dict:
    """Restore vendors, POs and invoice history from data/master, and clear every run (caches are kept)."""
    counts = seed_master(engine)
    Base.metadata.drop_all(engine, tables=list(reversed(RUN_TABLES)))
    Base.metadata.create_all(engine, tables=RUN_TABLES)
    return {"reset": True, **counts, "runs": 0}


@router.post("/admin/reset-demo")
def post_reset(request: Request) -> dict:
    return reset_demo(engine_of(request))
