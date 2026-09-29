#!/bin/bash
# Builds the public sandbox VM on the Proxmox host. Run as root.
# The VM is provisioned on the LAN, then moved to the isolated bridge vmbr1 and snapshotted as "clean".
set -euo pipefail

VMID=200
BUILD_IP=192.168.1.30
DIR=$(cd "$(dirname "$0")" && pwd)
IMG_DIR=/var/lib/vz/sandbox
IMG=$IMG_DIR/debian-13-genericcloud-amd64.qcow2
BASE=https://cloud.debian.org/images/cloud/trixie/latest
KEY=/root/.ssh/sandbox_build
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR builder@$BUILD_IP"

if qm config $VMID >/dev/null 2>&1; then
  echo "VM $VMID already exists, remove it first: qm destroy $VMID --purge" >&2
  exit 1
fi

mkdir -p $IMG_DIR
wget -q -O $IMG "$BASE/debian-13-genericcloud-amd64.qcow2"
wget -q -O $IMG_DIR/SHA512SUMS "$BASE/SHA512SUMS"
(cd $IMG_DIR && grep " debian-13-genericcloud-amd64.qcow2\$" SHA512SUMS | sha512sum -c -)

rm -f $KEY $KEY.pub
ssh-keygen -q -t ed25519 -N "" -C sandbox-build -f $KEY

qm create $VMID --name sandbox \
  --description "Public sandbox: web terminal on the isolated bridge vmbr1, rolled back every 30 min" \
  --ostype l26 --machine q35 --cpu x86-64-v2-AES --cores 1 --cpulimit 0.5 \
  --memory 768 --balloon 0 --scsihw virtio-scsi-single \
  --net0 virtio,bridge=vmbr0,firewall=0,rate=5 \
  --serial0 socket --vga serial0 --tablet 0 --agent 0 \
  --onboot 1 --startup order=6
qm set $VMID --scsi0 "local-zfs:0,import-from=$IMG,iothread=1,discard=on,mbps_rd=40,mbps_wr=20,iops_rd=400,iops_wr=200"
qm resize $VMID scsi0 6G
qm set $VMID --ide2 local-zfs:cloudinit --boot order=scsi0 \
  --ciuser builder --sshkeys $KEY.pub \
  --ipconfig0 ip=$BUILD_IP/24,gw=192.168.1.1 --nameserver 192.168.1.2

qm start $VMID
for i in $(seq 1 60); do $SSH true 2>/dev/null && break; sleep 5; done
$SSH true

$SSH "sudo bash -s" < "$DIR/provision.sh"
for i in $(seq 1 60); do [ "$(qm status $VMID | awk '{print $2}')" = stopped ] && break; sleep 2; done
if [ "$(qm status $VMID | awk '{print $2}')" != stopped ]; then
  echo "VM did not power off after provisioning" >&2
  exit 1
fi

MAC=$(qm config $VMID | sed -n 's/^net0: virtio=\([^,]*\),.*/\1/p')
qm set $VMID --delete ide2,ciuser,sshkeys,ipconfig0,nameserver
qm set $VMID --net0 "virtio=$MAC,bridge=vmbr1,firewall=1,rate=5"
qm snapshot $VMID clean --description "Clean sandbox state, restored every 30 minutes"
qm start $VMID

rm -f $KEY $KEY.pub
echo "sandbox VM $VMID built"
