"""RackWatch ASGI entrypoint.

Lifespan starts the collector, MQTT bridge, and SQLite schema.
HTTP routers: pages (Jinja), /api/v1, inbound webhooks, /ws.

Run locally:
    uvicorn app.main:app --reload --port 8080

Prometheus scrapes GET /metrics (process + custom gauges).
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest
from starlette.middleware.sessions import SessionMiddleware

from app import __app_name__, __version__
from app.config import get_settings
from app.database import init_db
from app.routers import api, pages, webhooks, ws
from app.services.alerter import Alerter
from app.services.collector import Collector
from app.services.docker_ctl import DockerControl
from app.services.homeassistant import HomeAssistant
from app.services.glances import GlancesClient
from app.services.hub import Hub
from app.services.mqtt_bridge import MqttBridge
from app.services.n8n_chat import N8nChat
from app.services.prometheus import PrometheusClient
from app.services.restarter import Restarter
from app.services.zfs import ZfsCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("rackwatch")

UP = Gauge("rackwatch_up", "RackWatch process is up")
OVERALL = Gauge("rackwatch_overall", "0=ok 1=warning 2=error")
CONTAINERS = Gauge("rackwatch_containers", "Tracked containers", ["severity"])
CPU = Gauge("rackwatch_cpu_percent", "Average CPU percent")
RAM = Gauge("rackwatch_ram_percent", "Average RAM percent")
DISK = Gauge("rackwatch_disk_percent", "Average disk percent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db()

    hub = Hub()
    prom = PrometheusClient(settings)
    docker = DockerControl(settings)
    zfs = ZfsCollector(prom)
    restarter = Restarter(settings, docker)
    ha = HomeAssistant(settings)
    mqtt = MqttBridge(settings)
    alerter = Alerter(settings, ha=ha, mqtt=mqtt)
    n8n_chat = N8nChat()
    glances = GlancesClient(settings)
    collector = Collector(
        hub=hub,
        prom=prom,
        docker=docker,
        zfs=zfs,
        restarter=restarter,
        alerter=alerter,
        ha=ha,
        mqtt=mqtt,
        glances=glances,
    )

    app.state.settings = settings
    app.state.hub = hub
    app.state.prom = prom
    app.state.docker = docker
    app.state.alerter = alerter
    app.state.n8n_chat = n8n_chat
    app.state.glances = glances
    app.state.ha = ha
    app.state.mqtt = mqtt
    app.state.collector = collector
    app.state.started_at = time.time()

    mqtt.start()
    collector.start()
    UP.set(1)
    log.info("RackWatch %s ready on :%s", __version__, settings.port)
    try:
        yield
    finally:
        UP.set(0)
        await collector.stop()
        mqtt.stop()
        docker.close()
        await prom.close()
        await ha.close()
        await alerter.close()
        await n8n_chat.close()
        await glances.close()
        log.info("RackWatch stopped")


settings = get_settings()
app = FastAPI(
    title=__app_name__,
    version=__version__,
    description="Self-hosted homelab monitor for CasaOS, Proxmox, and Docker.",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_dev else None,
    redoc_url=None,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 24 * 14,
)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(pages.router)
app.include_router(api.router)
app.include_router(webhooks.router)
app.include_router(ws.router)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    snap = request.app.state.hub.latest
    if snap and snap.summary:
        mapping = {"ok": 0, "warning": 1, "error": 2}
        OVERALL.set(mapping.get(str(snap.summary.get("overall")), 1))
        if snap.summary.get("cpu") is not None:
            CPU.set(snap.summary["cpu"])
        if snap.summary.get("ram") is not None:
            RAM.set(snap.summary["ram"])
        if snap.summary.get("disk") is not None:
            DISK.set(snap.summary["disk"])
        CONTAINERS.labels(severity="ok").set(
            snap.summary.get("containers_total", 0)
            - snap.summary.get("containers_down", 0)
            - snap.summary.get("containers_warn", 0)
        )
        CONTAINERS.labels(severity="warning").set(snap.summary.get("containers_warn", 0))
        CONTAINERS.labels(severity="error").set(snap.summary.get("containers_down", 0))
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if exc.headers and exc.headers.get("X-Redirect"):
        return RedirectResponse(exc.headers["X-Redirect"], status_code=303)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Internal error"}, status_code=500)
