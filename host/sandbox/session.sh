#!/bin/bash
# /usr/local/sbin/sandbox-session: one throwaway container per browser session, like Killercoda.
# ttyd (user "ttyd") starts it through sudo. The visitor gets root inside a fresh Debian container:
#   - read-only base image with a tmpfs overlay (--volatile=overlay): nothing survives the session;
#   - user namespace with a fixed range (the base image is shifted to it at build time):
#     container root is uid 524288 on the VM, not root;
#   - no network at all (--private-network), own hostname, own process tree;
#   - its own cgroup scope with memory, CPU and task limits, 15 minutes at most.
# The VM itself stays the hard boundary and is rolled back to a clean snapshot every 30 minutes.
set -euo pipefail
ID="s$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
exec timeout --kill-after=10 900 systemd-nspawn --quiet \
  --directory=/var/lib/machines/base \
  --volatile=overlay \
  --private-users=524288:65536 \
  --private-network \
  --machine="$ID" --hostname=sandbox \
  --as-pid2 --chdir=/root \
  --setenv=TERM=xterm-256color \
  --property=MemoryMax=96M --property=MemorySwapMax=0 \
  --property=TasksMax=64 --property=CPUQuota=15% \
  /bin/bash --login
