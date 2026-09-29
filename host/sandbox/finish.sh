#!/bin/bash
# Resume the build after provisioning, if build.sh stopped midway: provision, move to vmbr1, snapshot.
set -euo pipefail
VMID=200
BUILD_IP=192.168.1.30
DIR=$(cd "$(dirname "$0")" && pwd)
KEY=/root/.ssh/sandbox_build
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR builder@$BUILD_IP"

$SSH "sudo bash -s" < "$DIR/provision.sh"
for i in $(seq 1 60); do [ "$(qm status $VMID | awk '{print $2}')" = stopped ] && break; sleep 2; done
[ "$(qm status $VMID | awk '{print $2}')" = stopped ] || { echo "VM did not power off" >&2; exit 1; }

MAC=$(qm config $VMID | sed -n 's/^net0: virtio=\([^,]*\),.*/\1/p')
qm set $VMID --delete ide2,ciuser,sshkeys,ipconfig0,nameserver
qm set $VMID --net0 "virtio=$MAC,bridge=vmbr1,firewall=1,rate=5"
qm snapshot $VMID clean --description "Clean sandbox state, restored every 30 minutes"
qm start $VMID
rm -f $KEY $KEY.pub
echo "sandbox VM $VMID finished"
