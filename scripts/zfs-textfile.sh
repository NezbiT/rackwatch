#!/bin/sh
# Write ZFS pool health in Prometheus textfile format.
# Cron on the host (every minute):
#   * * * * * /opt/rackwatch/scripts/zfs-textfile.sh > /opt/rackwatch/data/textfile/zfs.prom
#
# node-exporter then scrapes the file (--collector.textfile.directory).
# RackWatch also reads `zpool list` directly when the binary is in PATH.

set -eu

if ! command -v zpool >/dev/null 2>&1; then
  echo "# no zpool binary"
  exit 0
fi

echo "# HELP zpool_health_info ZFS pool health (1 = this state is active)."
echo "# TYPE zpool_health_info gauge"
echo "# HELP zpool_capacity_percent Pool capacity used."
echo "# TYPE zpool_capacity_percent gauge"

zpool list -Hp -o name,health,cap | while IFS= read -r line; do
  name=$(echo "$line" | awk '{print $1}')
  health=$(echo "$line" | awk '{print $2}')
  cap=$(echo "$line" | awk '{print $3}' | tr -d '%')
  [ -n "$name" ] || continue
  echo "zpool_health_info{pool=\"$name\",health=\"$health\"} 1"
  echo "zpool_capacity_percent{pool=\"$name\"} ${cap:-0}"
done
