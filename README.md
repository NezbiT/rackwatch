<p align="center">
  <img src="app/static/img/logo.svg" width="96" height="96" alt="RackWatch Logo">
</p>

# RackWatch

Self-hosted real-time homelab operations dashboard and automated recovery system for **Docker**, **CasaOS**, and **Proxmox**.

RackWatch provides real-time telemetry (CPU, RAM, disk, network, container health, and ZFS pools), automated service healing with denylist protection, multi-channel alerting, an AI-driven operator API, and a desktop status bar widget for **Omarchy**.

> Spanish documentation is available at [README.es.md](README.es.md). Detailed architecture and technical guides are located in [docs/](docs/).

---

## 1. The Base Stack (`docker compose up -d`)

RackWatch is deployed as a coordinated 5-container stack defined in `docker-compose.yml`. Each container handles a distinct role in metrics acquisition, persistence, visualization, or management:

| Container / Image | Default Port | Why It Is Required |
|---|---|---|
| **`rackwatch`**<br>`rackwatch:0.1.0` *(FastAPI)* | `8080`<br>*(or `8180` on CasaOS)* | **Core System Engine:** Serves the web interface, REST API (`/api/v1`), and live WebSocket stream (~3s tick). Executes the collector loop, evaluates alert thresholds, and orchestrates container restarts. |
| **`prometheus`**<br>`prom/prometheus:v3.2.1` | `9090` | **Time-Series Database (TSDB):** Stores high-resolution metric history (15-day retention by default) for CPU, memory, filesystem, and network I/O. Prevents high-frequency metrics from ballooning the local SQLite database. |
| **`node-exporter`**<br>`prom/node-exporter:v1.9.1` | `9100` | **Host OS Metrics Collector:** Runs with direct read access to host virtual filesystems (`/:/host:ro`, `/proc`, `/sys`). Collects physical CPU load, memory utilization, disk partition saturation, and ZFS pool status. |
| **`cadvisor`**<br>`gcr.io/cadvisor/cadvisor:v0.51.0` | `8081` | **Container Metrics Collector:** Analyzes real-time CPU and memory usage of each running Docker container on the host. Prometheus scrapes cAdvisor, allowing RackWatch to display individual container resource consumption. |
| **`grafana`**<br>`grafana/grafana:11.6.0` | `3001`<br>*(or `3002` on CasaOS)* | **Historical Analytics & Deep Inspection:** Renders long-term performance graphs. Ships with pre-provisioned datasources and dashboards (`rackwatch-overview.json`) embedded directly into the `/graphs` tab. |

---

## 2. Host Requirements & Permissions

Before running the stack, verify that your host environment satisfies the following requirements:

### Prerequisites Check

Run this command on your host to verify that Docker and Docker Compose are available:

```bash
docker --version && docker compose version
```

- **Linux Operating System:** Debian, Ubuntu Server, Arch Linux, CasaOS, Unraid, or Proxmox (LXC/VM).
- **Docker Engine (24+) & Docker Compose v2:** Required to run the multi-container stack and manage service networks.

### Docker Socket Access (`/var/run/docker.sock`)

Both `rackwatch` and `cadvisor` require access to the Docker daemon socket:

```bash
ls -la /var/run/docker.sock
```

**Why it is required:**
- **`cadvisor`:** Reads container metadata and cgroups directly from Docker to export container statistics.
- **`rackwatch`:** Queries container states (`running`, `unhealthy`, `exited`) and performs auto-restart actions when a service fails.

**Permission Modes:**
- **Read-Write (`/var/run/docker.sock:/var/run/docker.sock:rw`) [Default]:** Allows RackWatch to restart failed containers automatically or on-demand via web UI / API.
- **Read-Only (`/var/run/docker.sock:/var/run/docker.sock:ro`):** Restricts RackWatch to observer mode (telemetry only; cannot restart containers).

---

## 3. Quick Start & Installation

### Step 1: Clone Repository

```bash
git clone https://github.com/NezbiT/rackwatch.git /opt/rackwatch
cd /opt/rackwatch
```

### Step 2: Configure Environment & Generate Secrets

Copy the environment template:

```bash
cp .env.example .env
```

Generate secure random tokens for session signing and API authentication:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Edit `.env` and set the required variables:

```env
# Required security tokens
RACKWATCH_SECRET_KEY=<generated_hex_string_32_bytes>
RACKWATCH_API_TOKEN=<generated_hex_string_32_bytes>

# Host endpoints
RACKWATCH_PUBLIC_URL=http://<YOUR_SERVER_IP>:8080
GRAFANA_PUBLIC_URL=http://<YOUR_SERVER_IP>:3001
GRAFANA_ADMIN_PASSWORD=<strong_password>
```

> **Security Note:** Never commit `.env` to source control. It is ignored in `.gitignore`.

### Step 3: Launch the Stack

Start all 5 services in detached mode:

```bash
docker compose up -d --build
```

### Step 4: Verify Health & Deployment

Check container statuses and verify the RackWatch health endpoint:

```bash
docker compose ps
curl -fsS http://127.0.0.1:8080/healthz
```

Expected output: `{"status":"ok"}`.

### Service Ports Overview

| Service | Access URL | Notes |
|---|---|---|
| **RackWatch Web UI** | `http://<SERVER_IP>:8080` | Main homelab dashboard |
| **Prometheus** | `http://<SERVER_IP>:9090` | PromQL metrics interface |
| **Grafana** | `http://<SERVER_IP>:3001` | Embedded analytics (user: `admin`) |

*For CasaOS setups where ports 8080 and 3001 are already in use, apply the CasaOS overlay to use ports **8180** and **3002**:*

```bash
docker compose -f docker-compose.yml -f docker-compose.casaos.yml up -d --build
```

---

## 4. Optional External Integrations

RackWatch can be extended with external automation and notification tools depending on your homelab architecture:

### 1. Telegram / WhatsApp / Generic Webhooks
- **Why:** Delivers instant mobile alerts when a container dies, ZFS pools degrade, or resource thresholds exceed critical limits (>90%).
- **Configuration:** Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (or `WHATSAPP_*` / `WEBHOOK_URL`) in `.env` or via **Settings** in the web UI.

### 2. n8n (Automation & AI Operator)
- **Why:** Enables bidirectional intelligence:
  - **Outbound:** Dispatches standardized JSON alert envelopes to n8n workflows for complex routing (e.g., alert filtering, ticket creation).
  - **Inbound AI Operator:** Powers the built-in `@n8n/chat` widget. An LLM agent in n8n can query `/api/v1/snapshot` and execute controlled recovery actions via the operator API using `X-API-Key`.
- **Configuration:** Set `N8N_WEBHOOK_URL` and `N8N_CHAT_WEBHOOK_URL` in `.env`.

### 3. Home Assistant
- **Why:** Provides two-way smart home synchronization:
  - **Telemetry Push:** Publishes `sensor.rackwatch_*` entities (CPU, RAM, disk, status) to Home Assistant via REST API.
  - **Notifications:** Forwards critical server alerts through Home Assistant's `notify` service.
- **Configuration:** Set `HA_URL`, `HA_TOKEN`, and `HA_NOTIFY_SERVICE` in `.env`.

### 4. Mosquitto (MQTT Broker)
- **Why:** Publishes real-time telemetry over MQTT topics and enables automatic discovery for Home Assistant without manual sensor definitions.
- **Command to launch:**
  ```bash
  docker compose --profile mqtt up -d
  ```

### 5. Omarchy Desktop Plugin (`nezbit.rackwatch`)
- **Why:** Native Linux desktop status bar widget and dropdown control panel for [Omarchy Shell](https://github.com/NezbiT/omarchy-rackwatch). Displays live CPU/RAM usage, container statuses, and active alerts, allowing you to acknowledge alerts or restart containers directly from the desktop panel without opening the browser.
- **Install via Omarchy Plugin Manager:**
  ```bash
  omarchy plugin add https://github.com/NezbiT/omarchy-rackwatch.git --enable
  ```
- **Manual Installation:**
  ```bash
  git clone https://github.com/NezbiT/omarchy-rackwatch.git ~/.config/omarchy/plugins/nezbit.rackwatch
  omarchy plugin validate ~/.config/omarchy/plugins/nezbit.rackwatch
  omarchy plugin enable nezbit.rackwatch right
  ```
- **Repository & Setup Guide:** [NezbiT/omarchy-rackwatch](https://github.com/NezbiT/omarchy-rackwatch)

---

## 5. Essential Management & API Commands

### View Live Container Logs

```bash
docker compose logs -f rackwatch
```

### Inspect Live Telemetry Snapshot (CLI)

```bash
curl -s -H "X-API-Key: <YOUR_RACKWATCH_API_TOKEN>" http://127.0.0.1:8080/api/v1/snapshot | jq .
```

### Trigger a Safe Container Restart via API

```bash
curl -X POST http://127.0.0.1:8080/api/v1/hooks/container \
  -H "X-API-Key: <YOUR_RACKWATCH_API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"container": "plex", "action": "restart", "reason": "operator CLI"}'
```

---

## Documentation

- **Architecture:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Installation Guide:** [docs/INSTALL.md](docs/INSTALL.md)
- **REST & WebSocket API:** [docs/API.md](docs/API.md)
- **Alerting Engine:** [docs/ALERTS.md](docs/ALERTS.md)
- **n8n & AI Integration:** [docs/N8N.md](docs/N8N.md)
- **Security Guide:** [docs/SECURITY.md](docs/SECURITY.md)
- **Security Assessment Report:** [SECURITY_BUG_PERFORMANCE_ASSESSMENT.md](SECURITY_BUG_PERFORMANCE_ASSESSMENT.md)
- **Tool Comparison:** [docs/COMPARE.md](docs/COMPARE.md)
- **Omarchy Desktop Widget:** [NezbiT/omarchy-rackwatch](https://github.com/NezbiT/omarchy-rackwatch)

---

## License

MIT License. See [LICENSE](LICENSE) for details.
