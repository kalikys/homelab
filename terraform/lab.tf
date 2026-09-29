# Kubernetes lab for CKA / CKAD / CKS practice: one control plane and two workers.
# Terraform only creates the VMs; host/lab/provision.sh installs containerd and kubeadm,
# and the cluster itself is bootstrapped by hand as part of the practice.
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

  node_name   = var.proxmox_node
  vm_id       = each.value.vm_id
  name        = each.key
  description = "${each.value.role}. Snapshots: base (clean, kubeadm installed), cluster (after bootstrap).\n"
  tags        = ["k8s-lab"]

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
