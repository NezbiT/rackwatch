"""Pytest fixtures. Isolated SQLite, no Docker or Prometheus required."""

from __future__ import annotations

import os

# Must be set before app.config / app.database are imported.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/test-rackwatch.db")
os.environ.setdefault("RACKWATCH_SECRET_KEY", "test-secret")
os.environ.setdefault("RACKWATCH_API_TOKEN", "test-token")
os.environ.setdefault("RACKWATCH_ENV", "development")
os.environ.setdefault("AUTO_RESTART_ENABLED", "false")
os.environ.setdefault("MQTT_HOST", "")
os.environ.setdefault("HA_URL", "")

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings


@pytest.fixture
def settings():
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def client():
    """Full ASGI app with lifespan (collector starts, then we hit routes)."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
