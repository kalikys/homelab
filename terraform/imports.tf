# Existing guests were created by hand before this repo existed and are adopted into state here.
import {
  for_each = { for name, container in local.containers : name => container if container.vm_id <= 104 }
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
  id = "${local.legacy_zone_id}/c88aade9123dca169c779ed48a409756"
}

import {
  to = cloudflare_dns_record.tunnel["status"]
  id = "${local.legacy_zone_id}/821fd5b07dc962619e757a1f0b394eeb"
}

import {
  to = cloudflare_dns_record.tunnel["shell"]
  id = "${local.legacy_zone_id}/51d27437ec9b0020438747f7c938919e"
}
