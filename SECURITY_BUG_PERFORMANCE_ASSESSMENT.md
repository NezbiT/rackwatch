# RackWatch Security, Bug & Performance Assessment Report

**Audit Branch:** `fix/security-audit-2026`  
**Assessment Date:** September 2026  
**Auditor:** Automated Security Engineering Review  
**Repository:** `rackwatch`  

---

## 1. Executive Summary

A comprehensive architectural and security audit was conducted on RackWatch, a lightweight, self-hosted infrastructure monitoring dashboard and management application. The audit reviewed authentication flows, session handling, WebSocket communication, Docker daemon interactions, database persistence, and internal service architecture.

Multiple critical and high-severity security vulnerabilities and performance bottlenecks were discovered and remediated in this branch:
1. **Open Redirect Vulnerability:** Unsanitized redirection targets in authentication and preference flows.
2. **Missing CSRF Protection:** Vulnerability of session-authenticated state-changing POST endpoints (restarts, exec, settings update, test alerts, logout).
3. **Unauthenticated WebSocket & Cross-Site WebSocket Hijacking (CSWSH):** WebSocket endpoint `/ws` lacked origin verification, authentication enforcement, and rate limiting.
4. **Unbounded Configuration Overrides:** Arbitrary settings modification without bounds checking or URL scheme validation in SQLite overrides.
5. **Arbitrary Container File Operations & Execution Risks:** Potential path traversal, reading of sensitive host/container pseudo-filesystems (`/proc`, `/sys`, `/dev`, `/etc/shadow`), absence of output/payload caps, and absence of target protection on the monitoring container itself.
6. **Network & Infrastructure Exposure:** Default `0.0.0.0` port bindings for unauthenticated auxiliary services (Prometheus TSDB, cAdvisor, Node Exporter, Mosquitto MQTT broker) and unsafe Grafana embed settings.
7. **Collector & Notification Bottlenecks:** Sequential metric polling, sequential alert dispatching, lack of cooldown persistence across service restarts, unindexed SQLite queries, and unbounded database table growth.

All vulnerabilities have been resolved, hardening measures implemented, and comprehensive test suites added to guarantee regression resistance.

---

## 2. Security Vulnerabilities & Remediation Details

### 2.1. Open Redirect Vulnerability
- **Severity:** High (CWE-601)
- **Vulnerability:** The login page `/login`, submission handler, and `/prefs` endpoint accepted a raw `next` query/form parameter and redirected the user via `RedirectResponse(next)`. Attackers could provide external URLs (e.g. `//evil.com`, `https://malicious.com`, or schema-bypass sequences like `/\\evil.com` and newline injections) to redirect authenticated operators to phishing or credential-harvesting landing pages.
- **Remediation:**
  - Implemented `safe_next(raw, fallback="/")` in `app/security.py` using `urllib.parse.urlsplit`.
  - Rejects URLs with network locations, URI schemes, double slashes (`//`), or backslashes (`\`), and strips carriage returns and newlines.
  - Re-exported in `app/i18n.py` to ensure uniform sanitization across all redirect targets.

### 2.2. Cross-Site Request Forgery (CSRF)
- **Severity:** High (CWE-352)
- **Vulnerability:** Web browser sessions authenticate via cookies (`SessionMiddleware`), but state-changing HTML form and HTMX POST actions (`/logout`, `/services/{name}/restart`, `/services/{name}/exec`, `/alerts/test`, `/settings`) had no CSRF token validation. A malicious webpage visited by an operator could execute unauthorized container restarts, run commands, or overwrite system settings.
- **Remediation:**
  - Implemented cryptographically secure CSRF token generation (`secrets.token_urlsafe(32)`) and constant-time validation (`hmac.compare_digest`) in `app/security.py`.
  - Created a FastAPI dependency `require_csrf(request: Request)` that validates tokens supplied in either form data (`csrf_token`) or custom headers (`X-CSRF-Token` / `X-CSRFToken`).
  - Automatically exempted API token requests (`X-API-Key` / Bearer token) as programmatic REST clients are not vulnerable to browser ambient-credential CSRF.
  - Embedded CSRF tokens in `base.html` meta tags (`<meta name="csrf-token">`), configured HTMX globally via `hx-headers`, and injected CSRF tokens into all JavaScript dynamic `fetch` calls in `app/static/js/app.js`.
  - Enforced token regeneration upon successful login in `login_submit` to eliminate session fixation.

### 2.3. WebSocket Authentication & Cross-Site WebSocket Hijacking (CSWSH)
- **Severity:** High (CWE-1385, CWE-306)
- **Vulnerability:** The live telemetry WebSocket `/ws` accepted all incoming connections without validating the `Origin` header and without enforcing authentication when `RACKWATCH_AUTH_USER` was configured. Any malicious site loaded in an operator's browser could open a WebSocket to `http://localhost:8080/ws` and exfiltrate real-time host infrastructure telemetry, container metrics, and sensitive alerts.
- **Remediation:**
  - Added `is_ws_origin_allowed(origin, host_header, settings)`: strictly verifies that the `Origin` header matches the `Host` header, `localhost`, `127.0.0.1`, or `RACKWATCH_PUBLIC_URL`.
  - Added `is_ws_authenticated(ws, settings)`: verifies user session cookies, `token`/`api_key` query parameters, or `x-api-key` headers when authentication is enabled.
  - If validation fails, immediately terminates the handshake with WebSocket status `WS_1008_POLICY_VIOLATION`.
  - Added sliding-window rate limiting on incoming client messages (30 messages per 5 seconds) to prevent socket flooding.

### 2.4. Safe Configuration Validation & Bounds Checking
- **Severity:** Medium (CWE-20)
- **Vulnerability:** Runtime configuration overrides persisted to SQLite (`settings_store.py`) lacked type range boundaries and URL scheme validation. Unchecked values (such as negative refresh intervals or arbitrary URI schemes like `javascript:` or `file://` in webhook URLs) could degrade services or trigger SSRF/XSS vectors.
- **Remediation:**
  - Introduced the Pydantic schema `SettingsUpdate` in `app/schemas.py`.
  - Constrained all numeric settings (e.g., CPU/RAM/Disk thresholds between `0.0` and `100.0`, `refresh_seconds >= 1`, `db_retention_days` between `1` and `3650`).
  - Added URL scheme validators restricting webhook URLs (`ha_url`, `n8n_webhook_url`, `whatsapp_webhook_url`, `generic_webhook_url`, `grafana_public_url`) exclusively to `http` or `https` with valid network hostnames.
  - Integrated `validate_settings_dict` into `settings_store.save_overrides` and added `@router.patch("/api/v1/settings")` for API-driven configuration.

### 2.5. Docker Exec & File Safeguards
- **Severity:** High (CWE-22, CWE-78)
- **Vulnerability:** Container execution and file read/write operations lacked granular payload boundaries, traversal prevention, sensitive path protection, and self-modification protections.
- **Remediation:**
  - Enforced POSIX path normalization (`posixpath.normpath`) preventing directory traversal (`..`).
  - Blocked access to virtual filesystems and sensitive credential paths (`/proc`, `/sys`, `/dev`, `/etc/shadow`, `/etc/gshadow`, `/etc/sudoers`).
  - Enforced a hard prohibition on modifying files within the `rackwatch` container itself.
  - Implemented streaming file size limit checks (maximum 1 MB for reading and writing) and tar entry validation (`isreg()` regular file verification).
  - Restricted container `exec` commands to a maximum length of 500 characters, blocked shell metacharacters, and wrapped executions in an asynchronous 15-second timeout (`EXEC_TIMEOUT_SECONDS`).

### 2.6. Infrastructure & Deployment Hardening
- **Severity:** Medium
- **Remediation:**
  - **Docker Compose:** Bound internal ports for `prometheus` (`9090`), `cadvisor` (`8081`), `node-exporter` (`9100`), and `mosquitto` (`1883`) to `127.0.0.1` instead of `0.0.0.0`, preventing exposed attack surfaces on the host's LAN.
  - **Grafana Embedding:** Added `sandbox="allow-scripts allow-same-origin allow-forms allow-popups"` and `referrerpolicy="no-referrer"` to the dashboard iframe in `grafana.html`. Configured `GF_SECURITY_COOKIE_SAMESITE: lax` in `docker-compose.yml`.
  - **MQTT Client:** Sanitized topic hierarchies against wildcard injection (`#`, `+`), added TLS support (`mqtt_tls` / port 8883), and enabled dynamic client reconnection when configuration changes.

---

## 3. Performance & Reliability Optimizations

### 3.1. Collector Concurrency
- **Previous State:** In `Collector.tick()`, Prometheus host discovery, container usage calculations, ZFS pool interrogation, Home Assistant entity polling, and Glances summaries were executed sequentially.
- **Optimized State:** Refactored `Collector.tick()` to gather all independent telemetry sources concurrently using `asyncio.gather()`. External mirrors (`ha.publish_snapshot` and `mqtt.publish_snapshot`) are dispatched in parallel as best-effort tasks, significantly reducing collector tick duration.

### 3.2. WebSocket Hub Broadcast & Payload Caching
- **Previous State:** The WebSocket Hub serialized the full snapshot independently for every connected client in a sequential loop. A slow or stalled WebSocket client could block the entire collector loop.
- **Optimized State:**
  - Implemented fast-path serialization caching: clients with empty default filters reuse the pre-serialized snapshot dictionary directly.
  - Broadcasts to all connected clients run concurrently with `asyncio.gather()`.
  - Wrapped each client send with an `asyncio.wait_for(..., timeout=4.0)` safeguard; failing or timed-out sockets are cleanly unregistered.

### 3.3. Outbound Alert Dispatch & Cooldown Persistence
- **Previous State:** Notifications were dispatched sequentially across channels (Telegram, WhatsApp, n8n, generic, Home Assistant, MQTT), causing cumulative HTTP latency. Alert cooldowns were held purely in memory (`_last_sent`), causing alert storm thundering herds upon application restarts. Alert queries in `recent_alerts()` filtered records in Python after loading arbitrary rows from SQLite.
- **Optimized State:**
  - Channels are dispatched in parallel via `asyncio.gather()`.
  - Added fallback database verification on `fingerprint` to maintain cooldown suppression across application restarts.
  - Updated `recent_alerts()` to filter `Alert.created_at >= cutoff` directly at the database layer using indexed timestamps.

### 3.4. SQLite Database Optimization & Automated Retention
- **Previous State:** SQLite tables (`alerts`, `restarts`, `webhook_deliveries`) lacked indexes on query and timestamp columns, ran in rollback journal mode without concurrency pragmas, and had no automated pruning mechanism.
- **Optimized State:**
  - Configured SQLite connection pragmas:
    - `PRAGMA journal_mode=WAL` (Write-Ahead Logging allows simultaneous reads and writes).
    - `PRAGMA synchronous=NORMAL` (reduces disk fsync stalls with WAL safety).
    - `PRAGMA busy_timeout=5000` (eliminates database lock exceptions under concurrent load).
    - `PRAGMA foreign_keys=ON`.
  - Added B-tree indexes: `created_at` on `Alert`, `RestartEvent`, and `WebhookDelivery`, composite indexes `ix_alerts_status_created` and `ix_alerts_fingerprint_created`.
  - Implemented automated retention pruning (`cleanup_old_records`), executed periodically (hourly) by the collector loop according to `RACKWATCH_RETENTION_DAYS` (default: 30 days).

---

## 4. Verification & Testing Matrix

A dedicated regression and security test suite (`tests/test_security_audit.py`) was developed alongside existing test cases.

| Test Case | Description | Result |
| :--- | :--- | :---: |
| `test_safe_next_open_redirect` | Validates rejection of protocol relative, external, CRLF, and malformed redirect URLs | **PASSED** |
| `test_csrf_token_logic` | Validates token generation entropy, storage, and constant-time verification | **PASSED** |
| `test_csrf_protected_endpoints` | Verifies rejection of unauthenticated/untokened POST requests and API key bypass | **PASSED** |
| `test_websocket_origin_security` | Tests CSWSH protection against malicious and untrusted origin headers | **PASSED** |
| `test_websocket_authentication` | Tests session cookie, query token, and API key authentication on `/ws` | **PASSED** |
| `test_settings_validation` | Tests bounds checks, URL scheme validation, and invalid key stripping | **PASSED** |
| `test_docker_control_safeguards` | Tests path traversal, `/proc`/`/sys`/`/etc/shadow` blocking, exec length/shell rules | **PASSED** |
| `test_sqlite_retention_policy` | Verifies retention cutoff purge and index execution in SQLite | **PASSED** |
| `test_hub_concurrent_broadcast` | Verifies non-blocking parallel client WebSocket fan-out | **PASSED** |
| **Full Regression Suite** | 41 unit and integration tests across alerter, filters, health, i18n, n8n, security | **41 / 41 PASSED** |

---

## 5. Deployment Recommendations

1. **Environment Secrets:**
   - Always override `RACKWATCH_SECRET_KEY` with a minimum 32-character random string in production.
   - Set strong passwords for `RACKWATCH_AUTH_PASSWORD` and `GRAFANA_ADMIN_PASSWORD`.
2. **Reverse Proxy & SSL/TLS:**
   - Deploy RackWatch behind a reverse proxy (e.g., Caddy, Nginx, or Traefik) terminating TLS.
   - When serving behind a reverse proxy, set `RACKWATCH_PUBLIC_URL` to the public HTTPS URL so that WebSocket origin checks and CSRF validation align with production hostnames.
3. **Docker Daemon Access:**
   - For environments that do not require container restart capabilities from the dashboard, mount the Docker socket as read-only (`/var/run/docker.sock:/var/run/docker.sock:ro`).
   - For multi-node setups, consider using a Docker socket proxy (such as `tecnativa/docker-socket-proxy`) with write operations restricted to authorized endpoints.
