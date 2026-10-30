"""FastAPI entry point: serves the API under /api and the built frontend at /."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import __version__
from app.config import REPO_ROOT, get_settings

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


class ModelsConfigured(BaseModel):
    gemini: bool
    groq: bool


class HealthResponse(BaseModel):
    status: str
    version: str
    models_configured: ModelsConfigured


def create_app(frontend_dist: Path = FRONTEND_DIST) -> FastAPI:
    """Build the app; the frontend is served only if it has been built."""
    app = FastAPI(title="Invoice Agent", version=__version__)

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness check; reports whether each model's API key is set (never the key itself)."""
        settings = get_settings()
        return HealthResponse(
            status="ok",
            version=__version__,
            models_configured=ModelsConfigured(
                gemini=settings.gemini_configured,
                groq=settings.groq_configured,
            ),
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
