"""Home Assistant REST client.

Two directions:
- Pull: GET /api/states  → dashboard cards.
- Push: POST /api/states/sensor.rackwatch_*  (metrics as HA entities)
        POST /api/services/<domain>/<service>  (notify on alerts)

A long-lived token is required. The integration is optional: empty
HA_URL disables every call.

SaaS note: a hosted RackWatch would use a per-tenant HA URL stored
encrypted, never in a shared `.env`.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings
from app.schemas import HAEntity, Snapshot
from app.services.status import level_from_percent

log = logging.getLogger("rackwatch.ha")

# Domains we surface on the dashboard when the operator did not pin any.
DEFAULT_DOMAINS = {
    "sensor",
    "binary_sensor",
    "switch",
    "light",
    "climate",
    "cover",
    "fan",
    "lock",
}


class HomeAssistant:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=4.0)
        self.ok = False

    def bind(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.ha_url and self.settings.ha_token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.ha_token}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.settings.ha_url.rstrip('/')}{path}"

    async def close(self) -> None:
        await self._client.aclose()

    async def ready(self) -> bool:
        if not self.enabled:
            self.ok = False
            return False
        try:
            res = await self._client.get(self._url("/api/"), headers=self._headers())
            self.ok = res.status_code == 200
            return self.ok
        except Exception as exc:
            log.debug("HA ping failed: %s", exc)
            self.ok = False
            return False

    async def entities(self) -> list[HAEntity]:
        if not self.enabled:
            return []
        try:
            res = await self._client.get(self._url("/api/states"), headers=self._headers())
            res.raise_for_status()
            self.ok = True
            raw = res.json()
        except Exception as exc:
            log.warning("HA states failed: %s", exc)
            self.ok = False
            return []

        pinned = set(self.settings.pinned_entities)
        picked: list[HAEntity] = []
        for item in raw:
            entity_id = item.get("entity_id") or ""
            domain = entity_id.split(".", 1)[0] if entity_id else ""
            attrs = item.get("attributes") or {}
            name = attrs.get("friendly_name") or entity_id
            if pinned:
                if entity_id not in pinned:
                    continue
            else:
                if domain not in DEFAULT_DOMAINS:
                    continue
                if entity_id.startswith("sensor.rackwatch_"):
                    # Always keep our own sensors if they exist.
                    pass
            state = str(item.get("state", ""))
            picked.append(
                HAEntity(
                    entity_id=entity_id,
                    name=name,
                    state=state,
                    unit=str(attrs.get("unit_of_measurement") or ""),
                    domain=domain,
                    last_changed=str(item.get("last_changed") or ""),
                    friendly=name,
                    icon=str(attrs.get("icon") or ""),
                    status=_entity_status(domain, state),
                )
            )
        # Prefer pinned order, then errors, then name. Cap the card grid.
        if pinned:
            order = {eid: i for i, eid in enumerate(self.settings.pinned_entities)}
            picked.sort(key=lambda e: order.get(e.entity_id, 999))
        else:
            picked.sort(key=lambda e: (e.status != "error", e.domain, e.name.lower()))
            picked = picked[:24]
        return picked

    async def publish_snapshot(self, snapshot: Snapshot) -> None:
        """Mirror RackWatch summary as HA sensors so dashboards / automations see it."""
        if not self.enabled:
            return
        summary = snapshot.summary or {}
        sensors = {
            "sensor.rackwatch_cpu": (
                summary.get("cpu"),
                "%",
                "CPU",
                "mdi:cpu-64-bit",
            ),
            "sensor.rackwatch_ram": (
                summary.get("ram"),
                "%",
                "RAM",
                "mdi:memory",
            ),
            "sensor.rackwatch_disk": (
                summary.get("disk"),
                "%",
                "Disk",
                "mdi:harddisk",
            ),
            "sensor.rackwatch_containers_down": (
                summary.get("containers_down"),
                "containers",
                "Containers down",
                "mdi:docker",
            ),
            "sensor.rackwatch_status": (
                summary.get("overall", "unknown"),
                None,
                "RackWatch status",
                "mdi:server",
            ),
        }
        for entity_id, (state, unit, name, icon) in sensors.items():
            if state is None:
                continue
            attrs: dict[str, Any] = {
                "friendly_name": f"RackWatch {name}",
                "icon": icon,
                "instance": snapshot.instance,
            }
            if unit:
                attrs["unit_of_measurement"] = unit
            await self._set_state(entity_id, state, attrs)

    async def _set_state(self, entity_id: str, state: Any, attributes: dict[str, Any]) -> None:
        try:
            await self._client.post(
                self._url(f"/api/states/{entity_id}"),
                headers=self._headers(),
                json={"state": state, "attributes": attributes},
            )
        except Exception as exc:
            log.debug("HA set_state %s failed: %s", entity_id, exc)

    async def notify(
        self,
        title: str,
        message: str,
        severity: str,
        payload: dict[str, Any],
    ) -> bool:
        if not self.enabled:
            return False
        service = self.settings.ha_notify_service or "notify.notify"
        parts = service.split(".", 1)
        if len(parts) != 2:
            domain, name = "notify", "notify"
        else:
            domain, name = parts
        body = {
            "title": f"RackWatch [{severity}]",
            "message": f"{title}\n{message}",
            "data": payload,
        }
        try:
            res = await self._client.post(
                self._url(f"/api/services/{domain}/{name}"),
                headers=self._headers(),
                json=body,
            )
            return res.is_success
        except Exception as exc:
            log.warning("HA notify failed: %s", exc)
            return False


def _entity_status(domain: str, state: str) -> str:
    s = (state or "").lower()
    if s in {"unavailable", "unknown"}:
        return "error"
    if domain == "binary_sensor" and s == "on":
        # Motion / leak / problem sensors often use device_class; treat on as warning.
        return "warning"
    if domain in {"lock"} and s == "unlocked":
        return "warning"
    cpuish = s.replace("%", "")
    try:
        return level_from_percent(float(cpuish), 80, 95)
    except Exception:
        return "ok"
