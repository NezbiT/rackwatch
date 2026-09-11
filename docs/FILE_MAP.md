# File map

Every path in this repository and why it exists. Use this when you onboard a second developer or start the SaaS split.

## Root

| File | Purpose |
|---|---|
| `README.md` | English product + quick start |
| `README.es.md` | Spanish product + quick start |
| `LICENSE` | MIT |
| `.env.example` | Documented env template. Copy to `.env`. |
| `.gitignore` | Secrets, venv, SQLite, volume data |
| `Dockerfile` | Slim Python image, healthcheck on `/healthz` |
| `docker-compose.yml` | App + Prometheus + Grafana + exporters + optional Mosquitto |
| `requirements.txt` | Pinned runtime + pytest |
| `pytest.ini` | asyncio mode, testpaths |

## Application (`app/`)

| File | Purpose |
|---|---|
| `__init__.py` | Version and package name |
| `main.py` | FastAPI app, lifespan, `/metrics`, session cookie |
| `config.py` | Pydantic Settings — single source of env |
| `database.py` | Async engine, `init_db`, session dependency |
| `models.py` | Alert, RestartEvent, SettingOverride, WebhookDelivery |
| `schemas.py` | Public JSON contracts (do not break lightly) |
| `security.py` | Optional login + API token |
| `routers/pages.py` | Jinja pages + HTMX restart + settings POST |
| `routers/api.py` | `/api/v1` JSON |
| `routers/webhooks.py` | Inbound n8n / HA hooks |
| `routers/ws.py` | `/ws` live stream |
| `services/collector.py` | 3s tick that fills the Hub |
| `services/hub.py` | Per-socket filters + broadcast |
| `services/prometheus.py` | PromQL host + cAdvisor usage |
| `services/docker_ctl.py` | List / start / stop / restart with denylist |
| `services/n8n_chat.py` | Same-origin proxy to n8n Chat Trigger |
| `services/zfs.py` | `zpool` + PromQL fallback |
| `services/restarter.py` | Delay, cooldown, hourly cap |
| `services/alerter.py` | Telegram, WhatsApp, n8n, generic, HA, MQTT |
| `services/homeassistant.py` | REST pull, state push, notify |
| `services/mqtt_bridge.py` | Discovery + snapshot + last will |
| `services/local_metrics.py` | psutil fallback when Prom is down |
| `services/settings_store.py` | SQLite overrides allow-list |
| `services/status.py` | Pure status helpers (unit-tested) |
| `templates/*.html` | Screens. `base.html` is the chrome. |
| `templates/partials/` | First-paint fragments JS later replaces |
| `static/css/app.css` | Aurora skin on top of Pico |
| `static/js/app.js` | WebSocket client, filters, toasts, parallax |
| `static/js/n8n-chat.js` | Official `@n8n/chat` widget |
| `static/img/` | Logo + favicon (rack LEDs) |

## Observability stack

| File | Purpose |
|---|---|
| `prometheus/prometheus.yml` | Scrape jobs |
| `prometheus/alerts.yml` | Optional Prom-native rules |
| `grafana/grafana.ini` | Embed + anonymous Viewer |
| `grafana/provisioning/datasources/datasource.yml` | Prometheus datasource |
| `grafana/provisioning/dashboards/dashboards.yml` | Load JSON from disk |
| `grafana/provisioning/dashboards/json/rackwatch-overview.json` | Default dashboard (UID `rackwatch-overview`) |
| `mosquitto/mosquitto.conf` | Dev broker (compose profile `mqtt`) |
| `scripts/zfs-textfile.sh` | Host cron → node-exporter textfile |
| `data/textfile/` | Drop-in directory for that textfile |

## Tests

| File | Purpose |
|---|---|
| `tests/conftest.py` | Isolated SQLite + TestClient with lifespan |
| `tests/test_health.py` | Pages, `/healthz`, `/metrics` |
| `tests/test_filters.py` | Hub filters + status helpers |
| `tests/test_alerter.py` | Fingerprint + severity gate |

## Docs

| File | Purpose |
|---|---|
| `docs/ARCHITECTURE.md` | Collector loop and failure modes |
| `docs/API.md` | REST + WS contract |
| `docs/INSTALL.md` | CasaOS, Proxmox, Unraid, proxy |
| `docs/HOME_ASSISTANT.md` | REST, notify, MQTT discovery |
| `docs/ALERTS.md` | Telegram / WhatsApp / n8n setup |
| `docs/N8N.md` | Alert webhook + chat widget + operator tools |
| `docs/COMPARE.md` | RackWatch vs Netdata / Grafana / Uptime Kuma / Dashy |
| `docs/CONFIGURATION.md` | Every env var |
| `docs/SECURITY.md` | Socket, tokens, what not to expose |
| `docs/SAAS.md` | Multi-tenant / hosted roadmap |
| `docs/FILE_MAP.md` | This file |
