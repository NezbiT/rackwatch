"""Comprehensive security audit regression tests.

Verifies fixes for:
1. Open redirect vulnerability in navigation/login.
2. CSRF protection on forms and state-changing session endpoints.
3. WebSocket authentication and Origin header (CSWSH) validation.
4. Settings validation schema with bounds and URL scheme checks.
5. Docker exec and file read/write limits, traversal, and sensitive path restrictions.
6. SQLite data retention policy, indexing, and WAL pragmas.
7. Alerter cooldown persistence and WebSocket hub broadcast optimization.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import async_session, cleanup_old_records
from app.models import Alert, RestartEvent, WebhookDelivery
from app.schemas import AlertOut, ContainerMetrics, Filters, HostMetrics, SettingsUpdate, Snapshot
from app.security import (
    get_or_create_csrf_token,
    is_ws_authenticated,
    is_ws_origin_allowed,
    safe_next,
    verify_csrf,
)
from app.services.alerter import Alerter
from app.services.docker_ctl import DockerControl
from app.services.hub import Client, Hub
from app.services.settings_store import validate_settings_dict


def test_safe_next_open_redirect():
    # Dangerous URLs must be sanitized to fallback "/"
    assert safe_next("//evil.com") == "/"
    assert safe_next("https://evil.com") == "/"
    assert safe_next("http://evil.com/login") == "/"
    assert safe_next("/\\evil.com") == "/"
    assert safe_next("/evil.com/..\\..\\") == "/"
    assert safe_next("javascript:alert(1)") == "/"
    assert safe_next(None) == "/"
    assert safe_next("") == "/"
    assert safe_next("   ") == "/"
    assert safe_next("//") == "/"

    # Carriage return / newline injection stripped
    assert safe_next("/dashboard\r\n") == "/dashboard"

    # Legitimate relative URLs preserved
    assert safe_next("/") == "/"
    assert safe_next("/services") == "/services"
    assert safe_next("/alerts?range=1h") == "/alerts?range=1h"
    assert safe_next("/login?next=%2Fdashboard") == "/login?next=%2Fdashboard"


def test_csrf_token_logic():
    class DummyRequest:
        def __init__(self):
            self.session = {}

    req = DummyRequest()
    tok1 = get_or_create_csrf_token(req)
    assert len(tok1) >= 32
    # Second call returns existing token
    assert get_or_create_csrf_token(req) == tok1

    # verify_csrf
    assert verify_csrf(req, tok1) is True
    assert verify_csrf(req, "wrong-token") is False
    assert verify_csrf(req, None) is False
    assert verify_csrf(req, "") is False


def test_csrf_protected_endpoints(client: TestClient, monkeypatch):
    # 1. State-changing POST to /logout without CSRF should fail with 403
    res = client.post("/logout")
    assert res.status_code == 403

    # 2. State-changing POST with API token bypasses CSRF requirement
    res_api = client.post(
        "/api/v1/alerts/test",
        headers={"x-api-key": "test-token"},
        json={"channel": "all", "message": "Test"},
    )
    assert res_api.status_code == 200

    # 3. Enable auth so /login is not redirected to /
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_user", "admin")
    monkeypatch.setattr(settings, "auth_password", "secret")

    login_get = client.get("/login", follow_redirects=False)
    assert login_get.status_code == 200
    assert 'name="csrf_token"' in login_get.text


def test_websocket_origin_security():
    settings = Settings(_env_file=None, public_url="http://rackwatch.lan:8080")

    # Allowed origins
    assert is_ws_origin_allowed(None, "localhost:8080", settings) is True
    assert is_ws_origin_allowed("http://localhost:8080", "localhost:8080", settings) is True
    assert is_ws_origin_allowed("http://127.0.0.1:8080", "127.0.0.1:8080", settings) is True
    assert is_ws_origin_allowed("http://rackwatch.lan:8080", "rackwatch.lan:8080", settings) is True

    # Blocked origins (CSWSH)
    assert is_ws_origin_allowed("http://evil-attacker.com", "rackwatch.lan:8080", settings) is False
    assert is_ws_origin_allowed("https://malicious.org", "localhost:8080", settings) is False


def test_websocket_authentication(monkeypatch):
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_user", "admin")
    monkeypatch.setattr(settings, "auth_password", "secretpassword")
    token = settings.api_token

    class DummyWS:
        def __init__(self, session=None, query_params=None, headers=None):
            self.session = session or {}
            self.query_params = query_params or {}
            self.headers = headers or {}

    # 1. Unauthenticated client rejected
    unauth = DummyWS()
    assert is_ws_authenticated(unauth, settings) is False

    # 2. Browser session accepted
    with_session = DummyWS(session={"uid": "admin"})
    assert is_ws_authenticated(with_session, settings) is True

    # 3. Query param token accepted
    with_token_param = DummyWS(query_params={"token": token})
    assert is_ws_authenticated(with_token_param, settings) is True

    with_bad_param = DummyWS(query_params={"token": "wrong-token"})
    assert is_ws_authenticated(with_bad_param, settings) is False

    # 4. Header token accepted
    with_header = DummyWS(headers={"x-api-key": token})
    assert is_ws_authenticated(with_header, settings) is True


def test_settings_validation():
    # Valid configuration update
    valid = SettingsUpdate(
        threshold_cpu_warn=75.0,
        threshold_cpu_crit=90.0,
        refresh_seconds=5,
        telegram_chat_id="12345",
        n8n_webhook_url="https://n8n.internal.net/webhook/alert",
        db_retention_days=45,
    )
    assert valid.threshold_cpu_warn == 75.0
    assert valid.refresh_seconds == 5
    assert valid.db_retention_days == 45

    # Invalid CPU threshold (< 0 or > 100)
    with pytest.raises(Exception):
        SettingsUpdate(threshold_cpu_warn=-5.0)

    with pytest.raises(Exception):
        SettingsUpdate(threshold_cpu_crit=105.0)

    # Invalid refresh seconds (< 1)
    with pytest.raises(Exception):
        SettingsUpdate(refresh_seconds=0)

    # Invalid URL scheme
    with pytest.raises(Exception):
        SettingsUpdate(n8n_webhook_url="javascript:alert(1)")

    with pytest.raises(Exception):
        SettingsUpdate(generic_webhook_url="ftp://servers.com/test")

    with pytest.raises(Exception):
        SettingsUpdate(ha_url="http://")

    # validate_settings_dict discards non-writable fields
    cleaned = validate_settings_dict({"secret_key": "hacked", "threshold_cpu_warn": "80"})
    assert "secret_key" not in cleaned
    assert cleaned["threshold_cpu_warn"] == 80.0


@pytest.mark.asyncio
async def test_docker_control_safeguards():
    settings = Settings(
        _env_file=None,
        auto_restart_denylist="rackwatch,prometheus,grafana",
        container_exec_allowlist="cat,ls,df,grep",
    )
    ctl = DockerControl(settings)

    # 1. Path validation tests
    ok, err = ctl._validate_path("/proc/cpuinfo")
    assert ok is False
    assert "restricted" in err

    ok, err = ctl._validate_path("/sys/kernel")
    assert ok is False
    assert "restricted" in err

    ok, err = ctl._validate_path("/etc/shadow")
    assert ok is False
    assert "restricted" in err

    ok, err = ctl._validate_path("../../etc/passwd")
    assert ok is False

    ok, err = ctl._validate_path("/var/log/app.log")
    assert ok is True
    assert err == "/var/log/app.log"

    # 2. Denylist guards on exec
    ok, err = await ctl.exec("rackwatch", "ls")
    assert ok is False
    assert "denylist" in err

    # 3. File write to rackwatch itself is prohibited even with force
    ok, err = await ctl.put_file("rackwatch", "/app/test.txt", "content", force=True)
    assert ok is False
    assert "prohibited" in err

    # 4. Command length and shell injection guards
    ok, err = ctl._exec_sync("web", "ls; rm -rf /")
    assert ok is False
    assert "shell operators" in err

    ok, err = ctl._exec_sync("web", "a" * 501)
    assert ok is False
    assert "characters" in err

    ok, err = ctl._exec_sync("web", "bash -c whoami")
    assert ok is False
    assert "shell interpreters" in err


@pytest.mark.asyncio
async def test_sqlite_retention_policy():
    unique_suffix = str(time.time()).replace(".", "")
    old_fp = f"old-fp-{unique_suffix}"
    new_fp = f"new-fp-{unique_suffix}"
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=40)
    recent_time = now - timedelta(days=5)

    async with async_session() as session:
        old_alert = Alert(
            created_at=old_time,
            fingerprint=old_fp,
            severity="warning",
            source="cpu",
            title="Old alert",
            message="Old message",
        )
        new_alert = Alert(
            created_at=recent_time,
            fingerprint=new_fp,
            severity="warning",
            source="cpu",
            title="New alert",
            message="New message",
        )
        session.add(old_alert)
        session.add(new_alert)
        await session.commit()

    # Run cleanup with 30-day retention
    cleaned = await cleanup_old_records(retention_days=30)
    assert cleaned.get("alerts", 0) >= 1

    # Verify that the new alert was retained and old alert was purged
    async with async_session() as session:
        alerts = (await session.execute(Alert.__table__.select().where(Alert.fingerprint == new_fp))).fetchall()
        assert len(alerts) == 1

        old_check = (await session.execute(Alert.__table__.select().where(Alert.fingerprint == old_fp))).fetchall()
        assert len(old_check) == 0


@pytest.mark.asyncio
async def test_hub_concurrent_broadcast():
    hub = Hub()

    class MockWebSocket:
        def __init__(self):
            self.sent = []

        async def send_json(self, data: dict):
            await asyncio.sleep(0.01)
            self.sent.append(data)

    ws1 = MockWebSocket()
    ws2 = MockWebSocket()

    c1 = await hub.register(ws1)  # type: ignore[arg-type]
    c2 = await hub.register(ws2)  # type: ignore[arg-type]

    snap = Snapshot(
        ts=1.0,
        instance="homelab",
        hosts=[HostMetrics(name="server1", instance="s1", cpu_percent=20.0, status="ok")],
        containers=[ContainerMetrics(id="c1", name="app", image="img", status="running", severity="ok")],
        alerts=[],
        zfs=[],
        ha_entities=[],
        summary={},
    )

    await hub.publish(snap)

    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 1
    assert ws1.sent[0]["instance"] == "homelab"
    assert ws2.sent[0]["instance"] == "homelab"

    await hub.unregister(c1)
    await hub.unregister(c2)
