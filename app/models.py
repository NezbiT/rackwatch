"""ORM tables.

Keep this module free of HTTP and collector logic so a future SaaS
control plane can import the same schema (or migrate it) without
pulling FastAPI.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Alert(Base):
    """Firing (or recently fired) alert. Deduped by `fingerprint`."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(16), default="firing")  # firing | resolved
    source: Mapped[str] = mapped_column(String(64))  # cpu | ram | disk | container | zfs | ha
    host: Mapped[str] = mapped_column(String(128), default="")
    service: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(256))
    message: Mapped[str] = mapped_column(Text, default="")
    delivered_to: Mapped[str] = mapped_column(String(256), default="")
    acked: Mapped[bool] = mapped_column(Boolean, default=False)


class RestartEvent(Base):
    """Audit log of every auto or manual container restart."""

    __tablename__ = "restarts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    container: Mapped[str] = mapped_column(String(128), index=True)
    container_id: Mapped[str] = mapped_column(String(64), default="")
    reason: Mapped[str] = mapped_column(String(256), default="")
    automatic: Mapped[bool] = mapped_column(Boolean, default=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(Text, default="")


class SettingOverride(Base):
    """Key/value overrides written by the Settings UI. Wins over env."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class WebhookDelivery(Base):
    """Outbound webhook attempt (Telegram / WhatsApp / n8n / HA / generic)."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    channel: Mapped[str] = mapped_column(String(32), index=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    status_code: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[str] = mapped_column(Text, default="")
    response: Mapped[str] = mapped_column(Text, default="")
