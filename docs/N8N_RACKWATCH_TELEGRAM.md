# RackWatch + Ollama + Telegram (Flujo n8n)

Workflow importable listo para producción: `docs/n8n-rackwatch-telegram-ollama.json`.

---

## 1. Variables de entorno en el contenedor n8n (CasaOS / Docker)

Configúralas en el stack o contenedor de n8n (no las guardes en texto plano dentro del workflow):

```env
RACKWATCH_URL=http://10.13.58.100:8180
RACKWATCH_API_TOKEN=<tu_RACKWATCH_API_TOKEN>
OLLAMA_URL=http://10.13.58.50:11434
OLLAMA_MODEL=qwen2.5:3b
TELEGRAM_BOT_TOKEN=<token_de_BotFather>
TELEGRAM_CHAT_ID=<tu_chat_id_autorizado>
```

> **Nota sobre el modelo de Ollama:** En `10.13.58.50:11434` los modelos disponibles verificados son `qwen2.5:3b` y `qwen2.5:3b-instruct` (o un modelfile custom `RackWatchBot`). El workflow usa por defecto `qwen2.5:3b`.

---

## 2. Importación y Activación en n8n

1. En n8n, ve a **Workflows** → **Import from File** y selecciona `docs/n8n-rackwatch-telegram-ollama.json`.
2. En el nodo **Telegram · Chat**, abre la configuración y selecciona tu credencial de Telegram Bot (creada con el token de BotFather).
3. Ambos paths de webhook están incluidos y activos para compatibilidad inmediata:
   - `/webhook/rackwatch-alert`
   - `/webhook/rackwatch-diagnose` (el configurado actualmente en RackWatch en CasaOS).
4. Guarda el flujo y haz clic en **Activate** (toggle verde).
5. En RackWatch (Ajustes o variable `N8N_WEBHOOK_URL`), asegúrate de apuntar a `http://10.13.58.100:5678/webhook/rackwatch-diagnose` (o `rackwatch-alert`).

---

## 3. Capacidades del Flujo

### 🚨 Alertas automáticas (CPU / RAM alta y contenedores)
- Cuando RackWatch detecta uso excesivo de **CPU** o **RAM** (o contenedores caídos):
  - Recibe la alerta vía webhook.
  - Consulta el snapshot actual de métricas de RackWatch.
  - Ordena e identifica automáticamente el **Top 5 de contenedores con mayor consumo de CPU y RAM**.
  - Si es una alerta de contenedor, recopila los últimos logs.
  - Consulta a Ollama con la evidencia estructurada para un diagnóstico conciso.
  - Envía a Telegram un mensaje enriquecido en HTML con:
    - Estado de severidad (`🔴 CRITICAL` o `⚠️ WARNING`)
    - Host y métricas afectadas
    - Lista de **Top Contenedores por CPU / RAM** (con sus % y MB/GB consumidos)
    - Diagnóstico de la IA con acciones seguras sugeridas
    - Fingerprint único para rastreo

### 💬 Interacción bidireccional por Telegram (Chat)
Al escribirle directamente a tu bot de Telegram:
- `/status` o `/estado`: Envía un informe instantáneo del homelab:
  - CPU, RAM (usada/total) y Disco del host.
  - Load average y Uptime.
  - Conteo de contenedores activos y caídos.
  - Top procesos/contenedores consumidores de CPU y memoria.
  - Estado y salud de pools ZFS.
  - Resumen de alertas recientes.
- `/cpu`: Desglose detallado de carga de CPU del host y lista de contenedores ordenados por CPU.
- `/ram` o `/memoria`: Desglose de uso de memoria física y lista de contenedores con más MB consumidos.
- `/alertas`: Lista las últimas alertas activas y recientes registradas en RackWatch.
- `/start` o `/ayuda`: Muestra el menú de comandos disponibles.
- **Consultas en lenguaje natural:** (ejemplo: *"¿por qué la CPU está al 90%?"*, *"diagnostica plex"*). El bot consulta el snapshot en tiempo real y pide a Ollama un diagnóstico del estado del homelab.

---

## 4. Pruebas de conectividad desde CasaOS / Docker

Desde el servidor CasaOS o dentro del contenedor de n8n, valida la red:

```sh
# Verificar acceso a Ollama
curl -fsS http://10.13.58.50:11434/api/tags | jq .

# Verificar acceso al API de RackWatch
curl -fsS http://10.13.58.100:8180/api/v1/health -H "X-API-Key: $RACKWATCH_API_TOKEN" | jq .

# Enviar una alerta de prueba desde RackWatch
curl -X POST http://10.13.58.100:8180/api/v1/alerts/test \
  -H "X-API-Key: $RACKWATCH_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"channel": "n8n", "message": "Prueba de alerta n8n + Telegram"}'
```
