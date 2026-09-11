"""Alerter fingerprint + payload contract used by n8n / HA / SaaS."""

from __future__ import annotations

from app.config import Settings
from app.services.alerter import Alerter


def test_fingerprint_is_stable():
    alerter = Alerter(Settings())
    a = alerter.fingerprint("container", "lab", "plex", "plex is down")
    b = alerter.fingerprint("container", "lab", "plex", "plex is down")
    c = alerter.fingerprint("container", "lab", "nginx", "nginx is down")
    assert a == b
    assert a != c
    assert len(a) == 20


def test_min_severity_gate():
    alerter = Alerter(Settings(alert_min_severity="warning"))
    assert alerter._allowed("info") is False
    assert alerter._allowed("warning") is True
    assert alerter._allowed("critical") is True
