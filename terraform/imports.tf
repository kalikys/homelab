# Existing guests were created by hand before this repo existed and are adopted into state here.
import {
  for_each = local.containers
  to       = proxmox_virtual_environment_container.lxc[each.key]
  id       = "${var.proxmox_node}/${each.value.vm_id}"
}

import {
  to = cloudflare_zero_trust_tunnel_cloudflared.public
  id = "${var.cloudflare_account_id}/0358b353-00db-4fb2-aaa8-8f01d950bb21"
}

import {
  to = cloudflare_zero_trust_tunnel_cloudflared_config.public
  id = "${var.cloudflare_account_id}/0358b353-00db-4fb2-aaa8-8f01d950bb21"
}

import {
  to = cloudflare_dns_record.tunnel["cv"]
  id = "${local.cloudflare_zone_id}/c88aade9123dca169c779ed48a409756"
}

import {
  to = cloudflare_dns_record.tunnel["status"]
  id = "${local.cloudflare_zone_id}/821fd5b07dc962619e757a1f0b394eeb"
}

# cloudflare_dns_record.tunnel["shell"]: import once the record exists (created together with the tunnel route).
