locals {
  # Public pages live on kalik8s.com. kalik8s.ru keeps the home zone (home.kalik8s.ru)
  # and its old public names only redirect to the new ones.
  public_zone_id = "70e79d3542071a5ee78e996fd30e5227"
  legacy_zone_id = "bf49c54c8775914b78435b97d296958f"
  legacy_zone    = "kalik8s.ru"

  # Route key -> public hostname, service inside the docker network on LXC "public",
  # and the guest that ends up serving it (used by the CV architecture diagram).
  public_routes = {
    cv     = { hostname = var.cloudflare_zone, service = "http://site:80", guest = "public" }
    www    = { hostname = "www.${var.cloudflare_zone}", service = "http://site:80", guest = "public" } # nginx redirects to the apex
    status = { hostname = "status.${var.cloudflare_zone}", service = "http://gatus:8080", guest = "public" }
    shell  = { hostname = "shell.${var.cloudflare_zone}", service = "http://10.66.0.10:7681", guest = "sandbox" } # sandbox VM on the isolated bridge, reached through LXC 104 eth1
  }

  # Old names under kalik8s.ru go to nginx on the site container, which answers with a 301.
  legacy_hosts = ["cv", "status", "shell"]

  # Ingress rules are an ordered list; keep this order stable to avoid no-op diffs.
  public_route_order = ["cv", "www", "status", "shell"]
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
      [for key in local.public_route_order : {
        hostname = local.public_routes[key].hostname
        service  = local.public_routes[key].service
      }],
      [for sub in local.legacy_hosts : {
        hostname = "${sub}.${local.legacy_zone}"
        service  = "http://site:80"
      }],
      [{ service = "http_status:404" }],
    )
  }
}

resource "cloudflare_dns_record" "public" {
  for_each = local.public_routes

  zone_id = local.public_zone_id
  name    = each.value.hostname
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.public.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1
}

# Old public names under kalik8s.ru, kept so existing links keep working (nginx redirects them).
resource "cloudflare_dns_record" "tunnel" {
  for_each = toset(local.legacy_hosts)

  zone_id = local.legacy_zone_id
  name    = "${each.key}.${local.legacy_zone}"
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.public.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1
}
