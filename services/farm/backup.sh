#!/bin/bash
# Nightly farm backup on VM 230: pg_dumpall + farm config + agent work (briefs, memos, decks) into an encrypted restic repo on R2.
# Installed as /opt/farm/backup.sh, run by /etc/cron.d/farm-backup. Secrets: /opt/farm/backup.env.
set -euo pipefail
set -a; . /opt/farm/.env; . /opt/farm/backup.env; set +a
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
docker exec farm-postgres-1 pg_dumpall -U "$POSTGRES_USER" | gzip > "$work/pg_dumpall.sql.gz"
cp /opt/farm/.env "$work/farm.env"
cp /opt/farm/compose.yaml "$work/"
tar -C /var/lib/docker/volumes/farm_agentwork/_data -czf "$work/agentwork.tgz" . 2>/dev/null || true
restic backup --quiet --tag farm "$work"
restic forget --quiet --tag farm --keep-daily 14 --keep-weekly 8 --prune
[ -n "${HC_PING_URL:-}" ] && curl -fsS -m 10 "$HC_PING_URL" >/dev/null || true
echo "farm backup ok $(date -Is)"
