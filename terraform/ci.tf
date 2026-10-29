# CI for vardhold/hub: GitLab Runner manager (VM 290) + the template every job VM is cloned from (VM 9100).
# Each job runs in a fresh linked clone (VMID 9200-9299, pool ci-jobs, name ci-<job id>) that is destroyed afterwards;
# those clones are made by services/ci-runner/executor/pvejob.py through the Proxmox API, never by Terraform.
# Network: bridge vmbr9 (10.99.0.0/24, host 10.99.0.1) with NAT to the internet and no route to the LAN, see
# host/ci-nat.sh. The bridge, pool, role and token are created by hand (services/ci-runner/README.md), because the
# terraform@pve token has no Sys.Modify / Pool.Allocate. User-data comes from Proxmox snippets copied by hand too:
# the provider has no SSH access to the node to upload them.
locals {
  ci_net = {
    bridge  = "vmbr9"
    cidr    = "10.99.0.0/24"
    gateway = "10.99.0.1"
    prefix  = 24
    dns     = ["1.1.1.1", "9.9.9.9"] # public: the LAN resolver is deliberately out of reach
  }

  ci_runner = {
    vm_id     = 290
    ip        = "192.168.1.42"
    mac       = "BC:24:11:4B:38:42"
    ci_ip     = "10.99.0.2"
    cores     = 1
    memory_mb = 1024
    disk_gb   = 16
    role      = "GitLab Runner manager for vardhold/hub: one throwaway VM per CI job"
    user_data = "local:snippets/ci-runner-manager.yaml" # services/ci-runner/cloud-init-manager.yaml
  }

  ci_template = {
    vm_id     = 9100
    build_ip  = "10.99.0.9" # used only during the one build boot
    cores     = 4
    memory_mb = 4096
    disk_gb   = 30
    user_data = "local:snippets/ci-template.yaml" # services/ci-runner/cloud-init-template.yaml
  }
}

resource "proxmox_virtual_environment_vm" "ci_runner" {
  node_name   = var.proxmox_node
  vm_id       = local.ci_runner.vm_id
  name        = "ci-runner"
  description = "${local.ci_runner.role}\n"
  tags        = ["ci"]

  on_boot = true
  startup {
    order = 10
  }

  machine       = "q35"
  scsi_hardware = "virtio-scsi-single"

  agent {
    enabled = true
  }

  cpu {
    cores = local.ci_runner.cores
    type  = "host"
  }

  memory {
    dedicated = local.ci_runner.memory_mb
  }

  disk {
    datastore_id = "local-zfs"
    interface    = "scsi0"
    import_from  = local.ubuntu_noble_image
    size         = local.ci_runner.disk_gb
    iothread     = true
    discard      = "on"
  }

  # net0: LAN (Proxmox API, gitlab.com, admin ssh). Filtered by host/firewall/290.fw.
  network_device {
    bridge      = local.lan.bridge
    mac_address = local.ci_runner.mac
    firewall    = true
  }

  # net1: CI bridge, only for ssh to job VMs. No gateway here: the default route stays on the LAN.
  network_device {
    bridge   = local.ci_net.bridge
    firewall = true
  }

  operating_system {
    type = "l26"
  }

  initialization {
    datastore_id      = "local-zfs"
    user_data_file_id = local.ci_runner.user_data

    dns {
      domain  = local.lan.domain
      servers = ["192.168.1.2"]
    }

    ip_config {
      ipv4 {
        address = "${local.ci_runner.ip}/${local.lan.prefix}"
        gateway = local.lan.gateway
      }
    }

    ip_config {
      ipv4 {
        address = "${local.ci_runner.ci_ip}/${local.ci_net.prefix}"
      }
    }
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [disk[0].import_from]
  }
}

# Template for job VMs. Two targeted applies (services/ci-runner/README.md, "Build the template"):
#   1. -var ci_template_build=true: a normal VM boots once, cloud-init installs the toolchain and powers it off;
#   2. default (false): Terraform converts the stopped VM into a template in place.
# The template is NOT in pool ci-jobs, so the runner's token can clone it but never change or delete it.
resource "proxmox_virtual_environment_vm" "ci_template" {
  node_name   = var.proxmox_node
  vm_id       = local.ci_template.vm_id
  name        = "ci-template"
  description = "Template for throwaway CI job VMs (vardhold/hub). Built from services/ci-runner/cloud-init-template.yaml; rebuild, never edit.\n"
  tags        = ["ci"]

  template = !var.ci_template_build
  started  = var.ci_template_build
  on_boot  = false

  machine       = "q35"
  scsi_hardware = "virtio-scsi-single"

  # Clones inherit this: pvejob.py reads each clone's SSH host key through the guest agent.
  agent {
    enabled = true
  }

  cpu {
    cores = local.ci_template.cores
    type  = "host"
  }

  memory {
    dedicated = local.ci_template.memory_mb
  }

  disk {
    datastore_id = "local-zfs"
    interface    = "scsi0"
    import_from  = local.ubuntu_noble_image
    size         = local.ci_template.disk_gb
    iothread     = true
    discard      = "on"
  }

  # No Proxmox firewall on job VMs: their VMIDs are throwaway, so per-VM .fw files cannot follow them.
  # Isolation is enforced on the host's routing path (host/ci-nat.sh) and on the manager's NIC (290.fw).
  network_device {
    bridge   = local.ci_net.bridge
    firewall = false
  }

  operating_system {
    type = "l26"
  }

  initialization {
    datastore_id      = "local-zfs"
    user_data_file_id = local.ci_template.user_data

    dns {
      servers = local.ci_net.dns
    }

    ip_config {
      ipv4 {
        address = "${local.ci_template.build_ip}/${local.ci_net.prefix}"
        gateway = local.ci_net.gateway
      }
    }
  }

  lifecycle {
    prevent_destroy = true
    # The VM powers itself off at the end of the build boot.
    ignore_changes = [disk[0].import_from, started]
  }
}
