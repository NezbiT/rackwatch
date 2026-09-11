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
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
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
    return secrets.token_urlsafe(24)
