"""In-process pub/sub for the live WebSocket feed.

One Hub instance is stored on `app.state.hub`. The collector writes
`latest`; every connected browser receives the same snapshot. Filters
are applied per-socket so one operator can watch "error only" without
affecting another tab.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import WebSocket

from app.schemas import Filters, Snapshot

log = logging.getLogger("rackwatch.hub")

RANGE_SECONDS = {
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "24h": 86400,
    "7d": 604800,
}


class Client:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.filters = Filters()


class Hub:
    def __init__(self) -> None:
        self.clients: set[Client] = set()
        self.latest: Snapshot | None = None
        self._lock = asyncio.Lock()

    async def register(self, ws: WebSocket) -> Client:
        client = Client(ws)
        async with self._lock:
            self.clients.add(client)
        log.info("ws connected (%s clients)", len(self.clients))
        return client

    async def unregister(self, client: Client) -> None:
        async with self._lock:
            self.clients.discard(client)
        log.info("ws disconnected (%s clients)", len(self.clients))

    def apply_filters(self, snapshot: Snapshot, filters: Filters) -> dict[str, Any]:
        """Return a JSON-ready snapshot reduced by the client's filters."""
        has_criteria = bool(
            filters.host
            or filters.service
            or filters.status
            or filters.severity
            or filters.time_range
        )
        if not has_criteria:
            base = snapshot.model_dump(mode="json")
            base["filters"] = filters.model_dump()
            return base

        hosts = snapshot.hosts
        containers = snapshot.containers
        alerts = snapshot.alerts
        zfs = snapshot.zfs

        if filters.host:
            needle = filters.host.lower()
            hosts = [h for h in hosts if needle in h.name.lower() or needle in h.instance.lower()]
            containers = [c for c in containers if needle in (c.host or c.name).lower()]
            alerts = [a for a in alerts if needle in a.host.lower()]

        if filters.service:
            needle = filters.service.lower()
            containers = [
                c
                for c in containers
                if needle in c.name.lower() or needle in c.image.lower()
            ]
            alerts = [
                a
                for a in alerts
                if needle in a.service.lower() or needle in a.source.lower()
            ]

        if filters.status:
            hosts = [h for h in hosts if h.status == filters.status]
            containers = [c for c in containers if c.severity == filters.status]
            zfs = [z for z in zfs if z.status == filters.status]

        if filters.severity:
            rank = {"info": 1, "warning": 2, "critical": 3}
            want = rank.get(filters.severity, 0)
            alerts = [a for a in alerts if rank.get(a.severity, 0) >= want]

        if filters.time_range:
            max_age = RANGE_SECONDS.get(filters.time_range)
            if max_age is not None:
                cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age)
                alerts = [
                    a for a in alerts
                    if a.created_at is None
                    or (a.created_at if a.created_at.tzinfo else a.created_at.replace(tzinfo=timezone.utc)) >= cutoff
                ]

        payload = snapshot.model_dump(mode="json")
        payload["hosts"] = [h.model_dump(mode="json") for h in hosts]
        payload["containers"] = [c.model_dump(mode="json") for c in containers]
        payload["alerts"] = [a.model_dump(mode="json") for a in alerts]
        payload["zfs"] = [z.model_dump(mode="json") for z in zfs]
        payload["filters"] = filters.model_dump()
        return payload

    async def publish(self, snapshot: Snapshot) -> None:
        self.latest = snapshot
        async with self._lock:
            targets = list(self.clients)
        if not targets:
            return

        # Cache filtered payloads per filter key for efficiency
        cache: dict[str, dict[str, Any]] = {}

        async def _send(client: Client) -> Client | None:
            try:
                filter_key = client.filters.model_dump_json()
                payload = cache.get(filter_key)
                if payload is None:
                    payload = self.apply_filters(snapshot, client.filters)
                    cache[filter_key] = payload

                await asyncio.wait_for(client.ws.send_json(payload), timeout=4.0)
                return None
            except Exception:
                return client

        results = await asyncio.gather(*[_send(c) for c in targets], return_exceptions=True)
        stale = [res for res in results if isinstance(res, Client)]
        for client in stale:
            await self.unregister(client)
