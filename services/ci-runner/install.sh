#!/bin/bash
# Installs the custom executor, the reaper and the runner config on VM 290 `ci-runner`. Idempotent; re-run after changes.
# From the Mac, in the homelab checkout:
#   scp -r services/ci-runner ci-runner:/tmp/ && ssh ci-runner 'sudo bash /tmp/ci-runner/install.sh'
# Secrets are never copied by this script; the owner places them (see README "Secrets on the manager").
set -euo pipefail
SRC=$(cd "$(dirname "$0")" && pwd)
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
command -v gitlab-runner >/dev/null || { echo "gitlab-runner missing: cloud-init (cloud-init-manager.yaml) has not finished" >&2; exit 1; }

install -d -m 0755 /opt/ci-runner /opt/ci-runner/executor
install -m 0755 "$SRC"/executor/{prepare.sh,run.sh,cleanup.sh,pvejob.py} /opt/ci-runner/executor/
install -m 0644 "$SRC"/executor/common.sh /opt/ci-runner/executor/
install -d -m 0700 /etc/ci-runner /etc/ci-runner/ssh /var/lib/ci-runner /var/lib/ci-runner/jobs

# The manager's key for job VMs. Generated here, never leaves this VM; pvejob.py puts the public half into each clone.
if [ ! -f /etc/ci-runner/ssh/id_ed25519 ]; then
  ssh-keygen -q -t ed25519 -N '' -C "ci-runner-290 job key" -f /etc/ci-runner/ssh/id_ed25519
fi

install -m 0644 "$SRC/reaper.service" /etc/systemd/system/ci-reaper.service
install -m 0644 "$SRC/reaper.timer" /etc/systemd/system/ci-reaper.timer
systemctl daemon-reload

missing=()
for f in /etc/ci-runner/pve-token /etc/ci-runner/pve-root-ca.pem /etc/ci-runner/runner-token; do
  [ -s "$f" ] || missing+=("$f")
done
for f in /etc/ci-runner/pve-token /etc/ci-runner/runner-token; do
  if [ -e "$f" ]; then chown root:root "$f"; chmod 0600 "$f"; fi
done

if [ -s /etc/ci-runner/runner-token ]; then
  token=$(tr -d '[:space:]' < /etc/ci-runner/runner-token)
  if ! [[ $token =~ ^glrt-[A-Za-z0-9._-]{10,}$ ]]; then
    echo "/etc/ci-runner/runner-token must hold a runner authentication token (glrt-...)" >&2
    exit 1
  fi
  umask 077
  install -d -m 0700 /etc/gitlab-runner
  tmp=$(mktemp /etc/gitlab-runner/.config.XXXXXX)
  # Substituted in bash, so the token never shows up in a process's argv.
  tmpl=$(< "$SRC/config.toml.tmpl")
  printf '%s\n' "${tmpl//__RUNNER_TOKEN__/$token}" > "$tmp"
  chmod 0600 "$tmp"
  mv "$tmp" /etc/gitlab-runner/config.toml
  unset token
  systemctl enable gitlab-runner >/dev/null 2>&1 || true
  systemctl restart gitlab-runner
  gitlab-runner verify >/dev/null && echo "runner config installed and verified"
fi

if [ ${#missing[@]} -eq 0 ]; then
  systemctl enable --now ci-reaper.timer
  echo "reaper timer enabled"
else
  echo "still missing (see services/ci-runner/README.md): ${missing[*]}"
fi
echo "job key (goes into every job VM via pvejob.py): $(cat /etc/ci-runner/ssh/id_ed25519.pub)"
