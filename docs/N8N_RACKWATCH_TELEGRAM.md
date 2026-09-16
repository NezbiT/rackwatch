# RackWatch + Ollama + Telegram

Workflow importable: `docs/n8n-rackwatch-telegram-ollama.json`.

## Variables de entorno de n8n

Configúralas en el contenedor/stack de n8n. No las guardes dentro del JSON:

```env
RACKWATCH_URL=http://10.13.58.100:8180
RACKWATCH_API_TOKEN=<el mismo RACKWATCH_API_TOKEN>
OLLAMA_URL=http://10.13.58.50:11434
OLLAMA_MODEL=RackWatchBot
TELEGRAM_BOT_TOKEN=<token de BotFather>
TELEGRAM_CHAT_ID=<chat id autorizado>
```

Si el modelo tiene otro nombre, cambia `OLLAMA_MODEL` por el nombre exacto de `ollama list`.

## Importación

1. Importa `n8n-rackwatch-telegram-ollama.json` en n8n.
2. En `Telegram · Chat`, selecciona la credencial del bot.
3. Reemplaza `REEMPLAZAR_CREDENTIAL_ID` si n8n no la vincula automáticamente.
4. Guarda y activa el workflow; usa la URL **Production** del nodo `RackWatch Alert`.
5. En RackWatch configura `N8N_WEBHOOK_URL` con esa URL de producción y prueba una alerta.
6. Envía `/start` o cualquier texto al bot de Telegram.

## Qué hace

- Alerta RackWatch: obtiene snapshot y logs, consulta Ollama y envía un diagnóstico HTML a Telegram.
- Chat Telegram: obtiene snapshot y las últimas alertas, consulta Ollama y responde en el mismo chat.
- No ejecuta reinicios ni comandos desde Telegram.
- Conserva el fingerprint de RackWatch en el mensaje de alerta para correlación.

## Prueba de conectividad

Desde el contenedor n8n, verifica que `10.13.58.50:11434` y la URL de RackWatch sean accesibles. El navegador del host no demuestra conectividad desde Docker.

```sh
curl -fsS "$OLLAMA_URL/api/tags"
curl -fsS "$RACKWATCH_URL/api/v1/health" -H "X-API-Key: $RACKWATCH_API_TOKEN"
```

