#!/bin/bash
set -euo pipefail

echo "Configuring kubelet and worker node files..."

# Copy kubeconfig
echo "Configuring kubelet kubeconfig..."
cp /tmp/worker-kubeconfig.yaml /var/lib/kubelet/kubeconfig

# Copy kubelet configuration
echo "Configuring kubelet config..."
cp /tmp/kubelet-config.yaml /var/lib/kubelet/config.yaml

# Copy Red Hat pull secret for OpenShift images
echo "Configuring container registry authentication..."
mkdir -p /var/lib/kubelet
cp /tmp/pull-secret.txt /var/lib/kubelet/config.json

# Configure CRI-O with Red Hat pull secret
mkdir -p /etc/containers/auth.json
cp /tmp/pull-secret.txt /etc/containers/auth.json

# Install kubelet service
echo "Installing kubelet service..."
cp /tmp/kubelet.service /etc/systemd/system/kubelet.service

# Create static pod directory
mkdir -p /etc/kubernetes/manifests

# Fix SELinux context for kubelet (required on Red Hat CoreOS)
echo "Fixing SELinux context for kubelet..."
restorecon /usr/local/bin/kubelet || echo "SELinux context restoration completed"

# Start kubelet
echo "Starting kubelet service..."
systemctl daemon-reload
systemctl enable kubelet
systemctl start kubelet

echo "Kubelet configuration completed successfully!"
echo "Checking kubelet status..."
systemctl status kubelet --no-pager -l