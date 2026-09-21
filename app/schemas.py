"""Pydantic contracts shared by the REST API, WebSocket, and alerter.

These shapes are the SaaS public API draft. Changing a field is a
breaking change — add, do not rename, and bump `/api/v1` when needed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


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

    host: str = Field(default="", max_length=128)
    service: str = Field(default="", max_length=128)
    severity: str = Field(default="", max_length=32)  # info | warning | critical | ""
    status: str = Field(default="", max_length=32)  # ok | warning | error | ""
    time_range: str = Field(default="1h", max_length=16)  # 15m | 1h | 6h | 24h | 7d


class Snapshot(BaseModel):
    """One collector tick. Broadcast on `/ws` every refresh_seconds."""

    type: Literal["snapshot"] = "snapshot"
    ts: float
    instance: str
    prometheus_ok: bool = False
    docker_ok: bool = False
    mqtt_ok: bool = False
    hosts: list[HostMetrics] = Field(default_factory=list)
    containers: list[ContainerMetrics] = Field(default_factory=list)
    zfs: list[ZfsPool] = Field(default_factory=list)
    alerts: list[AlertOut] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    glances: dict[str, Any] = Field(default_factory=dict)


class WsClientMessage(BaseModel):
    type: Literal["filter", "ping"] = "filter"
    host: str = Field(default="", max_length=128)
    service: str = Field(default="", max_length=128)
    severity: str = Field(default="", max_length=32)
    status: str = Field(default="", max_length=32)
    time_range: str = Field(default="1h", max_length=16)


class RestartRequest(BaseModel):
    reason: str = "manual"


class ContainerActionRequest(BaseModel):
    reason: str = "manual"


class ContainerExecRequest(BaseModel):
    command: str = Field(min_length=1, max_length=500)


class ContainerFileReadRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1000)


class ContainerFileWriteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    content: str = Field(max_length=1_048_576)  # 1 MB max payload


class SettingsUpdate(BaseModel):
    instance_name: str | None = Field(default=None, max_length=64)
    refresh_seconds: int | None = Field(default=None, ge=1, le=300)
    threshold_cpu_warn: float | None = Field(default=None, ge=0.0, le=100.0)
    threshold_cpu_crit: float | None = Field(default=None, ge=0.0, le=100.0)
    threshold_ram_warn: float | None = Field(default=None, ge=0.0, le=100.0)
    threshold_ram_crit: float | None = Field(default=None, ge=0.0, le=100.0)
    threshold_disk_warn: float | None = Field(default=None, ge=0.0, le=100.0)
    threshold_disk_crit: float | None = Field(default=None, ge=0.0, le=100.0)
    auto_restart_enabled: bool | None = None
    auto_restart_delay_seconds: int | None = Field(default=None, ge=0, le=3600)
    auto_restart_cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)
    auto_restart_max_per_hour: int | None = Field(default=None, ge=1, le=100)
    auto_restart_denylist: str | None = Field(default=None, max_length=1000)
    auto_restart_allowlist: str | None = Field(default=None, max_length=1000)
    telegram_bot_token: str | None = Field(default=None, max_length=256)
    telegram_chat_id: str | None = Field(default=None, max_length=128)
    whatsapp_phone: str | None = Field(default=None, max_length=64)
    whatsapp_apikey: str | None = Field(default=None, max_length=256)
    whatsapp_webhook_url: str | None = Field(default=None, max_length=512)
    n8n_webhook_url: str | None = Field(default=None, max_length=512)
    n8n_chat_webhook_url: str | None = Field(default=None, max_length=512)
    n8n_chat_auth_header: str | None = Field(default=None, max_length=512)
    generic_webhook_url: str | None = Field(default=None, max_length=512)
    alert_cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)
    alert_min_severity: Literal["info", "warning", "critical"] | None = None
    mqtt_host: str | None = Field(default=None, max_length=256)
    mqtt_port: int | None = Field(default=None, ge=1, le=65535)
    mqtt_username: str | None = Field(default=None, max_length=128)
    mqtt_password: str | None = Field(default=None, max_length=256)
    mqtt_base_topic: str | None = Field(default=None, max_length=256)
    mqtt_tls: bool | None = None
    db_retention_days: int | None = Field(default=None, ge=1, le=3650)
    grafana_public_url: str | None = Field(default=None, max_length=512)
    grafana_dashboard_uid: str | None = Field(default=None, max_length=128)

    @field_validator(
        "whatsapp_webhook_url",
        "n8n_webhook_url",
        "n8n_chat_webhook_url",
        "generic_webhook_url",
        "grafana_public_url",
        mode="before",
    )
    @classmethod
    def validate_url(cls, v: Any) -> str | None:
        if v is None:
            return None
        text = str(v).strip()
        if not text:
            return ""
        parsed = urlsplit(text)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"URL scheme must be http or https, got {parsed.scheme!r}")
        if not parsed.netloc:
            raise ValueError("URL must have a valid host")
        return text



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
    channel: Literal["telegram", "whatsapp", "n8n", "generic", "all"] = "all"
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
    mqtt: bool
    uptime_seconds: float
