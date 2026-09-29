# Cloud images shared by the VMs created from Terraform (agent, Kubernetes lab).
# The Terraform token may not download by URL (needs Sys.Modify on /), so images are fetched on the host by hand:
#   F=/var/lib/vz/import/ubuntu-24.04-server-cloudimg-amd64-20260926.qcow2
#   wget -O $F https://cloud-images.ubuntu.com/releases/noble/release-20260926/ubuntu-24.04-server-cloudimg-amd64.img
#   echo "6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2  $F" | sha256sum -c -
locals {
  ubuntu_noble_image = "local:import/ubuntu-24.04-server-cloudimg-amd64-20260926.qcow2"
}
