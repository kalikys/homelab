#!/bin/bash
# Prepares VM 230 for the startup farm: Docker Engine + compose plugin, guest agent, unattended upgrades.
# Run as root over SSH: ssh farm 'sudo bash -s' < host/farm/provision.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

cloud-init status --wait >/dev/null || true
apt-get update -q
apt-get -y -q upgrade
apt-get install -y -q qemu-guest-agent unattended-upgrades git curl jq ca-certificates restic postgresql-client
systemctl start qemu-guest-agent
timedatectl set-timezone Asia/Tbilisi

install -d -m 755 /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt-get update -q
apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker

install -d -m 750 -o root -g root /opt/farm
echo "provisioned $(hostname)"
