#!/bin/sh
# Sums up contact clicks on kalik8s.com from the nginx events log (see the /e/ location in
# services/public/nginx/default.conf). Line format: time event source creative language country.
# Usage: scripts/site-events.sh [days] [log file]
set -eu

days="${1:-7}"
log="${2:-/opt/public/logs/events.log}"

[ -f "$log" ] || { echo "no events yet: $log"; exit 0; }

since="$(date -u -d "$days days ago" +%Y-%m-%d)"

awk -v since="$since" '
  substr($1, 1, 10) >= since { total++; by[$2 " " $3]++ }
  END {
    printf "contact clicks since %s: %d\n", since, total
    for (k in by) printf "%5d  %s\n", by[k], k
  }' "$log" | { read -r head; echo "$head"; sort -rn; }
