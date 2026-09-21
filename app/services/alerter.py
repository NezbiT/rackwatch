"""Outbound alerts: Telegram, WhatsApp, n8n, generic webhook, MQTT.

Payload shape (also documented in docs/ALERTS.md) is stable and is
the contract n8n / future SaaS subscribers should parse:

{
  "source": "rackwatch",
  "instance": "homelab",
  "severity": "critical",
  "title": "...",
  "message": "...",
  "host": "...",
  "service": "...",
  "fingerprint": "...",
  "url": "http://rackwatch/alerts",
  "ts": 1710000000
}

Dedup: the same fingerprint is silent for ALERT_COOLDOWN_SECONDS.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select

from app.config import Settings
from app.database import async_session
from app.models import Alert, WebhookDelivery
from app.schemas import AlertOut, ContainerMetrics, HostMetrics, Snapshot, ZfsPool

log = logging.getLogger("rackwatch.alerter")

SEVERITY_RANK = {"info": 1, "warning": 2, "critical": 3}


class Alerter:
    def __init__(self, settings: Settings, mqtt: Any = None) -> None:
        self.settings = settings
        self.mqtt = mqtt
        self._last_sent: dict[str, float] = {}
        self._client = httpx.AsyncClient(timeout=8.0)

    def bind(self, settings: Settings, mqtt: Any = None) -> None:
        self.settings = settings
        if mqtt is not None:
            self.mqtt = mqtt

    async def close(self) -> None:
        await self._client.aclose()

    def fingerprint(self, source: str, host: str, service: str, title: str) -> str:
        raw = f"{source}|{host}|{service}|{title}"
        return hashlib.sha256(raw.encode()).hexdigest()[:20]

    def _allowed(self, severity: str) -> bool:
        return SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK.get(
            self.settings.alert_min_severity, 2
        )

    async def _cooled(self, fingerprint: str) -> bool:
        last = self._last_sent.get(fingerprint)
        if last is None:
            # Query recent DB record to preserve cooldown across app restarts
            try:
                async with async_session() as session:
                    row = await session.execute(
                        select(Alert.created_at)
                        .where(Alert.fingerprint == fingerprint)
                        .order_by(Alert.created_at.desc())
                        .limit(1)
                    )
                    recent_dt = row.scalar_one_or_none()
                    if recent_dt is not None:
                        if recent_dt.tzinfo is None:
                            recent_dt = recent_dt.replace(tzinfo=timezone.utc)
                        last = recent_dt.timestamp()
                        self._last_sent[fingerprint] = last
            except Exception:
                pass

        if last is None:
            return False
        return (time.time() - last) < self.settings.alert_cooldown_seconds

    async def evaluate(self, snapshot: Snapshot) -> list[Alert]:
        candidates: list[dict[str, str]] = []
        for host in snapshot.hosts:
            candidates.extend(self._from_host(host, snapshot.containers))
        for container in snapshot.containers:
            if container.severity == "error":
                candidates.append(
                    {
                        "severity": "critical",
                        "source": "container",
                        "host": container.host,
                        "service": container.name,
                        "title": f"{container.name} is down",
                        "message": f"status={container.status} health={container.health or 'n/a'}",
                    }
                )
            elif container.severity == "warning":
                candidates.append(
                    {
                        "severity": "warning",
                        "source": "container",
                        "host": container.host,
                        "service": container.name,
                        "title": f"{container.name} is {container.status or 'degraded'}",
                        "message": f"health={container.health or 'n/a'}",
                    }
                )
            elif (
                container.cpu_percent is not None
                and container.cpu_percent >= self.settings.threshold_cpu_crit
            ):
                candidates.append(
                    {
                        "severity": "critical",
                        "source": "container_cpu",
                        "host": container.host,
                        "service": container.name,
                        "title": f"High CPU: {container.name} at {container.cpu_percent:.0f}%",
                        "message": f"Container {container.name} CPU is critical: {container.cpu_percent:.1f}% >= {self.settings.threshold_cpu_crit:g}%",
                    }
                )
            elif (
                container.memory_percent is not None
                and container.memory_percent >= self.settings.threshold_ram_crit
            ):
                candidates.append(
                    {
                        "severity": "critical",
                        "source": "container_ram",
                        "host": container.host,
                        "service": container.name,
                        "title": f"High RAM: {container.name} at {container.memory_percent:.0f}%",
                        "message": f"Container {container.name} RAM is critical: {container.memory_percent:.1f}% >= {self.settings.threshold_ram_crit:g}%",
                    }
                )
        for pool in snapshot.zfs:
            if pool.status in {"warning", "error"}:
                candidates.append(
                    {
                        "severity": "critical" if pool.status == "error" else "warning",
                        "source": "zfs",
                        "host": snapshot.instance,
                        "service": pool.name,
                        "title": f"ZFS pool {pool.name} is {pool.health}",
                        "message": f"capacity={pool.capacity_percent}%",
                    }
                )
        if not snapshot.prometheus_ok:
            candidates.append(
                {
                    "severity": "warning",
                    "source": "prometheus",
                    "host": snapshot.instance,
                    "service": "prometheus",
                    "title": "Prometheus is unreachable",
                    "message": "RackWatch is falling back to local Docker / psutil metrics.",
                }
            )

        created: list[Alert] = []
        for item in candidates:
            if not self._allowed(item["severity"]):
                continue
            fp = self.fingerprint(item["source"], item["host"], item["service"], item["title"])
            if await self._cooled(fp):
                continue
            alert = await self.fire(
                title=item["title"],
                message=item["message"],
                severity=item["severity"],  # type: ignore[arg-type]
                source=item["source"],
                host=item["host"],
                service=item["service"],
                fingerprint=fp,
            )
            created.append(alert)
        return created

    def _from_host(
        self, host: HostMetrics, containers: list[ContainerMetrics] | None = None
    ) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        checks = (
            ("cpu", host.cpu_percent, self.settings.threshold_cpu_warn, self.settings.threshold_cpu_crit),
            ("ram", host.ram_percent, self.settings.threshold_ram_warn, self.settings.threshold_ram_crit),
            ("disk", host.disk_percent, self.settings.threshold_disk_warn, self.settings.threshold_disk_crit),
        )
        for source, value, warn, crit in checks:
            if value is None:
                continue
            if value >= crit:
                sev = "critical"
            elif value >= warn:
                sev = "warning"
            else:
                continue

            msg = f"threshold warn={warn:g} crit={crit:g}"
            if containers and source == "cpu":
                top_cpu = sorted(
                    [c for c in containers if c.cpu_percent is not None and c.cpu_percent > 0],
                    key=lambda c: c.cpu_percent or 0,
                    reverse=True,
                )[:3]
                if top_cpu:
                    msg += " · Top CPU: " + ", ".join(f"{c.name} ({c.cpu_percent:.1f}%)" for c in top_cpu)
            elif containers and source == "ram":
                top_ram = sorted(
                    [
                        c
                        for c in containers
                        if (c.memory_percent is not None and c.memory_percent > 0)
                        or (c.memory_bytes and c.memory_bytes > 0)
                    ],
                    key=lambda c: c.memory_bytes or (c.memory_percent or 0),
                    reverse=True,
                )[:3]
                if top_ram:
                    def _fmt_mem(c: ContainerMetrics) -> str:
                        if c.memory_bytes and c.memory_bytes > 1024 * 1024:
                            mb = c.memory_bytes / (1024 * 1024)
                            return f"{c.name} ({mb:.0f} MB)" if mb < 1024 else f"{c.name} ({mb/1024:.1f} GB)"
                        if c.memory_percent:
                            return f"{c.name} ({c.memory_percent:.0f}%)"
                        return c.name
                    msg += " · Top RAM: " + ", ".join(_fmt_mem(c) for c in top_ram)

            out.append(
                {
                    "severity": sev,
                    "source": source,
                    "host": host.name,
                    "service": source,
                    "title": f"{host.name} {source.upper()} at {value:.0f}%",
                    "message": msg,
                }
            )
        return out

    async def fire(
        self,
        *,
        title: str,
        message: str,
        severity: str,
        source: str,
        host: str = "",
        service: str = "",
        fingerprint: str = "",
        channels: list[str] | None = None,
    ) -> Alert:
        fp = fingerprint or self.fingerprint(source, host, service, title)
        payload = {
            "source": "rackwatch",
            "instance": self.settings.instance_name,
            "severity": severity,
            "title": title,
            "message": message,
            "host": host,
            "service": service,
            "fingerprint": fp,
            "url": f"{self.settings.public_url.rstrip('/')}/alerts",
            "ts": int(time.time()),
        }
        wanted = channels or ["telegram", "whatsapp", "n8n", "generic", "mqtt"]

        async def _dispatch_task(channel: str) -> tuple[str, bool]:
            ok = await self._dispatch(channel, payload, title, message, severity)
            return channel, ok

        results = await asyncio.gather(*[_dispatch_task(ch) for ch in wanted], return_exceptions=True)
        delivered: list[str] = [
            res[0] for res in results if isinstance(res, tuple) and res[1]
        ]

        self._last_sent[fp] = time.time()
        alert = Alert(
            created_at=datetime.now(timezone.utc),
            fingerprint=fp,
            severity=severity,
            status="firing",
            source=source,
            host=host,
            service=service,
            title=title,
            message=message,
            delivered_to=",".join(delivered),
        )
        async with async_session() as session:
            session.add(alert)
            await session.commit()
            await session.refresh(alert)
        return alert

    async def _dispatch(
        self,
        channel: str,
        payload: dict[str, Any],
        title: str,
        message: str,
        severity: str,
    ) -> bool:
        try:
            if channel == "telegram":
                return await self._telegram(title, message, severity)
            if channel == "whatsapp":
                return await self._whatsapp(title, message, severity)
            if channel == "n8n":
                return await self._post("n8n", self.settings.n8n_webhook_url, payload)
            if channel == "generic":
                return await self._post("generic", self.settings.generic_webhook_url, payload)
            if channel == "mqtt" and self.mqtt:
                return self.mqtt.publish_alert(payload)
        except Exception as exc:
            log.warning("%s dispatch failed: %s", channel, exc)
            await _log_delivery(channel, False, 0, str(payload), str(exc))
        return False

    async def _telegram(self, title: str, message: str, severity: str) -> bool:
        token = self.settings.telegram_bot_token
        chat = self.settings.telegram_chat_id
        if not token or not chat:
            return False
        emoji = "🔴" if severity == "critical" else "⚠️" if severity == "warning" else "ℹ️"
        text = f"{emoji} <b>RackWatch [{severity.upper()}]</b>\n<b>{title}</b>\n{message}"
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        res = await self._client.post(
            url,
            json={"chat_id": chat, "text": text, "parse_mode": "HTML"},
        )
        await _log_delivery("telegram", res.is_success, res.status_code, text, res.text[:500])
        return res.is_success

    async def _whatsapp(self, title: str, message: str, severity: str) -> bool:
        text = f"RackWatch [{severity.upper()}] {title} — {message}"
        if self.settings.whatsapp_webhook_url:
            return await self._post(
                "whatsapp",
                self.settings.whatsapp_webhook_url,
                {"text": text, "title": title, "severity": severity},
            )
        phone = self.settings.whatsapp_phone
        key = self.settings.whatsapp_apikey
        if not phone or not key:
            return False
        # CallMeBot free homelab path. See docs/ALERTS.md.
        url = (
            "https://api.callmebot.com/whatsapp.php"
            f"?phone={quote(phone)}&text={quote(text)}&apikey={quote(key)}"
        )
        res = await self._client.get(url)
        await _log_delivery("whatsapp", res.is_success, res.status_code, text, res.text[:500])
        return res.is_success

    async def _post(self, channel: str, url: str, payload: dict[str, Any]) -> bool:
        if not url:
            return False
        res = await self._client.post(url, json=payload)
        await _log_delivery(channel, res.is_success, res.status_code, str(payload), res.text[:500])
        return res.is_success


async def _log_delivery(channel: str, ok: bool, status_code: int, payload: str, response: str) -> None:
    try:
        async with async_session() as session:
            session.add(
                WebhookDelivery(
                    channel=channel,
                    ok=ok,
                    status_code=status_code,
                    payload=payload[:4000],
                    response=response[:4000],
                )
            )
            await session.commit()
    except Exception:
        log.debug("could not persist webhook delivery")


async def recent_alerts(limit: int = 80, time_range: str = "24h") -> list[AlertOut]:
    seconds = {"15m": 900, "1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800}.get(time_range, 86400)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    async with async_session() as session:
        rows = await session.execute(
            select(Alert)
            .where(Alert.created_at >= cutoff)
            .order_by(Alert.created_at.desc())
            .limit(limit)
        )
        out: list[AlertOut] = []
        for row in rows.scalars():
            out.append(
                AlertOut(
                    id=row.id,
                    created_at=row.created_at,
                    fingerprint=row.fingerprint,
                    severity=row.severity,  # type: ignore[arg-type]
                    status=row.status,
                    source=row.source,
                    host=row.host,
                    service=row.service,
                    title=row.title,
                    message=row.message,
                    delivered_to=row.delivered_to,
                    acked=row.acked,
                )
            )
        return out


# Referenced so type checkers keep HostMetrics / ContainerMetrics / ZfsPool imported
# if evaluate is refactored. They are used.
_ = (HostMetrics, ContainerMetrics, ZfsPool)
