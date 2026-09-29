# K8s lab for CKA / CKAD / CKS: design

Date: 2026-09-29
Status: approved in chat, pending spec review

## Goal

A home lab for CKA, CKAD and CKS preparation, plus two views of it:

- internal: per-VM monitoring for me (LAN / Tailscale);
- public: a showcase page `kalik8s.com/lab/` with preparation progress, lab state and a read-only live terminal stream when I choose to go on air.

Built from ready-made pieces wherever possible (asciinema, Pulse, GitHub); custom code is limited to Terraform, one static page and small nginx/cron additions following existing patterns.

## Non-goals

- No Prometheus/Grafana stack, no self-written collector.
- No self-hosted asciinema-server (possible later).
- No automated task grading (killer.sh-style).
- Monitoring does not run inside the lab cluster (the cluster is rebuilt often).

## 1. Lab VMs

Managed by Terraform (`bpg/proxmox`) as `local.lab_vms`, separate from `local.containers`.

| VMID | Name | IP | vCPU | RAM | Disk |
|---|---|---|---|---|---|
| 210 | `k8s-cp` | 192.168.1.20/24 | 2 | 4 GB | 30 GB |
| 211 | `k8s-w1` | 192.168.1.21/24 | 2 | 4 GB | 30 GB |
| 212 | `k8s-w2` | 192.168.1.22/24 | 2 | 4 GB | 30 GB |

- `vmbr0` (LAN), gateway 192.168.1.1, DNS 192.168.1.2.
- Ubuntu 24.04 cloud image, checksum verified; disks on `local-zfs`.
- cloud-init: user `kalikys` with my SSH key, passwordless sudo; `qemu-guest-agent`; `containerd` (systemd cgroup driver); `kubeadm`, `kubelet`, `kubectl` from `pkgs.k8s.io` pinned to the current exam version, held; swap off; `br_netfilter`/`overlay` modules and sysctls; `asciinema` 3.x.
- `kubeadm init` is **not** run: bootstrapping the cluster is part of the practice.
- Hostnames inside the guests are the VM names (`k8s-cp`, `k8s-w1`, `k8s-w2`; Proxmox cloud-init sets them). The public page shows only the short labels `cp`, `w1`, `w2`.
- `onboot = false`: the lab runs only when needed.
- Snapshots: `base` taken right after provisioning (by the build step); `cluster` taken by me after the first successful cluster bootstrap.
- Host script `/usr/local/sbin/lab` (source in `host/lab/`):
  - `lab up` / `lab down`: start / shut down VMs 210–212;
  - `lab reset base|cluster`: stop, roll back all three to the snapshot, start;
  - `lab status`: state of the three VMs.
- Mac `~/.ssh/config`: aliases `k8s-cp`, `k8s-w1`, `k8s-w2`.
- Terraform ignores snapshot-related drift; lifecycle `prevent_destroy` like the LXCs.

## 2. Live terminal (asciinema)

- I stream with `asciinema stream -r` (remote mode, relay asciinema.org) from `k8s-cp` or from the Mac. One-time `asciinema auth` is done by me by hand.
- The stream is one-way by design: only output leaves the terminal, there is no input channel. No ports opened on the VMs, no tunnel routes, no firewall changes.
- Viewers joining mid-stream get the current screen (server-side virtual terminal).
- Responsibility rule while streaming: no secrets, tokens, `kubeconfig` contents on screen; stop the stream before working with them.
- Recordings (optional, when I want them) are uploaded to the same asciinema.org account.

## 3. Internal monitoring (Pulse)

- `rcourtman/pulse` as a Docker container in LXC 103 `apps` (compose in `services/apps/pulse/`), next to Homepage and Uptime Kuma. The Pulse LXC installer is not used (it would bypass Terraform).
- Proxmox access: user `pulse@pve`, API token `monitor`, role `PVEAuditor` on `/`. The token lives only in Pulse's own data volume on LXC 103, never in git.
- NPM: `pulse.home.kalik8s.ru` → LXC 103 Pulse port; covered by the existing `*.home.kalik8s.ru` DNS and wildcard certificate.
- Homepage: a Pulse tile.
- Pulse shows VMs 210–212 (CPU, RAM, disk, network, history) using the guest agent.
- Lab VM Terraform lives in its own file `terraform/lab.tf`.

## 4. Progress repo `kalikys/k8s-certs` (public)

- `cka.md`, `ckad.md`, `cks.md`: curriculum domains as `## <Domain> (<weight>%)` headings with `- [ ]` / `- [x]` items.
- `exams.json`: `{ "cka": null | "YYYY-MM-DD", "ckad": ..., "cks": ... }`.
- `notes/`, `solutions/`: filled by me over time.
- Progress per exam = sum over domains of `weight × done/total`.
- Streak = consecutive days (Asia/Tbilisi) with at least one commit in the repo, counting from today or yesterday.

## 5. Public page `kalik8s.com/lab/`

Static page in the existing site (`services/public/site/lab/`), vanilla JS, EN + RU (`/lab/` and `/ru/lab/` via `build-ru.py`), same styles, CSP and headers as the main page.

Sections:

1. Header: "Preparing for CKA → CKAD → CKS", countdown to the nearest exam with a date.
2. Progress: three cards with weighted percentage; each expands to its domains.
3. Activity: streak, 12-week commit heatmap, last 5 commits of `k8s-certs`.
4. Lab: three cards `cp` / `w1` / `w2` with state (running/stopped), vCPU, RAM, and uptime. No IPs, no internal names.
5. Live: when a stream is live, a "● LIVE" badge and the asciinema player after a "Watch" click; otherwise "Not on air" with a link to my asciinema profile.

Main page: the CKA/CKAD block in `#learning` becomes CKA/CKAD/CKS with live percentages and a "Follow the preparation →" link to `/lab/`. `sitemap.xml`, `llms.txt`, `cv.md` updated.

### Data sources

| Endpoint | Source | Cache |
|---|---|---|
| `/api/github/certs/<file>` | raw `cka.md`, `ckad.md`, `cks.md`, `exams.json` from `kalikys/k8s-certs` | 15 min, stale on error |
| `/api/github/certs-commits` | GitHub commits API for `k8s-certs` (enough for 12 weeks) | 15 min, stale on error |
| (none) | stream status: asciinema.org has no JSON API; the host cron reads the public stream page and writes `live` into `stats.json` | 5 min |
| `/data/stats.json` | existing host cron `site-stats.sh`, extended with a `lab` block | existing, 60 s |

`stats.json` `lab` block: `[{ "id": "cp", "status": "running", "cpus": 2, "mem_gb": 4, "uptime_seconds": 1234 }, ...]` built from `qm` on the host; no IPs, no VMIDs, no hostnames beyond `cp`/`w1`/`w2`.

`stats.json` `live` block: `{ "on": true|false, "stream": "<public stream ID or empty>" }`. The stream ID is public (it is part of the stream URL) and is kept on the host in `/etc/lab/asciinema-stream`; `on` is true when the public stream page shows the LIVE marker.

nginx proxies follow the existing `/api/github/*` pattern (fixed upstream paths only, GET only, cache in `/var/cache/nginx`).

CSP: the asciinema player JS/CSS is vendored into `site/vendor/` (no third-party script host); `connect-src` gains `wss://asciinema.org` (and `https://asciinema.org` if the player needs it).

## Error handling

- GitHub or asciinema unavailable: nginx serves stale cache; with no cache the page hides the affected block and shows a short "data unavailable" line, the rest renders.
- Lab VMs off: cards show "stopped"; this is the normal state, not an error.
- `exams.json` without dates: no countdown.
- Malformed checklist markdown: domains without a weight are shown but excluded from the percentage.

## Testing / verification

- `terraform plan` shows only the three new VMs (and no LXC changes); apply; VMs reachable by SSH; cloud-init finished; `kubeadm version` matches the pinned version; `base` snapshot exists.
- `lab up/down/reset/status` exercised once each.
- Pulse lists VMs 210–212 with guest-agent data.
- `curl` each new endpoint via LAN and via `https://kalik8s.com`; `stats.json` contains no IPs or internal names.
- `/lab/` and `/ru/lab/` checked in the browser, in both "live" and "not on air" states; CSP errors absent in the console.
- CI (`ru` build check) passes.

## Docs and diagram

- Obsidian: new notes `VM 210-212 K8s lab` and `Pulse`; update `Домашняя инфраструктура`, `Proxmox` (guests, tokens, `lab` script), `Сеть и адресация` (.20–.22), `LXC 103 Apps`, `Homepage`, `LXC 104 Public` (`/lab/`, new endpoints, CSP).
- Site diagram: add the VMs to Terraform outputs `site_inventory`, run `scripts/export-site-data.py`, deploy `homelab.json`.
