#!/usr/bin/env bash
# Deploy kalik8s.com from origin/main right now, instead of waiting for the 5-minute autodeploy timer.
#
# The site is built and synced on the `public` container (LXC 104) from git only — see autodeploy/README.md.
# Local, unpushed changes cannot be deployed on purpose: merge them first.
#   ./deploy.sh                 # origin/main
#   BRANCH=feat/x ./deploy.sh   # preview a pushed branch on the live site (the timer returns it to main)
set -euo pipefail

REMOTE="${REMOTE:-homeserver}"   # pve host (NOPASSWD sudo -> pct)
CT="${CT:-104}"                  # `public` container

ssh "$REMOTE" "sudo -n pct exec $CT -- env FORCE=1 BRANCH=${BRANCH:-main} /usr/local/sbin/public-site-deploy"
