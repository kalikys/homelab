# shellcheck shell=bash
# Shared by prepare.sh, run.sh and cleanup.sh (GitLab Runner custom executor).
# Contract: https://docs.gitlab.com/runner/executors/custom/ — job variables arrive as CUSTOM_ENV_*,
# failures exit with $BUILD_FAILURE_EXIT_CODE (the job's fault) or $SYSTEM_FAILURE_EXIT_CODE (ours).

EXECUTOR_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC2034 # used by the scripts that source this file
PVEJOB=(python3 "$EXECUTOR_DIR/pvejob.py")
STATE_ROOT=${CI_RUNNER_STATE:-/var/lib/ci-runner/jobs}
SSH_KEY=${CI_SSH_KEY:-/etc/ci-runner/ssh/id_ed25519}
JOB_USER=ci
SYSTEM_FAILURE_EXIT_CODE=${SYSTEM_FAILURE_EXIT_CODE:-1}
BUILD_FAILURE_EXIT_CODE=${BUILD_FAILURE_EXIT_CODE:-1}

JOB_ID=${CUSTOM_ENV_CI_JOB_ID:-}
if ! [[ $JOB_ID =~ ^[0-9]{1,20}$ ]]; then
  echo "executor: CUSTOM_ENV_CI_JOB_ID is missing or not numeric" >&2
  exit "$SYSTEM_FAILURE_EXIT_CODE"
fi
JOB_DIR=$STATE_ROOT/$JOB_ID

# The host key is pinned per job from the guest agent (pvejob.py wait); nothing else is trusted.
SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$JOB_DIR/known_hosts" -o GlobalKnownHostsFile=/dev/null
  -o HostKeyAlgorithms=ssh-ed25519 -o ConnectTimeout=10 -o ServerAliveInterval=30 -o ServerAliveCountMax=4
  -o LogLevel=ERROR)

job_ssh() {
  # shellcheck disable=SC2029 # the arguments are fixed commands meant to run on the VM
  ssh "${SSH_OPTS[@]}" "$JOB_USER@$VM_IP" "$@"
}

load_vm() {
  # shellcheck disable=SC2034 # VM_ID is used by the callers
  if ! read -r VM_ID VM_IP 2>/dev/null < "$JOB_DIR/vm" || [ -z "${VM_IP:-}" ]; then
    echo "executor: no VM recorded for job $JOB_ID" >&2
    return 1
  fi
}
