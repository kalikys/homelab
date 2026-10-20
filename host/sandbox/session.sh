#!/bin/bash
# /usr/local/sbin/sandbox-session: one throwaway container per browser session, like Killercoda.
# ttyd (user "ttyd") starts it through sudo. The visitor gets root inside a fresh Debian container:
#   - read-only base image with a tmpfs overlay (--volatile=overlay): nothing survives the session;
#   - user namespace (--private-users=pick): container root is an unprivileged uid on the VM;
#   - no network at all (--private-network), own hostname, own process tree;
#   - its own cgroup scope with memory, CPU and task limits, 15 minutes at most.
# The VM itself stays the hard boundary and is rolled back to a clean snapshot every 30 minutes.
set -euo pipefail
ID="s$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
exec timeout --kill-after=10 900 systemd-nspawn --quiet \
  --directory=/var/lib/machines/base \
  --volatile=overlay \
  --private-users=pick --private-users-ownership=map \
  --private-network \
  --machine="$ID" --hostname=sandbox \
  --as-pid2 --chdir=/root \
  --setenv=TERM=xterm-256color \
  --property=MemoryMax=96M --property=MemorySwapMax=0 \
  --property=TasksMax=64 --property=CPUQuota=15% \
  /bin/bash --login
