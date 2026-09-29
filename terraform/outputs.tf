locals {
  guest_roles = {
    adguard    = "DNS and ad blocking for the LAN and VPN"
    tailscale  = "VPN subnet router and exit node"
    npm        = "Reverse proxy with wildcard TLS"
    apps       = "Home apps in Docker"
    public     = "Public edge: CV, status page, Cloudflare Tunnel"
    monitoring = "Prometheus metrics, Grafana dashboards and network probes"
  }
}

# Public-safe inventory for the CV site: no addresses, no secrets.
# scripts/export-site-data.py reads local.site_inventory through `terraform console`.
output "homelab_inventory" {
  description = "Inventory exported to services/public/site/data/homelab.json."
  value       = local.site_inventory
}

locals {
  site_inventory = {
    host = {
      name     = var.proxmox_node
      platform = "Proxmox VE"
      storage  = "ZFS"
    }
    guests = concat(
      [for name, c in local.containers : {
        name      = name
        id        = c.vm_id
        kind      = "lxc"
        cores     = c.cores
        memory_mb = c.memory
        disk_gb   = c.disk_gb
        role      = local.guest_roles[name]
        network   = c.dmz_ip == null ? ["lan"] : ["lan", "dmz"]
      }],
      [{
        name      = "sandbox"
        id        = 200
        kind      = "vm"
        cores     = 1
        memory_mb = 768
        disk_gb   = 6
        role      = "Public web terminal, isolated network, reset every 30 minutes"
        network   = ["dmz"]
      }],
    )
    networks = {
      lan = "Home LAN behind double NAT, no inbound ports"
      dmz = "Isolated bridge without uplink; only the edge container can reach the sandbox"
    }
    public_routes = [for key in local.public_route_order : {
      hostname = local.public_routes[key].hostname
      guest    = local.public_routes[key].guest
    } if key != "www"]
  }
}
