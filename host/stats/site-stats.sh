#!/bin/sh
# Publishes anonymous lab stats for the CV site: host uptime, running guests, Docker containers in LXC 103, load average.
# No addresses or internal names end up in the file. Installed to /usr/local/sbin, run from /etc/cron.d/site-stats.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin

SITE_CT=104
APPS_CT=103
DEST=/opt/public/site/data/stats.json
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

uptime_s=$(cut -d' ' -f1 /proc/uptime | cut -d. -f1)
read -r load1 load5 load15 _ < /proc/loadavg
ct_running=$(pct list | awk 'NR > 1 && $2 == "running"' | wc -l)
ct_total=$(pct list | awk 'NR > 1' | wc -l)
vm_running=$(qm list | awk 'NR > 1 && $3 == "running"' | wc -l)
vm_total=$(qm list | awk 'NR > 1' | wc -l)
containers=$(pct exec "$APPS_CT" -- docker ps -q 2>/dev/null | wc -l || echo 0)
cpus=$(nproc)
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)

cat > "$TMP" <<EOF
{
  "updated_at": "$now",
  "uptime_seconds": $uptime_s,
  "guests_running": $((ct_running + vm_running)),
  "guests_total": $((ct_total + vm_total)),
  "containers_running": $containers,
  "load": [$load1, $load5, $load15],
  "cpus": $cpus
}
EOF

pct push "$SITE_CT" "$TMP" "$DEST" --perms 644
