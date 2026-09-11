"""Hub filter logic — the same rules the WebSocket applies per client."""

from __future__ import annotations

from app.schemas import AlertOut, ContainerMetrics, Filters, HostMetrics, Snapshot
from app.services.hub import Hub
from app.services.status import container_severity, level_from_percent, zfs_status


def _snap() -> Snapshot:
    return Snapshot(
        ts=1.0,
        instance="lab",
        hosts=[
            HostMetrics(name="proxmox", instance="pve:9100", cpu_percent=10, status="ok"),
            HostMetrics(name="casaos", instance="casa:9100", cpu_percent=92, status="warning"),
        ],
        containers=[
            ContainerMetrics(id="a", name="nginx", image="nginx:latest", status="running", severity="ok", host="casaos"),
            ContainerMetrics(id="b", name="plex", image="plex", status="exited", severity="error", host="casaos"),
        ],
        alerts=[
            AlertOut(fingerprint="1", severity="warning", source="cpu", host="casaos", service="cpu", title="hot"),
            AlertOut(fingerprint="2", severity="critical", source="container", host="casaos", service="plex", title="down"),
        ],
    )


def test_filter_by_status():
    hub = Hub()
    out = hub.apply_filters(_snap(), Filters(status="error"))
    assert len(out["containers"]) == 1
    assert out["containers"][0]["name"] == "plex"
    assert len(out["hosts"]) == 0


def test_filter_by_service():
    hub = Hub()
    out = hub.apply_filters(_snap(), Filters(service="plex"))
    assert [c["name"] for c in out["containers"]] == ["plex"]
    assert [a["service"] for a in out["alerts"]] == ["plex"]


def test_filter_by_severity():
    hub = Hub()
    out = hub.apply_filters(_snap(), Filters(severity="critical"))
    assert len(out["alerts"]) == 1
    assert out["alerts"][0]["severity"] == "critical"


def test_level_from_percent():
    assert level_from_percent(10, 85, 95) == "ok"
    assert level_from_percent(90, 85, 95) == "warning"
    assert level_from_percent(99, 85, 95) == "error"
    assert level_from_percent(None, 85, 95) == "unknown"


def test_container_and_zfs_status():
    assert container_severity("running", "healthy") == "ok"
    assert container_severity("exited", "") == "error"
    assert container_severity("restarting", "") == "warning"
    assert zfs_status("ONLINE") == "ok"
    assert zfs_status("DEGRADED") == "warning"
    assert zfs_status("FAULTED") == "error"
