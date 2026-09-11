"""Server-rendered pages (Jinja2 + HTMX fragments).

First paint is SSR from `hub.latest` so the dashboard is useful
before the WebSocket connects. HTMX swaps fragments for restarts,
filter chips, and settings saves.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app import __version__
from app.config import Settings, get_settings
from app.i18n import (
    COOKIE_LANG,
    COOKIE_MAX_AGE,
    COOKIE_THEME,
    LANGS,
    THEMES,
    catalog,
    resolve_lang,
    resolve_theme,
    safe_next,
    translate,
)
from app.security import is_signed_in, require_session, verify_login
from app.services import settings_store
from app.services.alerter import recent_alerts
from app.services.restarter import recent_restarts

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")


def _ctx(request: Request, settings: Settings, **extra: object) -> dict:
    hub = getattr(request.app.state, "hub", None)
    latest = getattr(hub, "latest", None) if hub else None
    lang = resolve_lang(request)
    theme = resolve_theme(request)

    def t(key: str, **kwargs: object) -> str:
        return translate(lang, key, **kwargs)

    here = request.url.path
    if request.url.query:
        here = f"{here}?{request.url.query}"
    n8n_chat = bool((getattr(settings, "n8n_chat_webhook_url", "") or "").strip())
    return {
        "request": request,
        "settings": settings,
        "version": __version__,
        "signed_in": is_signed_in(request, settings),
        "auth_enabled": settings.auth_enabled,
        "snapshot": latest,
        "nav": extra.pop("nav", ""),
        "lang": lang,
        "theme": theme,
        "t": t,
        "here": here,
        "n8n_chat": n8n_chat,
        "i18n_json": json.dumps(catalog(lang), ensure_ascii=False),
        **extra,
    }


def _set_pref_cookies(response: Response, *, lang: str | None, theme: str | None) -> None:
    cookie_kw = {
        "max_age": COOKIE_MAX_AGE,
        "httponly": False,
        "samesite": "lax",
        "path": "/",
    }
    if lang in LANGS:
        response.set_cookie(COOKIE_LANG, lang, **cookie_kw)
    if theme in THEMES:
        response.set_cookie(COOKIE_THEME, theme, **cookie_kw)


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    next: str = "/",
):
    if not settings.auth_enabled or is_signed_in(request, settings):
        return RedirectResponse(next or "/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        _ctx(request, settings, nav="login", error="", next=next),
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
):
    if verify_login(username.strip(), password, settings):
        request.session["uid"] = username.strip()
        return RedirectResponse(next or "/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        _ctx(
            request,
            settings,
            nav="login",
            error=translate(resolve_lang(request), "login.error"),
            next=next,
        ),
        status_code=401,
    )


@router.get("/prefs")
async def set_prefs(
    request: Request,
    lang: str | None = None,
    theme: str | None = None,
    next: str = "/",
):
    """Set language / theme cookies and stay on the current page."""
    dest = safe_next(next or request.headers.get("referer"), "/")
    response = RedirectResponse(dest, status_code=303)
    _set_pref_cookies(response, lang=lang, theme=theme)
    return response


@router.post("/prefs")
async def set_prefs_post(request: Request):
    """JSON/form POST for the theme toggle (no full navigation)."""
    lang = None
    theme = None
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        body = await request.json()
        lang = str(body.get("lang") or "") or None
        theme = str(body.get("theme") or "") or None
    else:
        form = await request.form()
        lang = str(form.get("lang") or "") or None
        theme = str(form.get("theme") or "") or None
    response = Response(status_code=204)
    _set_pref_cookies(response, lang=lang, theme=theme)
    return response


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    _: Annotated[None, Depends(require_session)],
):
    live = await settings_store.merged()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _ctx(request, live, nav="dashboard"),
    )


@router.get("/services", response_class=HTMLResponse)
async def services_page(
    request: Request,
    _: Annotated[None, Depends(require_session)],
):
    live = await settings_store.merged()
    restarts = await recent_restarts(30)
    return templates.TemplateResponse(
        request,
        "services.html",
        _ctx(request, live, nav="services", restarts=restarts),
    )


@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(
    request: Request,
    _: Annotated[None, Depends(require_session)],
    range: str = "24h",
):
    live = await settings_store.merged()
    alerts = await recent_alerts(limit=100, time_range=range)
    return templates.TemplateResponse(
        request,
        "alerts.html",
        _ctx(request, live, nav="alerts", alerts=alerts, time_range=range),
    )


@router.get("/graphs", response_class=HTMLResponse)
async def graphs_page(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[None, Depends(require_session)],
    panel: str = "overview",
    range: str = "1h",
):
    live = await settings_store.merged()
    return templates.TemplateResponse(
        request,
        "grafana.html",
        _ctx(
            request,
            live,
            nav="graphs",
            panel=panel,
            time_range=range,
        ),
    )


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    _: Annotated[None, Depends(require_session)],
):
    live = await settings_store.merged()
    return templates.TemplateResponse(
        request,
        "chat.html",
        _ctx(request, live, nav="chat"),
    )


@router.get("/home-assistant", response_class=HTMLResponse)
async def ha_page(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[None, Depends(require_session)],
):
    live = await settings_store.merged()
    return templates.TemplateResponse(
        request,
        "homeassistant.html",
        _ctx(request, live, nav="ha"),
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[None, Depends(require_session)],
    saved: int = 0,
):
    live = await settings_store.merged()
    return templates.TemplateResponse(
        request,
        "settings.html",
        _ctx(request, live, nav="settings", saved=bool(saved)),
    )


@router.post("/services/{name}/restart", response_class=HTMLResponse)
async def restart_from_ui(
    name: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[None, Depends(require_session)],
    force: int = 0,
):
    """HTMX endpoint: restart a container and return a toast fragment."""
    docker = request.app.state.docker
    ok, detail = await docker.restart(name, force=bool(force))
    from datetime import datetime, timezone

    from app.database import async_session
    from app.models import RestartEvent

    async with async_session() as session:
        session.add(
            RestartEvent(
                created_at=datetime.now(timezone.utc),
                container=name,
                reason="manual-ui",
                automatic=False,
                success=ok,
                error="" if ok else detail,
            )
        )
        await session.commit()
    lang = resolve_lang(request)
    return templates.TemplateResponse(
        request,
        "partials/toast.html",
        _ctx(
            request,
            settings,
            toast_ok=ok,
            toast_title=translate(lang, "toast.restarted" if ok else "toast.restart_fail", name=name),
            toast_body=detail if not ok else translate(lang, "toast.restart_ok"),
        ),
    )


@router.post("/alerts/test", response_class=HTMLResponse)
async def test_alert_from_ui(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[None, Depends(require_session)],
    channel: Annotated[str, Form()] = "all",
    message: Annotated[str, Form()] = "",
):
    """HTMX/form variant of POST /api/v1/alerts/test — uses the browser session, not the API token."""
    lang = resolve_lang(request)
    alerter = request.app.state.alerter
    channels = None if channel == "all" else [channel]
    alert = await alerter.fire(
        title="RackWatch test",
        message=message or "Settings",
        severity="info",
        source="test",
        host=settings.instance_name,
        service="rackwatch",
        channels=channels,
    )
    delivered = alert.delivered_to or translate(lang, "toast.none")
    return templates.TemplateResponse(
        request,
        "partials/toast.html",
        _ctx(
            request,
            settings,
            toast_ok=True,
            toast_title=translate(lang, "toast.test_sent"),
            toast_body=translate(lang, "toast.delivered", channels=delivered),
        ),
    )


@router.post("/settings", response_class=HTMLResponse)
async def settings_save(
    request: Request,
    _: Annotated[None, Depends(require_session)],
):
    form = await request.form()
    values: dict = {}
    bools = {"auto_restart_enabled"}
    for key, kind in settings_store.WRITABLE.items():
        if key in bools:
            values[key] = key in form
            continue
        if key not in form:
            continue
        raw = str(form.get(key) or "")
        values[key] = raw
    await settings_store.save_overrides(values)
    return RedirectResponse("/settings?saved=1", status_code=303)
