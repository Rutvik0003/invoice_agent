"""Application settings, read from environment variables (and a local .env file)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """All configurable values. Defaults match CLAUDE.md §5; env vars override them."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    database_url: str = "sqlite:///./local.db"

    # AI providers (keys are secrets: never log or return them)
    gemini_api_key: str = ""
    groq_api_key: str = ""
    gemini_model: str = ""
    groq_model: str = ""
    default_model: str = "gemini"

    # Business rules
    tolerance_pct: float = 1.0
    tolerance_abs_inr: float = 500.0
    confidence_threshold: float = 0.80
    po_infer_min_score: float = 0.85
    po_infer_min_gap: float = 0.15
    po_infer_floor: float = 0.50
    possible_dup_days: int = 3

    @property
    def gemini_configured(self) -> bool:
        """True when a Gemini API key is set."""
        return bool(self.gemini_api_key.strip())

    @property
    def groq_configured(self) -> bool:
        """True when a Groq API key is set."""
        return bool(self.groq_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
