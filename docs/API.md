# HTTP and WebSocket API

Base URL: `http://<host>:8080`

Machine calls send:

```
X-API-Key: <RACKWATCH_API_TOKEN>
```

or `Authorization: Bearer <RACKWATCH_API_TOKEN>`.

A signed-in browser session is also accepted for the same routes. If `RACKWATCH_API_TOKEN` is empty, only a signed-in session can mutate.

OpenAPI is mounted at `/docs` when `RACKWATCH_ENV=development`.

---

## Liveness (no auth)

| Method | Path | Notes |
|---|---|---|
| GET | `/healthz` | Process up. Used by Docker HEALTHCHECK. |
| GET | `/metrics` | Prometheus text format (RackWatch's own gauges). |
| GET | `/api/v1/health` | JSON: version, prometheus/docker/ha/mqtt flags, uptime. |

---

## Snapshots and lists (session or token)

Reads accept a signed-in session **or** `X-API-Key` / `Authorization: Bearer` (n8n). Open-LAN dashboards still work without a token.

### `GET /api/v1/snapshot`

Latest collector tick. Shape: `app.schemas.Snapshot`.

```json
{
  "type": "snapshot",
  "ts": 1710000000.1,
  "instance": "homelab",
  "prometheus_ok": true,
  "docker_ok": true,
  "ha_ok": true,
  "mqtt_ok": false,
  "hosts": [],
  "containers": [],
  "zfs": [],
  "ha_entities": [],
  "alerts": [],
  "summary": { "cpu": 12.4, "ram": 41.0, "disk": 33.2, "overall": "ok" }
}
```

Returns **503** until the first tick finishes (~3s after boot).

### `GET /api/v1/alerts?range=24h&limit=80`

`range`: `15m` | `1h` | `6h` | `24h` | `7d`

### `GET /api/v1/restarts?limit=50`

### `GET /api/v1/containers/{name}/logs?lines=80`

Last N lines of Docker logs for that container (timestamps on). 404 if Docker cannot find it.

### `GET /api/v1/settings`

Operator overrides (thresholds, denylist, webhook URLs). Secret values are `***`.

### `GET /api/v1/ha/entities`

Live HA state list (same objects the dashboard renders).

---

## Mutations (token required)

### `POST /api/v1/containers/{name}/restart?force=false`

```json
{ "reason": "manual" }
```

`force=true` bypasses the denylist. The UI confirm dialog is the only place that should send it.

### `POST /api/v1/containers/{name}/start?force=false`

### `POST /api/v1/containers/{name}/stop?force=false`

Same denylist / allow-list as restart. Body `{ "reason": "n8n" }` is optional.

### `POST /api/v1/alerts/{id}/ack`

Marks the row acknowledged. Does not resolve the underlying condition.

### `POST /api/v1/alerts/test`

```json
{ "channel": "telegram", "message": "hello" }
```

`channel`: `telegram` | `whatsapp` | `n8n` | `generic` | `homeassistant` | `all`

---

## Inbound webhooks

### `POST /api/v1/hooks/alert`

n8n, HA automations, or the future SaaS ingest create a RackWatch alert and fan it out to every configured channel.

```json
{
  "title": "UPS on battery",
  "message": "5 minutes remaining",
  "severity": "warning",
  "source": "homeassistant",
  "host": "lab",
  "service": "ups"
}
```

### `POST /api/v1/hooks/restart`

```json
{ "container": "plex", "reason": "n8n night job", "force": false }
```

### `POST /api/v1/hooks/container`

One node for n8n Switch:

```json
{ "container": "plex", "action": "start", "reason": "n8n", "force": false }
```

`action`: `start` | `stop` | `restart`.

### Chat proxy (browser session, not API token)

The `@n8n/chat` widget posts here. RackWatch forwards to `N8N_CHAT_WEBHOOK_URL`.

- `GET|POST /api/v1/chat/n8n` — pass-through (`action=sendMessage` / `loadPreviousSession`)
- `POST /api/v1/chat/test` — ping the Chat Trigger; used by Settings

n8n workflows that *control* RackWatch should use `X-API-Key` on `/api/v1/*`, not this proxy.

---

## WebSocket `GET /ws`

JSON both ways.

Server → client, every tick (and immediately on connect / filter change):

Same body as `GET /api/v1/snapshot`, plus a `filters` echo.

Client → server:

```json
{ "type": "filter", "host": "", "service": "plex", "severity": "warning", "status": "error", "time_range": "1h" }
```

```json
{ "type": "ping" }
```

Empty strings mean “any”. Filters are **per socket** — two tabs can watch different slices.

Reconnect with backoff is implemented in `app/static/js/app.js`.

---

## Pages (HTML)

| Path | Purpose |
|---|---|
| `/` | Live dashboard |
| `/chat` | n8n chat (fullscreen widget, or setup empty state) |
| `/services` | Containers + restart log |
| `/alerts` | Alert history |
| `/graphs` | Grafana embed |
| `/home-assistant` | HA entity grid |
| `/settings` | Overrides form |
| `/login` `/logout` | Optional session |

`POST /services/{name}/restart` is the HTMX variant of the JSON restart route; it returns `partials/toast.html`.

---

## Compatibility promise

- Additive changes inside `/api/v1` are allowed.
- Renames or type changes require `/api/v2`.
- The alert JSON envelope (`source`, `instance`, `severity`, `title`, `message`, `host`, `service`, `fingerprint`, `url`, `ts`) is frozen for n8n and the SaaS agent.
