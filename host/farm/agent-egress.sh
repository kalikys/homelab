#!/bin/bash
# VM 230: lock the agent container down. It may talk only to the egress proxy and Phoenix (traces);
# no direct internet, no n8n, no Postgres, no host, no LAN. Applied by farm-agent-egress.service after Docker.
set -euo pipefail
AGENT=172.30.0.10
PROXY=172.30.0.3
PHOENIX=172.30.0.4
modprobe br_netfilter
sysctl -q -w net.bridge.bridge-nf-call-iptables=1
iptables -N FARM-AGENT 2>/dev/null || true
iptables -F FARM-AGENT
iptables -A FARM-AGENT -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -A FARM-AGENT -d "$PROXY" -p tcp --dport 3128 -j RETURN
iptables -A FARM-AGENT -d "$PHOENIX" -p tcp -m multiport --dports 6006,4317 -j RETURN
iptables -A FARM-AGENT -j LOG --log-prefix "farm-agent-drop " --log-level 4 -m limit --limit 6/min
iptables -A FARM-AGENT -j DROP
iptables -C DOCKER-USER -s "$AGENT" -j FARM-AGENT 2>/dev/null || iptables -I DOCKER-USER 1 -s "$AGENT" -j FARM-AGENT
iptables -C INPUT -s "$AGENT" -m conntrack --ctstate NEW -j DROP 2>/dev/null || iptables -I INPUT 1 -s "$AGENT" -m conntrack --ctstate NEW -j DROP
echo "farm agent egress rules applied"
