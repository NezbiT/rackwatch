#!/usr/bin/env bash
# Run RackWatch on this machine for UI development (no Docker Compose).
# Prometheus/Grafana are optional — the dashboard falls back to psutil.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Missing .venv. Create it with Python 3.12:"
  echo "  python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

export RACKWATCH_ENV="${RACKWATCH_ENV:-development}"
export RACKWATCH_HOST="${RACKWATCH_HOST:-127.0.0.1}"
export RACKWATCH_PORT="${RACKWATCH_PORT:-8080}"
export RACKWATCH_PUBLIC_URL="${RACKWATCH_PUBLIC_URL:-http://127.0.0.1:${RACKWATCH_PORT}}"
export GRAFANA_PUBLIC_URL="${GRAFANA_PUBLIC_URL:-http://127.0.0.1:3002}"
export PROMETHEUS_URL="${PROMETHEUS_URL:-http://127.0.0.1:9090}"
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///./data/rackwatch.db}"
export RACKWATCH_INSTANCE_NAME="${RACKWATCH_INSTANCE_NAME:-laptop}"

mkdir -p data
echo "RackWatch local → ${RACKWATCH_PUBLIC_URL}"
exec "${ROOT}/.venv/bin/uvicorn" app.main:app \
  --host "${RACKWATCH_HOST}" \
  --port "${RACKWATCH_PORT}" \
  --reload
