variable "proxmox_endpoint" {
  description = "Proxmox VE API endpoint."
  type        = string
  default     = "https://proxmox.home.kalik8s.ru/"
}

variable "proxmox_api_token" {
  description = "Proxmox API token in the form user@realm!tokenid=secret."
  type        = string
  sensitive   = true
}

variable "proxmox_node" {
  description = "Proxmox node name."
  type        = string
  default     = "pve"
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token: Zone DNS Edit, Zone Read, Account Cloudflare Tunnel Edit."
  type        = string
  sensitive   = true
}

variable "cloudflare_account_id" {
  description = "Cloudflare account ID."
  type        = string
}

variable "cloudflare_zone" {
  description = "Public DNS zone."
  type        = string
  default     = "kalik8s.com"
}
