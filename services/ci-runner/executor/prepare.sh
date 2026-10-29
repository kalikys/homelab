#!/bin/bash
# prepare_exec: clone a fresh VM from template 9100, start it, wait until the job user can run docker over ssh.
# Gives up after 5 minutes and destroys whatever it created.
set -euo pipefail
# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

DEADLINE=$((SECONDS + ${CI_PREPARE_TIMEOUT:-300}))

fail() {
  echo "executor: $1" >&2
  "${PVEJOB[@]}" destroy --job-id "$JOB_ID" >/dev/null || echo "executor: destroy failed, the reaper will retry" >&2
  rm -rf "$JOB_DIR"
  exit "$SYSTEM_FAILURE_EXIT_CODE"
}

install -d -m 700 "$STATE_ROOT" "$JOB_DIR"
# A retried prepare for the same job must not leave the first VM behind.
"${PVEJOB[@]}" destroy --job-id "$JOB_ID" >/dev/null || fail "could not clear an old VM for job $JOB_ID"

out=$("${PVEJOB[@]}" clone --job-id "$JOB_ID") || fail "clone failed"
read -r VM_ID VM_IP <<<"$out"
echo "$VM_ID $VM_IP" > "$JOB_DIR/vm"
echo "Job $JOB_ID: VM $VM_ID (ci-$JOB_ID) at $VM_IP, cloned from template 9100"

left=$((DEADLINE - SECONDS))
[ "$left" -gt 0 ] || fail "timed out before the VM booted"
"${PVEJOB[@]}" wait --vmid "$VM_ID" --known-hosts "$JOB_DIR/known_hosts" --timeout "$left" \
  || fail "VM $VM_ID did not come up"

# cloud-init creates the job user and its key; docker must answer before the job starts.
until job_ssh 'cloud-init status --wait >/dev/null 2>&1; docker info >/dev/null' </dev/null 2>/dev/null; do
  [ "$SECONDS" -lt "$DEADLINE" ] || fail "ssh to $VM_IP not ready within ${CI_PREPARE_TIMEOUT:-300}s"
  sleep 3
done
echo "VM $VM_ID ready after ${SECONDS}s"
