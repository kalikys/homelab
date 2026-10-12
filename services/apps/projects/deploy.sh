#!/usr/bin/env bash
# Deploy the projects dashboard to LXC 103 (apps): sources -> /opt/projects, docker compose build, cron backup.
set -euo pipefail
cd "$(dirname "$0")"
CT=103
in_ct() { ssh homeserver "sudo pct exec $CT -- bash -lc $(printf %q "$1")"; }

COPYFILE_DISABLE=1 tar --no-xattrs -czf - \
  --exclude=data --exclude=.secrets --exclude=.venv --exclude=web/node_modules --exclude=web/dist \
  --exclude=__pycache__ --exclude=.pytest_cache --exclude=tests --exclude=client \
  . | ssh homeserver "sudo pct exec $CT -- bash -c 'mkdir -p /opt/projects/data && tar -xzf - -C /opt/projects'"

in_ct 'cd /opt/projects && docker compose up -d --build 2>&1 | tail -3'
in_ct 'echo "30 3 * * * root docker exec projects python /app/backup.py >/dev/null 2>&1" > /etc/cron.d/projects-backup && chmod 644 /etc/cron.d/projects-backup'
for i in $(seq 1 20); do
  if in_ct 'curl -sf localhost:8790/api/health' >/dev/null 2>&1; then echo "health: ok"; break; fi
  sleep 2
  [ "$i" = 20 ] && { echo "health: FAILED"; in_ct 'docker logs --tail 30 projects'; exit 1; }
done
python3 npm_proxy.py
