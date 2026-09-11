# Install

Primary target is a Linux box already running Docker: CasaOS, a Proxmox VM/LXC, Debian, Ubuntu Server, Unraid.

Windows Docker Desktop can run the **app** for UI development. `node-exporter` and `cadvisor` expect a Linux host — treat Windows as a dev-only environment.

---

## 1. Docker Compose (any Linux host)

```bash
git clone <repo> /opt/rackwatch
cd /opt/rackwatch
cp .env.example .env
nano .env
```

Set at least:

```env
RACKWATCH_SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
RACKWATCH_API_TOKEN=<another long random string>
RACKWATCH_PUBLIC_URL=http://192.168.1.10:8080
GRAFANA_PUBLIC_URL=http://192.168.1.10:3001
GRAFANA_ADMIN_PASSWORD=<not changeme>
```

Then:

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8080/healthz
```

Open `http://<ip>:8080`.

Optional MQTT broker:

```bash
docker compose --profile mqtt up -d
# then set MQTT_HOST=mosquitto in .env and recreate rackwatch
```

---

## 2. CasaOS

CasaOS is Docker with a friendly store. Two working methods:

### A. Custom compose (recommended)

CasaOS already binds **8080** (its UI) and often **3001** (Uptime Kuma). Use the overlay so RackWatch lands on **8180** and Grafana on **3002**:

```bash
# On the CasaOS host
docker compose -f docker-compose.yml -f docker-compose.casaos.yml up -d --build
```

Set in `.env` before that:

```env
RACKWATCH_PUBLIC_URL=http://10.13.58.100:8180
GRAFANA_PUBLIC_URL=http://10.13.58.100:3002
```

Open `http://<casaos-ip>:8180`.

Or from the CasaOS UI:

1. Copy this whole folder to `/DATA/AppData/rackwatch` (or any share).
2. CasaOS → App store → **Install a customized app** → **Compose**.
3. Import `docker-compose.yml` **and** merge the port changes from `docker-compose.casaos.yml` (8180 / 3002 / 8082). CasaOS sometimes rewrites relative bind mounts — change them to absolute paths:

```yaml
volumes:
  - /DATA/AppData/rackwatch/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
  - /DATA/AppData/rackwatch/grafana/provisioning:/etc/grafana/provisioning:ro
```

4. Paste env from `.env` (`RACKWATCH_PUBLIC_URL` on **8180**, `GRAFANA_PUBLIC_URL` on **3002**).
5. Install. Publish **8180**, not 8080.

### B. Already-running Docker on the same host

If CasaOS already has Prometheus / Grafana from another app, you do **not** have to start a second pair. Run only the `rackwatch` service and point `PROMETHEUS_URL` at the existing Prometheus. Add a scrape job for `rackwatch:8080` in that Prometheus.

---

## 3. Proxmox

### VM (simplest)

The existing **CasaOS** VM (`Casaos-server` on this lab) is the right target: Docker is already there. Copy the repo onto that VM and use `docker-compose.casaos.yml` so ports do not collide with CasaOS `:8080` or Uptime Kuma `:3001`.

Bare Debian 12 VM: install Docker Engine + Compose plugin, follow section 1. Give the VM enough RAM for Prometheus + Grafana (2 GB comfortable).

### LXC (privileged)

Unprivileged LXC cannot mount `/var/run/docker.sock` or `/` for node-exporter cleanly.

```
# CT features: nesting=1, keyctl=1, and privileged if you want the socket
```

Install Docker **inside** the CT *or* mount the host socket:

```
# On the Proxmox host
lxc.apparmor.profile: unconfined
lxc.mount.entry: /var/run/docker.sock var/run/docker.sock none bind,rw 0 0
```

A cleaner Proxmox setup is: node-exporter as a **systemd unit on the host** (or on each node), and RackWatch + Prometheus in one VM that scrapes `192.168.x.x:9100`. Uncomment `nodes-extra` in `prometheus/prometheus.yml`.

---

## 4. Unraid / other NAS

Use the folder as a custom stack. Map:

| Host | Container |
|---|---|
| `/var/run/docker.sock` | `/var/run/docker.sock` |
| appdata `/rackwatch/data` | `/data` |
| appdata prometheus/grafana dirs | as in compose |

Set `GRAFANA_PUBLIC_URL` to `http://<unraid-ip>:3001`.

---

## 5. Reverse proxy

Example Caddy (TLS + one hostname):

```
watch.home.arpa {
  reverse_proxy rackwatch:8080
}
```

WebSockets (`/ws`) work through Caddy and nginx without extra config if you proxy HTTP/1.1 or HTTP/2 correctly.

nginx:

```
location /ws {
  proxy_pass http://rackwatch:8080/ws;
  proxy_http_version 1.1;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";
  proxy_set_header Host $host;
  proxy_read_timeout 3600;
}
```

Set `RACKWATCH_PUBLIC_URL=https://watch.home.arpa` so alert links are correct.

Grafana embed: either keep Grafana on `:3001` or put it on `https://watch.home.arpa/grafana/` and update `GRAFANA_PUBLIC_URL` plus Grafana `root_url` / `serve_from_sub_path`. The default compose exposes Grafana on 3001 to avoid a sub-path fight.

---

## 6. ZFS on the host

If this box is a TrueNAS / Proxmox ZFS node:

```bash
chmod +x scripts/zfs-textfile.sh
mkdir -p data/textfile
# cron every minute
* * * * * /opt/rackwatch/scripts/zfs-textfile.sh > /opt/rackwatch/data/textfile/zfs.prom
```

The compose bind-mounts `./data/textfile` into node-exporter. RackWatch also tries `zpool` directly if you later bake `zfsutils-linux` into the image.

---

## 7. First-run checklist

1. Dashboard shows a host card within 10 seconds (local fallback if Prometheus is still starting).
2. Services page lists containers.
3. Settings → **Test telegram / n8n / homeassistant** after you paste tokens.
4. Optional chat: Chat Trigger (Embedded Chat) → paste production URL into **n8n chat webhook URL** → **Test chat**. Details: [N8N.md](N8N.md).
4. Graphs page: if the iframe is blank, open `GRAFANA_PUBLIC_URL` once in the same browser (anonymous Viewer is on) and confirm `allow_embedding = true`.
5. Home Assistant page explains itself until `HA_URL` + token are set.

---

## 8. Upgrade

```bash
cd /opt/rackwatch
git pull
docker compose up -d --build
```

SQLite lives in the `rackwatch-data` volume. Prometheus and Grafana have their own volumes. Pulling the image does not wipe history.

---

## 9. Uninstall

```bash
docker compose down
# add -v to also delete metrics history and the SQLite file
```
