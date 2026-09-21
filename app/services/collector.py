"""Collector loop — the heart of the live dashboard.

Every `refresh_seconds` (default 3):
1. Reload setting overrides from SQLite.
2. Pull Prometheus hosts + cAdvisor usage.
3. List Docker containers (merge usage).
4. Read ZFS + Home Assistant.
5. Fall back to psutil if Prometheus is empty.
6. Auto-restart failed services.
7. Evaluate and fan-out alerts.
8. Mirror summary into HA (REST) and MQTT.
9. Broadcast the snapshot on the WebSocket hub.

The loop is cancelled from FastAPI lifespan on shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.database import cleanup_old_records
from app.schemas import Snapshot
from app.services import settings_store
from app.services.alerter import Alerter, recent_alerts
from app.services.docker_ctl import DockerControl
from app.services.homeassistant import HomeAssistant
from app.services.hub import Hub
from app.services.local_metrics import read_local_host
from app.services.mqtt_bridge import MqttBridge
from app.services.prometheus import PrometheusClient
from app.services.restarter import Restarter
from app.services.zfs import ZfsCollector

log = logging.getLogger("rackwatch.collector")


class Collector:
    def __init__(
        self,
        *,
        hub: Hub,
        prom: PrometheusClient,
        docker: DockerControl,
        zfs: ZfsCollector,
        restarter: Restarter,
        alerter: Alerter,
        ha: HomeAssistant,
        mqtt: MqttBridge,
        glances=None,
    ) -> None:
        self.hub = hub
        self.prom = prom
        self.docker = docker
        self.zfs = zfs
        self.restarter = restarter
        self.alerter = alerter
        self.ha = ha
        self.mqtt = mqtt
        self.glances = glances
        self.started_at = time.time()
        self._task: asyncio.Task[None] | None = None
        self._last_cleanup = 0.0

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="rackwatch-collector")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        # Prime psutil cpu_percent so the first sample is not 0.0.
        try:
            import psutil

            psutil.cpu_percent(interval=None)
        except Exception:
            pass

        while True:
            try:
                snapshot = await self.tick()
                await self.hub.publish(snapshot)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("collector tick failed")

            # Periodic SQLite retention cleanup (once per hour)
            now = time.time()
            if now - self._last_cleanup > 3600:
                self._last_cleanup = now
                try:
                    settings = await settings_store.merged()
                    retention_days = getattr(settings, "db_retention_days", 30)
                    cleaned = await cleanup_old_records(retention_days)
                    log.info("SQLite retention cleanup completed: %s", cleaned)
                except Exception as exc:
                    log.debug("SQLite retention cleanup error: %s", exc)

            settings = await settings_store.merged()
            await asyncio.sleep(max(1, settings.refresh_seconds))

    async def tick(self) -> Snapshot:
        settings = await settings_store.merged()
        self.prom.settings = settings
        self.docker.settings = settings
        self.restarter.settings = settings
        self.alerter.bind(settings, self.ha, self.mqtt)
        self.ha.bind(settings)
        self.mqtt.bind(settings)

        prom_ok, docker_ok, ha_ok = await asyncio.gather(
            self.prom.ready(),
            self.docker.ready(),
            self.ha.ready(),
        )

        async def _fetch_hosts():
            return await self.prom.hosts() if prom_ok else []

        async def _fetch_usage():
            return await self.prom.container_usage() if prom_ok else {}

        async def _fetch_zfs():
            return await self.zfs.pools()

        async def _fetch_ha():
            return await self.ha.entities() if ha_ok else []

        async def _fetch_glances():
            return await self.glances.summary() if self.glances else {}

        # Fetch telemetry metrics concurrently
        hosts, usage, zfs, ha_entities, glances_data = await asyncio.gather(
            _fetch_hosts(),
            _fetch_usage(),
            _fetch_zfs(),
            _fetch_ha(),
            _fetch_glances(),
        )

        containers = await self.docker.list_containers(usage)

        if not hosts:
            hosts = [read_local_host(settings)]

        summary = _summarize(hosts, containers, zfs)
        snapshot = Snapshot(
            ts=time.time(),
            instance=settings.instance_name,
            prometheus_ok=prom_ok,
            docker_ok=docker_ok,
            ha_ok=ha_ok,
            mqtt_ok=self.mqtt.ok,
            hosts=hosts,
            containers=containers,
            zfs=zfs,
            ha_entities=ha_entities,
            alerts=[],
            summary=summary,
            glances=glances_data,
        )

        await self.restarter.evaluate(containers)
        await self.alerter.evaluate(snapshot)
        snapshot.alerts = await recent_alerts(limit=40, time_range="6h")

        # Best-effort mirrors — never fail the tick.
        async def _mirror_ha():
            try:
                await self.ha.publish_snapshot(snapshot)
            except Exception:
                log.debug("HA publish failed", exc_info=True)

        async def _mirror_mqtt():
            try:
                self.mqtt.publish_snapshot(snapshot)
            except Exception:
                log.debug("MQTT publish failed", exc_info=True)

        await asyncio.gather(_mirror_ha(), _mirror_mqtt())

        return snapshot


def _summarize(hosts: Any, containers: Any, zfs: Any) -> dict[str, Any]:
    cpus = [h.cpu_percent for h in hosts if h.cpu_percent is not None]
    rams = [h.ram_percent for h in hosts if h.ram_percent is not None]
    disks = [h.disk_percent for h in hosts if h.disk_percent is not None]
    down = sum(1 for c in containers if c.severity == "error")
    warn = sum(1 for c in containers if c.severity == "warning")
    zfs_bad = sum(1 for z in zfs if z.status in {"warning", "error"})
    host_bad = any(h.status == "error" for h in hosts)
    overall = "ok"
    if down or zfs_bad or host_bad:
        overall = "error"
    elif warn or any(h.status == "warning" for h in hosts):
        overall = "warning"
    return {
        "cpu": round(sum(cpus) / len(cpus), 1) if cpus else None,
        "ram": round(sum(rams) / len(rams), 1) if rams else None,
        "disk": round(sum(disks) / len(disks), 1) if disks else None,
        "containers_total": len(containers),
        "containers_down": down,
        "containers_warn": warn,
        "zfs_pools": len(zfs),
        "zfs_bad": zfs_bad,
        "overall": overall,
        "hosts": len(hosts),
    }
