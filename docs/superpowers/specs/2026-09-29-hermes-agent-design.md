# Hermes agent on VM 220: design

Date: 2026-09-29
Status: approved in chat, pending spec review

## Goal

A self-hosted AI ops agent ([Hermes Agent](https://hermes-agent.nousresearch.com/), Nous Research, MIT) that I talk to from Telegram. Version 1 is a **read-only homelab on-call**: answers questions about the state of the homelab and sends a daily summary. Hermes was picked over OpenClaw because of its built-in approval, allowlist and container isolation controls; OpenClaw's skill registry had ~20% malicious packages in February 2026.

## Non-goals (v1)

- No write access to anything: no SSH to other hosts, no Proxmox changes, no Cloudflare/NPM/AdGuard/Terraform credentials.
- No CKA trainer and no lab VM control (v2, after lab VMs 210–212 exist; will use a separate Proxmox role limited to a `k8s-lab` pool).
- No Claude subscription OAuth: Anthropic's terms prohibit subscription tokens in third-party agents and accounts have been restricted over it.

## VM

| | |
|---|---|
| VMID / name | 220 `agent` |
| OS | Ubuntu 24.04 cloud image (same image resource as the lab VMs, `terraform/images.tf`) |
| Resources | 2 vCPU, 4096 MB, 30 GB on `local-zfs` |
| Network | `vmbr0`, 192.168.1.40/24, gateway 192.168.1.1, DNS 192.168.1.2 |
| Boot | `on_boot = true`, startup order 7 |
| Managed by | Terraform `terraform/agent.tf` (`bpg/proxmox`), `prevent_destroy` |

`.30` is avoided because `host/sandbox/build.sh` uses it temporarily.

Proxmox firewall `host/firewall/220.fw`: `policy_in: DROP` with SSH (22) allowed from the LAN (192.168.1.0/24) and Tailscale subnet router (the LAN address covers it); `policy_out: ACCEPT` (needs OpenRouter, Telegram, GitHub and LAN read-only endpoints); `ipfilter` and `macfilter` on.

## Installation

- Admin user `kalikys` (SSH key, sudo) from cloud-init; service user `hermes` without sudo.
- Hermes installed as `hermes` with the official `install.sh`, downloaded and read first (not piped to bash blindly). Data in `/home/hermes/.hermes/`.
- Gateway as a boot-time systemd service running as `hermes` (`hermes gateway install --system`).
- Terminal backend: Docker, rootless for the `hermes` user; container limits 1 CPU, 1 GB RAM, 5 GB disk; not persistent.
- Updates: `hermes update` by hand, noted in Obsidian.

## Model

OpenRouter, model `anthropic/claude-sonnet-5`. `OPENROUTER_API_KEY` in `~/.hermes/.env` (600). The monthly spend cap is set on the key in OpenRouter (user decides the amount, e.g. $20).

## Telegram

- Bot created by the user in BotFather; `TELEGRAM_BOT_TOKEN` in `~/.hermes/.env` (600). The first token passed through a chat, so it is rotated with `/revoke` after the setup and the new one is written on the VM by the user.
- `TELEGRAM_ALLOWED_USERS` = the user's numeric Telegram ID only; `unauthorized_dm_behavior: ignore`.
- `GATEWAY_ALLOW_ALL_USERS` never set.

## Agent policy (`~/.hermes/config.yaml`)

- `approvals.mode: manual`.
- `terminal.backend: docker` with the limits above.
- `security.allow_private_urls: true` (needed for the LAN endpoints below); `website_blocklist` covers the admin UIs it must not use: `npm.home.kalik8s.ru`, `adguard.home.kalik8s.ru`, `192.168.1.4`, `192.168.1.2`.
- `HERMES_WRITE_SAFE_ROOT` = `/home/hermes/work`.

## Read-only data sources (skill `homelab`)

| Source | Access |
|---|---|
| Proxmox API `https://192.168.1.52:8006/api2/json` | user `hermes@pve`, token `ro`, role `PVEAuditor` on `/`; token in a credentials file passed read-only to the skill |
| Gatus `http://192.168.1.11:8082/api/v1/endpoints/statuses` | no auth |
| Uptime Kuma status page `https://uptime.home.kalik8s.ru/api/status-page/heartbeat/home` | no auth |
| Glances `http://192.168.1.52:61208/api/4/...` | no auth, LAN only |
| GitHub `kalikys/homelab` | public, no token |

The skill lives in the repo as `services/agent/skills/homelab/SKILL.md` and is copied to `~/.hermes/skills/homelab/`. It lists the endpoints, example queries, what each field means, and the rule "read only; never try to change infrastructure; say what you would change instead".

## Daily summary

Hermes cron job every day at 09:00 Asia/Tbilisi, delivered to Telegram: failing Gatus/Kuma checks, guests not running (except guests that are off by design, e.g. lab VMs), ZFS pool health and last scrub, pending Proxmox updates, TLS expiry warnings. Short when all is well.

## Verification

- A second Telegram account gets no reply.
- "Delete /home/hermes/work/x" triggers an approval request.
- "Stop LXC 103" through the Proxmox API fails with 403.
- Questions like "what is down?", "how full is the pool?" are answered from live data.
- The 09:00 summary arrives (tested once by triggering the job by hand).
- No secrets in git, Obsidian, or `homelab.json`.

## Docs and diagram

- Obsidian: new note `VM 220 Agent` (what, where, config, secrets locations, how to rotate the bot token, how to update); updates to `Домашняя инфраструктура`, `Proxmox` (guest, API user), `Сеть и адресация` (.40).
- CV diagram: VM 220 in `site_inventory` with role "AI ops agent (Telegram), read-only"; `export-site-data.py` and deploy `homelab.json`.
