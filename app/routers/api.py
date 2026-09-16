"""Versioned REST API (`/api/v1`).

This is the SaaS-facing contract. Keep it JSON-only. The HTML
dashboard never depends on breaking these paths.

Auth: `X-API-Key: <RACKWATCH_API_TOKEN>` or a signed-in session.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app import __version__
from app.config import get_settings
from app.database import async_session
from app.models import Alert, RestartEvent
from app.schemas import (
    AlertTestRequest,
    ContainerActionRequest,
    ContainerExecOut,
    ContainerExecRequest,
    HealthOut,
    RestartRequest,
    Snapshot,
)
from app.security import require_api_token, require_read, require_session
from app.services import settings_store
from app.services.alerter import recent_alerts
from app.services.restarter import recent_restarts

router = APIRouter(prefix="/api/v1", tags=["api"])


def _collector_started(app) -> float:
    collector = getattr(app.state, "collector", None)
    return getattr(collector, "started_at", time.time())


@router.get("/health", response_model=HealthOut)
async def health_check(request: Request) -> HealthOut:
    settings = get_settings()
    hub = getattr(request.app.state, "hub", None)
    snap: Snapshot | None = getattr(hub, "latest", None) if hub else None
    return HealthOut(
        status="ok",
        version=__version__,
        instance=settings.instance_name,
        prometheus=bool(snap.prometheus_ok) if snap else False,
        docker=bool(snap.docker_ok) if snap else False,
        homeassistant=bool(snap.ha_ok) if snap else False,
        mqtt=bool(snap.mqtt_ok) if snap else False,
        uptime_seconds=time.time() - _collector_started(request.app),
    )


@router.get("/snapshot", response_model=Snapshot)
async def snapshot(
    request: Request,
    _: Annotated[None, Depends(require_read)],
) -> Snapshot:
    snap = request.app.state.hub.latest
    if snap is None:
        raise HTTPException(status_code=503, detail="Collector has not published a snapshot yet")
    return snap


@router.get("/glances")
async def glances_summary(
    request: Request,
    _: Annotated[None, Depends(require_read)],
):
    data = await request.app.state.glances.summary()
    if not data:
        raise HTTPException(status_code=503, detail="Glances is not configured or unreachable")
    return {"ok": True, "data": data}


@router.get("/alerts")
async def list_alerts(
    _: Annotated[None, Depends(require_read)],
    range: str = Query(default="24h"),
    limit: int = Query(default=80, ge=1, le=500),
):
    return await recent_alerts(limit=limit, time_range=range)


@router.post("/alerts/{alert_id}/ack")
async def ack_alert(
    alert_id: int,
    _: Annotated[None, Depends(require_api_token)],
):
    async with async_session() as session:
        row = await session.get(Alert, alert_id)
        if not row:
            raise HTTPException(status_code=404, detail="Alert not found")
        row.acked = True
        await session.commit()
    return {"ok": True, "id": alert_id}


@router.get("/restarts")
async def list_restarts(
    _: Annotated[None, Depends(require_read)],
    limit: int = Query(default=50, ge=1, le=200),
):
    rows = await recent_restarts(limit)
    return [
        {
            "id": r.id,
            "created_at": r.created_at,
            "container": r.container,
            "reason": r.reason,
            "automatic": r.automatic,
            "success": r.success,
            "error": r.error,
        }
        for r in rows
    ]


_SECRET_SETTING_KEYS = {
    "telegram_bot_token",
    "telegram_chat_id",
    "whatsapp_apikey",
    "ha_token",
    "mqtt_password",
    "auth_password",
    "api_token",
    "secret_key",
    "n8n_chat_auth_header",
}


@router.get("/containers/{name}/logs")
async def container_logs(
    name: str,
    request: Request,
    _: Annotated[None, Depends(require_read)],
    lines: int = Query(default=80, ge=1, le=500),
):
    docker = request.app.state.docker
    ok, detail = await docker.logs(name, lines=lines)
    if not ok:
        raise HTTPException(status_code=404, detail=detail)
    return {"ok": True, "container": name, "lines": lines, "logs": detail}


@router.get("/containers/{name}/inspect")
async def inspect_container(
    name: str,
    request: Request,
    _: Annotated[None, Depends(require_read)],
):
    ok, detail = await request.app.state.docker.inspect(name)
    if not ok:
        raise HTTPException(status_code=404, detail=detail)
    return {"ok": True, "container": name, "inspect": detail}


@router.post("/containers/{name}/exec", response_model=ContainerExecOut)
async def exec_container(
    name: str,
    request: Request,
    body: ContainerExecRequest,
    _: Annotated[None, Depends(require_api_token)],
):
    ok, detail = await request.app.state.docker.exec(name, body.command)
    if not ok:
        raise HTTPException(status_code=400, detail=detail)
    result = detail
    return ContainerExecOut(
        ok=True,
        container=name,
        command=body.command,
        exit_code=result["exit_code"],
        output=result["output"],
    )


@router.get("/settings")
async def get_settings_public(
    _: Annotated[None, Depends(require_read)],
):
    live = await settings_store.merged()
    data = live.model_dump()
    for key in _SECRET_SETTING_KEYS:
        if key in data and data[key]:
            data[key] = "***"
    return {k: data[k] for k in settings_store.WRITABLE if k in data}


async def _mutate_container(request: Request, name: str, action: str, reason: str, force: bool) -> dict:
    docker = request.app.state.docker
    method = {"start": docker.start, "stop": docker.stop, "restart": docker.restart}[action]
    ok, detail = await method(name, force=force)
    async with async_session() as session:
        session.add(
            RestartEvent(
                created_at=datetime.now(timezone.utc),
                container=name,
                reason=reason,
                automatic=False,
                success=ok,
                error="" if ok else detail,
            )
        )
        await session.commit()
    if not ok:
        raise HTTPException(status_code=400, detail=detail)
    return {"ok": True, "container": name, "action": action, "detail": detail}


@router.post("/containers/{name}/restart")
async def restart_container(
    name: str,
    request: Request,
    _: Annotated[None, Depends(require_api_token)],
    body: RestartRequest | None = None,
    force: bool = False,
):
    return await _mutate_container(
        request, name, "restart", body.reason if body else "manual", force
    )


@router.post("/containers/{name}/start")
async def start_container(
    name: str,
    request: Request,
    _: Annotated[None, Depends(require_api_token)],
    body: ContainerActionRequest | None = None,
    force: bool = False,
):
    return await _mutate_container(
        request, name, "start", body.reason if body else "manual", force
    )


@router.post("/containers/{name}/stop")
async def stop_container(
    name: str,
    request: Request,
    _: Annotated[None, Depends(require_api_token)],
    body: ContainerActionRequest | None = None,
    force: bool = False,
):
    return await _mutate_container(
        request, name, "stop", body.reason if body else "manual", force
    )


@router.post("/alerts/test")
async def test_alert(
    request: Request,
    body: AlertTestRequest,
    _: Annotated[None, Depends(require_api_token)],
):
    alerter = request.app.state.alerter
    channels = None if body.channel == "all" else [body.channel]
    alert = await alerter.fire(
        title="RackWatch test",
        message=body.message,
        severity="info",
        source="test",
        host=get_settings().instance_name,
        service="rackwatch",
        channels=channels,
    )
    return {"ok": True, "id": alert.id, "delivered_to": alert.delivered_to}


@router.get("/ha/entities")
async def ha_entities(
    request: Request,
    _: Annotated[None, Depends(require_read)],
):
    ha = request.app.state.ha
    return await ha.entities()


@router.api_route("/chat/n8n", methods=["GET", "POST"])
async def n8n_chat_proxy(
    request: Request,
    _: Annotated[None, Depends(require_session)],
):
    """Same-origin stand-in for the n8n Chat Trigger webhook (browser widget)."""
    body = await request.body()
    query = {k: v for k, v in request.query_params.multi_items()}
    return await request.app.state.n8n_chat.proxy(
        method=request.method,
        query=query,
        body=body,
        content_type=request.headers.get("content-type"),
    )


@router.post("/chat/test")
async def n8n_chat_test(
    request: Request,
    _: Annotated[None, Depends(require_session)],
):
    return await request.app.state.n8n_chat.ping()
