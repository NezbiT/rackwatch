"""Central configuration.

Every env var from `.env.example` lands here via Pydantic Settings.
The Settings UI writes *overrides* into SQLite (`settings` table);
`app.services.settings_store` merges those on top of this file at
runtime so a restart is not required after saving the form.

SaaS note: this module is the single-tenant config surface. A future
cloud control plane would replace it with a per-tenant row and an
agent token instead of a shared `.env`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


Severity = Literal["info", "warning", "critical"]


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


class Settings(BaseSettings):
    """Process-wide settings. Load once via `get_settings()`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # App
    host: str = Field(default="0.0.0.0", validation_alias="RACKWATCH_HOST")
    port: int = Field(default=8080, validation_alias="RACKWATCH_PORT")
    env: str = Field(default="production", validation_alias="RACKWATCH_ENV")
    secret_key: str = Field(
        default="insecure-dev-key-change-me",
        validation_alias="RACKWATCH_SECRET_KEY",
    )
    auth_user: str = Field(default="", validation_alias="RACKWATCH_AUTH_USER")
    auth_password: str = Field(default="", validation_alias="RACKWATCH_AUTH_PASSWORD")
    api_token: str = Field(default="", validation_alias="RACKWATCH_API_TOKEN")
    public_url: str = Field(
        default="http://localhost:8080",
        validation_alias="RACKWATCH_PUBLIC_URL",
    )
    instance_name: str = Field(
        default="homelab",
        validation_alias="RACKWATCH_INSTANCE_NAME",
    )
    refresh_seconds: int = Field(default=3, validation_alias="RACKWATCH_REFRESH_SECONDS")

    # Metrics backends
    prometheus_url: str = Field(default="http://prometheus:9090", validation_alias="PROMETHEUS_URL")
    grafana_url: str = Field(default="http://grafana:3000", validation_alias="GRAFANA_URL")
    grafana_public_url: str = Field(
        default="http://localhost:3001",
        validation_alias="GRAFANA_PUBLIC_URL",
    )
    grafana_dashboard_uid: str = Field(
        default="rackwatch-overview",
        validation_alias="GRAFANA_DASHBOARD_UID",
    )
    glances_url: str = Field(default="", validation_alias="GLANCES_URL")

    # Thresholds
    threshold_cpu_warn: float = Field(default=85, validation_alias="THRESHOLD_CPU_WARN")
    threshold_cpu_crit: float = Field(default=95, validation_alias="THRESHOLD_CPU_CRIT")
    threshold_ram_warn: float = Field(default=85, validation_alias="THRESHOLD_RAM_WARN")
    threshold_ram_crit: float = Field(default=95, validation_alias="THRESHOLD_RAM_CRIT")
    threshold_disk_warn: float = Field(default=80, validation_alias="THRESHOLD_DISK_WARN")
    threshold_disk_crit: float = Field(default=90, validation_alias="THRESHOLD_DISK_CRIT")

    # Auto-restart
    auto_restart_enabled: bool = Field(default=True, validation_alias="AUTO_RESTART_ENABLED")
    auto_restart_delay_seconds: int = Field(
        default=8, validation_alias="AUTO_RESTART_DELAY_SECONDS"
    )
    auto_restart_cooldown_seconds: int = Field(
        default=120, validation_alias="AUTO_RESTART_COOLDOWN_SECONDS"
    )
    auto_restart_max_per_hour: int = Field(
        default=3, validation_alias="AUTO_RESTART_MAX_PER_HOUR"
    )
    auto_restart_denylist: str = Field(
        default="rackwatch,prometheus,grafana,casaos,cadvisor,node-exporter",
        validation_alias="AUTO_RESTART_DENYLIST",
    )
    auto_restart_allowlist: str = Field(default="", validation_alias="AUTO_RESTART_ALLOWLIST")

    # Operator console. Commands are passed as argv (never through a shell)
    # and the executable must match this allow-list.
    container_exec_allowlist: str = Field(
        default="cat,df,du,env,free,grep,head,hostname,id,ip,ls,n8n,node,printenv,ps,pwd,ss,stat,tail,uname,uptime,whoami",
        validation_alias="CONTAINER_EXEC_ALLOWLIST",
    )

    docker_host: str = Field(default="unix:///var/run/docker.sock", validation_alias="DOCKER_HOST")

    # Alerts
    telegram_bot_token: str = Field(default="", validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", validation_alias="TELEGRAM_CHAT_ID")
    whatsapp_phone: str = Field(default="", validation_alias="WHATSAPP_PHONE")
    whatsapp_apikey: str = Field(default="", validation_alias="WHATSAPP_APIKEY")
    whatsapp_webhook_url: str = Field(default="", validation_alias="WHATSAPP_WEBHOOK_URL")
    n8n_webhook_url: str = Field(default="", validation_alias="N8N_WEBHOOK_URL")
    n8n_chat_webhook_url: str = Field(default="", validation_alias="N8N_CHAT_WEBHOOK_URL")
    n8n_chat_auth_header: str = Field(default="", validation_alias="N8N_CHAT_AUTH_HEADER")
    generic_webhook_url: str = Field(default="", validation_alias="GENERIC_WEBHOOK_URL")
    # Structured triage (TypeSafe Jev). Not a chat model: it returns a cause
    # and a safe action; RackWatch writes the message.
    typesafe_api_key: str = Field(default="", validation_alias="TYPESAFE_API_KEY")
    typesafe_model: str = Field(default="jev-latest", validation_alias="TYPESAFE_MODEL")
    alert_cooldown_seconds: int = Field(default=900, validation_alias="ALERT_COOLDOWN_SECONDS")
    alert_min_severity: Severity = Field(default="warning", validation_alias="ALERT_MIN_SEVERITY")

    # MQTT
    mqtt_host: str = Field(default="", validation_alias="MQTT_HOST")
    mqtt_port: int = Field(default=1883, validation_alias="MQTT_PORT")
    mqtt_username: str = Field(default="", validation_alias="MQTT_USERNAME")
    mqtt_password: str = Field(default="", validation_alias="MQTT_PASSWORD")
    mqtt_base_topic: str = Field(default="rackwatch", validation_alias="MQTT_BASE_TOPIC")
    mqtt_tls: bool = Field(default=False, validation_alias="MQTT_TLS")

    # SQLite data retention policy (in days)
    db_retention_days: int = Field(default=30, validation_alias="RACKWATCH_RETENTION_DAYS")

    # Relative path works on Windows and Linux. Compose overrides to /data/.
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/rackwatch.db",
        validation_alias="DATABASE_URL",
    )

    @field_validator("refresh_seconds")
    @classmethod
    def _refresh_floor(cls, value: int) -> int:
        # Sub-second loops melt Prometheus. 3s is the product default.
        return max(1, value)

    @field_validator("db_retention_days")
    @classmethod
    def _retention_bounds(cls, value: int) -> int:
        return max(1, min(int(value), 3650))

    @property
    def auth_enabled(self) -> bool:
        return bool(self.auth_user and self.auth_password)

    @property
    def denylist(self) -> list[str]:
        return [n.lower() for n in _csv(self.auto_restart_denylist)]

    @property
    def allowlist(self) -> list[str]:
        return [n.lower() for n in _csv(self.auto_restart_allowlist)]

    @property
    def exec_allowlist(self) -> list[str]:
        return [n.lower() for n in _csv(self.container_exec_allowlist)]

    @property
    def is_dev(self) -> bool:
        return self.env.lower() in {"dev", "development", "local"}


@lru_cache
def get_settings() -> Settings:
    """Cached process settings. Call `get_settings.cache_clear()` after tests."""
    return Settings()
