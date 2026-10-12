# Content pipeline: scheduled short videos and article drafts. See docs/superpowers/specs/2026-10-02-content-pipeline-design.md.
locals {
  content = {
    vm_id     = 250
    ip        = "192.168.1.41"
    mac       = "BC:24:11:4B:38:41"
    cores     = 4
    memory_mb = 6144
    disk_gb   = 80
    role      = "Content pipeline: videos and article drafts"
  }
}

resource "proxmox_virtual_environment_vm" "content" {
  node_name   = var.proxmox_node
  vm_id       = local.content.vm_id
  name        = "content"
  description = "${local.content.role}\n"
  tags        = ["content"]

  on_boot = true
  startup {
    order = 9
  }

  machine       = "q35"
  scsi_hardware = "virtio-scsi-single"

  agent {
    enabled = true
  }

  cpu {
    cores = local.content.cores
    type  = "host"
  }

  memory {
    dedicated = local.content.memory_mb
  }

  disk {
    datastore_id = "local-zfs"
    interface    = "scsi0"
    import_from  = local.ubuntu_noble_image
    size         = local.content.disk_gb
    iothread     = true
    discard      = "on"
  }

  network_device {
    bridge      = local.lan.bridge
    mac_address = local.content.mac
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
        address = "${local.content.ip}/${local.lan.prefix}"
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
