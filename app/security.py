"""Optional dashboard login and API token checks.

Homelab default is open-on-LAN (no AUTH_USER). Mutating API routes
always require `RACKWATCH_API_TOKEN` when it is set, even if the UI
is open — that is what inbound n8n / HA automations use.

SaaS note: replace SessionMiddleware + form login with OIDC / Clerk
and per-tenant API keys. Keep `require_api_token` as the machine
identity surface.
"""

from __future__ import annotations

import hmac
import re
import secrets
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_login(user: str, password: str, settings: Settings) -> bool:
    if not settings.auth_enabled:
        return True
    return hmac.compare_digest(user, settings.auth_user) and hmac.compare_digest(
        password, settings.auth_password
    )


def has_session(request: Request) -> bool:
    return bool(request.session.get("uid"))


def is_signed_in(request: Request, settings: Settings) -> bool:
    """True when the UI should treat this browser as an operator.

    Open-LAN (no AUTH_USER) ⇒ everyone is an operator for HTML pages.
    That must NOT grant machine API access — see require_api_token.
    """
    if not settings.auth_enabled:
        return True
    return has_session(request)


def _presented_api_key(request: Request, api_key: str | None) -> str:
    presented = api_key or ""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        presented = auth.split(" ", 1)[1].strip()
    return presented


def api_key_matches(presented: str, settings: Settings) -> bool:
    if not settings.api_token or not presented:
        return False
    return hmac.compare_digest(presented, settings.api_token)


async def require_session(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if is_signed_in(request, settings):
        return
    # HTMX / fetch get 401. Browsers following a page GET are sent to /login
    # via the HTTPException handler in app.main.
    if request.headers.get("HX-Request") or request.url.path.startswith("/api/"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in required")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sign in required",
        headers={"X-Redirect": "/login"},
    )


async def require_api_token(
    request: Request,
    api_key: Annotated[str | None, Depends(API_KEY_HEADER)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Machine identity for webhooks and JSON mutations.

    - Valid X-API-Key / Bearer always wins.
    - A real login cookie wins when dashboard auth is enabled.
    - Open LAN with *no* token configured stays open (homelab default).
    - Open LAN *with* a token configured requires the token.
    """
    presented = _presented_api_key(request, api_key)
    if api_key_matches(presented, settings):
        return
    if settings.auth_enabled and has_session(request):
        return
    if not settings.api_token and not settings.auth_enabled:
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")


async def require_read(
    request: Request,
    api_key: Annotated[str | None, Depends(API_KEY_HEADER)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """JSON reads for the dashboard *or* n8n (X-API-Key / Bearer)."""
    if api_key_matches(_presented_api_key(request, api_key), settings):
        return
    if is_signed_in(request, settings):
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in or API token required")


def new_csrf() -> str:
    return secrets.token_urlsafe(32)


def get_or_create_csrf_token(request: Request) -> str:
    """Retrieve existing CSRF token from session or generate a new one."""
    token = request.session.get("csrf_token")
    if not token or not isinstance(token, str):
        token = new_csrf()
        request.session["csrf_token"] = token
    return token


def verify_csrf(request: Request, presented_token: str | None) -> bool:
    """Verify presented CSRF token against session token via constant-time comparison."""
    session_token = request.session.get("csrf_token")
    if not session_token or not presented_token:
        return False
    return hmac.compare_digest(session_token, presented_token)


async def require_csrf(request: Request) -> None:
    """Enforce CSRF token verification on state-changing session requests.

    Inspects both form body (csrf_token) and headers (X-CSRF-Token / X-CSRFToken).
    """
    # API token requests (X-API-Key / Bearer) are immune from CSRF by definition
    auth_header = request.headers.get("authorization", "")
    if request.headers.get("x-api-key") or auth_header.lower().startswith("bearer "):
        return

    presented = request.headers.get("x-csrf-token") or request.headers.get("x-csrftoken")
    if not presented and request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        ctype = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype:
            try:
                form = await request.form()
                token_val = form.get("csrf_token")
                if token_val and isinstance(token_val, str):
                    presented = token_val
            except Exception:
                pass
        elif "application/json" in ctype:
            try:
                body = await request.json()
                if isinstance(body, dict) and "csrf_token" in body:
                    presented = str(body["csrf_token"])
            except Exception:
                pass

    if not verify_csrf(request, presented):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token",
        )


def safe_next(raw: str | None, fallback: str = "/") -> str:
    """Validate redirect destination to prevent open redirect vulnerabilities.

    Ensures the target is a relative path starting with '/', containing no scheme,
    no netloc, no backslashes, and no leading double-slash or slash-backslash.
    """
    if not raw or not isinstance(raw, str):
        return fallback
    cleaned = raw.strip().replace("\r", "").replace("\n", "")
    if not cleaned:
        return fallback
    if not cleaned.startswith("/") or cleaned.startswith("//") or cleaned.startswith("/\\"):
        return fallback
    if "\\" in cleaned:
        return fallback
    try:
        parsed = urlsplit(cleaned)
        if parsed.scheme or parsed.netloc:
            return fallback
    except Exception:
        return fallback
    return cleaned


def is_ws_origin_allowed(origin: str | None, host_header: str | None, settings: Settings) -> bool:
    """Validate WebSocket Origin header against host and allowed origins to prevent CSWSH."""
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        origin_netloc = parsed.netloc.lower()
        origin_host = parsed.hostname.lower() if parsed.hostname else ""
    except Exception:
        return False

    allowed_netlocs = set()
    allowed_hosts = {"localhost", "127.0.0.1", "::1"}
    if host_header:
        allowed_netlocs.add(host_header.lower())
        host_only = host_header.split(":", 1)[0].lower()
        allowed_hosts.add(host_only)
    if settings.public_url:
        try:
            pub = urlsplit(settings.public_url)
            if pub.netloc:
                allowed_netlocs.add(pub.netloc.lower())
            if pub.hostname:
                allowed_hosts.add(pub.hostname.lower())
        except Exception:
            pass

    return origin_netloc in allowed_netlocs or origin_host in allowed_hosts


def is_ws_authenticated(ws: WebSocket, settings: Settings) -> bool:
    """Validate WebSocket connection credentials.

    Checks browser session uid, query param tokens, or API headers.
    """
    if not settings.auth_enabled:
        return True

    # 1. Browser session cookie
    if has_session(ws):
        return True

    # 2. Query param token (?token=... or ?api_key=...)
    token = ws.query_params.get("token") or ws.query_params.get("api_key")
    if token and api_key_matches(token, settings):
        return True

    # 3. Request header token
    presented = _presented_api_key(ws, ws.headers.get("x-api-key"))
    if presented and api_key_matches(presented, settings):
        return True

    return False

