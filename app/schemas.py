"""Pydantic contracts shared by the REST API, WebSocket, and alerter.

These shapes are the SaaS public API draft. Changing a field is a
breaking change — add, do not rename, and bump `/api/v1` when needed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


Status = Literal["ok", "warning", "error", "unknown"]
Severity = Literal["info", "warning", "critical"]


class HostMetrics(BaseModel):
    name: str
    instance: str = ""
    cpu_percent: float | None = None
    ram_percent: float | None = None
    ram_used_bytes: int | None = None
    ram_total_bytes: int | None = None
    disk_percent: float | None = None
    disk_used_bytes: int | None = None
    disk_total_bytes: int | None = None
    load1: float | None = None
    uptime_seconds: float | None = None
    status: Status = "unknown"
    source: str = "prometheus"  # prometheus | local


class ContainerMetrics(BaseModel):
    id: str
    name: str
    image: str = ""
    status: str = ""  # running | exited | restarting | paused | created | dead
    health: str = ""  # healthy | unhealthy | starting | none
    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_bytes: int | None = None
    restart_count: int = 0
    started_at: str = ""
    compose_project: str = ""
    severity: Status = "ok"
    host: str = ""


class ZfsPool(BaseModel):
    name: str
    health: str = "UNKNOWN"  # ONLINE | DEGRADED | FAULTED | OFFLINE | UNAVAIL | UNKNOWN
    size_bytes: int | None = None
    allocated_bytes: int | None = None
    free_bytes: int | None = None
    capacity_percent: float | None = None
    status: Status = "unknown"
    source: str = "none"


class HAEntity(BaseModel):
    entity_id: str
    name: str = ""
    state: str = ""
    unit: str = ""
    domain: str = ""
    last_changed: str = ""
    friendly: str = ""
    icon: str = ""
    status: Status = "ok"


class AlertOut(BaseModel):
    id: int | None = None
    created_at: datetime | None = None
    fingerprint: str
    severity: Severity
    status: str = "firing"
    source: str
    host: str = ""
    service: str = ""
    title: str
    message: str = ""
    delivered_to: str = ""
    acked: bool = False


class RestartOut(BaseModel):
    id: int | None = None
    created_at: datetime | None = None
    container: str
    reason: str = ""
    automatic: bool = True
    success: bool = False
    error: str = ""


class Filters(BaseModel):
    """Live dashboard filters. Empty string means 'any'."""

    host: str = ""
    service: str = ""
    severity: str = ""  # info | warning | critical | ""
    status: str = ""  # ok | warning | error | ""
    time_range: str = "1h"  # 15m | 1h | 6h | 24h | 7d


class Snapshot(BaseModel):
    """One collector tick. Broadcast on `/ws` every refresh_seconds."""

    type: Literal["snapshot"] = "snapshot"
    ts: float
    instance: str
    prometheus_ok: bool = False
    docker_ok: bool = False
    ha_ok: bool = False
    mqtt_ok: bool = False
    hosts: list[HostMetrics] = Field(default_factory=list)
    containers: list[ContainerMetrics] = Field(default_factory=list)
    zfs: list[ZfsPool] = Field(default_factory=list)
    ha_entities: list[HAEntity] = Field(default_factory=list)
    alerts: list[AlertOut] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class WsClientMessage(BaseModel):
    type: Literal["filter", "ping"] = "filter"
    host: str = ""
    service: str = ""
    severity: str = ""
    status: str = ""
    time_range: str = "1h"


class RestartRequest(BaseModel):
    reason: str = "manual"


class ContainerActionRequest(BaseModel):
    reason: str = "manual"


class ContainerExecRequest(BaseModel):
    command: str = Field(min_length=1, max_length=500)


class ContainerExecOut(BaseModel):
    ok: bool
    container: str
    command: str
    exit_code: int | None = None
    output: str = ""


class ContainerHookIn(BaseModel):
    container: str = Field(min_length=1)
    action: Literal["start", "stop", "restart"] = "restart"
    reason: str = "webhook"
    force: bool = False


class AlertTestRequest(BaseModel):
    channel: Literal["telegram", "whatsapp", "n8n", "generic", "homeassistant", "all"] = "all"
    message: str = "RackWatch test alert"


class WebhookAlertIn(BaseModel):
    """Inbound payload (n8n / HA / custom) that creates a RackWatch alert."""

    title: str
    message: str = ""
    severity: Severity = "warning"
    source: str = "webhook"
    host: str = ""
    service: str = ""


class HealthOut(BaseModel):
    status: str
    version: str
    instance: str
    prometheus: bool
    docker: bool
    homeassistant: bool
    mqtt: bool
    uptime_seconds: float
