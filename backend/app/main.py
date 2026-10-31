"""FastAPI entry point: serves the API under /api and the built frontend at /."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app import __version__
from app.api import admin, batches, data, email, eval as eval_api, holds, runs
from app.config import REPO_ROOT, get_settings
from app.db import get_engine, init_db
from app.extraction import extract_document
from app.logging_setup import configure_logging
from app.models import Vendor
from app.pipeline.batch_queue import BatchWorker
from app.pipeline.orchestrator import mark_interrupted_runs
from app.seed import seed_master
from app.verification.ocr import OcrStatus, tesseract_status

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


class ModelsConfigured(BaseModel):
    gemini: bool
    groq: bool


class HealthResponse(BaseModel):
    status: str
    version: str
    models_configured: ModelsConfigured
    ocr: OcrStatus


def prepare_database(engine: Engine) -> None:
    """Create tables, and load the seeded master data into an empty database (e.g. a fresh deploy)."""
    init_db(engine)
    with Session(engine) as session:
        empty = session.scalar(select(func.count()).select_from(Vendor)) == 0
    if empty:
        seed_master(engine)


def create_app(frontend_dist: Path = FRONTEND_DIST, engine: Engine | None = None, extract_fn=None) -> FastAPI:
    """Build the app. Tests pass their own database engine and a fake extractor (no network)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        prepare_database(app.state.engine)
        mark_interrupted_runs(app.state.engine)
        app.state.batch_worker.start()
        yield
        app.state.batch_worker.stop()

    app = FastAPI(title="Invoice Agent", version=__version__, lifespan=lifespan)
    app.state.engine = engine or get_engine()
    app.state.extract_fn = extract_fn or extract_document
    app.state.batch_worker = BatchWorker(app.state.engine, app.state.extract_fn)
    for module in (runs, batches, email, holds, data, admin, eval_api):
        app.include_router(module.router)

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness check; reports configured models (never the keys) and whether OCR is available."""
        settings = get_settings()
        return HealthResponse(
            status="ok",
            version=__version__,
            models_configured=ModelsConfigured(
                gemini=settings.gemini_configured,
                groq=settings.groq_configured,
            ),
            ocr=tesseract_status(settings),
        )

    if (frontend_dist / "index.html").is_file():
        _mount_frontend(app, frontend_dist)

    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve built assets, falling back to index.html for client-side routes."""
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist.resolve()):
            return FileResponse(file)
        return FileResponse(dist / "index.html")


app = create_app()
