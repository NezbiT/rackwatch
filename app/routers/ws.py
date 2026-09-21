"""WebSocket live stream.

Protocol (JSON):
  server → client   Snapshot (see app.schemas.Snapshot) every refresh tick
  client → server   {"type":"filter","host":"","service":"","severity":"","status":"","time_range":"1h"}
  client → server   {"type":"ping"}
  server → client   {"type":"pong","ts": ...}

Reconnect is the client's job (app/static/js/app.js). The hub drops
dead sockets on the next publish.
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.status import WS_1008_POLICY_VIOLATION

from app.config import get_settings
from app.schemas import Filters
from app.security import is_ws_authenticated, is_ws_origin_allowed

router = APIRouter()
log = logging.getLogger("rackwatch.ws")


@router.websocket("/ws")
async def metrics_ws(ws: WebSocket) -> None:
    settings = getattr(ws.app.state, "settings", None) or get_settings()

    # 1. Origin verification against CSWSH (Cross-Site WebSocket Hijacking)
    origin = ws.headers.get("origin")
    host = ws.headers.get("host")
    if not is_ws_origin_allowed(origin, host, settings):
        log.warning("WebSocket rejected: unauthorized origin '%s'", origin)
        await ws.close(code=WS_1008_POLICY_VIOLATION, reason="Origin not allowed")
        return

    # 2. Authentication check (session cookie, query param, or API header)
    if not is_ws_authenticated(ws, settings):
        log.warning("WebSocket rejected: unauthenticated client")
        await ws.close(code=WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return

    await ws.accept()
    hub = ws.app.state.hub
    client = await hub.register(ws)

    msg_count = 0
    window_start = time.time()

    try:
        if hub.latest is not None:
            try:
                await asyncio.wait_for(
                    ws.send_json(hub.apply_filters(hub.latest, client.filters)),
                    timeout=5.0,
                )
            except (asyncio.TimeoutError, Exception) as exc:
                log.debug("ws initial send error: %s", exc)
                return

        while True:
            data = await ws.receive_json()

            # Rate limit incoming messages (max 30 per 5 seconds)
            now = time.time()
            if now - window_start > 5.0:
                window_start = now
                msg_count = 0
            msg_count += 1
            if msg_count > 30:
                log.warning("ws client rate limit exceeded, closing connection")
                await ws.close(code=WS_1008_POLICY_VIOLATION, reason="Rate limit exceeded")
                break

            msg_type = data.get("type", "filter")
            if msg_type == "ping":
                await ws.send_json({"type": "pong", "ts": time.time()})
                continue

            client.filters = Filters(
                host=str(data.get("host") or "")[:128],
                service=str(data.get("service") or "")[:128],
                severity=str(data.get("severity") or "")[:32],
                status=str(data.get("status") or "")[:32],
                time_range=str(data.get("time_range") or "1h")[:16],
            )
            if hub.latest is not None:
                await asyncio.wait_for(
                    ws.send_json(hub.apply_filters(hub.latest, client.filters)),
                    timeout=5.0,
                )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.debug("ws error: %s", exc)
    finally:
        await hub.unregister(client)

