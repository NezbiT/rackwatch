# Architecture

RackWatch is a single FastAPI process plus three companion containers (Prometheus, Grafana, exporters). There is no message bus required. The collector loop is the source of truth for the UI.

```
                    ┌────────────┐
  Browser  ─HTTP──► │  FastAPI   │
           ─WS /ws─►│  Jinja/HTMX│
                    └─────┬──────┘
                          │ every 3s
                    ┌─────▼──────┐
                    │ Collector  │
                    └─┬──┬──┬──┬─┘
          Prometheus  │  │  │  │  Docker SDK
          HTTP API    │  │  │  │  /var/run/docker.sock
                      │  │  │  │
            node-exp ─┘  │  │  └─ cAdvisor
            zpool/textfile┤
                          │
                 HA REST + MQTT
                          │
              Telegram / WhatsApp / n8n (alerts + chat proxy)
```

## Tick (one collector loop)

Implemented in `app/services/collector.py`:

1. Reload SQLite setting overrides (`settings_store.merged`).
2. `GET {prometheus}/-/ready` and PromQL for host + cAdvisor usage.
3. `docker.containers.list(all=True)` merged with cAdvisor CPU/RAM.
4. ZFS via `zpool list` or PromQL `zpool_health_info`.
5. Home Assistant `GET /api/states` (optional).
6. If Prometheus is empty → `psutil` local host card (`source=local`).
7. Restarter evaluates failed containers.
8. Alerter evaluates thresholds, writes `alerts`, fans out webhooks.
9. Push summary to HA sensors and MQTT.
10. `Hub.publish` → every WebSocket client, with that client's filters.

A tick must finish well under `refresh_seconds`. HTTP timeouts are 2s (Prometheus) and 4s (HA) so a sick dependency cannot stall the live LED.

## Processes and state

| Piece | Process | State |
|---|---|---|
| FastAPI + collector | one uvicorn worker | in-memory Hub snapshot |
| Settings / alerts / restarts | SQLite `/data/rackwatch.db` | durable |
| Metrics history | Prometheus TSDB | 15 days default |
| Dashboards | Grafana provisioning | files in git |
| MQTT | optional broker | last-will `offline` |

Do **not** run multiple uvicorn workers against one SQLite file and one Hub. Compose uses a single worker. SaaS will move durable state to Postgres and the Hub to Redis pub/sub. See [SAAS.md](SAAS.md).

## Status model

Every visual object carries `ok | warning | error | unknown`:

- Host: worst of CPU / RAM / disk vs thresholds
- Container: `exited`/`unhealthy` → error; `restarting`/`starting` → warning
- ZFS: `ONLINE` ok, `DEGRADED` warning, `FAULTED`/`UNAVAIL` error
- HA entity: `unavailable` error; numeric sensors reuse the percent helper

The UI always pairs color with a text pill. Filters compare against these same strings.

## Why Jinja + HTMX instead of a SPA

The first paint is server-rendered from `hub.latest`, so a slow phone still sees cards before the socket opens. HTMX is used only for **actions** (restart, save settings). The live numbers travel over WebSocket JSON — cheaper than swapping HTML 20 times a minute.

## Failure modes

| Dependency down | What the user sees |
|---|---|
| Prometheus | Banner + local psutil host + Docker list without cAdvisor CPU |
| Docker socket | Empty container table + banner, host gauges still work |
| Home Assistant | HA card explains how to connect; rest of the UI is unchanged |
| MQTT | `mqtt_ok=false` in the snapshot; REST HA still works |
| Grafana | Graphs page iframe is blank; live dashboard is independent |

## File responsibilities

| Path | Responsibility |
|---|---|
| `app/main.py` | lifespan, middleware, `/metrics` |
| `app/config.py` | env schema |
| `app/database.py` | engine, `init_db` |
| `app/models.py` | ORM only |
| `app/schemas.py` | public contracts |
| `app/security.py` | session + API token |
| `app/services/collector.py` | tick orchestration |
| `app/services/hub.py` | WS fan-out + filters |
| `app/services/prometheus.py` | PromQL |
| `app/services/docker_ctl.py` | list + start/stop/restart |
| `app/services/n8n_chat.py` | Chat Trigger proxy |
| `app/services/zfs.py` | pool health |
| `app/services/restarter.py` | loop protection |
| `app/services/alerter.py` | outbound channels |
| `app/services/homeassistant.py` | REST pull/push |
| `app/services/mqtt_bridge.py` | discovery + snapshot |
| `app/routers/pages.py` | HTML |
| `app/routers/api.py` | `/api/v1` |
| `app/routers/webhooks.py` | inbound automation |
| `app/routers/ws.py` | `/ws` |
