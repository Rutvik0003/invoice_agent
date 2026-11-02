"""Shared pytest fixtures."""

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch):
    """Clear cached settings so each test sees its own environment. Real-mode sign-in is off unless a test turns it
    on (a developer's .env may lock real mode to their Google account)."""
    for name in ("OWNER_EMAIL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI", "TOKEN_ENCRYPTION_KEY"):
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
