#!/bin/sh
# Sums up kalik8s.com events from the nginx events log (see the /e/ location in
# services/public/nginx/default.conf). Line format: time event source creative language country.
# Contact clicks are counted by event and source; reach_<chapter> events (sent by motion.js once
# per page view when a chapter comes into view) are shown as a scroll funnel in chapter order.
# Usage: scripts/site-events.sh [days] [log file]
set -eu

days="${1:-7}"
log="${2:-/opt/public/logs/events.log}"

[ -f "$log" ] || { echo "no events yet: $log"; exit 0; }

since="$(date -u -d "$days days ago" +%Y-%m-%d)"

awk -v since="$since" '
  substr($1, 1, 10) < since { next }
  $2 ~ /^(reach_|cv_curl$|cv_json$|cv_link$)/ { next }
  { total++; by[$2 " " $3]++ }
  END {
    printf "contact clicks since %s: %d\n", since, total
    for (k in by) printf "%5d  %s\n", by[k], k
  }' "$log" | { read -r head; echo "$head"; sort -rn; }

awk -v since="$since" '
  substr($1, 1, 10) >= since && $2 ~ /^reach_/ { n[$2]++ }
  END {
    print ""
    print "scroll funnel (page views that reached each chapter):"
    split("payload flightlog origin ground contact", order, " ")
    for (i = 1; i <= 5; i++) printf "%5d  %s\n", n["reach_" order[i]] + 0, order[i]
  }' "$log"

awk -v since="$since" '
  substr($1, 1, 10) >= since && ($2 == "cv_curl" || $2 == "cv_json" || $2 == "cv_link") { n[$2]++ }
  END {
    print ""
    print "terminal CV (curl kalik8s.com/cv, /cv.json) and browser clicks on the /cv short link:"
    printf "%5d  cv_curl\n%5d  cv_json\n%5d  cv_link\n", n["cv_curl"] + 0, n["cv_json"] + 0, n["cv_link"] + 0
  }' "$log"
