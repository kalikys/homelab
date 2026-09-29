#!/bin/bash
# Kubernetes lab VMs (210-212): start, stop, roll back, snapshot. Installed to /usr/local/sbin/lab, run with sudo.
#   lab up | down | status | reset <snapshot> | snapshot <name>
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin

VMS=(210 211 212)

state() { qm status "$1" | awk '{print $2}'; }

up() {
  for id in "${VMS[@]}"; do
    [ "$(state "$id")" = running ] || qm start "$id"
  done
}

down() {
  for id in "${VMS[@]}"; do
    [ "$(state "$id")" = stopped ] || qm shutdown "$id" --timeout 120 --forceStop 1
  done
}

status() {
  for id in "${VMS[@]}"; do
    printf '%s\t%s\t%s\n' "$id" "$(qm config "$id" | sed -n 's/^name: //p')" "$(state "$id")"
  done
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  status) status ;;
  reset)
    snap=${2:?usage: lab reset <snapshot>}
    down
    for id in "${VMS[@]}"; do qm rollback "$id" "$snap"; done
    up
    ;;
  snapshot)
    name=${2:?usage: lab snapshot <name>}
    down
    for id in "${VMS[@]}"; do
      qm listsnapshot "$id" | grep -qw "$name" && qm delsnapshot "$id" "$name"
      qm snapshot "$id" "$name" --description "lab snapshot $name, $(date -I)"
    done
    ;;
  *)
    echo "usage: lab up|down|status|reset <snapshot>|snapshot <name>" >&2
    exit 2
    ;;
esac
