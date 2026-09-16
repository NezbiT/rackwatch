"""Optional Glances REST client for host-level metrics not covered by Prometheus."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import Settings


class GlancesClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=2.0)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.glances_url.strip())

    async def close(self) -> None:
        await self._client.aclose()

    async def summary(self) -> dict[str, Any]:
        if not self.enabled:
            return {}
        base = self.settings.glances_url.rstrip("/")
        paths = {
            "quicklook": "/api/4/quicklook",
            "memswap": "/api/4/memswap",
            "network": "/api/4/network",
            "diskio": "/api/4/diskio",
            "processes": "/api/4/processlist",
            "sensors": "/api/4/sensors",
            "containers": "/api/4/containers",
        }

        async def get(key: str, path: str) -> tuple[str, Any]:
            try:
                res = await self._client.get(base + path)
                res.raise_for_status()
                value = res.json()
                if key == "processes" and isinstance(value, list):
                    value = sorted(value, key=lambda p: float(p.get("cpu_percent", 0) or 0), reverse=True)[:10]
                return key, value
            except Exception:
                return key, [] if key in {"network", "diskio", "processes", "sensors", "containers"} else {}

        results = await asyncio.gather(*(get(k, p) for k, p in paths.items()))
        return {k: v for k, v in results}
