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

cat > /etc/motd <<'EOF'

  Homelab sandbox: a throwaway Debian VM on Proxmox VE.

  - Isolated network: no internet, no access to other hosts.
  - 1 vCPU capped at 50%, 768 MB RAM, 6 GB disk.
  - Every session is its own throwaway container: you are root, nobody
    else sees your session, and it is gone when you close the tab.
  - A session lasts up to 15 minutes (5 minutes idle); the whole VM is
    rolled back to a clean snapshot every 30 minutes.

  Things to try: htop, uname -a, df -h, cat /etc/os-release

EOF

# --- Per-session containers (sourced by provision.sh inside the VM, as root) ---
# Every browser session gets its own throwaway container with root inside (see session.sh).
apt-get install -y -qq systemd-container debootstrap >/dev/null

# Base image for the containers: a small Debian 13 with the tools visitors try first.
BASE=/var/lib/machines/base
if [ ! -x "$BASE/bin/bash" ]; then
  debootstrap --variant=minbase --include=bash-completion,curl,htop,tree,jq,nano,less,procps,iproute2,iputils-ping,vim-tiny,python3,ncurses-term \
    trixie "$BASE" http://deb.debian.org/debian >/dev/null
fi
cp /etc/motd "$BASE/etc/motd"
echo sandbox > "$BASE/etc/hostname"
printf '%s\n' 'cat /etc/motd' '[ -f ~/.bashrc ] && . ~/.bashrc' > "$BASE/root/.bash_profile"
printf '%s\n' 'TMOUT=300' 'readonly TMOUT' 'export TMOUT' > "$BASE/etc/profile.d/zz-sandbox.sh"
rm -rf "$BASE/var/cache/apt/archives/"*.deb "$BASE/var/lib/apt/lists/"*

install -m 0755 /tmp/session.sh /usr/local/sbin/sandbox-session  # copied in by build.sh

# ttyd runs as an unprivileged user that may start exactly one root helper.
id ttyd >/dev/null 2>&1 || useradd -r -M -d /nonexistent -s /usr/sbin/nologin ttyd
echo 'ttyd ALL=(root) NOPASSWD: /usr/local/sbin/sandbox-session' > /etc/sudoers.d/sandbox-session
chmod 0440 /etc/sudoers.d/sandbox-session
visudo -cf /etc/sudoers.d/sandbox-session >/dev/null
userdel -r guest >/dev/null 2>&1 || true

# Nothing on the VM may trace another process.
echo 'kernel.yama.ptrace_scope = 2' > /etc/sysctl.d/90-sandbox.conf

cat > /etc/systemd/system/sandbox-shell.service <<'UNIT'
[Unit]
Description=Public sandbox web terminal (ttyd), one container per session
After=network-online.target
Wants=network-online.target

[Service]
User=ttyd
Group=ttyd
WorkingDirectory=/
Environment=TERM=xterm-256color
ExecStart=/usr/local/bin/ttyd --port 7681 --writable --max-clients 5 --ping-interval 30 -t fontSize=14 -t titleFixed=sandbox /usr/bin/sudo -n /usr/local/sbin/sandbox-session
Restart=always
RestartSec=2
# ttyd needs sudo for the helper, so NoNewPrivileges stays off for this unit only;
# the visitor runs in a separate container scope with its own limits.
ProtectKernelModules=yes
ProtectKernelLogs=yes
LockPersonality=yes
MemoryMax=600M
TasksMax=512

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable sandbox-shell.service >/dev/null
# --- end per-session containers ---

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
