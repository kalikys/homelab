#!/bin/bash
# Proxmox host: internet for the CI bridge vmbr9 (10.99.0.0/24), and nothing else.
#   * job VMs reach the internet through MASQUERADE on the LAN uplink (the Keenetic does the second NAT);
#   * no forwarding to private/LAN ranges (192.168.1.0/24 included), no new connections from the LAN into vmbr9;
#   * the host itself (10.99.0.1, 192.168.1.52, the Proxmox API, ssh) is unreachable from vmbr9;
#   * no IPv6 on vmbr9 at all (otherwise the host's link-local address would expose pveproxy/ssh).
# The manager VM 290 talks to job VMs inside the bridge (L2, never routed by the host); host/firewall/290.fw guards it.
# Idempotent: own chains are flushed and refilled, hooks are added once. `ci-nat.sh --check` only verifies.
# Installed as /usr/local/sbin/ci-nat.sh, run at boot by host/systemd/ci-nat.service.
set -euo pipefail

BR=${CI_BRIDGE:-vmbr9}
NET=${CI_NET:-10.99.0.0/24}
WAN=${CI_WAN:-vmbr0}
PRIVATE=(10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16 224.0.0.0/4 240.0.0.0/4)
IPT=(iptables -w)
IP6T=(ip6tables -w)

if [ "${1:-}" = "--check" ]; then
  ok=1
  "${IPT[@]}" -C FORWARD -i "$BR" -j CI-OUT 2>/dev/null || { echo "missing: FORWARD -i $BR -> CI-OUT"; ok=0; }
  "${IPT[@]}" -C FORWARD -o "$BR" -j CI-IN 2>/dev/null || { echo "missing: FORWARD -o $BR -> CI-IN"; ok=0; }
  "${IPT[@]}" -C INPUT -i "$BR" -j CI-HOST 2>/dev/null || { echo "missing: INPUT -i $BR -> CI-HOST"; ok=0; }
  "${IPT[@]}" -t nat -C POSTROUTING -s "$NET" -o "$WAN" -j MASQUERADE 2>/dev/null || { echo "missing: MASQUERADE"; ok=0; }
  "${IP6T[@]}" -C INPUT -i "$BR" -j DROP 2>/dev/null || { echo "missing: ip6 INPUT drop"; ok=0; }
  [ "$(sysctl -n net.ipv4.ip_forward)" = 1 ] || { echo "ip_forward is off"; ok=0; }
  [ "$ok" = 1 ] && echo "ci-nat: rules in place"
  [ "$ok" = 1 ]
  exit
fi

ip link show "$BR" >/dev/null 2>&1 || { echo "bridge $BR does not exist (see services/ci-runner/README.md)" >&2; exit 1; }

sysctl -q -w net.ipv4.ip_forward=1
sysctl -q -w "net.ipv4.conf.$BR.rp_filter=1"
sysctl -q -w "net.ipv6.conf.$BR.disable_ipv6=1"

chain() {  # create or flush
  "${IPT[@]}" -N "$1" 2>/dev/null || "${IPT[@]}" -F "$1"
}
hook() {  # insert a rule at the top once
  "${IPT[@]}" -C "$@" 2>/dev/null || "${IPT[@]}" -I "$1" 1 "${@:2}"
}

# Routed traffic leaving the CI bridge.
chain CI-OUT
"${IPT[@]}" -A CI-OUT -s "$NET" -d "$NET" -j RETURN   # bridged job <-> manager frames (br_netfilter); not routed
"${IPT[@]}" -A CI-OUT ! -s "$NET" -j DROP              # spoofed source
for dst in "${PRIVATE[@]}"; do
  "${IPT[@]}" -A CI-OUT -d "$dst" -m limit --limit 6/min -j LOG --log-prefix "ci-drop-lan " --log-level 4
  "${IPT[@]}" -A CI-OUT -d "$dst" -j DROP
done
"${IPT[@]}" -A CI-OUT -o "$WAN" -j ACCEPT
"${IPT[@]}" -A CI-OUT -j DROP

# Routed traffic entering the CI bridge: only replies to what the job VMs started.
chain CI-IN
"${IPT[@]}" -A CI-IN -s "$NET" -d "$NET" -j RETURN
"${IPT[@]}" -A CI-IN -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
"${IPT[@]}" -A CI-IN -j DROP

# The host itself, on any of its addresses: replies only (job VMs use public DNS, static IPs, no DHCP).
chain CI-HOST
"${IPT[@]}" -A CI-HOST -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
"${IPT[@]}" -A CI-HOST -m limit --limit 6/min -j LOG --log-prefix "ci-drop-host " --log-level 4
"${IPT[@]}" -A CI-HOST -j DROP

hook FORWARD -i "$BR" -j CI-OUT
hook FORWARD -o "$BR" -j CI-IN
hook INPUT -i "$BR" -j CI-HOST
"${IPT[@]}" -t nat -C POSTROUTING -s "$NET" -o "$WAN" -j MASQUERADE 2>/dev/null \
  || "${IPT[@]}" -t nat -A POSTROUTING -s "$NET" -o "$WAN" -j MASQUERADE

# IPv6: none on this bridge, in any direction.
"${IP6T[@]}" -C INPUT -i "$BR" -j DROP 2>/dev/null || "${IP6T[@]}" -I INPUT 1 -i "$BR" -j DROP
"${IP6T[@]}" -C FORWARD -i "$BR" -j DROP 2>/dev/null || "${IP6T[@]}" -I FORWARD 1 -i "$BR" -j DROP
"${IP6T[@]}" -C FORWARD -o "$BR" -j DROP 2>/dev/null || "${IP6T[@]}" -I FORWARD 1 -o "$BR" -j DROP

echo "ci-nat: $NET on $BR -> internet via $WAN; LAN and host blocked"
