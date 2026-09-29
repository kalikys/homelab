# homelab

Infrastructure code and service configs for my home lab: one mini-PC running Proxmox VE, a handful of LXC containers, and two public pages published through Cloudflare Tunnel.

Live pages:

- CV: <https://kalik8s.com>
- Status (Gatus): <https://status.kalik8s.com>

## Hardware

Lenovo ThinkCentre M920x: Intel Core i7-8700K (6 cores, 12 threads), 32 GB RAM, one 500 GB NVMe SSD with ZFS.

## Network

```mermaid
flowchart LR
  internet((Internet)) --- isp[ISP router]
  isp -- WISP --- keenetic[Keenetic<br/>192.168.1.1]
  keenetic --- pve[Proxmox VE<br/>192.168.1.52]
  cf[Cloudflare edge] -. tunnel .- public
  ts[Tailscale] -. VPN .- tailscale

  subgraph pve_guests[LXC on Proxmox]
    adguard[adguard<br/>DNS, .2]
    tailscale[tailscale<br/>subnet router, .3]
    npm[npm<br/>reverse proxy, .4]
    apps[apps<br/>Docker, .10]
    public[public<br/>CV + Gatus, .11]
  end
  pve --- pve_guests
```

- The home network sits behind two NAT layers (ISP router, then Keenetic over WISP), so nothing is port-forwarded.
- Remote access goes through Tailscale; the `tailscale` container advertises `192.168.1.0/24`.
- AdGuard Home is the DNS server for the whole LAN and for Tailscale clients. It also serves the internal zone `home.kalik8s.ru`, with a wildcard pointing at the reverse proxy.
- Nginx Proxy Manager terminates TLS for internal services with a wildcard Let's Encrypt certificate issued through the Cloudflare DNS-01 challenge.
- Only the `public` container is reachable from the internet, through a remotely managed Cloudflare Tunnel.

## What runs where

| Guest | ID | Services |
|---|---|---|
| `adguard` | 100 | AdGuard Home |
| `tailscale` | 101 | Tailscale subnet router and exit node |
| `npm` | 102 | Nginx Proxy Manager |
| `apps` | 103 | Homepage, Paperless-ngx, Speedtest Tracker, Uptime Kuma |
| `public` | 104 | CV site (nginx), Gatus, cloudflared |
| `sandbox` | 200 (VM) | Public web terminal (ttyd), see below |

## Public sandbox

`shell.kalik8s.com` opens a real shell in a throwaway Debian VM. Isolation, from the outside in:

- The VM sits alone on `vmbr1`, a bridge with no physical port and no host address. It has no gateway and no DNS.
- The only other member of `vmbr1` is the `public` container (second NIC, `10.66.0.2`), where cloudflared forwards visitors to the terminal.
- Proxmox firewall on the VM: inbound only TCP 7681 from `10.66.0.2`, outbound `DROP`, IP and MAC filtering on. On the `public` container's DMZ NIC: inbound `DROP`, so the sandbox cannot open connections to it.
- Inside the VM the terminal runs as an unprivileged user under a systemd unit with `NoNewPrivileges`, a read-only system, and task, memory and CPU limits. SSH, cloud-init and the build user are removed.
- VM limits: 1 vCPU capped at 50%, 768 MB RAM, 6 GB disk with I/O throttling, 5 MB/s NIC.
- A cron job on the host rolls the VM back to the `clean` snapshot every 30 minutes.

`host/sandbox/build.sh` builds the VM from the official Debian cloud image (checksum-verified) and `host/sandbox/isolation-test.py` checks the isolation through the same websocket a visitor uses.

## Repository layout

```
terraform/   Proxmox LXC guests and Cloudflare tunnel + DNS (bpg/proxmox, cloudflare/cloudflare)
services/    docker compose files and app configs, one directory per LXC
host/        files placed on the Proxmox host (systemd units, firewall rules, sandbox build)
scripts/     export-site-data.py: Terraform inventory -> services/public/site/data/homelab.json
```

## Terraform

The guests existed before this repo, so they were adopted with `import` blocks instead of being recreated. Every container has `prevent_destroy`.

```sh
cd terraform
cp terraform.tfvars.example secrets.auto.tfvars   # fill in tokens, never committed
terraform init
terraform plan
```

State is kept locally and is not committed. The Proxmox API token belongs to a dedicated `terraform@pve` user. Cloudflare (tunnel `CV`, its ingress rules and the three CNAME records) is imported the same way; `terraform plan` is clean for both providers.

Note: changing a container's network interfaces through the provider restarts the container, even though the plan shows an in-place update.

The CV site's architecture data comes from Terraform: `local.site_inventory` in `terraform/outputs.tf` (no addresses) is exported with `scripts/export-site-data.py`.

## Secrets

Nothing secret is committed: `.env` files, `*.tfvars`, and Terraform state are ignored, and every secret file has a `*.example` next to it. The repo is checked with `gitleaks` before each push.

## Install notes

Proxmox was installed without a monitor or keyboard. `kexec` into the installer hung on this hardware, so the unattended installer was network-booted instead: iPXE (`snponly.efi` with an embedded script) chain-loads the kernel, initrd and the installer ISO over HTTP, and the answer file is fetched over HTTP too. The Keenetic DHCP server needed `next-server`/`bootfile` set explicitly, because the Intel PXE ROM ignores options 66/67.
