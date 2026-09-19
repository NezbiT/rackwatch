<p align="center">
  <img src="app/static/img/logo.svg" width="96" height="96" alt="RackWatch Logo">
</p>

# RackWatch

**Monitor y panel de control self-hosted** para **CasaOS**, **Proxmox** y **Docker**.

Dashboard en vivo (CPU / RAM / disco, contenedores, ZFS, Home Assistant). Los servicios caídos pueden reiniciarse solos. Las alertas salen por Telegram, WhatsApp, **n8n**, webhook, MQTT y notify de HA. Incluye **chat con n8n** (y agentes OpenAI detrás de n8n) y una API de operador para automatizar el lab.

> **English docs:** [docs/](docs/) · Comparativa: [docs/COMPARE.md](docs/COMPARE.md) · n8n: [docs/N8N.md](docs/N8N.md)

---

## Descripción

RackWatch es la **sala de máquinas** del homelab:

- Ves el estado en tiempo real (~3 s por WebSocket).
- Actúas (reiniciar / arrancar / parar contenedores).
- Alertas salen del servidor hacia tus canales.
- **n8n** y **OpenAI** (vía n8n o clave en `.env`) pueden leer el snapshot y ejecutar acciones con `X-API-Key`.

No es un launcher de apps (eso es Dashy), ni un comprobador HTTP puro (Uptime Kuma), ni un almacén histórico de métricas (Grafana/Netdata). **Complementa** esas piezas.

---

## Comparativa rápida

| | RackWatch | Netdata | Grafana | Uptime Kuma | Dashy v4 |
|---|---|---|---|---|---|
| Estado live del host | Sí | Excelente | Vía Prom | No | Widgets |
| Contenedores + reinicio | **Sí** | Ver | Ver | No | Enlaces |
| Auto-restart + denylist | **Sí** | No | No | No | No |
| ZFS / HA bridge | Sí | Parcial | Sí | No | No |
| Gráficas históricas | Embed Grafana | Sí | **Especialista** | Uptime | No |
| Checks HTTP/ping | Vía n8n | Sí | Alerting | **Especialista** | Status |
| Homepage de apps | No | No | No | No | **Especialista** |
| Chat / IA / n8n | **Sí** | No | No | No | No |

Detalle: **[docs/COMPARE.md](docs/COMPARE.md)**.

**Stack típico recomendado**

```
Dashy          → portal / bookmarks
Uptime Kuma    → “¿responde la URL pública?”
Netdata/Prom   → métricas finas
Grafana        → histórico (embebido en RackWatch)
RackWatch      → operar + alertar + n8n/OpenAI
```

---

## Funciones

| Función | Detalle |
|---|---|
| Dashboard live | WebSocket cada 3 s (configurable) |
| Host | Prometheus + node-exporter, fallback `psutil` |
| Contenedores | Docker socket + cAdvisor; start / stop / restart |
| Auto-reinicio | Delay, cooldown, tope/hora, denylist / allow-list |
| ZFS | `zpool` o textfile Prometheus |
| Home Assistant | REST entities, sensores `sensor.rackwatch_*`, MQTT discovery, notify |
| Alertas | Telegram, WhatsApp (CallMeBot o webhook), n8n, genérico, HA, MQTT |
| Chat n8n | Widget oficial `@n8n/chat` + proxy `/api/v1/chat/n8n` |
| API operador | Snapshot, alertas, ack, logs, hooks (`/api/v1/hooks/*`) |
| Gráficas | Grafana iframe en `/graphs` |
| i18n | EN / ES · tema dark / light |
| Auth | Login opcional + `RACKWATCH_API_TOKEN` para máquinas |

---

## Instalación rápida (Docker)

```bash
git clone https://github.com/NezbiT/rackwatch.git
cd rackwatch
cp .env.example .env
# Edita .env — como mínimo:
#   RACKWATCH_SECRET_KEY
#   RACKWATCH_API_TOKEN
#   RACKWATCH_PUBLIC_URL=http://TU_IP:8080

docker compose up -d --build
```

Abre:

| Servicio | URL |
|---|---|
| RackWatch | http://localhost:8080 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3001 (admin / `changeme`) |

CasaOS: App personalizada / Compose → pega `docker-compose.yml` y publica **8080**. Guía: [docs/INSTALL.md](docs/INSTALL.md).

### Desarrollo local (sin Compose)

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
./scripts/run-local.sh
```

---

## Dónde van las claves privadas (importante)

**Nunca subas `.env` a Git.** Está en `.gitignore`. Solo se versiona `.env.example` (plantilla vacía).

| Secreto | Dónde ponerlo | Quién lo usa |
|---|---|---|
| `RACKWATCH_SECRET_KEY` | `.env` | Cookie de sesión |
| `RACKWATCH_API_TOKEN` | `.env` | n8n / OpenAI tools / webhooks → `/api/v1` |
| `RACKWATCH_AUTH_USER` / `PASSWORD` | `.env` (opcional) | Login del dashboard |
| `TELEGRAM_BOT_TOKEN` / `CHAT_ID` | `.env` o Settings UI | Alertas |
| `WHATSAPP_*` | `.env` o Settings | Alertas |
| `N8N_WEBHOOK_URL` | `.env` o Settings | Alertas → n8n |
| `N8N_CHAT_WEBHOOK_URL` | `.env` o Settings | Chat Trigger (Embedded) |
| `N8N_CHAT_AUTH_HEADER` | `.env` o Settings | Auth del Chat Trigger |
| `HA_TOKEN` | `.env` o Settings | Home Assistant |
| `MQTT_PASSWORD` | `.env` o Settings | Broker MQTT |
| **`OPENAI_API_KEY`** | **Preferible en n8n Credentials**; opcional en `.env` | Agente LLM |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` | `.env` si RackWatch llama al modelo | OpenAI u compatible |

### Buenas prácticas

1. Genera secretos fuertes:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
2. En CasaOS / Proxmox, monta `.env` o variables del compose; **no** pegues tokens en el README ni en issues.
3. Si usas la UI de Settings, los overrides van a SQLite (`/data/rackwatch.db`); también son secretos locales.
4. Rota cualquier clave que hayas pegado en un chat o captura de pantalla.

---

## Integración n8n

Dos URLs distintas:

| Variable | Dirección | Uso |
|---|---|---|
| `N8N_WEBHOOK_URL` | RackWatch → n8n | Cada alerta (JSON fijo) |
| `N8N_CHAT_WEBHOOK_URL` | Navegador → RackWatch → n8n | Widget de chat (Chat Trigger **Embedded**) |

El navegador **no** habla con n8n a pelo: el proxy `/api/v1/chat/n8n` evita CORS y permite URLs Docker internas (`http://n8n:5678/...`).

Guía paso a paso: **[docs/N8N.md](docs/N8N.md)**.

### Que n8n / el agente controle el lab

En el Agent de n8n, tools HTTP con header:

```http
X-API-Key: <RACKWATCH_API_TOKEN>
```

| Acción | Método | Ruta |
|---|---|---|
| Snapshot | GET | `/api/v1/snapshot` |
| Alertas | GET | `/api/v1/alerts?range=24h` |
| Ack | POST | `/api/v1/alerts/{id}/ack` |
| Start/stop/restart | POST | `/api/v1/hooks/container` |
| Crear alerta | POST | `/api/v1/hooks/alert` |

```json
{ "container": "plex", "action": "restart", "reason": "n8n agent", "force": false }
```

---

## Integración OpenAI

Hay **dos formas** (recomendamos la 1):

### 1. OpenAI dentro de n8n (recomendado)

1. n8n → Credentials → **OpenAI API** → pega `OPENAI_API_KEY` **solo en n8n**.
2. Chat Trigger → Agent / OpenAI node → tools HTTP hacia RackWatch (`X-API-Key`).
3. En RackWatch solo configuras `N8N_CHAT_WEBHOOK_URL`.

Así la clave de OpenAI **no** vive en el contenedor de RackWatch.

### 2. Clave en RackWatch (`.env`)

Si más adelante el propio RackWatch llama al modelo:

```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

Compatible con proxies tipo Azure OpenAI / SpaceXAI / OpenRouter cambiando `OPENAI_BASE_URL`.

---

## Pantallas

```
/              Dashboard live
/services      Contenedores + log de reinicios
/alerts        Historial de alertas
/chat          Chat n8n (fullscreen)
/graphs        Grafana
/home-assistant
/settings      Umbrales, canales, n8n, HA, MQTT
```

---

## API

- OpenAPI: `/docs` si `RACKWATCH_ENV=development`
- Contrato: [docs/API.md](docs/API.md)
- Alertas: [docs/ALERTS.md](docs/ALERTS.md)
- Seguridad: [docs/SECURITY.md](docs/SECURITY.md)

---

## Licencia

MIT — ver [LICENSE](LICENSE).

---

## Español corto

Instala con Docker, rellena `.env` (nunca lo subas), apunta n8n (alertas + chat) y deja la clave de OpenAI en las **Credentials de n8n**. RackWatch es el panel para **ver y actuar** en tu lab; Grafana/Netdata/Kuma/Dashy siguen haciendo lo suyo. Más detalle en [docs/COMPARE](docs/COMPARE.md) y [docs/N8N.md](docs/N8N.md).
