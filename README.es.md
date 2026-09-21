# RackWatch (ES)

La documentación principal (instalación, comparativa, secretos OpenAI/n8n) está en **[README.md](README.md)**.

- Comparativa vs Netdata / Grafana / Uptime Kuma / Dashy: [docs/COMPARE.md](docs/COMPARE.md)
- n8n (alertas + chat + API): [docs/N8N.md](docs/N8N.md)
- Instalación detallada: [docs/INSTALL.md](docs/INSTALL.md)

**Resumen:** RackWatch es el panel para **ver y actuar** en el homelab (Docker, ZFS, alertas). Grafana/Netdata hacen histórico; Uptime Kuma sondea URLs; Dashy es el launcher. OpenAI conviene configurarlo en **Credentials de n8n**; las claves de RackWatch van solo en `.env` (nunca en Git).

---

## Qué incluye

| Función | Cómo funciona |
|---|---|
| Dashboard en vivo | Snapshot WebSocket cada **3 segundos** |
| Métricas del host | Prometheus + node-exporter, con fallback psutil |
| Contenedores | Socket de Docker + uso de cAdvisor |
| ZFS | `zpool list` o textfile de node-exporter |
| Filtros | Host, servicio, severidad, estado, rango de tiempo |
| Auto-reinicio | Delay + cooldown + tope por hora + denylist |
| Alertas | Telegram, WhatsApp, n8n, webhook, MQTT |
| n8n | Webhook de alertas + widget Chat Trigger + API de operador |
| Gráficas | Grafana embebido en la UI |
| Plugin para Omarchy | Widget en barra de estado y panel de control (`nezbit.rackwatch`) |
| Auth | Login opcional + token de API para webhooks |

Sin Rust en este MVP. Stack: **Python FastAPI**, **Jinja2 + HTMX + Pico.css**, **Prometheus**, **Grafana**, **Docker Compose**.

---

## Arranque rápido (Docker)

```bash
cd rackwatch
cp .env.example .env
# Edita .env — como mínimo RACKWATCH_SECRET_KEY y RACKWATCH_API_TOKEN

docker compose up -d --build
```

Abre:

- **RackWatch** → http://localhost:8080
- **Prometheus** → http://localhost:9090
- **Grafana** → http://localhost:3001  (admin / `changeme`)

En CasaOS u otra máquina, cambia `localhost` por la IP del host y pon esa IP en `GRAFANA_PUBLIC_URL` y `RACKWATCH_PUBLIC_URL` para que los iframes y los enlaces de alerta funcionen.

---

## Instalar en CasaOS

1. CasaOS → **App store** → **Instalar app personalizada** (o **Compose**).
2. Pega el `docker-compose.yml` o apunta a esta carpeta.
3. Asegúrate de que las carpetas `prometheus/`, `grafana/` y `mosquitto/` viajan junto al compose.
4. Carga las variables de `.env.example`.
5. Publica el puerto **8080**. Abre `http://<ip-casaos>:8080`.

Proxmox y más detalle: [docs/INSTALL.md](docs/INSTALL.md).

---

## Widget de escritorio para Omarchy (`nezbit.rackwatch`)

Para monitorizar métricas del host, ver estado de contenedores, silenciar alertas y reiniciar servicios directamente desde la barra de estado de Linux en **Omarchy**:

### Instalación mediante el gestor de plugins de Omarchy

```bash
omarchy plugin add https://github.com/NezbiT/omarchy-rackwatch.git --enable
```

### Instalación manual

```bash
git clone https://github.com/NezbiT/omarchy-rackwatch.git ~/.config/omarchy/plugins/nezbit.rackwatch
omarchy plugin validate ~/.config/omarchy/plugins/nezbit.rackwatch
omarchy plugin enable nezbit.rackwatch right
```

Repositorio y documentación del plugin: [NezbiT/omarchy-rackwatch](https://github.com/NezbiT/omarchy-rackwatch).

---

## Contrato del webhook de alerta

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

Pon `N8N_WEBHOOK_URL` en un nodo webhook de n8n. Pon `N8N_CHAT_WEBHOOK_URL` en un Chat Trigger (Embedded Chat); la UI lo proxifica en `/api/v1/chat/n8n`. Las automatizaciones hacen POST a `/api/v1/hooks/alert` o `/api/v1/hooks/container` con `X-API-Key`. Guía: [docs/N8N.md](docs/N8N.md).

---

## Verlo en local (esta laptop)

Hace falta **Python 3.12** (3.14 no sirve con las dependencias actuales):

```bash
# una vez
mise install python@3.12   # o cualquier Python 3.12
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# cada vez
./scripts/run-local.sh
```

Abre http://127.0.0.1:8080 — CPU/RAM/disco salen con psutil. Sin Docker en la laptop no hay lista de contenedores.

## Instalar en CasaOS / Proxmox

En el VM de CasaOS los puertos 8080 y 3001 ya están ocupados. Overlay:

```bash
# en el host CasaOS, con .env apuntando a su IP
# RACKWATCH_PUBLIC_URL=http://10.13.58.100:8180
# GRAFANA_PUBLIC_URL=http://10.13.58.100:3002
docker compose -f docker-compose.yml -f docker-compose.casaos.yml up -d --build
```

RackWatch → http://10.13.58.100:8180  
Grafana → http://10.13.58.100:3002

Detalle: [docs/INSTALL.md](docs/INSTALL.md).

---

## Mapa del proyecto

Cada archivo de código lleva un docstring de módulo explicando para qué existe y cómo encaja. Documentación larga:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/API.md](docs/API.md)
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md)
- [docs/SECURITY.md](docs/SECURITY.md)
- [SECURITY_BUG_PERFORMANCE_ASSESSMENT.md](SECURITY_BUG_PERFORMANCE_ASSESSMENT.md) — Auditoría técnica de seguridad y rendimiento
- [docs/SAAS.md](docs/SAAS.md) — hoja de ruta multi-tenant / SaaS online
- [NezbiT/omarchy-rackwatch](https://github.com/NezbiT/omarchy-rackwatch) — Plugin para barra de estado en Omarchy

---

## Licencia

MIT. Ver [LICENSE](LICENSE).
