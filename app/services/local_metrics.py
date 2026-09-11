"""Local host metrics via psutil.

Used when Prometheus is down or not yet scraped so the dashboard
never shows a blank first-run. Marked `source=local` so operators
can see they are looking at the RackWatch container's view of the
host (which, with pid=host in Compose, is the real machine).
"""

from __future__ import annotations

from app.config import Settings
from app.schemas import HostMetrics
from app.services.status import level_from_percent


def read_local_host(settings: Settings) -> HostMetrics:
    try:
        import psutil
    except ImportError:
        return HostMetrics(name=settings.instance_name, source="local", status="unknown")

    cpu = psutil.cpu_percent(interval=None)
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    load1 = None
    try:
        load1 = round(psutil.getloadavg()[0], 2)
    except (AttributeError, OSError):
        pass
    boot = None
    try:
        boot = psutil.boot_time()
        import time

        uptime = time.time() - boot
    except Exception:
        uptime = None

    host = HostMetrics(
        name=settings.instance_name,
        instance="local",
        cpu_percent=round(cpu, 1),
        ram_percent=round(vm.percent, 1),
        ram_used_bytes=int(vm.used),
        ram_total_bytes=int(vm.total),
        disk_percent=round(disk.percent, 1),
        disk_used_bytes=int(disk.used),
        disk_total_bytes=int(disk.total),
        load1=load1,
        uptime_seconds=uptime,
        source="local",
    )
    host.status = _worst(
        level_from_percent(host.cpu_percent, settings.threshold_cpu_warn, settings.threshold_cpu_crit),
        level_from_percent(host.ram_percent, settings.threshold_ram_warn, settings.threshold_ram_crit),
        level_from_percent(host.disk_percent, settings.threshold_disk_warn, settings.threshold_disk_crit),
    )
    return host


def _worst(*levels: str) -> str:
    rank = {"ok": 0, "unknown": 1, "warning": 2, "error": 3}
    return max(levels, key=lambda x: rank.get(x, 0))
