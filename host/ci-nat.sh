#!/bin/bash
# Proxmox host: internet for the CI bridge vmbr9 (10.99.0.0/24), and nothing else.
#   * job VMs reach the internet through MASQUERADE on the LAN uplink (the Keenetic does the second NAT);
#   * no forwarding to private/LAN ranges (192.168.1.0/24 included), no new connections from the LAN into vmbr9;
#   * the host itself (10.99.0.1, 192.168.1.52, the Proxmox API, ssh) is unreachable from vmbr9;
#   * no IPv6 on vmbr9 at all (otherwise the host's link-local address would expose pveproxy/ssh).
# The manager VM 290 talks to job VMs inside the bridge (L2, never routed by the host); host/firewall/290.fw guards it.
# WAN side: the uplink is double NAT (ISP router, then Keenetic) and this relies on the Keenetic having NO port
# forwards to LAN hosts and NAT loopback (hairpin) OFF; otherwise a job VM could reach a LAN service through the
# home's public IP. To also block that IP explicitly, list it (space-separated IPv4 CIDRs) in CI_EXTRA_DROP, e.g. in
# /etc/default/ci-nat:  CI_EXTRA_DROP="203.0.113.7/32"   (read by host/systemd/ci-nat.service).
#
# Fail closed:
#   * CI_EXTRA_DROP is validated before any rule or sysctl is touched; a bad word exits 1 and changes no rule
#     (if no isolation rules exist yet, e.g. at boot, vmbr9 is taken down instead of being left open);
#   * protective parts go first (IPv6 drops, then CI-HOST + its INPUT hook), forwarding parts after;
#   * every CI-* chain is first reduced to a single DROP and then filled by inserting above that DROP, so at any
#     point of an aborted run the chain ends in DROP; IPv4 forwarding is switched on only as the very last step;
#   * any error after validation takes vmbr9 down (job VMs and the manager lose the bridge) and exits non-zero,
#     which also marks ci-nat.service failed: check `systemctl is-failed ci-nat` after boot.
# Idempotent. `ci-nat.sh --check` only verifies. Installed as /usr/local/sbin/ci-nat.sh.
set -Eeuo pipefail

BR=${CI_BRIDGE:-vmbr9}
NET=${CI_NET:-10.99.0.0/24}
WAN=${CI_WAN:-vmbr0}
PRIVATE=(10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16 224.0.0.0/4 240.0.0.0/4)
IPT=(iptables -w)
IP6T=(ip6tables -w)

# --- validation: nothing has been touched yet -----------------------------------------------------------------
valid_cidr() {
  local w=$1 ip o
  [[ $w =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}(/([0-9]|[12][0-9]|3[0-2]))?$ ]] || return 1
  ip=${w%%/*}
  IFS=. read -r -a o <<<"$ip"
  for x in "${o[@]}"; do
    [[ $x =~ ^(0|[1-9][0-9]{0,2})$ ]] && [ "$x" -le 255 ] || return 1
  done
}
read -r -a EXTRA <<<"${CI_EXTRA_DROP:-}"
for w in ${EXTRA[@]+"${EXTRA[@]}"}; do
  if ! valid_cidr "$w"; then
    echo "ci-nat: CI_EXTRA_DROP has an invalid entry '$w' (want IPv4 CIDRs separated by spaces); no rules changed" >&2
    # Previous good rules stay as they are. With no rules at all (e.g. at boot) the host would be open to vmbr9,
    # so then the bridge goes down instead.
    if [ "${1:-}" != "--check" ] && ! "${IPT[@]}" -C INPUT -i "$BR" -j CI-HOST 2>/dev/null; then
      echo "ci-nat: no isolation rules present; taking $BR down" >&2
      ip link set dev "$BR" down 2>/dev/null || true
    fi
    exit 1
  fi
done

# --- check mode -----------------------------------------------------------------------------------------------
if [ "${1:-}" = "--check" ]; then
  ok=1
  miss() { echo "missing: $*"; ok=0; }
  "${IPT[@]}" -C FORWARD -i "$BR" -j CI-OUT 2>/dev/null || miss "FORWARD -i $BR -> CI-OUT"
  "${IPT[@]}" -C FORWARD -o "$BR" -j CI-IN 2>/dev/null || miss "FORWARD -o $BR -> CI-IN"
  "${IPT[@]}" -C INPUT -i "$BR" -j CI-HOST 2>/dev/null || miss "INPUT -i $BR -> CI-HOST"
  for c in CI-OUT CI-IN CI-HOST; do
    [ "$("${IPT[@]}" -S "$c" 2>/dev/null | tail -n 1)" = "-A $c -j DROP" ] || miss "$c does not end in DROP"
  done
  for dst in "${PRIVATE[@]}" ${EXTRA[@]+"${EXTRA[@]}"}; do
    "${IPT[@]}" -C CI-OUT -d "$dst" -j DROP 2>/dev/null || miss "CI-OUT DROP for $dst"
  done
  "${IPT[@]}" -t nat -C POSTROUTING -s "$NET" -o "$WAN" -j MASQUERADE 2>/dev/null || miss "MASQUERADE"
  "${IP6T[@]}" -C INPUT -i "$BR" -j DROP 2>/dev/null || miss "ip6 INPUT drop"
  "${IP6T[@]}" -C FORWARD -i "$BR" -j DROP 2>/dev/null || miss "ip6 FORWARD -i drop"
  "${IP6T[@]}" -C FORWARD -o "$BR" -j DROP 2>/dev/null || miss "ip6 FORWARD -o drop"
  [ "$(sysctl -n net.ipv4.ip_forward)" = 1 ] || miss "ip_forward=1"
  [ "$ok" = 1 ] && echo "ci-nat: rules in place"
  [ "$ok" = 1 ]
  exit
fi

ip link show "$BR" >/dev/null 2>&1 || { echo "ci-nat: bridge $BR does not exist (see services/ci-runner/README.md)" >&2; exit 1; }

# From here on, any failure closes the bridge instead of leaving it half-protected.
trap 'echo "ci-nat: FAILED at line $LINENO; taking $BR down so job VMs cannot reach anything" >&2; ip link set dev "$BR" down || true' ERR

closed_chain() {  # create, or reduce to a single DROP without ever being empty
  "${IPT[@]}" -N "$1" 2>/dev/null || true
  "${IPT[@]}" -I "$1" 1 -j DROP
  while "${IPT[@]}" -D "$1" 2 2>/dev/null; do :; done
}
add() {  # add a rule just above the chain's final DROP
  local chain=$1 n
  shift
  n=$("${IPT[@]}" -S "$chain" | grep -c '^-A ')
  "${IPT[@]}" -I "$chain" "$n" "$@"
}
hook() {  # insert a jump at the top once
  "${IPT[@]}" -C "$@" 2>/dev/null || "${IPT[@]}" -I "$1" 1 "${@:2}"
}

# 1. IPv6: none on this bridge, in any direction.
sysctl -q -w "net.ipv6.conf.$BR.disable_ipv6=1"
"${IP6T[@]}" -C INPUT -i "$BR" -j DROP 2>/dev/null || "${IP6T[@]}" -I INPUT 1 -i "$BR" -j DROP
"${IP6T[@]}" -C FORWARD -i "$BR" -j DROP 2>/dev/null || "${IP6T[@]}" -I FORWARD 1 -i "$BR" -j DROP
"${IP6T[@]}" -C FORWARD -o "$BR" -j DROP 2>/dev/null || "${IP6T[@]}" -I FORWARD 1 -o "$BR" -j DROP

# 2. The host itself, on any of its addresses: replies only (job VMs use public DNS, static IPs, no DHCP).
closed_chain CI-HOST
hook INPUT -i "$BR" -j CI-HOST
add CI-HOST -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
add CI-HOST -m limit --limit 6/min -j LOG --log-prefix "ci-drop-host " --log-level 4

# 3. Routed traffic entering the CI bridge: only replies to what the job VMs started.
closed_chain CI-IN
hook FORWARD -o "$BR" -j CI-IN
add CI-IN -s "$NET" -d "$NET" -j RETURN
add CI-IN -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# 4. Routed traffic leaving the CI bridge. The ACCEPT to the uplink goes in last, after every DROP.
closed_chain CI-OUT
hook FORWARD -i "$BR" -j CI-OUT
add CI-OUT -s "$NET" -d "$NET" -j RETURN   # bridged job <-> manager frames (br_netfilter); not routed
add CI-OUT ! -s "$NET" -j DROP              # spoofed source
for dst in "${PRIVATE[@]}" ${EXTRA[@]+"${EXTRA[@]}"}; do
  add CI-OUT -d "$dst" -m limit --limit 6/min -j LOG --log-prefix "ci-drop-lan " --log-level 4
  add CI-OUT -d "$dst" -j DROP
done
add CI-OUT -o "$WAN" -j ACCEPT

# 5. NAT, anti-spoofing, and only then forwarding.
"${IPT[@]}" -t nat -C POSTROUTING -s "$NET" -o "$WAN" -j MASQUERADE 2>/dev/null \
  || "${IPT[@]}" -t nat -A POSTROUTING -s "$NET" -o "$WAN" -j MASQUERADE
sysctl -q -w "net.ipv4.conf.$BR.rp_filter=1"
sysctl -q -w net.ipv4.ip_forward=1

trap - ERR
echo "ci-nat: $NET on $BR -> internet via $WAN; LAN and host blocked${EXTRA[*]:+; also dropped: ${EXTRA[*]}}"
