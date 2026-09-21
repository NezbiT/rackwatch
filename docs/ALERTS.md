# Alerts

RackWatch evaluates thresholds every collector tick and fans a **single JSON envelope** out to every channel you configured. The same envelope is what n8n, a future SaaS subscriber, or HA MQTT should parse.

```json
{
  "source": "rackwatch",
  "instance": "homelab",
  "severity": "critical",
  "title": "plex is down",
  "message": "status=exited health=n/a",
  "host": "homelab",
  "service": "plex",
  "fingerprint": "a1b2c3d4e5f6a7b8c9d0",
  "url": "http://192.168.1.10:8080/alerts",
  "ts": 1710000000
}
```

`fingerprint` is a stable hash of `source|host|service|title`. The same fingerprint is silent for `ALERT_COOLDOWN_SECONDS` (default 15 minutes) so a stuck plex does not spam you.

`ALERT_MIN_SEVERITY` (`info` | `warning` | `critical`) is the floor that leaves the box. The Alerts page still stores what fired.

Every attempt is written to `webhook_deliveries` (channel, status code, truncated body) for debugging.

---

## When an alert fires

| Condition | Severity |
|---|---|
| CPU / RAM / disk ≥ warn threshold | warning |
| CPU / RAM / disk ≥ crit threshold | critical |
| Container exited / dead / unhealthy | critical |
| Container restarting / starting / paused | warning |
| ZFS DEGRADED | warning |
| ZFS FAULTED / UNAVAIL | critical |
| Prometheus unreachable | warning |
| Inbound `/api/v1/hooks/alert` | as posted |

---

## Telegram

1. Talk to [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. Start a chat with the bot (or add it to a group).
3. Get the chat id (`@userinfobot`, or hit `getUpdates` after messaging the bot).
4. Set:

```env
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=987654321
```

5. Settings → **Test telegram**.

RackWatch calls `https://api.telegram.org/bot<token>/sendMessage`.

---

## WhatsApp

Two supported paths.

### A. CallMeBot (zero-cost homelab)

Follow [CallMeBot WhatsApp](https://www.callmebot.com/blog/free-api-whatsapp-messages/) to link your number and receive an apikey.

```env
WHATSAPP_PHONE=34600111222
WHATSAPP_APIKEY=123456
```

### B. Webhook (n8n, Twilio, Meta Cloud API)

```env
WHATSAPP_WEBHOOK_URL=https://n8n.example/webhook/whatsapp
```

RackWatch POSTs `{ "text", "title", "severity" }`. Build the official WhatsApp send in n8n / Twilio so this repo never holds a Meta app secret.

If both are set, the webhook wins.

---

## n8n

1. n8n → new workflow → **Webhook** node (POST).
2. Copy the production URL.

```env
N8N_WEBHOOK_URL=https://n8n.example/webhook/rackwatch
```

3. Add a Switch on `severity`, then Telegram / Discord / email / HA as you like.
4. Settings → **Test n8n**.

The node receives the envelope above. Do not depend on extra fields.

Chat widget (separate URL): [N8N.md](N8N.md).

---

## Generic webhook

```env
GENERIC_WEBHOOK_URL=https://example.com/hooks/rackwatch
```

Same JSON POST. Use this for Slack incoming webhooks **only if** you transform the body (Slack wants `{"text": "..."}`). Prefer n8n as the adapter.

---

## MQTT Broker

- MQTT topic `{MQTT_BASE_TOPIC}/alerts`
- Publish alert envelopes to external MQTT subscribers.

---

## Inbound (the other way)

Create an alert from anywhere:

```bash
curl -X POST http://127.0.0.1:8080/api/v1/hooks/alert \
  -H "X-API-Key: $RACKWATCH_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"UPS on battery","severity":"warning","source":"nut"}'
```

That alert is stored **and** fanned out to every outbound channel.

---

## Testing without leaving the UI

Settings page → **Test telegram / whatsapp / n8n / generic / all**.

The button hits `POST /api/v1/alerts/test` using your browser session. Delivered channels are listed in the toast and on the Alerts page (`source=test`).
