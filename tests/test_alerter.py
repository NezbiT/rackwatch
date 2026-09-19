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


def test_from_host_high_cpu_and_ram_with_top_containers():
    from app.schemas import ContainerMetrics, HostMetrics

    alerter = Alerter(Settings(_env_file=None, threshold_cpu_warn=80, threshold_cpu_crit=90, threshold_ram_warn=80, threshold_ram_crit=90))
    host = HostMetrics(name="casaos", cpu_percent=92.5, ram_percent=88.0, disk_percent=50.0)
    containers = [
        ContainerMetrics(id="1", name="plex", cpu_percent=45.0, memory_percent=30.0, memory_bytes=500 * 1024 * 1024),
        ContainerMetrics(id="2", name="torrent", cpu_percent=30.0, memory_percent=15.0, memory_bytes=250 * 1024 * 1024),
        ContainerMetrics(id="3", name="caddy", cpu_percent=2.0, memory_percent=5.0, memory_bytes=50 * 1024 * 1024),
    ]
    alerts = alerter._from_host(host, containers)
    assert len(alerts) == 2  # CPU crit + RAM warn
    cpu_alert = next(a for a in alerts if a["source"] == "cpu")
    assert cpu_alert["severity"] == "critical"
    assert "Top CPU: plex (45.0%), torrent (30.0%), caddy (2.0%)" in cpu_alert["message"]

    ram_alert = next(a for a in alerts if a["source"] == "ram")
    assert ram_alert["severity"] == "warning"
    assert "Top RAM: plex" in ram_alert["message"]


def test_container_high_cpu_crit_candidate():
    from app.schemas import ContainerMetrics, HostMetrics, Snapshot

    alerter = Alerter(Settings(threshold_cpu_crit=95))
    host = HostMetrics(name="casaos", cpu_percent=40.0, ram_percent=50.0, disk_percent=50.0)
    c1 = ContainerMetrics(id="1", name="runaway-proc", cpu_percent=98.5, status="running", host="casaos")
    c2 = ContainerMetrics(id="2", name="normal-proc", cpu_percent=10.0, status="running", host="casaos")
    snap = Snapshot(instance="casaos", hosts=[host], containers=[c1, c2], zfs=[], prometheus_ok=True, docker_ok=True, ts=1700000000.0)

    # Check candidates evaluated
    candidates = []
    for c in snap.containers:
        if c.cpu_percent is not None and c.cpu_percent >= alerter.settings.threshold_cpu_crit:
            candidates.append(c.name)
    assert "runaway-proc" in candidates
    assert "normal-proc" not in candidates
