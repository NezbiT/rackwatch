# Security

RackWatch is designed for a **trusted LAN**. The Docker socket and anonymous Grafana embed are powerful. Do not publish port 8080 to the internet without the steps below.

---

## What this process can do

- Read every container name, image, and status
- Restart any container not on the denylist (or any, with `force=1`)
- Read HA state and call notify
- Hold Telegram / WhatsApp / HA tokens in SQLite if you pasted them in Settings

Treat a compromised RackWatch container as a compromised Docker host.

---

## Minimum hardening on a home lab

1. Generate real secrets:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Set `RACKWATCH_SECRET_KEY` and `RACKWATCH_API_TOKEN`.

2. Turn on dashboard login:

```env
RACKWATCH_AUTH_USER=you
RACKWATCH_AUTH_PASSWORD=<long>
```

3. Put Caddy / nginx with TLS in front. Do not forward 9090, 3001, 9100, 8081, or 1883 to the WAN. Those ports are for the LAN and for the compose network.

4. If you do not want auto-restart, either set `AUTO_RESTART_ENABLED=false` or mount the socket read-only:

```yaml
- /var/run/docker.sock:/var/run/docker.sock:ro
```

Manual restart will then fail (by design).

5. Keep the denylist. Never remove `rackwatch` from it unless you like crash loops.

6. Grafana anonymous Viewer is on so the iframe works. That is **read-only metrics**. Change `GF_AUTH_ANONYMOUS_ENABLED=false` if Grafana is reachable outside the house, and log in once before using Graphs.

---

## API token

Inbound hooks (`/api/v1/hooks/*`) and JSON mutations require the token when it is set — even if dashboard login is off. A signed-in session only substitutes for the token when `RACKWATCH_AUTH_USER` is enabled.

The Settings “Test …” buttons and the container Restart buttons go through HTML/HTMX routes that use the browser session (or open LAN), not the API token.

n8n / HA must send:

```
X-API-Key: <RACKWATCH_API_TOKEN>
```

Rotate the token by changing `.env` and recreating the container. Old automations will get 401.

---

## Cookies

`SessionMiddleware` uses `SameSite=Lax` and `https_only=False` so a LAN `http://` install works. Behind TLS, consider flipping `https_only=True` in `app/main.py`.

---

## Supply chain

Images are pinned by registry digest in `docker-compose.yml` and the Dockerfile base image. Python deps are hash-locked in `requirements.txt`. Review both before a SaaS deploy. There is no phone-home and no third-party analytics in the app.

---

## Reporting

This is an MVP. If you find a way to restart a denylisted container without `force`, or to read Settings secrets from an unauthenticated session, that is a real bug — fix it before any public SaaS launch.
