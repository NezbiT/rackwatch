"""Proxy browser chat traffic to an n8n Chat Trigger.

The widget posts same-origin to RackWatch so the browser never needs
the Docker-internal n8n URL or CORS. Alert webhooks stay on
N8N_WEBHOOK_URL and are unrelated to this path.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from fastapi import HTTPException, Response

from app.services import settings_store

log = logging.getLogger("rackwatch.n8n_chat")


class N8nChat:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)

    async def close(self) -> None:
        await self._client.aclose()

    async def ping(self) -> dict[str, Any]:
        live = await settings_store.merged()
        url = (live.n8n_chat_webhook_url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="n8n chat webhook is not configured")
        body = {
            "action": "sendMessage",
            "sessionId": "rackwatch-test",
            "chatInput": "ping",
            "metadata": {
                "instance": live.instance_name,
                "public_url": live.public_url,
                "source": "test",
            },
        }
        status, media, content, elapsed_ms = await self._send("POST", url, {}, body, live.n8n_chat_auth_header)
        preview = content.decode("utf-8", "replace")[:400]
        ok = 200 <= status < 300
        return {
            "ok": ok,
            "status_code": status,
            "elapsed_ms": elapsed_ms,
            "content_type": media,
            "preview": preview,
        }

    async def proxy(self, *, method: str, query: dict[str, str], body: bytes, content_type: str | None) -> Response:
        live = await settings_store.merged()
        url = (live.n8n_chat_webhook_url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="n8n chat webhook is not configured")

        payload: Any = None
        if body:
            try:
                payload = json.loads(body)
            except Exception:
                payload = None
        if isinstance(payload, dict):
            meta = payload.get("metadata")
            if not isinstance(meta, dict):
                meta = {}
                payload["metadata"] = meta
            meta.setdefault("instance", live.instance_name)
            meta.setdefault("public_url", live.public_url)
            body = json.dumps(payload).encode("utf-8")
            content_type = "application/json"

        status, media, content, elapsed_ms = await self._send(
            method, url, query, body if method.upper() != "GET" else None, live.n8n_chat_auth_header, content_type
        )
        log.info("n8n chat proxy status=%s ms=%s", status, elapsed_ms)
        return Response(content=content, status_code=status, media_type=media)

    async def _send(
        self,
        method: str,
        url: str,
        query: dict[str, str],
        body: Any,
        auth_header: str,
        content_type: str | None = "application/json",
    ) -> tuple[int, str, bytes, int]:
        headers = {"Accept": "application/json, text/event-stream, */*"}
        if content_type:
            headers["Content-Type"] = content_type
        extra = (auth_header or "").strip()
        if extra:
            if ":" in extra:
                name, value = extra.split(":", 1)
                headers[name.strip()] = value.strip()
            else:
                headers["Authorization"] = extra

        target = _with_query(url, query)
        started = time.perf_counter()
        try:
            kwargs: dict[str, Any] = {"headers": headers}
            if isinstance(body, (dict, list)):
                kwargs["json"] = body
            elif body is not None:
                kwargs["content"] = body
            res = await self._client.request(method.upper(), target, **kwargs)
        except httpx.RequestError as exc:
            log.warning("n8n chat unreachable: %s", exc)
            raise HTTPException(status_code=502, detail="n8n chat webhook is unreachable") from exc
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        media = res.headers.get("content-type") or "application/json"
        return res.status_code, media, res.content, elapsed_ms


def _with_query(url: str, query: dict[str, str]) -> str:
    if not query:
        return url
    parts = urlsplit(url)
    extra = urlencode({k: v for k, v in query.items() if v is not None})
    joined = "&".join(p for p in (parts.query, extra) if p)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, joined, parts.fragment))
