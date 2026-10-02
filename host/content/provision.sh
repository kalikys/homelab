#!/bin/bash
# Prepares VM 250 for the content pipeline: service user without sudo, Node, ffmpeg, headless Chromium, Python.
# Run as root over SSH from the Proxmox host: ssh content 'sudo bash -s' < host/content/provision.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

cloud-init status --wait >/dev/null || true
apt-get update -q
apt-get -y -q upgrade
apt-get install -y -q qemu-guest-agent unattended-upgrades git curl ca-certificates gnupg rsync jq sqlite3 \
  ffmpeg python3 python3-numpy python3-yaml fonts-noto-color-emoji
systemctl start qemu-guest-agent
timedatectl set-timezone Asia/Tbilisi

# Node 22 from NodeSource: Ubuntu 24.04 ships Node 18, too old for the Playwright version the project pins.
install -d -m 755 /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/nodesource.gpg
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list >/dev/null
apt-get update -q
apt-get install -y -q nodejs

id content >/dev/null 2>&1 || useradd --create-home --shell /bin/bash content
loginctl enable-linger content
install -d -o content -g content -m 700 /opt/content /opt/content/secrets
install -d -o content -g content -m 755 /opt/content/app /opt/content/state /opt/content/logs

# System libraries for headless Chromium; the browser itself is installed by the project as the content user.
npx --yes playwright@1.63.0 install-deps chromium

echo "provisioned $(hostname): node $(node -v), ffmpeg $(ffmpeg -version | head -1 | cut -d' ' -f3), python $(python3 -V | cut -d' ' -f2)"
