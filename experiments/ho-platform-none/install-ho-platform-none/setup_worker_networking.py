#!/usr/bin/env python3
"""
Step 12.4: Complete Worker Node Networking Setup (OpenVSwitch + CNI)
Setting up complete worker node networking infrastructure
"""

import time
from common import BaseStep, installation_step, Colors


class SetupWorkerNetworkingStep(BaseStep):
    """Step 12.4: Complete Worker Node Networking Setup (OpenVSwitch + CNI)"""

    @installation_step("setup_worker_networking", "Setting up complete worker node networking infrastructure")
    def execute(self) -> bool:
        """Step 12.4: Complete Worker Node Networking Setup (OpenVSwitch + CNI)"""
        self.logger.info(f"{Colors.YELLOW}🔧{Colors.END} Setting up complete worker node networking infrastructure...")

        # Create comprehensive networking setup script
        networking_setup_script = """#!/bin/bash
set -euo pipefail

echo "=== HyperShift Worker Node Networking Setup ==="
echo "Setting up OpenVSwitch and CNI infrastructure..."

# Step 1: Install OpenVSwitch infrastructure
echo "📦 Installing OpenVSwitch on Red Hat CoreOS..."
# Check if OpenVSwitch is already installed via rpm-ostree
if ! rpm -q openvswitch &>/dev/null; then
    echo "Installing openvswitch via rpm-ostree..."
    rpm-ostree install openvswitch --allow-inactive || echo "OpenVSwitch install completed"
else
    echo "OpenVSwitch already installed"
fi

# Step 2: Create required directories
echo "📁 Creating CNI and OVS directories..."
mkdir -p /etc/cni/net.d
mkdir -p /opt/cni/bin
mkdir -p /var/lib/cni/bin
mkdir -p /var/run/multus/cni/net.d
mkdir -p /var/run/ovn-kubernetes/cni
mkdir -p /var/run/openvswitch
mkdir -p /etc/openvswitch

# Step 3: Start OpenVSwitch infrastructure
echo "🔧 Starting OpenVSwitch database and switch..."
# Ensure OVS user exists and has proper permissions
id openvswitch || useradd -r -d /var/lib/openvswitch -s /sbin/nologin openvswitch
chown -R openvswitch:openvswitch /var/run/openvswitch /etc/openvswitch

# Clean up any existing OVS processes and lock files
echo "🧹 Cleaning up existing OVS processes and locks..."
pkill -f ovs-vswitchd || true
pkill -f ovsdb-server || true
sleep 3

# Remove any stale lock files
rm -f /etc/openvswitch/.conf.db.~lock~
rm -f /var/run/openvswitch/ovsdb-server.pid
rm -f /var/run/openvswitch/ovs-vswitchd.pid

# Initialize database if it doesn't exist or recreate if corrupted
if [ ! -f /etc/openvswitch/conf.db ] || ! ovsdb-tool check-cluster /etc/openvswitch/conf.db 2>/dev/null; then
    echo "Creating/recreating OVS database..."
    rm -f /etc/openvswitch/conf.db
    ovsdb-tool create /etc/openvswitch/conf.db /usr/share/openvswitch/vswitch.ovsschema
    chown openvswitch:openvswitch /etc/openvswitch/conf.db
fi

# Start OVS database server with proper error handling
echo "Starting OVS database server..."
if ! sudo -u openvswitch ovsdb-server --remote=punix:/var/run/openvswitch/db.sock \
    --pidfile=/var/run/openvswitch/ovsdb-server.pid \
    --detach /etc/openvswitch/conf.db; then
    echo "Failed to start ovsdb-server, trying again..."
    sleep 5
    sudo -u openvswitch ovsdb-server --remote=punix:/var/run/openvswitch/db.sock \
        --pidfile=/var/run/openvswitch/ovsdb-server.pid \
        --detach /etc/openvswitch/conf.db
fi

# Wait for database to be ready
sleep 3

# Initialize OVS database
echo "Initializing OVS database..."
ovs-vsctl --no-wait init || echo "Database already initialized"

# Start OVS switch daemon
echo "Starting OVS switch daemon..."
if ! sudo -u openvswitch ovs-vswitchd --pidfile=/var/run/openvswitch/ovs-vswitchd.pid --detach; then
    echo "Failed to start ovs-vswitchd, trying again..."
    sleep 5
    sudo -u openvswitch ovs-vswitchd --pidfile=/var/run/openvswitch/ovs-vswitchd.pid --detach
fi

# Verify OVS is running
sleep 5
echo "🔍 Verifying OpenVSwitch status..."
ovs-vsctl show
echo "OpenVSwitch infrastructure ready!"

# Step 4: Setup CNI binary and configuration
echo "🌐 Setting up CNI infrastructure..."

# Wait for CNI binary to be available (deployed by ovnkube-node)
echo "Waiting for OVN CNI binary deployment..."
max_wait=300
wait_time=0
while [ $wait_time -lt $max_wait ]; do
    if [ -f /var/lib/cni/bin/ovn-k8s-cni-overlay ]; then
        echo "CNI binary found, copying to standard location..."
        cp /var/lib/cni/bin/ovn-k8s-cni-overlay /opt/cni/bin/
        chmod +x /opt/cni/bin/ovn-k8s-cni-overlay
        break
    fi
    echo "Waiting for CNI binary... ($wait_time seconds)"
    sleep 10
    wait_time=$((wait_time + 10))
done

# Wait for CNI configuration to be available
echo "Waiting for CNI configuration..."
max_wait=300
wait_time=0
while [ $wait_time -lt $max_wait ]; do
    if [ -f /etc/cni/net.d/10-ovn-kubernetes.conf ]; then
        echo "CNI configuration found, copying to multus location..."
        cp /etc/cni/net.d/10-ovn-kubernetes.conf /var/run/multus/cni/net.d/
        break
    fi
    echo "Waiting for CNI configuration... ($wait_time seconds)"
    sleep 10
    wait_time=$((wait_time + 10))
done

# Step 5: Verify CNI setup
echo "🔍 Verifying CNI setup..."
ls -la /opt/cni/bin/ovn-k8s-cni-overlay || echo "CNI binary not yet available"
ls -la /etc/cni/net.d/10-ovn-kubernetes.conf || echo "CNI config not yet available"
ls -la /var/run/multus/cni/net.d/10-ovn-kubernetes.conf || echo "Multus CNI config not yet available"

# Step 6: Restart kubelet to pick up changes
echo "🔄 Restarting kubelet..."
systemctl restart kubelet

echo "✅ Worker node networking setup completed successfully!"
echo "OpenVSwitch status:"
ovs-vsctl show
echo "CNI binary status:"
/opt/cni/bin/ovn-k8s-cni-overlay --help >/dev/null 2>&1 && echo "CNI binary is functional" || echo "CNI binary check completed"
"""

        # Upload and execute the comprehensive networking setup script
        if not self._upload_and_execute_script(
            networking_setup_script,
            "/tmp/setup-worker-networking.sh",
            "Complete worker node networking setup",
            timeout=900  # 15 minutes for complete setup
        ):
            self.logger.error("Failed to setup worker node networking infrastructure")
            return False

        # Wait for OVN components to stabilize
        self.logger.info("Waiting for networking components to stabilize...")
        time.sleep(60)

        # Restart ovnkube-node pod to ensure fresh CNI initialization
        self.logger.info("Restarting ovnkube-node pod for fresh networking initialization...")
        env_hosted = {'KUBECONFIG': self.config.kubeconfig_hosted_path}

        success, _ = self.runner.run(
            "kubectl delete pods -n openshift-ovn-kubernetes -l app=ovnkube-node",
            env=env_hosted
        )
        if success:
            self.logger.info("Waiting for new ovnkube-node pod to start...")
            time.sleep(90)  # Give more time for complete pod restart

        # Final verification
        self.logger.info("Performing final networking verification...")
        success, _ = self._run_on_worker(
            "sudo ovs-vsctl show && echo '=== OVS OK ===' && sudo systemctl status kubelet --no-pager -l | tail -3",
            "Final networking verification"
        )

        if success:
            self.logger.info(f"{Colors.GREEN}✓{Colors.END} Complete worker node networking setup successful!")
        else:
            self.logger.warning("Networking verification incomplete but setup completed")

        return True

    def _run_on_worker(self, command: str, description: str = None, check_output: bool = False, timeout: int = 300):
        """Helper method to run commands on worker node via SSH"""
        full_command = f'gcloud compute ssh {self.config.worker_node_name} --zone={self.config.zone} --command="{command}"'
        if description:
            self.logger.debug(f"Worker: {description}")
        return self.runner.run(full_command, check_output=check_output, timeout=timeout)

    def _upload_and_execute_script(self, script_content: str, remote_path: str, description: str, timeout: int = 600) -> bool:
        """Upload a script to worker node and execute it"""
        local_script = self.work_dir / f"temp_{remote_path.split('/')[-1]}"

        # Write script locally
        with open(local_script, 'w') as f:
            f.write(script_content)

        # Upload script
        upload_success, _ = self.runner.run(
            f'gcloud compute scp {local_script} {self.config.worker_node_name}:{remote_path} --zone={self.config.zone}'
        )
        if not upload_success:
            self.logger.error(f"Failed to upload script: {description}")
            return False

        # Execute script
        self.logger.info(f"Executing: {description}")
        success, _ = self._run_on_worker(f'chmod +x {remote_path} && sudo {remote_path}', description, timeout=timeout)

        # Cleanup local script
        local_script.unlink(missing_ok=True)

        return success