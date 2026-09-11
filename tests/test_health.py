"""Smoke tests for liveness and the public API surface."""

from __future__ import annotations


def test_healthz(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_dashboard_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "RackWatch" in res.text
    assert "Dashboard" in res.text
    assert "filter-form" in res.text


def test_services_and_settings_render(client):
    assert client.get("/services").status_code == 200
    assert client.get("/alerts").status_code == 200
    assert client.get("/graphs").status_code == 200
    assert client.get("/home-assistant").status_code == 200
    assert client.get("/settings").status_code == 200
    assert client.get("/chat").status_code == 200


def test_api_health(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "prometheus" in body


def test_metrics_endpoint(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "rackwatch_up" in res.text


def test_snapshot_accepts_api_token(client):
    res = client.get("/api/v1/snapshot", headers={"X-API-Key": "test-token"})
    assert res.status_code in {200, 503}


def test_settings_read_redacts_secrets(client):
    res = client.get("/api/v1/settings", headers={"X-API-Key": "test-token"})
    assert res.status_code == 200
    body = res.json()
    assert "threshold_cpu_warn" in body
    assert "ha_token" in body
    assert body["ha_token"] in {"", "***"}


def test_container_logs_unknown(client):
    res = client.get("/api/v1/containers/no-such-box/logs", headers={"X-API-Key": "test-token"})
    assert res.status_code in {404, 400}


def test_hooks_require_token(client):
    res = client.post("/api/v1/hooks/alert", json={"title": "nope"})
    assert res.status_code == 401
    res = client.post(
        "/api/v1/hooks/alert",
        json={"title": "ok", "severity": "info"},
        headers={"X-API-Key": "test-token"},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
