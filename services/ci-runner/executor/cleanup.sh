#!/bin/bash
# cleanup_exec: runs after every job (success, failure, cancel, timeout). Always destroys the job VM.
# Idempotent: a VM that is already gone counts as success. If Proxmox refuses, the reaper retries later.
set -uo pipefail
# shellcheck source=SCRIPTDIR/common.sh
. "$(dirname "$0")/common.sh"

rc=0
"${PVEJOB[@]}" destroy --job-id "$JOB_ID" >/dev/null || rc=$?
if [ -r "$JOB_DIR/vm" ] && load_vm 2>/dev/null; then
  "${PVEJOB[@]}" destroy --vmid "$VM_ID" >/dev/null || rc=$?
fi
rm -rf "$JOB_DIR"
if [ "$rc" -ne 0 ]; then
  echo "executor: could not destroy the VM of job $JOB_ID; ci-reaper.timer will remove it" >&2
  exit "$SYSTEM_FAILURE_EXIT_CODE"
fi
echo "Job $JOB_ID: VM destroyed"
