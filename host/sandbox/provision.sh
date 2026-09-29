#!/bin/bash
# Runs inside the sandbox VM (as root) while it is still on the LAN.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# cloud-init runs its own apt on first boot and holds the lock until it finishes.
cloud-init status --wait >/dev/null 2>&1 || true

apt-get update -qq
apt-get install -y -qq curl htop tree jq nano less bash-completion procps iproute2 >/dev/null

# ttyd is not packaged in Debian 13: use the upstream static build, verified against the release checksums.
TTYD_VER=1.7.7
TTYD_URL=https://github.com/tsl0922/ttyd/releases/download/$TTYD_VER
TMP=$(mktemp -d)
curl -fsSL -o "$TMP/ttyd.x86_64" "$TTYD_URL/ttyd.x86_64"
curl -fsSL -o "$TMP/SHA256SUMS" "$TTYD_URL/SHA256SUMS"
(cd "$TMP" && grep " ttyd.x86_64\$" SHA256SUMS | sha256sum -c -)
install -m 0755 "$TMP/ttyd.x86_64" /usr/local/bin/ttyd
rm -rf "$TMP"

id guest >/dev/null 2>&1 || useradd -m -s /bin/bash guest
passwd -l guest >/dev/null

cat > /etc/motd <<'EOF'

  Homelab sandbox: a throwaway Debian VM on Proxmox VE.

  - Isolated network: no internet, no access to other hosts.
  - 1 vCPU capped at 50%, 768 MB RAM, 6 GB disk.
  - The whole VM is rolled back to a clean snapshot every 30 minutes.

  Things to try: htop, uname -a, df -h, cat /etc/os-release

EOF

cat > /home/guest/.bash_profile <<'EOF'
cat /etc/motd
[ -f ~/.bashrc ] && . ~/.bashrc
EOF
chown guest:guest /home/guest/.bash_profile

cat > /etc/systemd/system/sandbox-shell.service <<'EOF'
[Unit]
Description=Public sandbox web terminal (ttyd)
After=network-online.target
Wants=network-online.target

[Service]
User=guest
Group=guest
WorkingDirectory=/home/guest
Environment=TERM=xterm-256color
ExecStart=/usr/local/bin/ttyd --port 7681 --writable --max-clients 5 -t fontSize=14 -t titleFixed=sandbox /bin/bash --login
Restart=always
RestartSec=2

NoNewPrivileges=yes
RestrictSUIDSGID=yes
ProtectSystem=strict
ReadWritePaths=/home/guest
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
LockPersonality=yes
RestrictNamespaces=yes
TasksMax=128
MemoryMax=400M
CPUQuota=50%

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable sandbox-shell.service >/dev/null

# Static address on the isolated bridge; no gateway, no DNS.
rm -f /etc/netplan/*.yaml /etc/network/interfaces.d/*cloud-init* 2>/dev/null || true
if systemctl list-unit-files networking.service >/dev/null 2>&1; then
  printf 'auto lo\niface lo inet loopback\n' > /etc/network/interfaces
  systemctl disable networking.service >/dev/null 2>&1 || true
fi
mkdir -p /etc/systemd/network
cat > /etc/systemd/network/10-dmz.network <<'EOF'
[Match]
Name=e*

[Network]
Address=10.66.0.10/24
LinkLocalAddressing=no
IPv6AcceptRA=no
EOF
systemctl enable systemd-networkd >/dev/null 2>&1

# Nothing but the web terminal should be reachable or usable for escalation.
touch /etc/cloud/cloud-init.disabled
apt-get purge -y -qq openssh-server >/dev/null
rm -f /etc/sudoers.d/90-cloud-init-users
passwd -l root >/dev/null
passwd -l builder >/dev/null
usermod -s /usr/sbin/nologin builder
rm -rf /home/builder/.ssh

apt-get clean
systemd-run --quiet --on-active=5 /bin/systemctl poweroff
echo "provision done, powering off"
