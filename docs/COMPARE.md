# RackWatch vs Netdata · Grafana · Uptime Kuma · Dashy v4

Comparativa orientada a **homelab / CasaOS / Proxmox / Docker**. RackWatch no sustituye a todos: se coloca en el centro operativo (estado + acción + automatización).

## Tabla rápida

| Capacidad | **RackWatch** | Netdata | Grafana | Uptime Kuma | Dashy v4 |
|---|---|---|---|---|---|
| Panel de estado en vivo | Sí (WS ~3s) | Sí (métricas) | Sí (consultas) | Parcial (checks) | Enlaces + widgets |
| CPU / RAM / disco | Sí | Excelente | Excelente (Prom) | No | Widgets limitados |
| Contenedores Docker | Sí + reinicio | Sí (vista) | Vía cAdvisor | No | Enlaces |
| Auto-reinicio con denylist | **Sí** | No | No | No | No |
| ZFS health | Sí | Plugins | Prom/textfile | No | No |
| Home Assistant | REST + MQTT + notify | No nativo | Sí (datasource) | No | Widgets |
| Historial / gráficas profundas | Embed Grafana | Sí | **Especialista** | Sí (uptime) | No |
| Monitor HTTP/TCP/DNS/ping | No (vía n8n) | Sí | Alerting | **Especialista** | Status dots |
| Homepage de apps (launcher) | No | No | No | No | **Especialista** |
| Alertas multi-canal | TG / WA / n8n / HA / MQTT | Sí | Alertmanager | Email/TG/Discord… | No (solo status) |
| API máquina + webhooks | `/api/v1` + hooks | API propia | HTTP API | API | Limitada |
| Chat / automatización IA | **n8n Chat + API operador** | No | No | No | No |
| OpenAI / agentes | Vía n8n (y clave en `.env`) | No | Plugins | No | No |
| Auth | Login opcional + API token | Sí | Sí | Sí | Sí / SSO |
| Stack típico | FastAPI + Prom + Grafana | Agente | LGTM / Prom | Node app | Node / static |
| Rol ideal | **Operar el lab** | Observabilidad host | Análisis / dashboards | ¿Está caído? | Puerta de entrada |

## Qué hace cada uno mejor

### Netdata
- Observabilidad de host en tiempo real, casi cero config.
- Muchas métricas, bajo esfuerzo.
- **No** reinicia contenedores ni orquesta HA/n8n como RackWatch.

### Grafana
- El estándar para paneles históricos y PromQL.
- RackWatch **lo embebe** en `/graphs`; no intenta reemplazarlo.
- Alerting potente, pero no es un “panel de acción” de Docker.

### Uptime Kuma
- Mejor en “¿este endpoint responde?” (HTTP, ping, DNS, keywords).
- Notificaciones maduras.
- RackWatch cubre umbrales internos (CPU, contenedor caído, ZFS); para sondeos externos usa Kuma **o** un workflow n8n.

### Dashy v4
- Homepage / launcher del homelab (temas, secciones, widgets, status dots).
- No gestiona reinicios ni alertas de infra profundas.
- Encaja **junto a** RackWatch: Dashy = puerta; RackWatch = sala de máquinas.

## Dónde encaja RackWatch

```
Dashy (inicio) ──► apps
Uptime Kuma ──► “¿responde la URL?”
Netdata / Prom+Grafana ──► métricas e histórico
RackWatch ──► estado live + reinicio + HA + alertas + n8n/OpenAI
```

**RackWatch gana** cuando quieres **ver y actuar** en el mismo sitio (reiniciar Plex, ack alertas, hablar con un agente n8n/OpenAI que llama a `/api/v1`).

**No sustituye** Grafana (histórico), Uptime Kuma (sondeos externos) ni Dashy (homepage de bookmarks).
