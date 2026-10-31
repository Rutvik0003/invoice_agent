"""Admin: reset the demo to the seeded state (CLAUDE.md §9)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.common import engine_of
from app.db import Base
from app.logging_setup import get_logger
from app.models import RUN_TABLES
from app.runtime_settings import EditableSettings, current_editable, save_editable
from app.seed import seed_master

router = APIRouter(prefix="/api", tags=["admin"])
logger = get_logger("admin")


def reset_demo(engine) -> dict:
    """Restore vendors, POs and invoice history from data/master, and clear every run (caches are kept)."""
    counts = seed_master(engine)
    Base.metadata.drop_all(engine, tables=list(reversed(RUN_TABLES)))
    Base.metadata.create_all(engine, tables=RUN_TABLES)
    logger.info("demo data reset", extra=counts)
    return {"reset": True, **counts, "runs": 0}


@router.post("/admin/reset-demo")
def post_reset(request: Request) -> dict:
    return reset_demo(engine_of(request))


@router.get("/admin/settings")
def get_editable(request: Request) -> EditableSettings:
    """The settings an admin may change here: the pause between AI requests."""
    return current_editable(engine_of(request))


@router.put("/admin/settings")
def put_editable(body: EditableSettings, request: Request) -> EditableSettings:
    """Save them (they override the environment defaults until changed again; a demo reset keeps them)."""
    saved = save_editable(engine_of(request), body)
    logger.info("settings changed", extra={"ai_request_gap_s": saved.ai_request_gap_s})
    return saved
