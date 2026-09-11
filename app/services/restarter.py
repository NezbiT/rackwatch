"""Auto-restart failed Docker containers.

Rules (in order):
1. AUTO_RESTART_ENABLED must be true.
2. Container status is exited/dead or health is unhealthy.
3. Name is not on the denylist (and is on the allow-list if set).
4. We waited AUTO_RESTART_DELAY_SECONDS after first seeing it down.
5. We have not restarted it inside AUTO_RESTART_COOLDOWN_SECONDS.
6. Restarts in the last hour < AUTO_RESTART_MAX_PER_HOUR.

Every attempt is written to `restarts` so the UI and SaaS audit
trail can show who/what bounced a box.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import Settings
from app.database import async_session
from app.models import RestartEvent
from app.schemas import ContainerMetrics
from app.services.docker_ctl import DockerControl

log = logging.getLogger("rackwatch.restarter")


class Restarter:
    def __init__(self, settings: Settings, docker: DockerControl) -> None:
        self.settings = settings
        self.docker = docker
        self._seen_down_at: dict[str, float] = {}
        self._last_restart: dict[str, float] = {}
        self._hour_window: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, name: str, now: float) -> int:
        window = self._hour_window[name]
        cutoff = now - 3600
        while window and window[0] < cutoff:
            window.popleft()
        return len(window)

    async def evaluate(self, containers: list[ContainerMetrics]) -> list[RestartEvent]:
        if not self.settings.auto_restart_enabled:
            self._seen_down_at.clear()
            return []

        now = time.time()
        events: list[RestartEvent] = []
        living = {c.name for c in containers if c.severity != "error"}
        for name in list(self._seen_down_at):
            if name in living:
                self._seen_down_at.pop(name, None)

        for container in containers:
            if container.severity != "error":
                continue
            name = container.name
            if self.docker.is_denied(name) or self.docker.allowlist_blocks(name):
                continue
            first = self._seen_down_at.setdefault(name, now)
            if now - first < self.settings.auto_restart_delay_seconds:
                continue
            last = self._last_restart.get(name, 0)
            if now - last < self.settings.auto_restart_cooldown_seconds:
                continue
            if self._prune(name, now) >= self.settings.auto_restart_max_per_hour:
                log.warning("restart cap reached for %s", name)
                continue

            reason = f"{container.status}" + (f"/{container.health}" if container.health else "")
            ok, detail = await self.docker.restart(name, force=False)
            self._last_restart[name] = now
            self._hour_window[name].append(now)
            event = RestartEvent(
                created_at=datetime.now(timezone.utc),
                container=name,
                container_id=container.id,
                reason=f"auto: {reason}",
                automatic=True,
                success=ok,
                error="" if ok else detail,
            )
            await _persist(event)
            events.append(event)
            log.info("auto-restart %s ok=%s %s", name, ok, detail)
        return events


async def _persist(event: RestartEvent) -> None:
    async with async_session() as session:
        session.add(event)
        await session.commit()
        await session.refresh(event)


async def recent_restarts(limit: int = 50) -> list[RestartEvent]:
    async with async_session() as session:
        rows = await session.execute(
            select(RestartEvent).order_by(RestartEvent.created_at.desc()).limit(limit)
        )
        return list(rows.scalars())
