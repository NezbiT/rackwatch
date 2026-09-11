"""Shared status helpers. Pure functions — safe to unit test."""

from __future__ import annotations

from app.schemas import Status


def level_from_percent(
    value: float | None,
    warn: float,
    crit: float,
) -> Status:
    if value is None:
        return "unknown"
    if value >= crit:
        return "error"
    if value >= warn:
        return "warning"
    return "ok"


def container_severity(status: str, health: str) -> Status:
    status_l = (status or "").lower()
    health_l = (health or "").lower()
    if status_l in {"exited", "dead", "removing"} or health_l == "unhealthy":
        return "error"
    if status_l in {"restarting", "created", "paused"} or health_l == "starting":
        return "warning"
    if status_l == "running":
        return "ok"
    return "unknown"


def zfs_status(health: str) -> Status:
    h = (health or "").upper()
    if h == "ONLINE":
        return "ok"
    if h in {"DEGRADED", "OFFLINE"}:
        return "warning"
    if h in {"FAULTED", "UNAVAIL", "REMOVED"}:
        return "error"
    return "unknown"
