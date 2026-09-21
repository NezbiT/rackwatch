"""Collector loop — the heart of the live dashboard.

Every `refresh_seconds` (default 3):
1. Reload setting overrides from SQLite.
2. Pull Prometheus hosts + cAdvisor usage.
3. List Docker containers (merge usage).
4. Read ZFS.
5. Fall back to psutil if Prometheus is empty.
6. Auto-restart failed services.
7. Evaluate and fan-out alerts.
8. Mirror summary into MQTT.
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
        mqtt: MqttBridge,
        glances=None,
    ) -> None:
        self.hub = hub
        self.prom = prom
        self.docker = docker
        self.zfs = zfs
        self.restarter = restarter
        self.alerter = alerter
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
        self.alerter.bind(settings, self.mqtt)
        self.mqtt.bind(settings)

        # Check backend readiness concurrently with exception isolation
        ready_results = await asyncio.gather(
            self.prom.ready(),
            self.docker.ready(),
            return_exceptions=True,
        )
        prom_ok = bool(ready_results[0]) if isinstance(ready_results[0], bool) else False
        docker_ok = bool(ready_results[1]) if isinstance(ready_results[1], bool) else False

        async def _fetch_hosts():
            try:
                return await self.prom.hosts() if prom_ok else []
            except Exception as exc:
                log.debug("Failed fetching Prometheus hosts: %s", exc)
                return []

        async def _fetch_usage():
            try:
                return await self.prom.container_usage() if prom_ok else {}
            except Exception as exc:
                log.debug("Failed fetching container usage: %s", exc)
                return {}

        async def _fetch_zfs():
            try:
                return await self.zfs.pools()
            except Exception as exc:
                log.debug("Failed fetching ZFS pools: %s", exc)
                return []

        async def _fetch_glances():
            try:
                return await self.glances.summary() if self.glances else {}
            except Exception as exc:
                log.debug("Failed fetching Glances summary: %s", exc)
                return {}

        # Fetch telemetry metrics concurrently with return_exceptions=True
        # so failure of any single provider does not abort the entire collection cycle
        metrics_results = await asyncio.gather(
            _fetch_hosts(),
            _fetch_usage(),
            _fetch_zfs(),
            _fetch_glances(),
            return_exceptions=True,
        )

        hosts = metrics_results[0] if isinstance(metrics_results[0], list) else []
        usage = metrics_results[1] if isinstance(metrics_results[1], dict) else {}
        zfs = metrics_results[2] if isinstance(metrics_results[2], list) else []
        glances_data = metrics_results[3] if isinstance(metrics_results[3], dict) else {}

        containers = []
        try:
            containers = await self.docker.list_containers(usage)
        except Exception as exc:
            log.debug("Failed listing containers: %s", exc)

        if not hosts:
            hosts = [read_local_host(settings)]

        summary = _summarize(hosts, containers, zfs)
        snapshot = Snapshot(
            ts=time.time(),
            instance=settings.instance_name,
            prometheus_ok=prom_ok,
            docker_ok=docker_ok,
            mqtt_ok=self.mqtt.ok,
            hosts=hosts,
            containers=containers,
            zfs=zfs,
            alerts=[],
            summary=summary,
            glances=glances_data,
        )

        try:
            await self.restarter.evaluate(containers)
        except Exception as exc:
            log.debug("Restarter evaluation failed: %s", exc)

        try:
            await self.alerter.evaluate(snapshot)
        except Exception as exc:
            log.debug("Alerter evaluation failed: %s", exc)

        try:
            snapshot.alerts = await recent_alerts(limit=40, time_range="6h")
        except Exception as exc:
            log.debug("Failed retrieving recent alerts: %s", exc)

        # Best-effort mirror to MQTT — never fail the tick
        try:
            self.mqtt.publish_snapshot(snapshot)
        except Exception:
            log.debug("MQTT publish failed", exc_info=True)

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
