# Startup farm: n8n skeleton (stages, guardrails, approvals), Postgres state, Claude agent runner. See Obsidian "Ферма — каркас на n8n".
locals {
  farm = {
    vm_id     = 230
    ip        = "192.168.1.30"
    mac       = "BC:24:11:4B:38:30"
    cores     = 4
    memory_mb = 8192
    disk_gb   = 40
    role      = "Startup farm: n8n workflows, Postgres, Claude agents, Phoenix tracing"
  }
}

resource "proxmox_virtual_environment_vm" "farm" {
  node_name   = var.proxmox_node
  vm_id       = local.farm.vm_id
  name        = "farm"
  description = "${local.farm.role}\n"
  tags        = ["farm"]

  on_boot = true
  startup {
    order = 8
  }

  machine       = "q35"
  scsi_hardware = "virtio-scsi-single"

  agent {
    enabled = true
  }

  cpu {
    cores = local.farm.cores
    type  = "host"
  }

  memory {
    dedicated = local.farm.memory_mb
  }

  disk {
    datastore_id = "local-zfs"
    interface    = "scsi0"
    import_from  = local.ubuntu_noble_image
    size         = local.farm.disk_gb
    iothread     = true
    discard      = "on"
  }

  network_device {
    bridge      = local.lan.bridge
    mac_address = local.farm.mac
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
        address = "${local.farm.ip}/${local.lan.prefix}"
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
