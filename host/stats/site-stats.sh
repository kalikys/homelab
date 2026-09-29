#!/bin/sh
# Publishes anonymous lab stats for the CV site: host uptime, running guests, Docker containers in LXC 103, load average, Kubernetes lab VMs, live stream state.
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

# Kubernetes lab VMs for /lab/, under short public labels. VMIDs, hostnames and addresses stay out of the file.
lab=""
for pair in 210:cp 211:w1 212:w2; do
  id=${pair%%:*}
  label=${pair#*:}
  qm config "$id" >/dev/null 2>&1 || continue
  st=$(qm status "$id" | awk '{print $2}')
  up=0
  if [ "$st" = running ]; then
    up=$(qm status "$id" --verbose | awk '$1 == "uptime:" {print $2}')
  fi
  cores=$(qm config "$id" | awk '$1 == "cores:" {print $2}')
  mem=$(qm config "$id" | awk '$1 == "memory:" {print $2}')
  lab="$lab${lab:+, }{\"id\": \"$label\", \"status\": \"$st\", \"cpus\": ${cores:-1}, \"mem_gb\": $(( ${mem:-0} / 1024 )), \"uptime_seconds\": ${up:-0}}"
done

# asciinema live stream. The stream ID is public (it is part of the stream URL).
# asciinema.org has no status API, so the public stream page is checked for its LIVE marker.
stream=""
live=false
if [ -s /etc/lab/asciinema-stream ]; then
  stream=$(tr -cd 'A-Za-z0-9_-' < /etc/lab/asciinema-stream)
  if curl -fsS --max-time 10 "https://asciinema.org/s/$stream" 2>/dev/null | grep -q 'icon-live">LIVE'; then
    live=true
  fi
fi

cat > "$TMP" <<EOF
{
  "updated_at": "$now",
  "uptime_seconds": $uptime_s,
  "guests_running": $((ct_running + vm_running)),
  "guests_total": $((ct_total + vm_total)),
  "containers_running": $containers,
  "load": [$load1, $load5, $load15],
  "cpus": $cpus,
  "lab": [$lab],
  "live": {"on": $live, "stream": "$stream"}
}
EOF

pct push "$SITE_CT" "$TMP" "$DEST" --perms 644
