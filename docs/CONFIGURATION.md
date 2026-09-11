# Configuration

Two layers, in this order:

1. Environment / `.env` (see `.env.example`) — loaded once at process start.
2. SQLite overrides written by **Settings** — applied every collector tick via `settings_store.merged()`.

UI values win until you delete the row (or the SQLite file). Secrets typed into Settings are stored in plaintext in `/data/rackwatch.db`. That is acceptable on a trusted LAN disk; it is **not** acceptable on a shared SaaS database without encryption. See [SAAS.md](SAAS.md).

---

## App

| Variable | Default | Meaning |
|---|---|---|
| `RACKWATCH_HOST` | `0.0.0.0` | Bind address |
| `RACKWATCH_PORT` | `8080` | Bind port |
| `RACKWATCH_ENV` | `production` | `development` enables `/docs` |
| `RACKWATCH_SECRET_KEY` | insecure default | Signs the session cookie |
| `RACKWATCH_AUTH_USER` | empty | Optional UI login |
| `RACKWATCH_AUTH_PASSWORD` | empty | Optional UI login |
| `RACKWATCH_API_TOKEN` | empty | Webhooks + mutations |
| `RACKWATCH_PUBLIC_URL` | `http://localhost:8080` | Links inside alerts |
| `RACKWATCH_INSTANCE_NAME` | `homelab` | Card title + HA unique_id |
| `RACKWATCH_REFRESH_SECONDS` | `3` | Collector / WS period |

---

## Metrics

| Variable | Default |
|---|---|
| `PROMETHEUS_URL` | `http://prometheus:9090` |
| `GRAFANA_URL` | `http://grafana:3000` |
| `GRAFANA_PUBLIC_URL` | `http://localhost:3001` |
| `GRAFANA_DASHBOARD_UID` | `rackwatch-overview` |
| `DOCKER_HOST` | `unix:///var/run/docker.sock` |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/rackwatch.db` |

Compose overrides `DATABASE_URL` to `/data/rackwatch.db`.

`GRAFANA_PUBLIC_URL` is what the **browser** loads. `grafana:3000` only works inside Docker DNS, so never put that in the iframe.

---

## Thresholds

| Variable | Default |
|---|---|
| `THRESHOLD_CPU_WARN` / `_CRIT` | 85 / 95 |
| `THRESHOLD_RAM_WARN` / `_CRIT` | 85 / 95 |
| `THRESHOLD_DISK_WARN` / `_CRIT` | 80 / 90 |

---

## Auto-restart

| Variable | Default |
|---|---|
| `AUTO_RESTART_ENABLED` | `true` |
| `AUTO_RESTART_DELAY_SECONDS` | `8` |
| `AUTO_RESTART_COOLDOWN_SECONDS` | `120` |
| `AUTO_RESTART_MAX_PER_HOUR` | `3` |
| `AUTO_RESTART_DENYLIST` | `rackwatch,prometheus,grafana,casaos,cadvisor,node-exporter` |
| `AUTO_RESTART_ALLOWLIST` | empty = all except denylist |

A name matches if the fragment appears anywhere in the container name (case-insensitive).

---

## Alert channels

| Variable | Default |
|---|---|
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | empty |
| `WHATSAPP_PHONE` / `WHATSAPP_APIKEY` | empty (CallMeBot) |
| `WHATSAPP_WEBHOOK_URL` | empty (wins over CallMeBot) |
| `N8N_WEBHOOK_URL` | empty |
| `N8N_CHAT_WEBHOOK_URL` | empty (Chat Trigger, Embedded Chat) |
| `N8N_CHAT_AUTH_HEADER` | empty |
| `GENERIC_WEBHOOK_URL` | empty |
| `ALERT_COOLDOWN_SECONDS` | `900` |
| `ALERT_MIN_SEVERITY` | `warning` |

---

## Home Assistant

| Variable | Default |
|---|---|
| `HA_URL` | empty = disabled |
| `HA_TOKEN` | empty |
| `HA_PINNED_ENTITIES` | empty = auto 24 |
| `HA_NOTIFY_SERVICE` | `notify.notify` |
| `MQTT_HOST` | empty = disabled |
| `MQTT_PORT` | `1883` |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | empty |
| `MQTT_BASE_TOPIC` | `rackwatch` |
| `MQTT_HA_DISCOVERY` | `true` |
| `MQTT_HA_DISCOVERY_PREFIX` | `homeassistant` |

---

## Grafana admin

Not read by FastAPI. Used only by compose:

```env
GRAFANA_ADMIN_PASSWORD=changeme
```

---

## Writable from the Settings page

See `WRITABLE` in `app/services/settings_store.py`. Auth credentials and `RACKWATCH_API_TOKEN` are **not** writable from the UI on purpose — change those in `.env` and recreate the container.
