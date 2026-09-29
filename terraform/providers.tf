provider "proxmox" {
  endpoint  = var.proxmox_endpoint
  api_token = var.proxmox_api_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}
