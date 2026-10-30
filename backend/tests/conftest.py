"""Shared pytest fixtures."""

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def fresh_settings():
    """Clear cached settings so each test sees its own environment."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
