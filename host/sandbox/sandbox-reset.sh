#!/bin/sh
# Rolls the sandbox VM back to its clean snapshot. Installed to /usr/local/sbin, run from /etc/cron.d/sandbox-reset.
VMID=200
qm stop $VMID --skiplock 1 --timeout 30 >/dev/null 2>&1 || true
qm rollback $VMID clean
qm start $VMID
