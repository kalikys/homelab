#!/bin/bash
# Prepares an Ubuntu 24.04 lab VM for kubeadm: containerd, kubelet/kubeadm/kubectl v1.35, guest agent, asciinema.
# Does not create a cluster. Run as root over SSH from the Mac:
#   for h in k8s-cp k8s-w1 k8s-w2; do ssh $h 'sudo bash -s' < host/lab/provision.sh; done
set -euo pipefail

K8S_MINOR=v1.35
ASCIINEMA_VERSION=3.2.1
ASCIINEMA_SHA256=bec9781bc8f297a9d3d74ff60205599507f2abba1183578b8b2f22be4c999214
export DEBIAN_FRONTEND=noninteractive

cloud-init status --wait >/dev/null || true
apt-get update -q
apt-get install -y -q qemu-guest-agent containerd apt-transport-https ca-certificates curl gpg bash-completion jq
systemctl enable --now qemu-guest-agent

# kubelet refuses to run with swap on.
swapoff -a
sed -i '/\sswap\s/d' /etc/fstab

cat > /etc/modules-load.d/k8s.conf <<EOF
overlay
br_netfilter
EOF
modprobe overlay
modprobe br_netfilter
cat > /etc/sysctl.d/99-k8s.conf <<EOF
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward = 1
EOF
sysctl --system >/dev/null

# containerd with the systemd cgroup driver, as kubeadm expects.
mkdir -p /etc/containerd
containerd config default > /etc/containerd/config.toml
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd

install -d -m 755 /etc/apt/keyrings
curl -fsSL "https://pkgs.k8s.io/core:/stable:/$K8S_MINOR/deb/Release.key" | gpg --dearmor --yes -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/$K8S_MINOR/deb/ /" > /etc/apt/sources.list.d/kubernetes.list
apt-get update -q
apt-get install -y -q kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl
systemctl enable kubelet

# asciinema 3 (static binary, checksum pinned) for the live stream.
curl -fsSL -o /tmp/asciinema "https://github.com/asciinema/asciinema/releases/download/v$ASCIINEMA_VERSION/asciinema-x86_64-unknown-linux-musl"
echo "$ASCIINEMA_SHA256  /tmp/asciinema" | sha256sum -c -
install -m 755 /tmp/asciinema /usr/local/bin/asciinema
rm -f /tmp/asciinema

# Exam-style shell: `k` alias with completion.
cat > /etc/profile.d/k8s-lab.sh <<'EOF'
alias k=kubectl
if [ -n "$BASH_VERSION" ]; then
  source <(kubectl completion bash)
  complete -o default -F __start_kubectl k
fi
EOF

apt-get clean
echo "provisioned $(hostname): kubeadm $(kubeadm version -o short), containerd $(containerd --version | awk '{print $3}')"
