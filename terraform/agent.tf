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
    import_from  = local.ubuntu_noble_image
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
