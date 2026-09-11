# n8n

RackWatch talks to n8n on **two URLs**. Do not mix them.

| Setting | Direction | Purpose |
|---|---|---|
| `N8N_WEBHOOK_URL` | RackWatch → n8n | Frozen **alert envelope** on every new alert |
| `N8N_CHAT_WEBHOOK_URL` | Browser → RackWatch → n8n | `@n8n/chat` widget (Chat Trigger, Embedded Chat) |

n8n **calls back** into RackWatch with `X-API-Key: <RACKWATCH_API_TOKEN>` on `/api/v1`.

The browser never talks to n8n. The widget posts same-origin to `/api/v1/chat/n8n`, which forwards to the Chat Trigger. That is why a Docker-only URL such as `http://n8n:5678/webhook/...` works here — CORS is not required.

---

## 1. Alert webhook

1. n8n → new workflow → **Webhook** node (POST).
2. Copy the production URL.

```env
N8N_WEBHOOK_URL=https://n8n.example/webhook/rackwatch
```

3. Add a Switch on `severity`, then Telegram / Discord / email as you like.
4. Settings → **Test n8n**.

Envelope: see [ALERTS.md](ALERTS.md). Do not depend on extra fields.

---

## 2. Chat widget

1. n8n → new workflow → **Chat Trigger**.
2. Mode = **Embedded Chat** (not Hosted Chat).
3. Make the chat publicly available / activate the production webhook.
4. Copy the **production Chat URL** into Settings → n8n chat webhook URL (`N8N_CHAT_WEBHOOK_URL`).
5. Optional: Chat Trigger header auth → paste `Authorization: Bearer …` into the auth header field.
6. Settings → **Test chat**. A floating window appears on every RackWatch page; `/chat` is the same widget fullscreen.

Hosted Chat page URLs will not work through the proxy.

Alerts are **not** injected into the n8n transcript (n8n has no API for that). They stay on `/alerts` and still POST to `N8N_WEBHOOK_URL`.

---

## 3. Operator tools for an Agent

Give the Chat Trigger’s Agent HTTP Request tools. Base URL is your RackWatch public URL. Header `X-API-Key`.

| What | Method | Path |
|---|---|---|
| Snapshot | GET | `/api/v1/snapshot` |
| Health | GET | `/api/v1/health` |
| Alerts | GET | `/api/v1/alerts?range=24h` |
| Ack | POST | `/api/v1/alerts/{id}/ack` |
| Settings (non-secrets) | GET | `/api/v1/settings` |
| Logs | GET | `/api/v1/containers/{name}/logs?lines=80` |
| Start / stop / restart | POST | `/api/v1/hooks/container` |

```json
{ "container": "plex", "action": "restart", "reason": "n8n chat", "force": false }
```

`force` is required for denylisted names (`rackwatch`, `prometheus`, `grafana`, …).

Create an alert from n8n:

```
POST /api/v1/hooks/alert
{ "title": "UPS on battery", "severity": "warning", "source": "n8n" }
```

---

## 4. Test without leaving the UI

Settings → **Test n8n** (alert channel) and **Test chat** (Chat Trigger ping).
