"""Runtime setting overrides persisted in SQLite.

The Settings page writes here. Readers should call `merged()` rather
than `get_settings()` when they need the operator's latest values
(thresholds, tokens, HA URL). Process-level Settings stay the
fallback and the source of defaults.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.config import Settings, get_settings
from app.database import async_session
from app.models import SettingOverride

# Keys the UI is allowed to write. Anything else is ignored (no mass-assign).
WRITABLE: dict[str, type] = {
    "instance_name": str,
    "refresh_seconds": int,
    "threshold_cpu_warn": float,
    "threshold_cpu_crit": float,
    "threshold_ram_warn": float,
    "threshold_ram_crit": float,
    "threshold_disk_warn": float,
    "threshold_disk_crit": float,
    "auto_restart_enabled": bool,
    "auto_restart_delay_seconds": int,
    "auto_restart_cooldown_seconds": int,
    "auto_restart_max_per_hour": int,
    "auto_restart_denylist": str,
    "auto_restart_allowlist": str,
    "telegram_bot_token": str,
    "telegram_chat_id": str,
    "whatsapp_phone": str,
    "whatsapp_apikey": str,
    "whatsapp_webhook_url": str,
    "n8n_webhook_url": str,
    "n8n_chat_webhook_url": str,
    "n8n_chat_auth_header": str,
    "generic_webhook_url": str,
    "alert_cooldown_seconds": int,
    "alert_min_severity": str,
    "ha_url": str,
    "ha_token": str,
    "ha_pinned_entities": str,
    "ha_notify_service": str,
    "mqtt_host": str,
    "mqtt_port": int,
    "mqtt_username": str,
    "mqtt_password": str,
    "mqtt_base_topic": str,
    "grafana_public_url": str,
    "grafana_dashboard_uid": str,
}


def _coerce(kind: type, raw: str) -> Any:
    if kind is bool:
        return str(raw).lower() in {"1", "true", "yes", "on"}
    if kind is int:
        return int(raw)
    if kind is float:
        return float(raw)
    return raw


async def load_overrides() -> dict[str, Any]:
    async with async_session() as session:
        rows = await session.execute(select(SettingOverride))
        out: dict[str, Any] = {}
        for row in rows.scalars():
            kind = WRITABLE.get(row.key)
            if kind is None:
                continue
            try:
                out[row.key] = _coerce(kind, row.value)
            except Exception:
                continue
        return out


async def save_overrides(values: dict[str, Any]) -> None:
    async with async_session() as session:
        for key, value in values.items():
            if key not in WRITABLE:
                continue
            if value is None:
                continue
            existing = await session.get(SettingOverride, key)
            as_text = "true" if value is True else "false" if value is False else str(value)
            if existing:
                existing.value = as_text
                existing.updated_at = datetime.now(timezone.utc)
            else:
                session.add(SettingOverride(key=key, value=as_text))
        await session.commit()


async def merged() -> Settings:
    """Env defaults + SQLite overrides. Used by the collector each tick."""
    base = get_settings()
    overrides = await load_overrides()
    if not overrides:
        return base
    # model_copy keeps env-loaded values and applies UI overrides on top.
    # Re-constructing Settings(**data) would let env win again.
    return base.model_copy(update=overrides)
