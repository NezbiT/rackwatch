"""In-process pub/sub for the live WebSocket feed.

One Hub instance is stored on `app.state.hub`. The collector writes
`latest`; every connected browser receives the same snapshot. Filters
are applied per-socket so one operator can watch "error only" without
affecting another tab.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

from app.schemas import Filters, Snapshot

log = logging.getLogger("rackwatch.hub")


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
        # Fast-path for clients without active filter criteria
        if not filters.host and not filters.service and not filters.status and not filters.severity:
            base = snapshot.model_dump(mode="json")
            base["filters"] = filters.model_dump()
            return base

        hosts = snapshot.hosts
        containers = snapshot.containers
        alerts = snapshot.alerts
        ha = snapshot.ha_entities
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
            ha = [
                e
                for e in ha
                if needle in e.entity_id.lower() or needle in e.name.lower()
            ]

        if filters.status:
            hosts = [h for h in hosts if h.status == filters.status]
            containers = [c for c in containers if c.severity == filters.status]
            zfs = [z for z in zfs if z.status == filters.status]
            ha = [e for e in ha if e.status == filters.status]

        if filters.severity:
            rank = {"info": 1, "warning": 2, "critical": 3}
            want = rank.get(filters.severity, 0)
            alerts = [a for a in alerts if rank.get(a.severity, 0) >= want]

        payload = snapshot.model_dump(mode="json")
        payload["hosts"] = [h.model_dump(mode="json") for h in hosts]
        payload["containers"] = [c.model_dump(mode="json") for c in containers]
        payload["alerts"] = [a.model_dump(mode="json") for a in alerts]
        payload["ha_entities"] = [e.model_dump(mode="json") for e in ha]
        payload["zfs"] = [z.model_dump(mode="json") for z in zfs]
        payload["filters"] = filters.model_dump()
        return payload

    async def publish(self, snapshot: Snapshot) -> None:
        self.latest = snapshot
        async with self._lock:
            targets = list(self.clients)
        if not targets:
            return

        # Pre-calculate unfiltered dump once for efficiency
        cached_unfiltered: dict[str, Any] | None = None

        async def _send(client: Client) -> Client | None:
            nonlocal cached_unfiltered
            try:
                if not client.filters.host and not client.filters.service and not client.filters.status and not client.filters.severity:
                    if cached_unfiltered is None:
                        cached_unfiltered = snapshot.model_dump(mode="json")
                    payload = dict(cached_unfiltered)
                    payload["filters"] = client.filters.model_dump()
                else:
                    payload = self.apply_filters(snapshot, client.filters)

                await asyncio.wait_for(client.ws.send_json(payload), timeout=4.0)
                return None
            except Exception:
                return client

        results = await asyncio.gather(*[_send(c) for c in targets], return_exceptions=True)
        stale = [res for res in results if isinstance(res, Client)]
        for client in stale:
            await self.unregister(client)
