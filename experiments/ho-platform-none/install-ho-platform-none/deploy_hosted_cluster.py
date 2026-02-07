#!/usr/bin/env python3
"""
Step 7: Deploy HostedCluster
Deploying HostedCluster
"""

from dataclasses import asdict
from common import BaseStep, installation_step, Colors


class DeployHostedClusterStep(BaseStep):
    """Step 7: Deploy HostedCluster"""

    @installation_step("deploy_hosted_cluster", "Deploying HostedCluster")
    def execute(self) -> bool:
        """Step 7: Deploy HostedCluster"""
        # Use GKE management cluster kubeconfig
        env_gke = {'KUBECONFIG': self.config.kubeconfig_gke_path}

        # Check if HostedCluster already exists
        success, _ = self.runner.run(f"kubectl get hostedcluster {self.config.hosted_cluster_name} -n clusters", env=env_gke)
        if success:
            self.logger.info(f"HostedCluster {self.config.hosted_cluster_name} already exists")
            return True

        # Get the external IP for the ignition server
        ignition_server_ip = self._get_ignition_server_ip()
        if not ignition_server_ip:
            self.logger.error("Failed to get ignition server IP for certificate configuration")
            return False

        # Render HostedCluster manifest from template
        template_vars = asdict(self.config)
        template_vars['ignition_server_ip'] = ignition_server_ip
        manifest_file = self.work_dir / f"hosted-cluster-{self.config.hosted_cluster_name}.yaml"

        success = self.templates.render_to_file("hosted-cluster.yaml", template_vars, manifest_file)
        if not success:
            return False

        # Apply manifest
        success, _ = self.runner.run(f"kubectl apply -f {manifest_file}", env=env_gke)
        return success

    def _get_ignition_server_ip(self) -> str:
        """Get the external IP for the ignition server (GKE node IP)"""
        self.logger.info("🌐 Getting ignition server endpoint...")

        # The ignition server runs on NodePort, so we need the GKE node external IP
        success, output = self.runner.run(
            'kubectl get nodes -o jsonpath="{.items[0].status.addresses[?(@.type==\\"ExternalIP\\")].address}"',
            check_output=True,
            env={'KUBECONFIG': self.config.kubeconfig_gke_path}
        )
        if success and output.strip():
            ip = output.strip()
            self.logger.info(f"✓ Ignition server IP: {ip}")
            return ip

        self.logger.error("Failed to get external IP from GKE nodes")
        return ""