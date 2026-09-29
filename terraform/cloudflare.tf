locals {
  cloudflare_zone_id = "bf49c54c8775914b78435b97d296958f"

  # Public hostname -> service inside the docker network on LXC "public".
  tunnel_routes = {
    cv     = "http://site:80"
    status = "http://gatus:8080"
    shell  = "http://10.66.0.10:7681" # sandbox VM on the isolated bridge, reached through LXC 104 eth1
  }

  # Ingress rules are an ordered list; keep this order stable to avoid no-op diffs.
  tunnel_route_order = ["cv", "status", "shell"]
}

# Remotely managed tunnel: cloudflared on LXC "public" only needs the token,
# routes live here.
resource "cloudflare_zero_trust_tunnel_cloudflared" "public" {
  account_id = var.cloudflare_account_id
  name       = "CV"
  config_src = "cloudflare"
}

resource "cloudflare_zero_trust_tunnel_cloudflared_config" "public" {
  account_id = var.cloudflare_account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.public.id

  config = {
    ingress = concat(
      [for sub in local.tunnel_route_order : {
        hostname = "${sub}.${var.cloudflare_zone}"
        service  = local.tunnel_routes[sub]
      }],
      [{ service = "http_status:404" }],
    )
  }
}

resource "cloudflare_dns_record" "tunnel" {
  for_each = local.tunnel_routes

  zone_id = local.cloudflare_zone_id
  name    = "${each.key}.${var.cloudflare_zone}"
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.public.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1
}
