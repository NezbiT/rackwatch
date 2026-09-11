"""ZFS pool health.

Sources, in order:
1. `zpool list` if the binary is on PATH (privileged / host-pid setups).
2. Prometheus node-exporter ZFS collector (`node_zfs_*`) when present.
3. Host textfile dumped by `scripts/zfs-textfile.sh`.

None of these are required. Missing ZFS is a quiet empty list, not
an error — most Docker-only labs do not run ZFS.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess

from app.schemas import ZfsPool
from app.services.status import zfs_status

log = logging.getLogger("rackwatch.zfs")


class ZfsCollector:
    def __init__(self, prom: object | None = None) -> None:
        self.prom = prom

    async def pools(self) -> list[ZfsPool]:
        local = await asyncio.to_thread(_from_zpool)
        if local:
            return local
        if self.prom is not None and hasattr(self.prom, "query"):
            remote = await _from_prometheus(self.prom)
            if remote:
                return remote
        return []


def _from_zpool() -> list[ZfsPool]:
    binary = shutil.which("zpool")
    if not binary:
        return []
    try:
        # name health size alloc free cap
        proc = subprocess.run(
            [binary, "list", "-Hp", "-o", "name,health,size,alloc,free,cap"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception as exc:
        log.debug("zpool list failed: %s", exc)
        return []
    if proc.returncode != 0:
        return []
    pools: list[ZfsPool] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) < 6:
            continue
        name, health, size, alloc, free, cap = parts[:6]
        cap_n = _num(cap.replace("%", ""))
        pools.append(
            ZfsPool(
                name=name,
                health=health.upper(),
                size_bytes=_int(size),
                allocated_bytes=_int(alloc),
                free_bytes=_int(free),
                capacity_percent=cap_n,
                status=zfs_status(health),
                source="zpool",
            )
        )
    return pools


async def _from_prometheus(prom: object) -> list[ZfsPool]:
    # node-exporter exposes node_zfs_arc_stats and dataset metrics;
    # pool health is usually injected via the textfile collector.
    rows = await prom.query('zpool_health_info')  # type: ignore[attr-defined]
    if not rows:
        rows = await prom.query('node_zfs_zpool_state')  # type: ignore[attr-defined]
    pools: list[ZfsPool] = []
    for row in rows:
        metric = row.get("metric", {})
        name = metric.get("pool") or metric.get("zpool") or metric.get("name") or "tank"
        health = (metric.get("state") or metric.get("health") or "UNKNOWN").upper()
        # Gauge may be 1 for the active state label.
        pools.append(
            ZfsPool(
                name=name,
                health=health,
                status=zfs_status(health),
                source="prometheus",
            )
        )
    return pools


def _int(raw: str) -> int | None:
    try:
        return int(float(raw))
    except Exception:
        return None


def _num(raw: str) -> float | None:
    try:
        return float(raw)
    except Exception:
        return None
