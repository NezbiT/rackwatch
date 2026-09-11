#!/usr/bin/env bash
# Run ON the Proxmox node (lenovo) as root.
# Creates CT 110: Debian 12, 2 cores, 10G RAM, 16G disk, Ollama + qwen2.5:3b-instruct.
set -euo pipefail

CTID="${CTID:-110}"
HOSTNAME="${HOSTNAME:-llm}"
STORAGE="${STORAGE:-local-lvm}"
BRIDGE="${BRIDGE:-vmbr0}"
CORES="${CORES:-2}"
MEMORY_MB="${MEMORY_MB:-10240}"
DISK_GB="${DISK_GB:-16}"
TEMPLATE="${TEMPLATE:-debian-12-standard_12.7-1_amd64.tar.zst}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root on the Proxmox host."
  exit 1
fi

if ! pveam list local | grep -q debian-12; then
  pveam update
  pveam download local debian-12-standard_12.7-1_amd64.tar.zst || true
fi

if pct status "$CTID" &>/dev/null; then
  echo "CT $CTID already exists: $(pct status "$CTID")"
else
  TEMPLATE_PATH="$(pveam list local | awk '/debian-12-standard/ {print $1; exit}')"
  pct create "$CTID" "$TEMPLATE_PATH" \
    --hostname "$HOSTNAME" \
    --cores "$CORES" \
    --memory "$MEMORY_MB" \
    --swap 512 \
    --rootfs "${STORAGE}:${DISK_GB}" \
    --net0 "name=eth0,bridge=${BRIDGE},ip=dhcp" \
    --unprivileged 1 \
    --features nesting=1 \
    --onboot 1 \
    --start 1
fi

pct exec "$CTID" -- bash -s << 'INSIDE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl
if ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
mkdir -p /etc/systemd/system/ollama.service.d
cat >/etc/systemd/system/ollama.service.d/limits.conf << EOF
[Service]
Environment=OLLAMA_HOST=0.0.0.0:11434
Environment=OLLAMA_MAX_LOADED_MODELS=1
Environment=OLLAMA_NUM_PARALLEL=1
Environment=OLLAMA_KEEP_ALIVE=5m
MemoryMax=6G
CPUQuota=180%
EOF
systemctl daemon-reload
systemctl enable --now ollama
ollama pull qwen2.5:3b-instruct
ip -br a
INSIDE

echo "Ollama: http://<ct-ip>:11434  model qwen2.5:3b-instruct"
echo "Point n8n Ollama node at that URL. In the workflow, replace 10.13.58.110 if DHCP gave another IP."
