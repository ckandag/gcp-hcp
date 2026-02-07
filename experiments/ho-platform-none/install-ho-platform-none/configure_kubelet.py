#!/usr/bin/env python3
"""
Step 12: Configure Kubelet and Required Files
Configuring kubelet and required files
"""

import re
import base64
from pathlib import Path
from dataclasses import asdict
from common import BaseStep, installation_step, Colors


class ConfigureKubeletStep(BaseStep):
    """Step 12: Configure Kubelet and Required Files"""

    @installation_step("configure_kubelet", "Configuring kubelet and required files")
    def execute(self) -> bool:
        """Step 12: Configure Kubelet and Required Files"""
        # Regenerate kubeconfigs to ensure fresh tokens
        if not self._regenerate_kubeconfigs():
            return False

        # Set KUBECONFIG for hosted cluster
        env = {'KUBECONFIG': self.config.kubeconfig_hosted_path}

        # Get worker node internal IP
        success, worker_ip = self.runner.run(
            f"gcloud compute instances describe {self.config.worker_node_name} --zone={self.config.zone} "
            f"--format='get(networkInterfaces[0].networkIP)'",
            check_output=True
        )
        if not success:
            return False

        # Get API server endpoint and CA certificate
        success, cluster_info = self.runner.run("kubectl cluster-info", check_output=True, env=env)
        if not success:
            return False

        # Extract API server IP from cluster-info
        api_match = re.search(r'https://([^:]+)', cluster_info)
        if not api_match:
            self.logger.error("Could not extract API server endpoint")
            return False
        api_server = api_match.group(1)

        # Get CA certificate
        success, ca_cert = self.runner.run(
            "kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}'",
            check_output=True,
            env=env
        )
        if not success:
            return False

        # Prepare template variables for kubelet configuration
        template_vars = {
            **asdict(self.config),
            'worker_ip': worker_ip,
            'api_server': api_server,
            'ca_cert': ca_cert,
            'worker_cert': base64.b64encode(open(self.work_dir / "worker-node.crt", "rb").read()).decode() if not self.config.dry_run else 'dry-run-cert',
            'worker_key': base64.b64encode(open(self.work_dir / "worker-node.key", "rb").read()).decode() if not self.config.dry_run else 'dry-run-key'
        }

        # Render kubelet configuration files
        kubeconfig_file = self.work_dir / "worker-kubeconfig.yaml"
        kubelet_config_file = self.work_dir / "kubelet-config.yaml"
        kubelet_service_file = self.work_dir / "kubelet.service"

        for template_name, output_file in [
            ("worker-kubeconfig.yaml", kubeconfig_file),
            ("kubelet-config.yaml", kubelet_config_file),
            ("kubelet.service", kubelet_service_file)
        ]:
            success = self.templates.render_to_file(template_name, template_vars, output_file)
            if not success:
                return False

        # Copy files to worker node
        copy_commands = [
            f"gcloud compute scp {kubeconfig_file} {self.config.worker_node_name}:/tmp/worker-kubeconfig.yaml --zone={self.config.zone}",
            f"gcloud compute scp {kubelet_config_file} {self.config.worker_node_name}:/tmp/kubelet-config.yaml --zone={self.config.zone}",
            f"gcloud compute scp {kubelet_service_file} {self.config.worker_node_name}:/tmp/kubelet.service --zone={self.config.zone}",
            f"gcloud compute scp {self.config.pull_secret_path} {self.config.worker_node_name}:/tmp/pull-secret.txt --zone={self.config.zone}"
        ]

        for cmd in copy_commands:
            success, _ = self.runner.run(cmd)
            if not success:
                return False

        # Render and execute worker configuration script
        worker_config_script = self.work_dir / "worker-config.sh"
        success = self.templates.render_to_file("worker-config.sh", template_vars, worker_config_script)
        if not success:
            return False

        success, _ = self.runner.run(
            f"gcloud compute scp {worker_config_script} {self.config.worker_node_name}:/tmp/worker-config.sh --zone={self.config.zone}"
        )
        if not success:
            return False

        # Execute configuration script on worker node
        success, _ = self.runner.run(
            f'gcloud compute ssh {self.config.worker_node_name} --zone={self.config.zone} --command="chmod +x /tmp/worker-config.sh && sudo /tmp/worker-config.sh"',
            timeout=300
        )

        # If the configuration failed, try to fix SELinux context issue directly
        if not success:
            self.logger.warning(f"{Colors.YELLOW}⚠{Colors.END} Worker configuration failed, attempting SELinux fix...")
            success, _ = self.runner.run(
                f'gcloud compute ssh {self.config.worker_node_name} --zone={self.config.zone} --command="sudo restorecon /usr/local/bin/kubelet && sudo systemctl restart kubelet"'
            )
            if success:
                self.logger.info(f"{Colors.GREEN}✓{Colors.END} SELinux fix applied successfully")
            else:
                self.logger.error(f"{Colors.RED}✗{Colors.END} Failed to apply SELinux fix")

        # Create CNI configuration to fix "cni plugin not initialized" error
        if not self._create_cni_configuration():
            self.logger.warning(f"{Colors.YELLOW}⚠{Colors.END} Failed to create CNI configuration, but continuing...")

        return success

    def _create_cni_configuration(self) -> bool:
        """Create CNI configuration to resolve 'cni plugin not initialized' error"""
        self.logger.info(f"{Colors.CYAN}🌐{Colors.END} Creating CNI configuration on worker node...")

        # Create CNI configuration content based on manual fix
        cni_config = """{
    "name": "ovn-kubernetes",
    "type": "ovn-k8s-cni-overlay",
    "cniVersion": "0.3.1",
    "logFile": "/var/log/ovn-kubernetes/ovn-k8s-cni-overlay.log",
    "logLevel": "5",
    "logfile-maxsize": 100,
    "logfile-maxbackups": 5,
    "logfile-maxage": 5
}"""

        # Create CNI setup script
        cni_setup_script = f"""#!/bin/bash
set -euo pipefail

echo "Setting up CNI configuration..."

# Create required CNI directories
sudo mkdir -p /etc/cni/net.d
sudo mkdir -p /opt/cni/bin
sudo mkdir -p /var/lib/cni/bin
sudo mkdir -p /etc/kubernetes/cni/net.d
sudo mkdir -p /var/run/multus/cni/net.d
sudo mkdir -p /var/log/ovn-kubernetes

# Create CNI configuration file
cat > /tmp/10-ovn-kubernetes.conf << 'EOF'
{cni_config}
EOF

# Install CNI configuration
sudo cp /tmp/10-ovn-kubernetes.conf /etc/cni/net.d/10-ovn-kubernetes.conf
sudo chmod 644 /etc/cni/net.d/10-ovn-kubernetes.conf

# Create symlinks for CNI compatibility (if needed)
if [ ! -L /var/lib/cni/bin ] && [ ! -d /var/lib/cni/bin ]; then
    sudo rm -rf /var/lib/cni/bin
    sudo ln -sf /opt/cni/bin /var/lib/cni/bin
fi

echo "CNI configuration created successfully"
echo "Contents of /etc/cni/net.d/:"
ls -la /etc/cni/net.d/

# Verify CNI configuration
echo "CNI configuration content:"
cat /etc/cni/net.d/10-ovn-kubernetes.conf
"""

        # Save CNI setup script to work directory
        cni_script_path = self.work_dir / "setup-cni.sh"
        if not self.config.dry_run:
            with open(cni_script_path, 'w') as f:
                f.write(cni_setup_script)

        # Copy and execute CNI setup script on worker node
        success, _ = self.runner.run(
            f"gcloud compute scp {cni_script_path} {self.config.worker_node_name}:/tmp/setup-cni.sh --zone={self.config.zone}"
        )
        if not success:
            return False

        # Execute CNI setup script
        success, _ = self.runner.run(
            f'gcloud compute ssh {self.config.worker_node_name} --zone={self.config.zone} --command="chmod +x /tmp/setup-cni.sh && sudo /tmp/setup-cni.sh"',
            timeout=120
        )

        if success:
            self.logger.info(f"{Colors.GREEN}✓{Colors.END} CNI configuration created successfully")
        else:
            self.logger.warning(f"{Colors.YELLOW}⚠{Colors.END} CNI configuration setup failed, but continuing...")

        return success

    def _regenerate_kubeconfigs(self) -> bool:
        """Regenerate kubeconfigs at runtime to avoid expired tokens"""
        self.logger.info(f"{Colors.CYAN}🔄{Colors.END} Regenerating kubeconfigs to ensure fresh tokens...")

        # Regenerate GKE management cluster kubeconfig
        success, _ = self.runner.run(
            f"gcloud container clusters get-credentials {self.config.gke_cluster_name} --zone={self.config.zone} --project={self.config.project_id}"
        )
        if not success:
            self.logger.error("Failed to regenerate GKE kubeconfig")
            return False

        # Copy current kubeconfig to GKE path
        success, _ = self.runner.run(f"cp ~/.kube/config {self.config.kubeconfig_gke_path}")
        if not success:
            self.logger.error("Failed to copy GKE kubeconfig")
            return False

        # Set KUBECONFIG back to GKE for management operations
        import os
        os.environ['KUBECONFIG'] = self.config.kubeconfig_gke_path

        # Re-extract hosted cluster kubeconfig (may have new tokens)
        success, kubeconfig_b64 = self.runner.run(
            f"kubectl get secret admin-kubeconfig -n clusters-{self.config.hosted_cluster_name} "
            f"-o jsonpath='{{.data.kubeconfig}}'",
            check_output=True
        )
        if not success:
            self.logger.error("Failed to re-extract hosted cluster kubeconfig")
            return False

        # Decode and save fresh hosted cluster kubeconfig
        if not self.config.dry_run:
            kubeconfig_data = base64.b64decode(kubeconfig_b64).decode('utf-8')
            with open(self.config.kubeconfig_hosted_path, 'w') as f:
                f.write(kubeconfig_data)

        self.logger.info(f"{Colors.GREEN}✓{Colors.END} Kubeconfigs regenerated with fresh tokens")
        return True