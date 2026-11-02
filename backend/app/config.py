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
    # other Gemini models the user may pick per run (comma-separated); GEMINI_MODEL is the default choice
    gemini_models: str = "gemini-2.5-flash,gemini-3.6-flash,gemini-3.8-flash"
    # minimum seconds between two AI requests (free-tier rate limits); editable in Settings
    ai_request_gap_s: float = 6.0

    # Demo mode (CLAUDE.md §12): a separate Gemini key (its own Google Cloud project = its own free-tier quota),
    # Gemini only; empty values fall back to GEMINI_API_KEY / GEMINI_MODEL
    demo_gemini_api_key: str = ""
    demo_gemini_model: str = ""
    demo_gemini_models: str = ""  # the models a demo visitor may pick; empty = GEMINI_MODELS
    demo_max_runs_per_hour: int = 20
    demo_sandbox_ttl_hours: float = 24.0
    demo_sandbox_dir: str = "demo_sandboxes"  # relative paths are under backend/

    # Business rules
    tolerance_pct: float = 1.0
    tolerance_abs_inr: float = 500.0
    confidence_threshold: float = 0.80
    po_infer_min_score: float = 0.85
    po_infer_min_gap: float = 0.15
    po_infer_floor: float = 0.50
    possible_dup_days: int = 3

    # Stage 3: verify on page (text layer / OCR)
    verify_enabled: bool = True
    ocr_dpi: int = 300
    ocr_min_word_conf: int = 40
    verify_fuzzy_min: int = 90
    tesseract_cmd: str = ""

    @property
    def gemini_configured(self) -> bool:
        """True when a Gemini API key is set."""
        return bool(self.gemini_api_key.strip())

    @property
    def gemini_choices(self) -> list[str]:
        """GEMINI_MODEL first, then every other model listed in GEMINI_MODELS (no duplicates)."""
        names = [self.gemini_model, *(m.strip() for m in self.gemini_models.split(","))]
        return list(dict.fromkeys(n for n in names if n))

    def model_choices(self, provider: str) -> list[str]:
        return self.gemini_choices if provider == "gemini" else [self.groq_model] if self.groq_model else []

    def for_demo(self) -> "Settings":
        """The settings a demo visitor runs with: Gemini only, on the demo key (no Groq, no fallback). The visitor
        may pick any of the Gemini models (free-tier limits are per model, so another model can still answer)."""
        return self.model_copy(update={
            "gemini_api_key": self.demo_gemini_api_key or self.gemini_api_key,
            "gemini_model": self.demo_gemini_model or self.gemini_model,
            "gemini_models": self.demo_gemini_models or self.gemini_models, "groq_api_key": "", "groq_model": "", "default_model": "gemini",
        })

    @property
    def groq_configured(self) -> bool:
        """True when a Groq API key is set."""
        return bool(self.groq_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
