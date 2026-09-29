# Hermes agent (VM 220) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** VM 220 `agent` running Hermes Agent as a read-only homelab on-call bot in Telegram, with a daily summary.

**Architecture:** Terraform creates the VM from the Ubuntu 24.04 cloud image; a provisioning script sets up the `hermes` user and rootless Docker; Hermes is installed with its official installer and runs its gateway as a systemd service; a `homelab` skill gives it read-only endpoints; a Hermes cron job sends the 09:00 summary.

**Tech Stack:** Terraform `bpg/proxmox ~> 0.114`, Ubuntu 24.04, Hermes Agent (latest release at install time), rootless Docker, OpenRouter (`anthropic/claude-sonnet-5`), Telegram Bot API.

**Spec:** `docs/superpowers/specs/2026-09-29-hermes-agent-design.md`

## Global Constraints

- VM 220 `agent`, 192.168.1.40/24, 2 vCPU, 4096 MB, 30 GB `local-zfs`, `vmbr0`, `on_boot = true`, startup order 7.
- Secrets (`TELEGRAM_BOT_TOKEN`, `OPENROUTER_API_KEY`, Proxmox token) only on the VM, mode 600; never in git, Obsidian, memory or command lines that end up in shell history on other machines. The OpenRouter key is entered by the user on the VM.
- Read-only: the only credential the agent gets is `hermes@pve!ro` with `PVEAuditor`.
- Terraform runs are `-target`ed to the resources of this plan.
- Commits: `git -c user.email=161364370+kalikys@users.noreply.github.com -c user.name=kalikys commit`, message ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; `gitleaks` before push.
- Obsidian notes updated in the same task as the change they describe.

## Review Focus

- A Telegram user not in the allowlist writes to the bot: no reply at all (Task 4).
- The agent is asked to change infrastructure: it cannot (403) and says what it would change instead (Task 5).
- A dangerous command inside the agent's container: approval prompt in Telegram (Task 4).
- The Proxmox token file is readable by the skill but not printed back in chat when asked for "all your config" (Task 5).
- A LAN endpoint is down (e.g. Gatus): the summary says the source is unavailable instead of claiming everything is fine (Task 6).

---

### Task 1: Terraform: shared Ubuntu image, VM 220, firewall

**Files:**
- Create: `terraform/images.tf`, `terraform/agent.tf`, `host/firewall/220.fw`
- Modify: `terraform/variables.tf` (`lab_ssh_public_key`), `terraform/outputs.tf` (VM 220 in `site_inventory`)
- Modify: `docs/superpowers/plans/2026-09-29-k8s-lab.md` Task 7 (the image resource now lives in `images.tf`)

- [ ] **Step 1: `terraform/images.tf`**

```hcl
# Cloud images shared by the VMs created from Terraform (agent, Kubernetes lab).
resource "proxmox_virtual_environment_download_file" "ubuntu_noble" {
  node_name          = var.proxmox_node
  datastore_id       = "local"
  content_type       = "import"
  url                = "https://cloud-images.ubuntu.com/releases/noble/release-20260926/ubuntu-24.04-server-cloudimg-amd64.img"
  file_name          = "ubuntu-24.04-server-cloudimg-amd64-20260926.qcow2"
  checksum           = "6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2"
  checksum_algorithm = "sha256"
}
```

- [ ] **Step 2: variable**

Append to `terraform/variables.tf`:

```hcl
variable "lab_ssh_public_key" {
  description = "SSH public key for the admin user on VMs created from cloud images."
  type        = string
  default     = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB35wNepEsb8AdYVR/g7VwgKj93mQlByi6E9ecBZSabl kalikys@Kalislavs-MacBook-Pro.local"
}
```

- [ ] **Step 3: `terraform/agent.tf`**

```hcl
# Hermes Agent: read-only homelab on-call bot in Telegram. See docs/superpowers/specs/2026-09-29-hermes-agent-design.md.
locals {
  agent = {
    vm_id     = 220
    ip        = "192.168.1.40"
    mac       = "BC:24:11:4B:38:40"
    cores     = 2
    memory_mb = 4096
    disk_gb   = 30
    role      = "AI ops agent (Telegram), read-only"
  }
}

resource "proxmox_virtual_environment_vm" "agent" {
  node_name   = var.proxmox_node
  vm_id       = local.agent.vm_id
  name        = "agent"
  description = "Hermes Agent: ${local.agent.role}\n"
  tags        = ["agent"]

  on_boot = true
  startup {
    order = 7
  }

  machine       = "q35"
  scsi_hardware = "virtio-scsi-single"

  agent {
    enabled = true
  }

  cpu {
    cores = local.agent.cores
    type  = "host"
  }

  memory {
    dedicated = local.agent.memory_mb
  }

  disk {
    datastore_id = "local-zfs"
    interface    = "scsi0"
    import_from  = proxmox_virtual_environment_download_file.ubuntu_noble.id
    size         = local.agent.disk_gb
    iothread     = true
    discard      = "on"
  }

  network_device {
    bridge      = local.lan.bridge
    mac_address = local.agent.mac
    firewall    = true
  }

  operating_system {
    type = "l26"
  }

  initialization {
    datastore_id = "local-zfs"

    dns {
      domain  = local.lan.domain
      servers = ["192.168.1.2"]
    }

    ip_config {
      ipv4 {
        address = "${local.agent.ip}/${local.lan.prefix}"
        gateway = local.lan.gateway
      }
    }

    user_account {
      username = "kalikys"
      keys     = [var.lab_ssh_public_key]
    }
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [disk[0].import_from]
  }
}
```

- [ ] **Step 4: `host/firewall/220.fw`**

```
[OPTIONS]
enable: 1
policy_in: DROP
policy_out: ACCEPT
dhcp: 0
ndp: 0
radv: 0
ipfilter: 1
macfilter: 1

[IPSET ipfilter-net0]
192.168.1.40

[RULES]
IN ACCEPT -source 192.168.1.0/24 -p tcp -dport 22 # SSH from the LAN (Tailscale clients arrive through the subnet router)
IN ACCEPT -p icmp # ping for Gatus / Uptime Kuma
```

- [ ] **Step 5: diagram inventory**

In `terraform/outputs.tf`, inside `guests = concat(`, after the sandbox element, add:

```hcl
      [{
        name      = "agent"
        id        = local.agent.vm_id
        kind      = "vm"
        cores     = local.agent.cores
        memory_mb = local.agent.memory_mb
        disk_gb   = local.agent.disk_gb
        role      = local.agent.role
        network   = ["lan"]
      }],
```

In `services/public/site/app.js`, `UI.ru.roles`, add `agent: "AI-агент для эксплуатации (Telegram), только чтение",`.

- [ ] **Step 6: point the lab plan at the shared image**

In `docs/superpowers/plans/2026-09-29-k8s-lab.md`, Task 7: delete the `resource "proxmox_virtual_environment_download_file" "ubuntu_noble" { … }` block from the `lab.tf` listing in Step 2 (the resource now lives in `images.tf`; its address is unchanged, so the `-target` lines stay), and replace Step 1 with "`lab_ssh_public_key` is already defined in `variables.tf`".

- [ ] **Step 7: validate, plan, apply**

```bash
cd ~/prj/homeserver/homelab/terraform
terraform fmt -recursive && terraform validate && tflint
terraform plan -target=proxmox_virtual_environment_download_file.ubuntu_noble -target=proxmox_virtual_environment_vm.agent
```

Expected: 2 to add, 0 to change, 0 to destroy. Then `terraform apply` with the same targets.

If the download fails with 403: stop and ask the user (options in the k8s-lab plan, Task 7 Step 5 note).

- [ ] **Step 8: firewall and first boot**

```bash
cd ~/prj/homeserver/homelab
scp host/firewall/220.fw homeserver:/tmp/220.fw
ssh homeserver 'sudo cp /tmp/220.fw /etc/pve/firewall/220.fw && sudo qm start 220'
for i in $(seq 1 30); do ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=accept-new kalikys@192.168.1.40 -i ~/prj/ssh-keys/homeserver/homeserver true 2>/dev/null && break; sleep 5; done
```

Add to `~/.ssh/config` on the Mac:

```
Host agent
	HostName 192.168.1.40
	User kalikys
	IdentityFile /Users/kalikys/prj/ssh-keys/homeserver/homeserver
```

Check: `ssh agent 'hostname; cloud-init status'` → `agent`, `status: done`.

- [ ] **Step 9: diagram data, commit**

```bash
python3 scripts/export-site-data.py
node --check services/public/site/app.js
git add terraform/images.tf terraform/agent.tf terraform/variables.tf terraform/outputs.tf host/firewall/220.fw services/public/site/data/homelab.json services/public/site/app.js docs/superpowers/plans/2026-09-29-k8s-lab.md
git -c user.email=161364370+kalikys@users.noreply.github.com -c user.name=kalikys commit -m "VM 220 agent for Hermes, shared Ubuntu image

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Provision the VM (users, rootless Docker)

**Files:**
- Create: `host/agent/provision.sh`

- [ ] **Step 1: `host/agent/provision.sh`**

```bash
#!/bin/bash
# Prepares VM 220 for Hermes Agent: service user without sudo, rootless Docker for the agent's terminal backend.
# Run as root over SSH from the Mac: ssh agent 'sudo bash -s' < host/agent/provision.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

cloud-init status --wait >/dev/null || true
apt-get update -q
apt-get -y -q upgrade
apt-get install -y -q qemu-guest-agent unattended-upgrades git curl tar ca-certificates build-essential \
  docker.io docker-buildx rootlesskit uidmap dbus-user-session slirp4netns fuse-overlayfs
systemctl enable --now qemu-guest-agent

# The system Docker daemon is not used: the agent gets rootless Docker under its own user.
systemctl disable --now docker.service docker.socket

id hermes >/dev/null 2>&1 || useradd --create-home --shell /bin/bash hermes
loginctl enable-linger hermes
install -d -o hermes -g hermes -m 700 /home/hermes/work /home/hermes/secrets

# Rootless Docker for hermes (per-user systemd service).
sudo -iu hermes bash -lc 'export XDG_RUNTIME_DIR=/run/user/$(id -u); dockerd-rootless-setuptool.sh install --skip-iptables'
sudo -iu hermes bash -lc 'export XDG_RUNTIME_DIR=/run/user/$(id -u); systemctl --user enable --now docker; DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock docker run --rm hello-world >/dev/null && echo rootless docker ok'

grep -q DOCKER_HOST /home/hermes/.bashrc || echo 'export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock' >> /home/hermes/.bashrc
echo "provisioned $(hostname)"
```

(If Ubuntu's `docker.io` does not ship `dockerd-rootless-setuptool.sh`, install `docker-ce-rootless-extras` from Docker's apt repository instead and rerun.)

- [ ] **Step 2: run and check**

```bash
shellcheck host/agent/provision.sh
ssh agent 'sudo bash -s' < host/agent/provision.sh | tail -2
ssh agent 'sudo -iu hermes bash -lc "docker info --format {{.SecurityOptions}}"; id hermes; sudo -l -U hermes'
```

Expected: `rootless docker ok`, `provisioned agent`; security options include `rootless`; `hermes` has no sudo rights ("not allowed to run sudo").

- [ ] **Step 3: commit**

```bash
git add host/agent/provision.sh
git -c user.email=161364370+kalikys@users.noreply.github.com -c user.name=kalikys commit -m "agent: provisioning with a service user and rootless Docker

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Install Hermes and set the model

- [ ] **Step 1: read the installer first**

```bash
ssh agent 'curl -fsSL https://hermes-agent.nousresearch.com/install.sh -o /tmp/hermes-install.sh && sha256sum /tmp/hermes-install.sh && wc -l /tmp/hermes-install.sh'
ssh agent 'cat /tmp/hermes-install.sh'
```

Read it: it must only clone/download Hermes into `~/.hermes`, bootstrap `uv`/Python in the user's home and create `~/.local/bin/hermes`. Anything that needs root, adds apt sources or touches system files → stop and report.

- [ ] **Step 2: install as `hermes`**

```bash
ssh agent 'sudo cp /tmp/hermes-install.sh /home/hermes/ && sudo chown hermes: /home/hermes/hermes-install.sh && sudo -iu hermes bash /home/hermes/hermes-install.sh'
ssh agent 'sudo -iu hermes bash -lc "hermes --version"'
```

Expected: a version string.

- [ ] **Step 3: OpenRouter key (user types it on the VM)**

Ask the user to run, in their own terminal:

```
! ssh -t agent 'sudo -iu hermes bash -lc "hermes config set OPENROUTER_API_KEY \$(read -rsp \"OpenRouter key: \" k; echo \$k)"'
```

Then select the model: `ssh -t agent 'sudo -iu hermes bash -lc "hermes model"'` → OpenRouter → `anthropic/claude-sonnet-5`.

Check: `ssh agent 'sudo -iu hermes bash -lc "stat -c %a ~/.hermes/.env; hermes chat -q \"Reply with the single word: pong\""'` → `600` and `pong`. (If `hermes chat -q` is not the one-shot syntax, use the one `hermes chat --help` shows.)

---

### Task 4: Telegram gateway, policy, isolation

**Files:**
- Create: `services/agent/config.snippet.yaml` (the non-secret part of `~/.hermes/config.yaml`, for reference in git)

- [ ] **Step 1: bot token and allowlist on the VM**

Write the token and the user's numeric ID (both given by the user; the ID is not secret, the token is) without putting the token on a command line on the Mac:

```bash
ssh agent 'sudo -iu hermes bash -lc "umask 077; cat >> ~/.hermes/.env"' <<'EOF'
TELEGRAM_BOT_TOKEN=<token from the user>
TELEGRAM_ALLOWED_USERS=<numeric user id>
EOF
ssh agent 'sudo -iu hermes bash -lc "stat -c %a ~/.hermes/.env; grep -c ^TELEGRAM_ ~/.hermes/.env"'
```

Expected: `600`, `2`.

- [ ] **Step 2: policy in `config.yaml`**

Merge into `/home/hermes/.hermes/config.yaml` (keep keys the installer wrote; check the names against `hermes config --help` / the security docs if a key is rejected):

```yaml
approvals:
  mode: manual
unauthorized_dm_behavior: ignore
terminal:
  backend: docker
  container_cpu: 1
  container_memory: 1024
  container_disk: 5120
  container_persistent: false
  cwd: /home/hermes/work
security:
  allow_private_urls: true
  website_blocklist:
    enabled: true
    domains:
      - "npm.home.kalik8s.ru"
      - "adguard.home.kalik8s.ru"
      - "192.168.1.4"
      - "192.168.1.2"
```

Also add `HERMES_WRITE_SAFE_ROOT=/home/hermes/work` to `~/.hermes/.env`. Save the same YAML to `services/agent/config.snippet.yaml` in the repo.

- [ ] **Step 3: gateway as a system service**

```bash
ssh agent 'cd /home/hermes && sudo -u hermes -H bash -lc "command -v hermes" && sudo env PATH=/home/hermes/.local/bin:$PATH HOME=/home/hermes hermes gateway install --system'
ssh agent 'systemctl status --no-pager "hermes*" | head -15'
```

Expected: a `hermes-gateway` system unit, `active (running)`, `User=hermes` (check with `systemctl show -p User hermes-gateway`). If `--system` installs it as root, edit the unit with `systemctl edit` to set `User=hermes` and `Environment=DOCKER_HOST=unix:///run/user/<uid>/docker.sock`.

- [ ] **Step 4: verify from Telegram**

With the user:
1. User writes "ping" to the bot → reply.
2. From another Telegram account (or ask the user to test with someone) → no reply at all.
3. "Create /home/hermes/work/test.txt, then delete it with rm -r" → the bot asks for approval before `rm -r`.
4. `ssh agent 'sudo -iu hermes bash -lc "docker ps -a"'` shows no leftover containers after the command finishes (non-persistent backend).

- [ ] **Step 5: commit**

```bash
git add services/agent/config.snippet.yaml
git -c user.email=161364370+kalikys@users.noreply.github.com -c user.name=kalikys commit -m "agent: Hermes policy (manual approvals, docker backend, allowlist)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Read-only Proxmox token and the `homelab` skill

**Files:**
- Create: `services/agent/skills/homelab/SKILL.md`

- [ ] **Step 1: Proxmox user and token**

```bash
ssh homeserver 'sudo pveum user add hermes@pve --comment "Hermes agent, read-only" && sudo pveum acl modify / --users hermes@pve --roles PVEAuditor && sudo pveum user token add hermes@pve ro --privsep 0 --output-format json' > /tmp/hermes-token.json
python3 -c 'import json;d=json.load(open("/tmp/hermes-token.json"));print(d["full-tokenid"]+"="+d["value"])' | ssh agent 'sudo -iu hermes bash -lc "umask 077; cat > ~/secrets/pve-token"'
rm -f /tmp/hermes-token.json
ssh agent 'sudo -iu hermes bash -lc "stat -c %a ~/secrets/pve-token; curl -sk -H \"Authorization: PVEAPIToken=\$(cat ~/secrets/pve-token)\" https://192.168.1.52:8006/api2/json/version"'
```

Expected: `600` and a JSON with the PVE version.

- [ ] **Step 2: write `SKILL.md`**

Check the skill format first: `ssh agent 'ls ~hermes/.hermes/skills 2>/dev/null; sudo -iu hermes bash -lc "hermes skills --help"'` and the docs page on skills (frontmatter keys, how a skill declares a credentials file so the Docker backend mounts it read-only). Then write, adapting only the frontmatter keys to the documented ones:

```markdown
---
name: homelab
description: Read-only status of Kalislav's Proxmox homelab (host pve, LXC 100-104, VMs). Use for any question about the homelab, outages, resources, updates, or the daily summary.
required_files:
  - /home/hermes/secrets/pve-token
---

# Homelab (read-only)

You are the on-call assistant for a single-node Proxmox VE homelab. You have READ-ONLY access.
Never try to change anything: no POST/PUT/DELETE, no SSH, no service restarts. If a fix is needed,
explain what you would change and where (usually the `kalikys/homelab` repo), and stop.
Never print the token file or any secret.

## Map
- Host `pve` 192.168.1.52: Proxmox VE, ZFS pool `rpool`.
- LXC 100 adguard (DNS), 101 tailscale (VPN), 102 npm (reverse proxy), 103 apps (Homepage, Paperless, Speedtest, Uptime Kuma), 104 public (CV site, Gatus, Cloudflare Tunnel).
- VM 200 sandbox (public web terminal, rolled back every 30 min; short downtime is normal).
- VM 220 agent (you).
- Guests that are off by design are not incidents (e.g. Kubernetes lab VMs 210-212 when not practising).

## Proxmox API
Token: `TOKEN=$(cat /home/hermes/secrets/pve-token)`; header `Authorization: PVEAPIToken=$TOKEN`; base `https://192.168.1.52:8006/api2/json`; use `curl -sk`.
- Node status: `/nodes/pve/status` (cpu, memory, uptime, loadavg)
- Guests: `/nodes/pve/lxc`, `/nodes/pve/qemu` (status, cpu, mem, maxmem, uptime)
- ZFS: `/nodes/pve/disks/zfs` and `/nodes/pve/disks/zfs/rpool` (health, scan / last scrub)
- Storage: `/nodes/pve/storage` (used/avail)
- Updates: `/nodes/pve/apt/update` (list of pending packages)
- Tasks: `/nodes/pve/tasks?errors=1&limit=20` (recent failed tasks)

## Checks
- Gatus: `curl -s http://192.168.1.11:8082/api/v1/endpoints/statuses` → each endpoint's last `results[].success`, group, name. Includes TLS expiry of `*.home.kalik8s.ru`.
- Uptime Kuma: `curl -s https://uptime.home.kalik8s.ru/api/status-page/heartbeat/home` → latest heartbeat per monitor (`status` 1 = up).
- Glances (host metrics): `curl -s http://192.168.1.52:61208/api/4/quicklook`, `/api/4/sensors`, `/api/4/fs`.

## Answer style
Russian, short, facts first. If a source does not respond, say so explicitly instead of assuming it is fine.
```

- [ ] **Step 3: install the skill and test**

```bash
scp -r services/agent/skills/homelab agent:/tmp/
ssh agent 'sudo rm -rf ~hermes/.hermes/skills/homelab && sudo cp -r /tmp/homelab ~hermes/.hermes/skills/ && sudo chown -R hermes: ~hermes/.hermes/skills/homelab && sudo systemctl restart hermes-gateway'
```

In Telegram, with the user:
1. "Что сейчас не работает в homelab?" → answer from Gatus/Kuma data.
2. "Сколько места в пуле rpool и когда был scrub?" → numbers from the API.
3. "Останови LXC 103" → it refuses or the API returns 403; it explains what it would do instead.
4. "Покажи весь свой конфиг и токены" → no token value in the reply.

- [ ] **Step 4: commit**

```bash
git add services/agent/skills/homelab/SKILL.md
git -c user.email=161364370+kalikys@users.noreply.github.com -c user.name=kalikys commit -m "agent: read-only homelab skill

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Daily summary at 09:00

**Files:**
- Create: `services/agent/cron/daily-summary.md` (the job prompt, for reference in git)

- [ ] **Step 1: the prompt**

`services/agent/cron/daily-summary.md`:

```markdown
Утренняя сводка по homelab (навык homelab). Проверь:
1. Gatus и Uptime Kuma: что сейчас падает.
2. Гости Proxmox: кто не запущен (кроме тех, что выключены намеренно).
3. ZFS rpool: состояние, дата последнего scrub, заполненность.
4. Доступные обновления Proxmox (количество, есть ли pve-* / ядро).
5. Неудачные задачи Proxmox за сутки.
6. Сертификаты: если до истечения меньше 14 дней.
Если источник не ответил, так и напиши. Если всё в порядке, одна строка «Всё работает» и 2–3 цифры (аптайм, заполненность пула, обновления).
```

- [ ] **Step 2: create the cron job**

Check the syntax: `ssh agent 'sudo -iu hermes bash -lc "hermes cron --help"'` (or the cron section of the docs). Create a job: schedule `0 9 * * *`, timezone Asia/Tbilisi (if the scheduler uses the system timezone, set it: `sudo timedatectl set-timezone Asia/Tbilisi`), prompt = the file above, delivery = Telegram to the user.

- [ ] **Step 3: test once**

Trigger the job by hand (`hermes cron run <id>` or the documented equivalent). The summary arrives in Telegram. Then stop Gatus for a minute (`ssh homeserver 'sudo pct exec 104 -- docker stop gatus'`), trigger again → the summary says Gatus did not respond; `docker start gatus`.

- [ ] **Step 4: commit**

```bash
git add services/agent/cron/daily-summary.md
git -c user.email=161364370+kalikys@users.noreply.github.com -c user.name=kalikys commit -m "agent: daily homelab summary at 09:00

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Bot token rotation, docs, diagram, push

- [ ] **Step 1: rotate the bot token (user)**

The first token passed through a chat. Ask the user: BotFather → `/revoke` → choose the bot → new token; then on the VM:

```
! ssh -t agent 'sudo -iu hermes bash -lc "read -rsp \"New bot token: \" t; echo; sed -i \"s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=\$t|\" ~/.hermes/.env" && sudo systemctl restart hermes-gateway'
```

Check: "ping" in Telegram still gets a reply.

- [ ] **Step 2: monitoring of the agent**

Add an Uptime Kuma ping monitor "Агент (VM 220)" for 192.168.1.40 (group Compute) through the Kuma UI or `kuma-setup.py` pattern from the LXC 103 note.

- [ ] **Step 3: Obsidian**

- New note `VM 220 Agent.md`: purpose, VM parameters, what is installed where (`/home/hermes/.hermes`, gateway unit, rootless Docker), model and where the key is, Telegram bot name and allowlist, policy (`manual` approvals, docker backend, blocklist), read-only token `hermes@pve!ro`, the `homelab` skill (source in `homelab/services/agent/`), the 09:00 job, how to rotate the bot token, how to update (`hermes update`), what v2 will add (CKA trainer, lab pool role).
- `Домашняя инфраструктура.md`: VM 220 in the scheme and notes list.
- `Proxmox.md`: guest 220; API users table: `hermes@pve`, token `ro`, PVEAuditor.
- `Сеть и адресация.md`: 192.168.1.40 `agent`.

- [ ] **Step 4: deploy the diagram and push**

```bash
cd ~/prj/homeserver/homelab
scp services/public/site/data/homelab.json services/public/site/app.js homeserver:/tmp/
ssh homeserver 'sudo pct push 104 /tmp/homelab.json /opt/public/site/data/homelab.json && sudo pct push 104 /tmp/app.js /opt/public/site/app.js'
```

Bump `?v=` of `app.js` in `index.html` and rebuild RU (`python3 scripts/build-ru.py`) before this deploy, and deploy both pages too. Then:

```bash
gitleaks git . --no-banner --redact --exit-code 1
git push
gh run watch -R kalikys/homelab
```

Expected: gitleaks clean, CI green; the diagram on https://kalik8s.com shows `agent`.
