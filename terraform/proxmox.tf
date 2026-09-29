locals {
  lan = {
    gateway = "192.168.1.1"
    prefix  = 24
    domain  = "home.kalik8s.ru"
    bridge  = "vmbr0"
  }

  lxc_template = "local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst"

  # All LXC guests. Keys are hostnames.
  containers = {
    adguard = {
      vm_id       = 100
      description = "AdGuard Home - home DNS"
      ip          = "192.168.1.2"
      mac         = "BC:24:11:FC:7B:69"
      cores       = 1
      memory      = 512
      swap        = 256
      disk_gb     = 4
      order       = 1
      dns         = ["1.1.1.1", "9.9.9.9"]
      keyctl      = false
      tun         = false
    }
    tailscale = {
      vm_id       = 101
      description = null
      ip          = "192.168.1.3"
      mac         = "BC:24:11:18:1E:20"
      cores       = 1
      memory      = 512
      swap        = 256
      disk_gb     = 4
      order       = 2
      dns         = ["192.168.1.2"]
      keyctl      = false
      tun         = true
    }
    npm = {
      vm_id       = 102
      description = "Nginx Proxy Manager (docker) - *.home.kalik8s.ru"
      ip          = "192.168.1.4"
      mac         = "BC:24:11:19:53:08"
      cores       = 2
      memory      = 1024
      swap        = 512
      disk_gb     = 8
      order       = 3
      dns         = ["192.168.1.2"]
      keyctl      = true
      tun         = false
    }
    apps = {
      vm_id       = 103
      description = "Docker apps: Homepage, Paperless-ngx"
      ip          = "192.168.1.10"
      mac         = "BC:24:11:BF:BA:B9"
      cores       = 4
      memory      = 4096
      swap        = 1024
      disk_gb     = 32
      order       = 4
      dns         = ["192.168.1.2"]
      keyctl      = true
      tun         = false
    }
    public = {
      vm_id       = 104
      description = "Public edge: CV site, Gatus status page, Cloudflare Tunnel"
      ip          = "192.168.1.11"
      mac         = "BC:24:11:24:32:AD"
      cores       = 1
      memory      = 768
      swap        = 256
      disk_gb     = 6
      order       = 5
      dns         = ["192.168.1.2"]
      keyctl      = true
      tun         = false
    }
  }
}

resource "proxmox_virtual_environment_container" "lxc" {
  for_each = local.containers

  node_name     = var.proxmox_node
  vm_id         = each.value.vm_id
  description   = each.value.description == null ? null : "${each.value.description}\n"
  unprivileged  = true
  start_on_boot = true
  started       = true

  startup {
    order = each.value.order
  }

  console {
    enabled   = true
    type      = "tty"
    tty_count = 2
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
