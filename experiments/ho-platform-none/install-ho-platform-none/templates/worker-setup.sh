#!/bin/bash
set -euo pipefail

echo "Starting Red Hat CoreOS worker node setup for HyperShift..."

# Red Hat CoreOS comes with CRI-O already installed and configured
# Check container runtime status
echo "Checking container runtime status..."
systemctl status crio || systemctl status podman || echo "Container runtime will be configured by kubelet"

# Install Open vSwitch using rpm-ostree (if needed)
echo "Installing Open vSwitch via rpm-ostree..."
if ! rpm -q openvswitch &>/dev/null; then
    echo "Installing openvswitch package..."
    rpm-ostree install openvswitch --allow-inactive
    echo "Reboot required after openvswitch installation, but continuing setup..."
fi

# Start and enable openvswitch service
echo "Enabling and starting openvswitch service..."
systemctl enable --now openvswitch || echo "OpenVSwitch will be started later"

# Red Hat CoreOS is already OpenShift-compatible, no OS identity changes needed
echo "Red Hat CoreOS is natively OpenShift-compatible"

# Create required directories (some may already exist in Red Hat CoreOS)
echo "Creating required directories..."
mkdir -p /etc/kubernetes/pki /var/lib/kubelet /etc/systemd/system/kubelet.service.d /opt/cni/bin /etc/cni/net.d

# Create additional multus-specific directories to prevent circular dependency
echo "Creating multus-specific directories..."
mkdir -p /var/run/multus/cni/net.d
mkdir -p /etc/kubernetes/cni/net.d
mkdir -p /run/multus/socket
mkdir -p /var/lib/cni/bin

# Set proper permissions for multus directories
chown -R root:root /var/run/multus /run/multus
chmod -R 755 /var/run/multus /run/multus

# Create initial CNI configuration files to break circular dependency
# This prevents multus from waiting for ovnkube-controller and allows both to start
echo "Creating initial CNI configuration files..."
cat > /var/run/multus/cni/net.d/10-ovn-kubernetes.conf << 'EOF'
{
  "cniVersion": "0.3.1",
  "name": "ovn-kubernetes",
  "type": "ovn-k8s-cni-overlay",
  "ipam": {},
  "dns": {},
  "logLevel": "5",
  "logfile": "/var/log/ovn-kubernetes/ovn-k8s-cni-overlay.log",
  "logfile-maxsize": 100,
  "logfile-maxbackups": 5,
  "logfile-maxage": 5
}
EOF

# Create the same file for kubelet's expected location
cp /var/run/multus/cni/net.d/10-ovn-kubernetes.conf /etc/kubernetes/cni/net.d/10-ovn-kubernetes.conf

# Set proper permissions for CNI configuration files
chown root:root /var/run/multus/cni/net.d/10-ovn-kubernetes.conf
chown root:root /etc/kubernetes/cni/net.d/10-ovn-kubernetes.conf
chmod 644 /var/run/multus/cni/net.d/10-ovn-kubernetes.conf
chmod 644 /etc/kubernetes/cni/net.d/10-ovn-kubernetes.conf

echo "✓ Multus circular dependency prevention configured"

# Install compatible kubelet version (v1.28.15 for OpenShift 4.14)
echo "Installing kubelet v1.28.15..."
curl -LO https://dl.k8s.io/release/v1.28.15/bin/linux/amd64/kubelet
chmod +x kubelet
mv kubelet /usr/local/bin/kubelet

# Configure CRI-O (preferred container runtime for OpenShift on Red Hat CoreOS)
echo "Configuring CRI-O for OpenShift compatibility..."
# Create CRI-O configuration
mkdir -p /etc/crio/crio.conf.d
tee /etc/crio/crio.conf.d/01-openshift.conf <<EOF
[crio.runtime]
cgroup_manager = "systemd"
default_runtime = "runc"
conmon = "/usr/bin/conmon"
conmon_cgroup = "pod"

[crio.image]
pause_image = "registry.redhat.io/ubi8/pause:latest"

[crio.network]
cni_default_network = "openshift-sdn"
plugin_dirs = ["/opt/cni/bin"]
network_dir = "/etc/cni/net.d"
EOF

# Enable and start CRI-O
systemctl enable --now crio

# Install CNI plugins if not already present
echo "Installing CNI plugins..."
if [ ! -f /opt/cni/bin/bridge ]; then
    curl -L https://github.com/containernetworking/plugins/releases/download/v1.3.0/cni-plugins-linux-amd64-v1.3.0.tgz | tar -C /opt/cni/bin -xz
else
    echo "CNI plugins already installed"
fi

echo "Red Hat CoreOS worker node setup completed successfully!"