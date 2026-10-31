"""Stage 2: AI extraction of invoice fields (the only place an LLM is used)."""

from __future__ import annotations

import hashlib

from PIL import Image
from sqlalchemy import Engine

from app.config import Settings
from app.extraction.base import Extractor, ProviderError, make_error
from app.extraction.cache import get_cached, put_cached
from app.extraction.pacing import wait_for_turn
from app.logging_setup import get_logger
from app.schemas import ExtractionResult

PROVIDERS = ("gemini", "groq")
logger = get_logger("extraction")


def file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def model_name_for(provider: str, settings: Settings) -> str:
    return settings.gemini_model if provider == "gemini" else settings.groq_model


def get_extractor(provider: str, settings: Settings) -> Extractor:
    """Build the extractor for 'gemini' or 'groq' from settings. Raises ProviderError if not configured."""
    from app.extraction.gemini import GeminiExtractor
    from app.extraction.groq import GroqExtractor

    if provider not in PROVIDERS:
        raise ValueError(f"Unknown model provider {provider!r}")
    model_name = model_name_for(provider, settings)
    if not model_name:
        raise ProviderError("auth_error", f"{provider.upper()}_MODEL is not set")
    if provider == "gemini":
        return GeminiExtractor(settings.gemini_api_key, model_name)
    return GroqExtractor(settings.groq_api_key, model_name)


def extract_document(
    file_bytes: bytes,
    mime: str,
    provider: str,
    settings: Settings,
    engine: Engine | None = None,
    use_cache: bool = False,
    page_images: list[Image.Image] | None = None,
) -> ExtractionResult:
    """Stage 2 entry point: cache lookup (only if asked), one extraction, cache store."""
    model_name = model_name_for(provider, settings)
    digest = file_hash(file_bytes)
    if use_cache and engine is not None:
        cached = get_cached(engine, digest, provider, model_name)
        if cached is not None:
            return cached
    try:
        extractor = get_extractor(provider, settings)
    except ProviderError as exc:
        return ExtractionResult(model_name=model_name or "(not set)", provider=provider,
                                error=make_error(provider, exc.error_type, exc.detail))
    waited = wait_for_turn(settings.ai_request_gap_s)
    if waited:
        logger.info("paced AI request", extra={"provider": provider, "waited_s": round(waited, 1)})
    result = extractor.extract(file_bytes, mime, page_images)
    if use_cache and engine is not None:
        put_cached(engine, digest, result)
    return result
