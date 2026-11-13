#!/usr/bin/env bash
# GitOps deploy of the projects dashboard on LXC 103, every 5 minutes from projects-deploy.timer.
#
# Fetches main of the public repo kalikys/homelab into /opt/projects-repo. On a new commit it copies
# services/apps/projects/ into /opt/projects (data/, ts-state/ and .env are never touched; tests/ and client/
# are not shipped, as in deploy.sh), rebuilds with docker compose, checks /api/health and restores the previous
# code if the check fails. Reinstalls itself after a deploy. FORCE=1 deploys even if the commit is live.
set -euo pipefail

REPO=/opt/projects-repo
LIVE=/opt/projects
STATE=/opt/.projects-deployed-sha
PREV=/opt/projects-prev.tgz
SKIP=(--exclude=./data --exclude=./ts-state --exclude=./.env --exclude=./web/node_modules --exclude=./web/dist
      --exclude=./tests --exclude=./client --exclude=./autodeploy --exclude='*.bak*' --exclude=__pycache__)

health() {
    for _ in $(seq 1 30); do curl -fsS -m 5 localhost:8790/api/health >/dev/null 2>&1 && return 0; sleep 3; done
    return 1
}
up() { (cd "$LIVE" && docker compose up -d --build >/dev/null 2>&1); }

[ -d "$REPO/.git" ] || git clone -q https://github.com/kalikys/homelab.git "$REPO"
git -C "$REPO" fetch -q origin main
sha=$(git -C "$REPO" rev-parse FETCH_HEAD)
[ "$sha" != "$(cat "$STATE" 2>/dev/null)" ] || [ "${FORCE:-0}" = 1 ] || exit 0
git -C "$REPO" checkout -q --force --detach "$sha"
src=$REPO/services/apps/projects
if [ ! -f "$src/projects_api/autopilot.py" ]; then
    echo "main@${sha:0:7} has no autopilot.py yet: it predates the dashboard sync, nothing deployed"
    exit 0
fi

(cd "$LIVE" && tar "${SKIP[@]}" -czf "$PREV" .)
(cd "$src" && tar "${SKIP[@]}" -cf - .) | (cd "$LIVE" && tar -xf -)

if up && health; then
    echo "$sha" > "$STATE"
    install -m 0755 "$src/autodeploy/projects-deploy.sh" /usr/local/sbin/projects-deploy
    echo "deployed main@${sha:0:7}"
else
    (cd "$LIVE" && tar -xzf "$PREV")
    up && health && echo "main@${sha:0:7} failed /api/health, previous code restored" \
        || echo "main@${sha:0:7} failed /api/health and the rollback did not come up either"
    exit 1
fi
