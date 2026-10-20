---
title: Proxmox Terraform with bpg: 5 LXC containers, 6 cloud-init VMs and the state drift I caused myself
description: bpg/proxmox Terraform provider in a real homelab on Proxmox VE 9: least-privilege API token, LXC, cloud-init VMs, import blocks, targeted applies, CI.
date: 2026-10-21
tags: [terraform, proxmox, homelab, iac, lxc]
lang: en
---

My home server is one mini-PC with Proxmox VE and 32 GB of RAM. Everything on it, 5 LXC containers and 6 VMs built from an Ubuntu cloud image, is described in Terraform with the [bpg/proxmox](https://registry.terraform.io/providers/bpg/proxmox/latest) provider, and the code is public at [github.com/kalikys/homelab](https://github.com/kalikys/homelab/tree/main/terraform). This post is the write-up I wished existed when I started: the provider setup, a container and a cloud-init VM that actually apply, and the part most tutorials skip, what happens when state and reality stop agreeing.

> **TL;DR**
>
> - Use `bpg/proxmox`, not Telmate. bpg targets Proxmox VE 9.x and ships a release every week or two; Telmate's latest is still a release candidate.
> - A dedicated `terraform@pve` user with a 21-privilege role. I ran `PVEAdmin` plus `Sys.Modify` since the repo started; the exact role that replaced it is below, verified with a full plan.
> - LXC: `proxmox_virtual_environment_container` with an `initialization` block for hostname, DNS and a static IP. Ignore `template_file_id` after creation.
> - VM: `proxmox_virtual_environment_vm` with `disk.import_from` pointing at a cloud image in the `import` content type and a full `initialization` block. No template VM, no clone.
> - Adopt hand-made guests with `import` blocks and `for_each`, then put `prevent_destroy` on everything you cannot rebuild in an hour.
> - When state lags reality, stop running bare `terraform apply`. Plan with `-target`, save the plan, read it, apply the file.

## Why bpg and not Telmate in 2026

When you search "proxmox terraform" most results still show the Telmate syntax. In 2026 that is the wrong default. The numbers from both projects' release pages as of 2026-10-20:

| | bpg/proxmox | Telmate/proxmox |
|---|---|---|
| Latest release | [v0.117.0, 2026-10-17](https://github.com/bpg/terraform-provider-proxmox/releases) | [v3.0.2-rc10, 2026-08-30](https://github.com/Telmate/terraform-provider-proxmox/releases) |
| Release cadence | 5 releases between 2026-09-21 and 2026-10-17 | Release candidates, no stable 3.x tag yet |
| Proxmox VE 9 | "targets Proxmox VE 9.x and is acceptance-tested against the current 9.x release" ([README](https://github.com/bpg/terraform-provider-proxmox)) | Not stated on the releases page |
| LXC resource | `proxmox_virtual_environment_container` | `proxmox_lxc` |
| Cloud-init | `initialization` block with `user_account`, `ip_config`, `dns`, or a snippet via `user_data_file_id` | `ciuser`, `sshkeys`, `ipconfig0` string attributes |
| Disk from cloud image | `disk.import_from`, no SSH needed | Clone from a template VM |
| Needs SSH to the node | Only for snippets, local file imports and LXC `idmap` ([docs](https://registry.terraform.io/providers/bpg/proxmox/latest/docs)) | For some disk operations |

bpg is a 0.x provider, and its README says so plainly: it "is not guaranteed to be backward compatible with all previous minor versions". That is why I pin it with a pessimistic constraint and let the lock file do the rest:

```hcl
terraform {
  required_version = ">= 1.9"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.114"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.26"
    }
  }
}
```

([versions.tf](https://github.com/kalikys/homelab/blob/main/terraform/versions.tf)). The lock file holds 0.114.0 today. Bumping it is a deliberate commit, not a side effect of `terraform init`.

## Provider setup and an API token with least privilege

The provider block is three lines. Everything that matters is in the token.

```hcl
provider "proxmox" {
  endpoint  = var.proxmox_endpoint
  api_token = var.proxmox_api_token
}
```

The token is a sensitive variable in the form `user@realm!tokenid=secret`. The repo ships a [terraform.tfvars.example](https://github.com/kalikys/homelab/blob/main/terraform/terraform.tfvars.example) with placeholder values; the real file is `secrets.auto.tfvars`, gitignored, and the repo is scanned with gitleaks on every push.

Honesty first, because until this week my own setup failed this section. The token has always belonged to a dedicated `terraform@pve` user, which is the right start. But when I ran `pveum acl list` while writing this post, the ACL on `/` gave that user the built-in `PVEAdmin` role plus a one-privilege custom role `TerraformSys` that added `Sys.Modify`, and the token `homelab` was created with `--privsep=0`, so it inherited every right the user had. One UUID in a tfvars file away from full control of the host. It happened the usual way: a plan failed on a permission, I added the privilege that made it pass, and `PVEAdmin` was the shortcut that made everything pass.

On 2026-10-20 I replaced both roles with one, built from the [provider's authentication docs](https://registry.terraform.io/providers/bpg/proxmox/latest/docs) and the [pveum privilege table](https://pve.proxmox.com/pve-docs/pveum.1.html). This is what the user has now, nothing else:

```sh
pveum user add terraform@pve
pveum role add TerraformMin -privs "VM.Allocate VM.Audit VM.Clone VM.Config.CDROM VM.Config.CPU \
  VM.Config.Cloudinit VM.Config.Disk VM.Config.HWType VM.Config.Memory VM.Config.Network \
  VM.Config.Options VM.PowerMgmt VM.Snapshot VM.Snapshot.Rollback VM.GuestAgent.Audit \
  Datastore.Allocate Datastore.AllocateSpace Datastore.AllocateTemplate Datastore.Audit \
  Sys.Audit SDN.Use"
pveum aclmod / -user terraform@pve -role TerraformMin
pveum acl delete / -user terraform@pve -role PVEAdmin
pveum acl delete / -user terraform@pve -role TerraformSys
pveum user token add terraform@pve homelab --privsep=0
```

Verified so far: a full `terraform plan`, which refreshes all 5 containers and 5 VMs through the API, runs with no permission errors. Not verified yet: an apply that creates or changes a guest. I will do that with the next VM and fix the list if something fails; the article will be updated if it does.

Four things about that role:

1. The provider docs give a much longer privilege list and say themselves it is "likely too permissive for most use cases". Start from the pveum table and add only what your plan fails on. The list above covers creating and editing VMs and containers, cloud-init, disks on existing datastores and reading node status.
2. Keep `SDN.Use` (or `SDN.Audit`) in the role. Without it Proxmox hides the bridges from the node network list and the provider cannot resolve `vmbr0`.
3. `VM.GuestAgent.Audit` is there because every VM in the repo has `agent { enabled = true }`, and on Proxmox VE 9 reading guest agent data (the IP the provider shows you after apply) is a separate privilege from `VM.Audit`. It was the one line I did not have in my first draft of the role.
4. `Sys.Modify` is gone. The pveum docs describe it as "create/modify/remove node network parameters" and say it "should be handled with care". The provider needs it on `/` only to download a cloud image by URL with `proxmox_virtual_environment_download_file`, which is the only reason `TerraformSys` ever existed. The repo does not use that resource. Instead, the image is fetched on the host by hand, checksum verified, and referenced as a local file, as the comment in [images.tf](https://github.com/kalikys/homelab/blob/main/terraform/images.tf) says. `Pool.Allocate` went too; there are no pools.

```hcl
# The Terraform token may not download by URL (needs Sys.Modify on /), so images are fetched on the host by hand:
#   F=/var/lib/vz/import/ubuntu-24.04-server-cloudimg-amd64-20260926.qcow2
#   wget -O $F https://cloud-images.ubuntu.com/releases/noble/release-20260926/ubuntu-24.04-server-cloudimg-amd64.img
#   echo "6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2  $F" | sha256sum -c -
locals {
  ubuntu_noble_image = "local:import/ubuntu-24.04-server-cloudimg-amd64-20260926.qcow2"
}
```

`--privsep=0` means the token inherits the user's permissions. Proxmox defaults to privilege separation, and that is the better choice if you manage several tokens per user, or if the user may ever carry more rights than the token should have, which is exactly how my `PVEAdmin` mistake reached the token. With one user, one purpose and a tight role, `privsep=0` is acceptable, since the ACL on the user is the ACL on the token. Still, the token is the next thing to fix: recreate it with privilege separation and put the ACL on the token itself, so a future "just add PVEAdmin for a minute" on the user cannot leak into it. Proxmox VE 9.2 added the ability to [regenerate a token's secret](https://pve.proxmox.com/wiki/Roadmap) through the API, which makes rotation a one-liner instead of delete-and-recreate.

One more thing the docs are clear about: some calls fail with any API token, even for `root@pam`, with `Permission check failed (user != root@pam)`. The answer is SSH to the node, not a bigger role. I have not needed it for containers or VMs.

## The LXC resource: five containers from one map

All five containers share one resource with `for_each` over a map in [proxmox.tf](https://github.com/kalikys/homelab/blob/main/terraform/proxmox.tf). The map holds the things that differ: ID, IP, MAC, sizing, boot order, which DNS to use, whether the container needs `keyctl` for Docker or `/dev/net/tun` for Tailscale.

```hcl
locals {
  lan = {
    gateway = "192.168.1.1"
    prefix  = 24
    domain  = "home.kalik8s.ru"
    bridge  = "vmbr0"
  }

  lxc_template = "local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst"

  containers = {
    adguard = {
      vm_id   = 100
      ip      = "192.168.1.2"
      mac     = "BC:24:11:FC:7B:69"
      cores   = 1
      memory  = 512
      swap    = 256
      disk_gb = 4
      order   = 1
      dns     = ["1.1.1.1", "9.9.9.9"]
      keyctl  = false
      tun     = false
      dmz_ip  = null
    }
    # tailscale, npm, apps, public ...
  }
}
```

The resource itself, trimmed to the parts that matter:

```hcl
resource "proxmox_virtual_environment_container" "lxc" {
  for_each = local.containers

  node_name     = var.proxmox_node
  vm_id         = each.value.vm_id
  unprivileged  = true
  start_on_boot = true
  started       = true

  startup {
    order = each.value.order
  }

  features {
    nesting = true
    keyctl  = each.value.keyctl
  }

  cpu {
    cores = each.value.cores
  }

  memory {
    dedicated = each.value.memory
    swap      = each.value.swap
  }

  disk {
    datastore_id = "local-zfs"
    size         = each.value.disk_gb
  }

  initialization {
    hostname = each.key

    dns {
      domain  = local.lan.domain
      servers = each.value.dns
    }

    ip_config {
      ipv4 {
        address = "${each.value.ip}/${local.lan.prefix}"
        gateway = local.lan.gateway
      }
    }
  }

  network_interface {
    name        = "eth0"
    bridge      = local.lan.bridge
    mac_address = each.value.mac
  }

  operating_system {
    template_file_id = local.lxc_template
    type             = "debian"
  }

  dynamic "device_passthrough" {
    for_each = each.value.tun ? ["/dev/net/tun"] : []
    content {
      path = device_passthrough.value
    }
  }

  lifecycle {
    prevent_destroy = true
    # The template is only used at creation time and cannot be read back from an existing container.
    ignore_changes = [operating_system[0].template_file_id]
  }
}
```

Notes on the choices:

- **`unprivileged = true` is not the default.** The provider defaults to `false`. Proxmox VE 9.0 made it harder to be careless here: creating a privileged container now needs `Sys.Modify` "in most cases" ([release notes](https://pve.proxmox.com/wiki/Roadmap)), so with the `TerraformMin` role above a privileged container simply fails to create. Good. With the old `PVEAdmin` plus `Sys.Modify` it would have succeeded silently.
- **`mac_address` is pinned.** The containers existed before the repo. If I let Proxmox generate MACs, the import would show a diff on every interface, and a guest that ever gets recreated would turn up as a new device on the LAN.
- **`features` beyond `nesting` need root.** The provider docs say "Changing flags (except nesting) is only allowed for `root@pam` authenticated user". `keyctl` is in the map because the Docker containers (`npm`, `apps`, `public`) have it on the host, and the code has to match what is there for the import to plan clean. Flipping it through the API token will fail; that is a UI change followed by a refresh.
- **`ignore_changes` on the template.** Proxmox does not store which template a container was made from, so after an import the provider would plan to replace the container to "fix" the template. That one lifecycle line is the difference between a clean plan and a destroyed DNS server.
- **The second NIC.** The `public` container has a `dynamic "ip_config"` and a `dynamic "network_interface"` for a leg into an isolated bridge where a throwaway sandbox VM lives. Changing a container's network interfaces through the provider restarts the container, even though the plan shows an in-place update. I learned that the loud way and put it in the README.

## A cloud-init VM without a template VM

The usual recipe is: make a template VM by hand, then `clone` it. I skipped the template. bpg's `disk.import_from` takes an image straight from a datastore with the `import` content type ("The image must be of `import` content type (uncompressed images only)", [VM resource docs](https://registry.terraform.io/providers/bpg/proxmox/latest/docs/resources/virtual_environment_vm)), and the docs say to "prefer `import_from` for uncompressed images". The three Kubernetes lab VMs in [lab.tf](https://github.com/kalikys/homelab/blob/main/terraform/lab.tf) are the cleanest example:

```hcl
locals {
  lab_vms = {
    k8s-cp = { vm_id = 210, ip = "192.168.1.20", mac = "BC:24:11:4B:38:20", role = "Kubernetes lab: control plane" }
    k8s-w1 = { vm_id = 211, ip = "192.168.1.21", mac = "BC:24:11:4B:38:21", role = "Kubernetes lab: worker" }
    k8s-w2 = { vm_id = 212, ip = "192.168.1.22", mac = "BC:24:11:4B:38:22", role = "Kubernetes lab: worker" }
  }
  lab_cores     = 2
  lab_memory_mb = 4096
  lab_disk_gb   = 30
}

resource "proxmox_virtual_environment_vm" "lab" {
  for_each = local.lab_vms

  node_name = var.proxmox_node
  vm_id     = each.value.vm_id
  name      = each.key
  tags      = ["k8s-lab"]

  # The lab runs only while practising: started with `lab up` on the host.
  on_boot = false
  started = false

  machine       = "q35"
  scsi_hardware = "virtio-scsi-single"

  agent {
    enabled = true
  }

  cpu {
    cores = local.lab_cores
    type  = "host"
  }

  memory {
    dedicated = local.lab_memory_mb
  }

  disk {
    datastore_id = "local-zfs"
    interface    = "scsi0"
    import_from  = local.ubuntu_noble_image
    size         = local.lab_disk_gb
    iothread     = true
    discard      = "on"
  }

  network_device {
    bridge      = local.lan.bridge
    mac_address = each.value.mac
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
        address = "${each.value.ip}/${local.lan.prefix}"
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
    # Started and stopped by the `lab` host script; the image is only used at creation.
    ignore_changes = [started, disk[0].import_from]
  }
}
```

What each part does:

- **`initialization.datastore_id`** is where the cloud-init ISO goes. The provider defaults to `local-lvm`, which does not exist on a ZFS install, so set it.
- **`user_account` vs `user_data_file_id`.** They conflict. `user_account` is enough for "a user with my SSH key"; the moment you need packages or `runcmd` you switch to a snippet, and snippets are one of the few things that still need SSH to the node. My provisioning for the lab (containerd, kubeadm) lives in a shell script on the host instead, so the token stays API-only.
- **`ip_config` with a static address** plus `dns.servers` pointing at AdGuard, which serves the internal zone `home.kalik8s.ru`. The MAC is pinned for the same reason as on the containers: a recreated VM should look like the same device.
- **`started = false` with `ignore_changes = [started]`.** The lab only runs when I practise, and a host script starts and stops it. Without the ignore, every plan would want to stop my running cluster.
- **`ignore_changes = [disk[0].import_from]`.** Same story as the LXC template: the image is a creation-time input. When I bump the image date in `images.tf` for a new VM, the old ones must not be recreated.
- **`agent.enabled = true`** so the provider can read the guest's IP, and `cpu.type = "host"` because nested virtualisation is useful in a Kubernetes lab.

The long-running VMs ([agent.tf](https://github.com/kalikys/homelab/blob/main/terraform/agent.tf), [farm.tf](https://github.com/kalikys/homelab/blob/main/terraform/farm.tf), [content.tf](https://github.com/kalikys/homelab/blob/main/terraform/content.tf)) are the same shape with `on_boot = true`, a `startup { order }` after the containers, and `firewall = true` on the NIC so the Proxmox firewall applies.

## Networking and DNS: keep the addresses in one map

The pattern across both resource types is the same: one `local.lan` object with gateway, prefix, domain and bridge, and per-guest IP and MAC in the map. Guests get static addresses from cloud-init or the LXC config; DNS goes to the AdGuard container (`192.168.1.2`), which serves the internal zone. Nothing is port-forwarded. The only public path is a Cloudflare Tunnel from the `public` container, and the tunnel, its ingress rules and the CNAME records are Terraform too ([cloudflare.tf](https://github.com/kalikys/homelab/blob/main/terraform/cloudflare.tf)).

One trick worth copying is in [outputs.tf](https://github.com/kalikys/homelab/blob/main/terraform/outputs.tf): a `local.site_inventory` built from the same maps, roles included and addresses left out, exported to JSON for the architecture diagram on [my CV page](https://kalik8s.com/#homelab). Add a VM in Terraform and the diagram follows.

## State and drift: import blocks, targeted applies, and the mistake I made

All five containers were created by hand before the repo existed. Recreating a DNS server and a reverse proxy to make Terraform happy is backwards, so I adopted them with `import` blocks ([imports.tf](https://github.com/kalikys/homelab/blob/main/terraform/imports.tf)). With `for_each` in the import block one stanza covers the whole map:

```hcl
import {
  for_each = local.containers
  to       = proxmox_virtual_environment_container.lxc[each.key]
  id       = "${var.proxmox_node}/${each.value.vm_id}"
}
```

The ID format for both containers and VMs is `node_name/vm_id`. Import blocks are plannable, so `terraform plan` shows exactly which attributes differ between the hand-made container and the code before anything is written to state. That plan is where `ignore_changes` on the template came from, and where I found the differences in `console` and `features` that I then wrote into the config rather than letting Terraform "fix".

Then I did the thing this section is really about. On 2026-10-05 the host was swapping. The code at that point asked for more memory than the machine has: 3 lab VMs at 4 GB, the agent at 4 GB, the farm at 8 GB, the content VM at 6 GB, plus 6.75 GB across the containers and a sandbox VM. That is about 38 GB of `dedicated` memory on a 32 GB host, with ZFS ARC on top. I fixed it in the UI: farm down to 4096 with a 2048 balloon, agent to 2048/1024, content to 4096/1024, ARC capped at 2 GB, zram swap on the host.

Reality was now correct. The code was not: [farm.tf](https://github.com/kalikys/homelab/blob/main/terraform/farm.tf) still says `memory_mb = 8192` and has no `floating` value. And state was behind both: it held the agent, the farm and the lab VMs, while the containers were still only import blocks and the content VM existed on the host but not in state. A bare `terraform plan` at that moment wanted to import five containers, create a VM that already existed, bump three VMs back to their old memory, and rewrite the tunnel config. Four unrelated changes, two of them capable of taking down services.

The rule I follow since then, at home and at work:

```sh
terraform plan -target=proxmox_virtual_environment_vm.farm -out=farm.tfplan
# read the diff: is it only what I meant to change?
terraform apply farm.tfplan
```

HashiCorp's docs say `-target` is for "exceptional circumstances only" and that routine use "can lead to undetected configuration drift". Both true. But on a box where state is already behind, a full apply is what causes the outage, and a targeted apply with a saved, reviewed plan is what lets you converge one resource at a time. `-out` is the key part: apply executes exactly what you read, not whatever the API returns thirty seconds later. Treat the file as sensitive; it holds your variables in cleartext.

The way back to a clean full plan is boring on purpose: fix the code to match the host for each guest (memory values, `floating` for the balloon), apply with `-target`, import what is missing, repeat until `terraform plan` says no changes. Then take `-target` out of your muscle memory. Every resource I cannot rebuild in an hour carries `prevent_destroy = true`, so even a wrong plan cannot delete it before I edit the code.

## Proxmox VE 9 gotchas I ran into or read about

My host runs Proxmox VE 9.2 on Debian 13; the LXC template in the repo is `debian-13-standard_13.6-1`. From the [release notes](https://pve.proxmox.com/wiki/Roadmap) and the provider docs, the items that affect Terraform users:

- **Privileges changed in 9.0.** `VM.Monitor` was dropped in favour of `Sys.Audit`, `VM.Replicate` is new, and privileged containers need `Sys.Modify`. If your `Terraform` role was created on PVE 8, run `pve8to9` and re-check the role; a custom role that references a removed privilege is reported by the script.
- **Network interface names can change on upgrade.** Proxmox 9 handles most renames transparently, but `pve-network-interface-pinning` before the upgrade is cheap insurance when your bridge config says `enp0s31f6`.
- **cgroup v1 is gone.** Old container templates that need the hybrid hierarchy will not start. Debian 13 and Ubuntu 24.04 are fine.
- **`host_managed` network interfaces need 9.1+.** The provider gates it on 9.1, and it matters for OCI application containers, which 9.1 introduced.
- **9.2 requires `VM.Config.Cloudinit` to dump the cloud-init password.** If your plan starts failing on read after the upgrade, that is the privilege to add.
- **TLS 1.3 by default.** The provider's endpoint connection requires TLS 1.3 unless you lower `min_tls`. PVE 9 is fine; an old reverse proxy in front of it may not be.
- **Idle connections.** bpg 0.117.0 fixed a case where the provider kept an API connection open longer than pveproxy did, which showed up as flaky plans on long runs. Worth the bump if you see random connection errors.

Not verified by me, so not claimed: volume-chain snapshots on LVM (my disks are ZFS), SDN fabrics, HA affinity rules on a one-node "cluster".

## CI: fmt, validate and tflint without credentials

The repo runs three checks on every push and pull request ([ci.yml](https://github.com/kalikys/homelab/blob/main/.github/workflows/ci.yml)). The Terraform job needs no backend and no token: providers are downloaded, `validate` runs offline.

```yaml
jobs:
  terraform:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: terraform
    steps:
      - uses: actions/checkout@v4

      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "~1.15"

      - name: fmt
        run: terraform fmt -check -recursive -diff

      # No backend and no credentials: providers are only downloaded, validate runs offline.
      - name: init
        run: terraform init -backend=false -input=false

      - name: validate
        run: terraform validate -no-color

      - uses: terraform-linters/setup-tflint@v4
        with:
          tflint_version: v0.64.0

      - name: tflint
        run: |
          tflint --init
          tflint --format compact
```

A separate job runs gitleaks over the full history with `--redact`. The lock file is committed, so CI installs the same provider build I plan with. This is the same shape as the pipelines I run at work, where Terraform and Ansible manage 100+ VMs across datacenters: cheap checks on every change with no credentials, apply as a separate, deliberate step.

What CI does not do is `terraform plan` against the live host. The host is behind double NAT with no open ports, and I do not want a GitHub runner holding a Proxmox token. Plans happen from my laptop over Tailscale.

## Cheat-sheet and next steps

| I want to | bpg resource or argument | Note |
|---|---|---|
| A container with a static IP | `proxmox_virtual_environment_container` + `initialization.ip_config.ipv4` | `address` in CIDR, `gateway` separate |
| Docker inside an unprivileged LXC | `features { nesting = true, keyctl = true }` | `keyctl` only settable as `root@pam` |
| Tailscale in an LXC | `device_passthrough { path = "/dev/net/tun" }` | Works unprivileged |
| A VM from a cloud image | `disk.import_from = "local:import/<file>.qcow2"` | Uncompressed only; put the file in the `import` content type |
| User and SSH key via cloud-init | `initialization.user_account` | Conflicts with `user_data_file_id` |
| Custom cloud-init YAML | `initialization.user_data_file_id` + `proxmox_virtual_environment_file` | Snippets need SSH to the node |
| Adopt an existing guest | `import { to = ..., id = "node/vmid" }` | Plan first, then add `ignore_changes` for creation-only inputs |
| Stop a plan from fighting a stopped VM | `lifecycle { ignore_changes = [started] }` | Same for `disk[0].import_from` and `template_file_id` |
| Never lose a guest to a bad plan | `lifecycle { prevent_destroy = true }` | On every guest in my repo |

If you are starting from zero on Proxmox VE 9:

1. Create `terraform@pve`, the `TerraformMin` role from the list above (not `PVEAdmin`), and a token with privilege separation. Keep the token in a gitignored `*.auto.tfvars`.
2. Download one cloud image to `/var/lib/vz/import/` on the host, verify the checksum, and bring up one VM with `import_from` and an `initialization` block.
3. If you already have guests, write the resource, add an `import` block, and read the plan before you apply. Add `ignore_changes` for the creation-only inputs it complains about.
4. Add `fmt`, `validate` and `tflint` to CI without credentials.
5. When state falls behind, converge with `-target` and saved plans, one resource at a time, until a full plan is empty again. Then stop using `-target`.

The full code is at [github.com/kalikys/homelab/tree/main/terraform](https://github.com/kalikys/homelab/tree/main/terraform). The first apply under `TerraformMin` and the privsep token are next; if the role needs another line, this post gets it.
