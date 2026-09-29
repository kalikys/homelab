#!/bin/bash
# Prepares VM 220 for Hermes Agent: service user without sudo, rootless Docker for the agent's terminal backend.
# Run as root over SSH from the Mac: ssh agent 'sudo bash -s' < host/agent/provision.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

cloud-init status --wait >/dev/null || true
apt-get update -q
apt-get -y -q upgrade
apt-get install -y -q qemu-guest-agent unattended-upgrades git curl tar ca-certificates build-essential \
  uidmap dbus-user-session slirp4netns fuse-overlayfs
systemctl start qemu-guest-agent
timedatectl set-timezone Asia/Tbilisi

# Docker from Docker's repository: Ubuntu's docker.io lacks the rootless setup tool (docker-ce-rootless-extras).
apt-get remove -y -q docker.io >/dev/null 2>&1 || true
install -d -m 755 /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt-get update -q
apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-ce-rootless-extras

# The system Docker daemon is not used: the agent gets rootless Docker under its own user.
systemctl disable --now docker.service docker.socket

id hermes >/dev/null 2>&1 || useradd --create-home --shell /bin/bash hermes
loginctl enable-linger hermes
install -d -o hermes -g hermes -m 700 /home/hermes/work /home/hermes/secrets

# Rootless Docker for hermes (per-user systemd service). The single-quoted parts expand in the hermes shell.
# shellcheck disable=SC2016
sudo -iu hermes bash -lc 'export XDG_RUNTIME_DIR=/run/user/$(id -u); dockerd-rootless-setuptool.sh install --skip-iptables'
# shellcheck disable=SC2016
sudo -iu hermes bash -lc 'export XDG_RUNTIME_DIR=/run/user/$(id -u); systemctl --user enable --now docker; DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock docker run --rm hello-world >/dev/null && echo rootless docker ok'

# shellcheck disable=SC2016
grep -q DOCKER_HOST /home/hermes/.bashrc || echo 'export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock' >> /home/hermes/.bashrc
echo "provisioned $(hostname)"
