# From homelab MVP to hosted SaaS

This file is the product brief for the **online** edition. The self-hosted app in this repo stays. The cloud product is a control plane that speaks the same `/api/v1` and the same alert envelope.

Do not rewrite the dashboard. Extend it.

---

## What already survives a lift

| MVP piece | Why it ports |
|---|---|
| `app/schemas.py` Snapshot / AlertOut / Filters | Public contract |
| `/api/v1/*` | Versioned, JSON only |
| Alert envelope | n8n and mobile apps can keep working |
| Hub filters | Per-connection, already multi-viewer |
| Settings WRITABLE allow-list | Becomes per-tenant config columns |
| Collector tick | Becomes the **agent** main loop |

---

## Target architecture

```
                  ┌──────────── cloud ────────────┐
  Browser ──────► │  Next.js (or this Jinja UI)   │
                  │  + OIDC (Clerk / Auth.js)     │
                  │  + billing                    │
                  └────────────┬──────────────────┘
                               │ HTTPS
                  ┌────────────▼──────────────────┐
                  │  API  /api/v2  (FastAPI)      │
                  │  Postgres  ·  Redis pub/sub   │
                  │  object store (alert shots)   │
                  └────────────┬──────────────────┘
                               │ mTLS or device JWT
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
   RackWatch agent        RackWatch agent        Grafana Cloud
   (this collector)       on Proxmox host        or Mimir
```

Each customer site runs a thin **agent**: today's `Collector` + `DockerControl` + `Alerter` (local only). The agent:

1. Scrapes local Prometheus or talks to node-exporter / Docker directly
2. Opens a WebSocket or HTTP/2 bidi to the cloud (`/api/v2/agents/stream`)
3. Receives restart commands signed with the device JWT
4. Never exposes the Docker socket to the internet

The cloud never mounts a customer's socket. That is the security boundary.

---

## Multi-tenancy plan

1. **Tenant** table: id, slug, plan, Grafana org id.
2. **User** table: OIDC subject, role (`owner` | `operator` | `viewer`).
3. **Agent** table: tenant_id, instance_name, last_seen, public key.
4. **Every** Snapshot, Alert, RestartEvent gains `tenant_id`.
5. SQLite → Postgres. Same SQLAlchemy models, new URL.
6. Hub: Redis channel `tenant:{id}:snapshot` instead of an in-process set.
7. Settings: one row per tenant, secrets in a KMS / Vault, never in the app DB in plaintext.

Row-level rule: a request without `tenant_id == session.tenant_id` is a 404, not a 403 (no existence leak).

---

## Auth evolution

| Stage | Auth |
|---|---|
| MVP (now) | Optional form login + API token |
| Private beta | Magic link / OIDC, one tenant per user |
| Public | Clerk / Auth.js, teams, RBAC |
| Enterprise | SAML, SCIM, per-agent mTLS |

Keep `require_api_token` as the **agent identity** surface. Human sessions never share that token.

---

## Product packaging

Suggested plans (names are placeholders — use boring words in the UI: Hobby, Team, Business):

| | Hobby | Team | Business |
|---|---|---|---|
| Agents | 1 | 5 | unlimited |
| Retention | 3 days | 30 days | 13 months |
| Channels | Telegram | + Slack / n8n | + webhook SLA |
| HA / MQTT | yes | yes | yes + SSO |
| Price signal | $0 self-host or $8 hosted | $19 | talk to us |

The **self-hosted** image remains MIT and feature-complete for one lab. Hosted value is: no Prometheus to run, history, multi-site, phone app, and someone else paging at 3am.

---

## What to build next (ordered)

1. Extract `app/services/collector.py` behind an `AgentProtocol` (local | remote).
2. Add `tenant_id` nullable column now (always `null` in MVP) so the migration is cheap.
3. Device registration: `POST /api/v1/agents/register` → one-time code the operator pastes.
4. Cloud ingest of Snapshot (drop Grafana iframe, render the same cards from stored ticks).
5. Billing (Stripe) + usage meter on `agents.last_seen`.
6. Mobile-friendly PWA (the current CSS already has a bottom nav).
7. Status page / public badge (`/status/{slug}`) for customers who want a “is the lab up” URL.

---

## What not to do

- Do not add Rust, a second frontend framework, or a Kubernetes operator in the same PR as tenants.
- Do not make the SaaS edition require Prometheus on the customer site. The agent must work with Docker + psutil alone (it already does).
- Do not reuse `RACKWATCH_SECRET_KEY` across tenants.
- Do not embed Grafana with anonymous auth on the public internet.

---

## API compatibility

The SaaS control plane continues to accept the MVP alert envelope. n8n workflows customers write against self-hosted RackWatch must work unchanged when they point the same URL at the cloud tenant webhook:

```
POST https://api.rackwatch.app/t/{slug}/hooks/alert
X-API-Key: rw_live_...
```

That path is the commercial twin of `/api/v1/hooks/alert`.
