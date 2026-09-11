"""Prometheus HTTP API client.

Queries are PromQL. Timeouts are short (2s) so a sick Prometheus
cannot stall the 3-second WebSocket tick. When Prometheus is down
the collector falls back to local psutil + Docker SDK.

SaaS note: each tenant agent would expose `/metrics`; a central
Prometheus (or Mimir) remote-writes them. This module stays the
query adapter.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings
from app.schemas import HostMetrics
from app.services.status import level_from_percent

log = logging.getLogger("rackwatch.prom")


class PrometheusClient:
    def __init__(self, settings: Settings) -> None:
        self.base = settings.prometheus_url.rstrip("/")
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=2.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def ready(self) -> bool:
        try:
            res = await self._client.get(f"{self.base}/-/ready")
            return res.status_code == 200
        except Exception:
            return False

    async def query(self, promql: str) -> list[dict[str, Any]]:
        try:
            res = await self._client.get(
                f"{self.base}/api/v1/query",
                params={"query": promql},
            )
            res.raise_for_status()
            data = res.json()
            if data.get("status") != "success":
                return []
            return data.get("data", {}).get("result", [])
        except Exception as exc:
            log.debug("promql failed: %s (%s)", promql[:80], exc)
            return []

    async def hosts(self) -> list[HostMetrics]:
        """Build one HostMetrics per node-exporter instance."""
        cpu_rows = await self.query(
            '100 - (avg by (instance, job) (rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)'
        )
        ram_rows = await self.query(
            "100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)"
        )
        ram_total = await self.query("node_memory_MemTotal_bytes")
        ram_avail = await self.query("node_memory_MemAvailable_bytes")
        disk_rows = await self.query(
            '100 * (1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs|ramfs",'
            'mountpoint="/"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs|ramfs",'
            'mountpoint="/"})'
        )
        disk_size = await self.query(
            'node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs|ramfs",mountpoint="/"}'
        )
        disk_avail = await self.query(
            'node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs|ramfs",mountpoint="/"}'
        )
        load_rows = await self.query("node_load1")
        uptime_rows = await self.query("time() - node_boot_time_seconds")

        by_instance: dict[str, HostMetrics] = {}

        def _inst(row: dict[str, Any]) -> str:
            return row.get("metric", {}).get("instance", "unknown")

        def _val(row: dict[str, Any]) -> float | None:
            try:
                return float(row["value"][1])
            except Exception:
                return None

        def _host(instance: str) -> HostMetrics:
            if instance not in by_instance:
                by_instance[instance] = HostMetrics(
                    name=instance.split(":")[0],
                    instance=instance,
                    source="prometheus",
                )
            return by_instance[instance]

        for row in cpu_rows:
            h = _host(_inst(row))
            h.cpu_percent = _round(_val(row))
        for row in ram_rows:
            h = _host(_inst(row))
            h.ram_percent = _round(_val(row))
        for row in ram_total:
            h = _host(_inst(row))
            v = _val(row)
            h.ram_total_bytes = int(v) if v is not None else None
        for row in ram_avail:
            h = _host(_inst(row))
            avail = _val(row)
            if avail is not None and h.ram_total_bytes:
                h.ram_used_bytes = int(h.ram_total_bytes - avail)
        for row in disk_rows:
            h = _host(_inst(row))
            h.disk_percent = _round(_val(row))
        for row in disk_size:
            h = _host(_inst(row))
            v = _val(row)
            h.disk_total_bytes = int(v) if v is not None else None
        for row in disk_avail:
            h = _host(_inst(row))
            avail = _val(row)
            if avail is not None and h.disk_total_bytes:
                h.disk_used_bytes = int(h.disk_total_bytes - avail)
        for row in load_rows:
            h = _host(_inst(row))
            h.load1 = _round(_val(row), 2)
        for row in uptime_rows:
            h = _host(_inst(row))
            h.uptime_seconds = _val(row)

        s = self.settings
        for h in by_instance.values():
            h.status = _worst(
                level_from_percent(h.cpu_percent, s.threshold_cpu_warn, s.threshold_cpu_crit),
                level_from_percent(h.ram_percent, s.threshold_ram_warn, s.threshold_ram_crit),
                level_from_percent(h.disk_percent, s.threshold_disk_warn, s.threshold_disk_crit),
            )
        return list(by_instance.values())

    async def container_usage(self) -> dict[str, dict[str, float]]:
        """cAdvisor CPU / memory keyed by container name."""
        cpu_rows = await self.query(
            'sum by (name) (rate(container_cpu_usage_seconds_total{name!=""}[1m])) * 100'
        )
        mem_rows = await self.query(
            'sum by (name) (container_memory_working_set_bytes{name!=""})'
        )
        mem_limit = await self.query(
            'sum by (name) (container_spec_memory_limit_bytes{name!=""})'
        )
        out: dict[str, dict[str, float]] = {}

        def bucket(name: str) -> dict[str, float]:
            return out.setdefault(name, {})

        for row in cpu_rows:
            name = row.get("metric", {}).get("name", "")
            if name:
                try:
                    bucket(name)["cpu"] = round(float(row["value"][1]), 2)
                except Exception:
                    pass
        limits: dict[str, float] = {}
        for row in mem_limit:
            name = row.get("metric", {}).get("name", "")
            if name:
                try:
                    limits[name] = float(row["value"][1])
                except Exception:
                    pass
        for row in mem_rows:
            name = row.get("metric", {}).get("name", "")
            if not name:
                continue
            try:
                used = float(row["value"][1])
            except Exception:
                continue
            bucket(name)["memory_bytes"] = used
            lim = limits.get(name) or 0
            if lim > 0:
                bucket(name)["memory_percent"] = round(used / lim * 100, 2)
        return out


def _round(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _worst(*levels: str) -> str:
    rank = {"ok": 0, "unknown": 1, "warning": 2, "error": 3}
    return max(levels, key=lambda x: rank.get(x, 0))
