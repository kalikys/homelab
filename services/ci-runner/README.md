# CI runner for vardhold/hub: one throwaway VM per job

Every CI job of `vardhold/hub` (runner tag `hub-vm`) runs in a fresh Proxmox VM, linked-cloned from a fixed template
and destroyed when the job ends: success, failure, cancel or timeout. Nothing is shared between jobs: no Docker
daemon, no cache, no files. Job VMs reach the internet (gitlab.com, registries, package mirrors) and nothing in the
home LAN. Design: `docs/superpowers/specs/2026-10-30-hub-gitops-design.md` §2 in the company repo.

```
gitlab.com ── VM 290 ci-runner (gitlab-runner, custom executor) ──Proxmox API──> clone 9100 -> 92xx, start, destroy
                   │ net0 LAN 192.168.1.42          │ net1 vmbr9 10.99.0.2
                   │                                └──ssh──> job VM ci-<job id> (10.99.0.100-199)
                   │                                                │ NAT on the host, no LAN, no host
Proxmox host: vmbr9 10.99.0.1 ── MASQUERADE via vmbr0 ──> internet
```

| Thing | Value |
|---|---|
| Manager | VM 290 `ci-runner`, 1 vCPU / 1024 MB / 16 GB, LAN 192.168.1.42 + vmbr9 10.99.0.2 |
| Template | VM 9100 `ci-template`, Ubuntu Noble, 4 vCPU / 4096 MB / 30 GB, `template = true`, not in any pool |
| Job VMs | VMID 9200–9299, name `ci-<CI_JOB_ID>`, pool `ci-jobs`, IP 10.99.0.(100 + VMID − 9200) |
| Network | bridge `vmbr9` (no physical port), 10.99.0.0/24, gateway 10.99.0.1 on the host |
| Runner | `concurrent = 1`, executor `custom`, no shared cache, tag `hub-vm`, untagged jobs off, locked to the project, max timeout 60 min |
| Reaper | `ci-reaper.timer` every 15 min: removes `ci-*` VMs in pool `ci-jobs`, VMID 9200–9299, older than 2 h |
| API token | `ci@pve!runner`: clone from 9100, manage VMs in pool `ci-jobs` only |

VMIDs 290, 9100 and 9200–9299, IP 192.168.1.42 and MAC `BC:24:11:4B:38:42` are not used anywhere else in this repo
(Terraform resources, `imports.tf`, host scripts). Check the live host too before the first apply: `qm list; pct list`.

## Files

| Path | What |
|---|---|
| `terraform/ci.tf` | VM 290 and template VM 9100 (`var.ci_template_build` switches the template's one build boot) |
| `host/ci-nat.sh`, `host/systemd/ci-nat.service` | NAT + isolation for vmbr9 on the Proxmox host, applied at boot |
| `host/firewall/290.fw` | Proxmox firewall of the manager: LAN ssh in, ssh out to job VMs on net1, nothing else on net1 |
| `cloud-init-template.yaml` | user-data of the template's build boot: Docker CE + buildx (Docker's repo, key fingerprint pinned), git, python3, shellcheck, curl, guest agent, gitlab-runner binary |
| `cloud-init-manager.yaml` | user-data of VM 290: gitlab-runner, guest agent, admin user |
| `install.sh` | puts the executor, reaper units and rendered `config.toml` on VM 290 (idempotent) |
| `config.toml.tmpl` | runner config; the token placeholder is filled on the VM from a root-only file |
| `executor/prepare.sh`, `run.sh`, `cleanup.sh`, `common.sh` | GitLab custom executor stages |
| `executor/pvejob.py` | Proxmox API: `clone`, `wait`, `destroy`, `reap` (stdlib only) |
| `reaper.service`, `reaper.timer` | installed as `ci-reaper.*` |
| `tests/test_pvejob.py` | pvejob against a fake API: `python3 -m pytest services/ci-runner/tests` |

## How a job runs

1. **prepare** (`prepare.sh`, gives up after 5 min and destroys what it made)
   - `pvejob.py reap --max-age 0 --except-job N` (sweep): destroys every other `ci-*` VM in pool `ci-jobs` within
     9200–9299, whatever its age. With `concurrent = 1` any such VM is a leftover whose cleanup failed, and it
     would share vmbr9 with the new job. If the sweep fails, the job fails as a system failure.
   - `pvejob.py destroy --job-id N`: a retried prepare never leaves the first VM behind.
   - `pvejob.py clone`: asks `/cluster/nextid?vmid=X` for X = 9200… until one is free (this sees VMIDs the token
     cannot otherwise see), linked-clones 9100 into pool `ci-jobs` as `ci-N` with
     `ci-job=N ci-nonce=<uuid4 of this call> ci-created=<epoch>` in the description, then sets on the clone: `delete=cicustom` (the template's build user-data must not run again),
     `ciuser=ci`, `sshkeys=<manager job key>`, `ipconfig0=ip=10.99.0.X/24,gw=10.99.0.1`, public nameservers,
     `ciupgrade=0`; starts it. A clone task that fails with "already exists" is a lost race for that VMID: the
     VM there is someone else's, it is left alone and the next VMID is tried. Any other failure destroys the VM,
     but only after re-reading its config and finding both this job's `ci-job` and this call's `ci-nonce`.
   - `pvejob.py wait`: waits until `/var/lib/cloud/instance/boot-finished` exists (cloud-init fully done, so the
     host keys are final), then reads the clone's `/etc/ssh/ssh_host_ed25519_key.pub` through the QEMU guest agent and writes
     it as the only entry of the job's `known_hosts`.
   - ssh in (`StrictHostKeyChecking=yes`, ed25519 only, that `known_hosts` only) until
     `cloud-init status --wait; docker info` succeeds.
2. **run** (`run.sh <script> <stage>`, once per stage): `ssh ci@10.99.0.X bash -s < script`. Exit 0 → success;
   ssh lost (255 and a follow-up `ssh true` fails) → `$SYSTEM_FAILURE_EXIT_CODE`; anything else →
   `$BUILD_FAILURE_EXIT_CODE`. The checkout (`get_sources`), artifacts and cache stages also run on the VM, which
   is why the template carries git and the `gitlab-runner` binary.
3. **cleanup** (`cleanup.sh`, always): destroy by job name and by the recorded VMID, the latter with
   `--expect-job N` so it refuses a VM whose description is not `ci-job=N` (stop, then delete with `purge=1`). A VM that is already gone counts as success. If Proxmox refuses, the reaper retries.

State between the stages lives in `/var/lib/ci-runner/jobs/<job id>/` (`vm`, `known_hosts`), root-only.

## Design decisions

**Job VM address: static, derived from the VMID.** 9200 → 10.99.0.100 … 9299 → 10.99.0.199, set through Proxmox's
cloud-init `ipconfig0` on the clone. No DHCP server anywhere, nothing listening on the bridge, and the manager knows
the address without asking the VM. DNS is 1.1.1.1 / 9.9.9.9 because the LAN resolver (AdGuard) is unreachable on purpose.

**SSH trust: key in, host key out, both through Proxmox.** The manager generates its own job key on VM 290
(`/etc/ci-runner/ssh/id_ed25519`, never leaves it); `pvejob.py clone` puts the public half into each clone with the
cloud-init `sshkeys` option. The clone's host key is generated on its first boot (the template has none and a fresh
cloud-init instance) and read back through the guest agent, a virtio channel controlled by the hypervisor, before
the job has run anything. That key is the only `known_hosts` entry and `StrictHostKeyChecking=yes`: no
trust-on-first-use, no `StrictHostKeyChecking=no`. Custom user-data per clone (a host key generated on the manager)
was the alternative; it needs snippets uploaded to the host per job, which the API token cannot do.

**Isolation is on the host's routing path, not per-VM firewall files.** Proxmox firewall rules live in
`/etc/pve/firewall/<vmid>.fw`, which cannot follow throwaway VMIDs, so job NICs have `firewall = false` and
`host/ci-nat.sh` does the work with iptables (what this host uses; `pve-firewall` keeps to its own `PVEFW-*` chains,
these are `CI-*`):
- `FORWARD -i vmbr9 → CI-OUT`: spoofed sources dropped; any private, CGNAT, link-local or multicast destination
  dropped and logged (`ci-drop-lan`), which covers 192.168.1.0/24, the ISP router's network and Tailscale; only then
  `-o vmbr0` is accepted. Frames between two 10.99.0.0/24 hosts are bridged, not routed, and are left alone here.
- `FORWARD -o vmbr9 → CI-IN`: only `ESTABLISHED,RELATED`, so nothing in the LAN can open a connection to a job VM.
- `INPUT -i vmbr9 → CI-HOST`: the host accepts nothing new from vmbr9 on any of its addresses (10.99.0.1,
  192.168.1.52, port 8006, ssh); logged as `ci-drop-host`.
- `POSTROUTING -s 10.99.0.0/24 -o vmbr0 MASQUERADE`; IPv4 forwarding on; rp_filter on vmbr9.
- No IPv6 on vmbr9: disabled on the bridge and dropped in ip6tables, because the host's link-local address would
  otherwise expose pveproxy and ssh.
- The manager is the only other member of vmbr9. Its ssh sessions to job VMs never touch the host's routing
  (same bridge), and `host/firewall/290.fw` drops anything a job VM opens towards it on net1, while it may only
  ssh out on net1.
- Job VMs share L2 on vmbr9 without a per-VM firewall, so a job VM could ARP-spoof 10.99.0.1 or attack another job
  VM if two were ever up at once. `concurrent = 1` alone does not guarantee that: a VM whose cleanup failed stays
  up until the reaper (2 h). That is why prepare **sweeps every other `ci-*` VM before cloning** and refuses to
  start the job when it can't, so a new job never shares the bridge with a leftover. The reaper stays as the
  backstop for when no job comes. Bridge-port isolation (`bridge link set dev tap<vmid>i0 isolated on`) was
  considered and left out: it would need a Proxmox hookscript on the template, and only `root@pam` may set
  `hookscript`, which neither Terraform's nor the runner's token is.
- **WAN side.** Job traffic leaves through the home's double NAT. Isolation from the LAN through that path relies
  on the Keenetic having **no port forwards to LAN hosts and NAT loopback (hairpin) off**; otherwise a job VM
  could reach a forwarded LAN service through the home's public IP. To block that IP explicitly as well, put
  `CI_EXTRA_DROP="<public IP>/32"` (space-separated CIDRs) into `/etc/default/ci-nat` on the host and restart
  `ci-nat`; those targets get the same LOG+DROP in `CI-OUT`. A dynamic public IP has to be kept up to date by hand.

**Decision (controller ruling R22): the runner's secrets are root-only files on VM 290, not SOPS in git.** This
repo has no SOPS setup (the Hub repo does) and none is introduced for two tokens that live in exactly one place;
this replaces the spec's "SOPS for the runner's age key" and keeps the secrets out of git entirely. Files (all placed by the owner, `root:root 0600`):

| File | Content |
|---|---|
| `/etc/ci-runner/pve-token` | one line `ci@pve!runner=<secret>`; pvejob refuses a file readable by group/others |
| `/etc/ci-runner/pve-root-ca.pem` | copy of the host's `/etc/pve/pve-root-ca.pem` (public, 0644 fine) |
| `/etc/ci-runner/runner-token` | the runner authentication token `glrt-…` from GitLab |
| `/etc/ci-runner/ssh/id_ed25519` | generated by `install.sh` |
| `/etc/gitlab-runner/config.toml` | rendered by `install.sh`, contains the runner token (gitlab-runner needs it there) |

`pvejob.py` scrubs the token (whole string and secret part) from every error and log line, and has no switch to
skip TLS verification: it talks to `https://192.168.1.52:8006` and checks the certificate against that CA file
(the default `pve-ssl.pem` is signed by it and lists the node's IP). If the host ever gets a custom certificate,
point `PVE_URL`/`PVE_CA_FILE` at matching values instead.

**If VM 290 is lost (or a token may have leaked)**, nothing is recovered from it. Both tokens are re-issued:
1. Proxmox: `ssh homeserver 'sudo pveum user token remove ci@pve runner && sudo pveum user token add ci@pve runner --privsep 0 --comment "ci-runner VM 290"'`
   (removing the token also revokes the old secret; user, roles and ACLs stay).
2. GitLab: `vardhold/hub` → Settings → CI/CD → Runners → delete the old runner (this revokes its `glrt-` token),
   then create a new one with the settings in checklist step 6.
3. Recreate VM 290 if needed (targeted apply of `proxmox_virtual_environment_vm.ci_runner`), run `install.sh`
   (it generates a new job ssh key; job VMs receive it per clone, so the template needs no change), place both
   tokens and the CA file as in step 5, run `install.sh` again.
4. Sweep anything the old manager left: `python3 /opt/ci-runner/executor/pvejob.py reap --max-age 0`.

**Proxmox permissions.** The template is outside the pool, so the token can clone it and nothing more. Inside pool
`ci-jobs` it can create, configure, start, stop, read the guest agent of and delete VMs. Proxmox ACLs cannot
express a VMID range, so the range 9200–9299, the `ci-` name prefix and "never a template" are enforced in
`pvejob.py` for every destroy and reap (tested). A stolen token can still burn CPU/RAM/disk inside the pool and
read files through the guest agent of job VMs; it cannot touch any other guest.

**Template build: cloud-init in one boot, then `template = true`.** Terraform creates VM 9100 with the snippet as
user-data; it installs everything, smoke-tests docker/buildx, deletes its host keys, runs
`cloud-init clean --logs --machine-id` and powers off only when all of that succeeded (otherwise it stays up for
inspection). A second targeted apply flips `template` to true in place. Clones remove `cicustom`, so the build
never reruns on a job VM; a clone boots in well under a minute (linked ZFS clone, no package installs).

**No shared cache.** `disable_cache` is a docker-executor key; with the custom executor the equivalent is no
`[runners.cache]` section and a `cache_dir` inside the job VM, which is destroyed with it.

## Owner checklist

Do these in order. Nothing here was done by the agent that wrote it.

### 1. Host: bridge and isolation
- [ ] Create the bridge (shows up in the GUI like vmbr1):
  ```sh
  ssh homeserver 'sudo pvesh create /nodes/pve/network --iface vmbr9 --type bridge --cidr 10.99.0.1/24 --autostart 1 \
      --comments "CI job VMs: NAT out, no LAN (host/ci-nat.sh)" && sudo pvesh set /nodes/pve/network'
  ```
- [ ] Install and start the isolation rules:
  ```sh
  scp host/ci-nat.sh host/systemd/ci-nat.service homeserver:/tmp/
  ssh homeserver 'sudo install -m 0755 /tmp/ci-nat.sh /usr/local/sbin/ci-nat.sh \
      && sudo install -m 0644 /tmp/ci-nat.service /etc/systemd/system/ci-nat.service \
      && sudo systemctl daemon-reload && sudo systemctl enable --now ci-nat.service && sudo /usr/local/sbin/ci-nat.sh --check'
  ```
- [ ] Keenetic: confirm there are **no port forwards** to LAN hosts and **NAT loopback is off**. Optionally put the
  public IP in `/etc/default/ci-nat` as `CI_EXTRA_DROP="<ip>/32"` and `systemctl restart ci-nat` (see Design decisions).
- [ ] Manager firewall: `scp host/firewall/290.fw homeserver:/tmp/ && ssh homeserver 'sudo cp /tmp/290.fw /etc/pve/firewall/290.fw'`
- [ ] Snippets: make sure storage `local` allows them (`grep -A3 '^dir: local' /etc/pve/storage.cfg`; if `snippets` is
  missing, `pvesm set local --content <the existing list>,snippets`), then copy the user-data:
  ```sh
  scp services/ci-runner/cloud-init-template.yaml homeserver:/tmp/ci-template.yaml
  scp services/ci-runner/cloud-init-manager.yaml homeserver:/tmp/ci-runner-manager.yaml
  ssh homeserver 'sudo install -m 0644 /tmp/ci-template.yaml /tmp/ci-runner-manager.yaml /var/lib/vz/snippets/'
  ```

### 2. Proxmox pool, role, user and token
```sh
ssh homeserver sudo bash -s <<'EOF'
pveum pool add ci-jobs --comment "Throwaway CI job VMs 9200-9299 (ci-runner VM 290)"
pveum role add CIRunnerPool --privs "VM.Allocate VM.Audit VM.Config.Cloudinit VM.Config.Network VM.PowerMgmt VM.GuestAgent.Audit VM.GuestAgent.FileRead Pool.Audit"
pveum role add CIRunnerClone --privs "VM.Clone VM.Audit"
pveum role add CIRunnerStorage --privs "Datastore.AllocateSpace Datastore.Audit"
pveum user add ci@pve --comment "GitLab runner manager VM 290 (API token only, no password)"
pveum acl modify /pool/ci-jobs --users ci@pve --roles CIRunnerPool
pveum acl modify /vms/9100 --users ci@pve --roles CIRunnerClone
pveum acl modify /storage/local-zfs --users ci@pve --roles CIRunnerStorage
pveum acl modify /sdn/zones/localnetwork/vmbr9 --users ci@pve --roles PVESDNUser
pveum user token add ci@pve runner --privsep 0 --comment "ci-runner VM 290"
EOF
```
The last command prints the secret once; it goes to the manager in step 5, nowhere else. (`VM.GuestAgent.*` are
the Proxmox VE 9 privileges; on 8.x use `VM.Monitor` instead.)

### 3. Terraform (from the main homelab checkout, after merging this branch; targeted only)
- [ ] `terraform plan -target=proxmox_virtual_environment_vm.ci_runner -target=proxmox_virtual_environment_vm.ci_template -var ci_template_build=true -out ci.tfplan`
  — must show exactly two resources to add and nothing else; then `terraform apply ci.tfplan`.
- [ ] Wait for the template's build boot to end: `ssh homeserver 'qm status 9100'` turns `stopped` (5–10 min).
  Still running after 20 min → `qm guest exec 9100 -- tail -n 50 /var/log/cloud-init-output.log`.
- [ ] `terraform plan -target=proxmox_virtual_environment_vm.ci_template -out ci.tfplan` — must show one in-place
  update (`template = true`); apply it.

### 4. Manager software
- [ ] `ssh ci-runner 'cloud-init status --wait'` (add `ci-runner` → 192.168.1.42 to `~/.ssh/config` first), then
  `scp -r services/ci-runner ci-runner:/tmp/ && ssh ci-runner 'sudo bash /tmp/ci-runner/install.sh'`.

### 5. Secrets on the manager
- [ ] Proxmox CA: `ssh homeserver 'cat /etc/pve/pve-root-ca.pem' | ssh ci-runner 'sudo tee /etc/ci-runner/pve-root-ca.pem >/dev/null'`
- [ ] API token, pasted on the manager so it never lands in a file on the Mac (paste `ci@pve!runner=<secret>`,
  Enter, Ctrl-D):
  `ssh -t ci-runner 'sudo install -m 600 /dev/null /etc/ci-runner/pve-token && sudo tee /etc/ci-runner/pve-token >/dev/null'`
- [ ] Smoke test before GitLab is involved (on the manager, as root): one full prepare/run/cleanup cycle and the
  network check from inside a job VM:
  ```sh
  export CUSTOM_ENV_CI_JOB_ID=1
  /opt/ci-runner/executor/prepare.sh
  cat > /tmp/probe.sh <<'P'
  curl -fsS -o /dev/null -w 'gitlab.com %{http_code}\n' https://gitlab.com
  for u in http://192.168.1.14 https://192.168.1.52:8006 http://10.99.0.1 http://192.168.1.1; do
    if curl -ksS -m 5 -o /dev/null "$u"; then echo "REACHABLE: $u"; exit 1; else echo "blocked: $u"; fi
  done
  docker run --rm hello-world >/dev/null && echo docker ok
  P
  /opt/ci-runner/executor/run.sh /tmp/probe.sh probe; echo "rc=$?"
  /opt/ci-runner/executor/cleanup.sh; python3 /opt/ci-runner/executor/pvejob.py reap --dry-run
  ```
  Expected: `gitlab.com 200`, every LAN/host URL `blocked` (timeout), `docker ok`, `rc=0`, VM gone.

### 6. Register the runner
- [ ] In `vardhold/hub` → Settings → CI/CD → Runners → New project runner: tags `hub-vm`, **Run untagged jobs** off,
  **Lock to current projects** on (project runners are), **Maximum job timeout** 3600, description `homelab ci-runner VM 290`.
  Turn **instance runners off** for the project on the same page.
- [ ] Put the `glrt-…` token on the manager the same way as the API token, into `/etc/ci-runner/runner-token`
  (same command with that path), then
  `ssh ci-runner 'sudo bash /tmp/ci-runner/install.sh'` again: it renders `/etc/gitlab-runner/config.toml`,
  restarts gitlab-runner, runs `gitlab-runner verify` and enables `ci-reaper.timer`.
  (This is what `gitlab-runner register --token glrt-… --template-config config.toml.tmpl` would write; with
  runner authentication tokens, tags/untagged/locked live in GitLab, not in `register` flags.)
- [ ] Run a pipeline in `vardhold/hub`; the job log starts with `Job N: VM 92xx (ci-N) at 10.99.0.1xx`.

## Operate

```sh
ssh ci-runner 'sudo journalctl -u gitlab-runner -n 50'          # runner and executor output
ssh ci-runner 'sudo systemctl list-timers ci-reaper.timer; sudo journalctl -u ci-reaper -n 20'
ssh ci-runner 'sudo python3 /opt/ci-runner/executor/pvejob.py reap --dry-run'
ssh homeserver 'sudo /usr/local/sbin/ci-nat.sh --check; sudo journalctl -k | grep ci-drop | tail'
```

Rebuild the template (new packages, new base image): `terraform state rm proxmox_virtual_environment_vm.ci_template`,
`ssh homeserver 'sudo qm destroy 9100'` (Terraform never destroys it: `prevent_destroy`), copy the snippet again if it
changed, then step 3 again. Jobs fail while 9100 is missing, so do it between pipelines.
