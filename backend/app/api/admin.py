"""Admin: reset the demo to the seeded state (CLAUDE.md §9)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.common import engine_of
from app.db import Base
from app.demo.mode import is_demo
from app.logging_setup import get_logger
from app.api.eval import clear_suite
from app.api.runs import clear_page_images
from app.extraction import pacing
from app.models import RUN_TABLES, AppSetting
from app.runtime_settings import EditableSettings, current_editable, save_editable
from app.seed import seed_master

router = APIRouter(prefix="/api", tags=["admin"])
logger = get_logger("admin")


def reset_demo(engine, whole_app: bool = True) -> dict:
    """Back to a first visit: vendors, POs and invoice history from data/master; every run, batch, hold action and
    email deleted; Settings back to their defaults; the Test Suite result and the request pacing forgotten.
    Only the extraction and OCR caches are kept: they are invisible (a cached reading is used only when asked for,
    and always badged) and they save free-tier quota. A demo visitor (whole_app=False) resets only their own
    sandbox: the Test Suite result and the request pacing belong to the whole app."""
    counts = seed_master(engine)
    Base.metadata.drop_all(engine, tables=list(reversed(RUN_TABLES)))
    Base.metadata.create_all(engine, tables=RUN_TABLES)
    with Session(engine) as session:
        session.execute(delete(AppSetting))
        session.commit()
    clear_page_images()
    if whole_app:
        clear_suite()
        pacing.reset()
    logger.info("demo data reset", extra=counts)
    return {"reset": True, **counts, "runs": 0}


@router.post("/admin/reset-demo")
def post_reset(request: Request) -> dict:
    return reset_demo(engine_of(request), whole_app=not is_demo(request))


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
