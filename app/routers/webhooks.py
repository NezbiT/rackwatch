"""Inbound webhooks (n8n, Home Assistant, generic automation).

POST /api/v1/hooks/alert       create a RackWatch alert and fan it out
POST /api/v1/hooks/restart     restart a container by name
POST /api/v1/hooks/container   start | stop | restart

Both require `X-API-Key: <RACKWATCH_API_TOKEN>`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.schemas import ContainerHookIn, WebhookAlertIn
from app.security import require_api_token

router = APIRouter(prefix="/api/v1/hooks", tags=["webhooks"])


class RestartHookIn(BaseModel):
    container: str = Field(min_length=1)
    reason: str = "webhook"
    force: bool = False


@router.post("/alert")
async def inbound_alert(
    request: Request,
    body: WebhookAlertIn,
    _: Annotated[None, Depends(require_api_token)],
):
    alerter = request.app.state.alerter
    alert = await alerter.fire(
        title=body.title,
        message=body.message,
        severity=body.severity,
        source=body.source or "webhook",
        host=body.host,
        service=body.service,
    )
    return {"ok": True, "id": alert.id, "delivered_to": alert.delivered_to}


@router.post("/restart")
async def inbound_restart(
    request: Request,
    body: RestartHookIn,
    _: Annotated[None, Depends(require_api_token)],
):
    docker = request.app.state.docker
    ok, detail = await docker.restart(body.container, force=body.force)
    if not ok:
        raise HTTPException(status_code=400, detail=detail)
    return {"ok": True, "container": body.container, "action": "restart", "detail": detail}


@router.post("/container")
async def inbound_container(
    request: Request,
    body: ContainerHookIn,
    _: Annotated[None, Depends(require_api_token)],
):
    docker = request.app.state.docker
    method = {"start": docker.start, "stop": docker.stop, "restart": docker.restart}[body.action]
    ok, detail = await method(body.container, force=body.force)
    if not ok:
        raise HTTPException(status_code=400, detail=detail)
    return {"ok": True, "container": body.container, "action": body.action, "detail": detail}
