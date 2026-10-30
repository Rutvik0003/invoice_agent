"""Extraction cache keyed by (file_hash, provider:model). Used only when use_cache=True (CLAUDE.md §9)."""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models import ExtractionCache
from app.schemas import ExtractionResult


def cache_key(provider: str, model_name: str) -> str:
    return f"{provider}:{model_name}"


def get_cached(engine: Engine, file_hash: str, provider: str, model_name: str) -> ExtractionResult | None:
    with Session(engine) as session:
        row = session.get(ExtractionCache, (file_hash, cache_key(provider, model_name)))
        if row is None:
            return None
        result = ExtractionResult.model_validate(row.result_json)
        return result.model_copy(update={"cached": True})


def put_cached(engine: Engine, file_hash: str, result: ExtractionResult) -> None:
    """Store only successful extractions (errors must be retried, not replayed)."""
    if result.invoice is None:
        return
    with Session(engine) as session:
        session.merge(ExtractionCache(
            file_hash=file_hash,
            model=cache_key(result.provider, result.model_name),
            result_json=result.model_copy(update={"cached": False}).model_dump(mode="json"),
        ))
        session.commit()
