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

import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.schemas import Filters

router = APIRouter()
log = logging.getLogger("rackwatch.ws")


@router.websocket("/ws")
async def metrics_ws(ws: WebSocket) -> None:
    await ws.accept()
    hub = ws.app.state.hub
    client = await hub.register(ws)
    try:
        if hub.latest is not None:
            await ws.send_json(hub.apply_filters(hub.latest, client.filters))
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "filter")
            if msg_type == "ping":
                await ws.send_json({"type": "pong", "ts": time.time()})
                continue
            client.filters = Filters(
                host=str(data.get("host") or ""),
                service=str(data.get("service") or ""),
                severity=str(data.get("severity") or ""),
                status=str(data.get("status") or ""),
                time_range=str(data.get("time_range") or "1h"),
            )
            if hub.latest is not None:
                await ws.send_json(hub.apply_filters(hub.latest, client.filters))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.debug("ws error: %s", exc)
    finally:
        await hub.unregister(client)
