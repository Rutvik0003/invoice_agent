"""Structured logs: one JSON object per line, tagged with the run_id, with API keys redacted.

Never log file contents or extracted invoice data: only ids, stages, statuses, timings and error types.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from app.config import get_settings

LOGGER_NAME = "invoice_agent"
REDACTED = "[redacted]"
# attributes every LogRecord has; anything else was passed with extra={...} and goes into the JSON
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


def secrets() -> list[str]:
    """Values that must never appear in a log line (the configured API keys)."""
    settings = get_settings()
    return [s for s in (settings.gemini_api_key.strip(), settings.groq_api_key.strip()) if len(s) >= 6]


def redact(text: str, hidden: list[str]) -> str:
    for secret in hidden:
        text = text.replace(secret, REDACTED)
    return text


class JsonFormatter(logging.Formatter):
    """{"time", "level", "logger", "message", ...extra fields, "exception"} on one line, secrets redacted."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update({k: v for k, v in vars(record).items() if k not in _STANDARD and not k.startswith("_")})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return redact(json.dumps(entry, default=str, ensure_ascii=False), secrets())


def configure_logging(level: int = logging.INFO) -> None:
    """Attach the JSON handler to the app's logger once (safe to call again, e.g. per test app)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    if not any(getattr(h, "_invoice_agent", False) for h in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        handler._invoice_agent = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
