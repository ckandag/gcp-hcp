#!/usr/bin/env python3
"""
Step 9: Extract Hosted Cluster Access
Extracting hosted cluster access credentials
"""

import base64
from common import BaseStep, installation_step, Colors


class ExtractHostedAccessStep(BaseStep):
    """Step 9: Extract Hosted Cluster Access"""

    @installation_step("extract_hosted_access", "Extracting hosted cluster access credentials")
    def execute(self) -> bool:
        """Step 9: Extract Hosted Cluster Access"""
        # Create resilient hosted cluster kubeconfig using the kubeconfig manager
        success = self.kubeconfig_manager.create_hosted_kubeconfig()
        if not success:
            self.logger.error("Failed to create resilient hosted cluster kubeconfig")
            return False

        # Test hosted cluster access (this might fail until worker nodes are ready, but that's ok)
        env = {'KUBECONFIG': self.config.kubeconfig_hosted_path}
        success, cluster_info = self.runner.run("kubectl cluster-info", check_output=True, env=env)
        if success:
            self.logger.info(f"Hosted cluster API server: {cluster_info.split()[5] if len(cluster_info.split()) > 5 else 'unknown'}")
        else:
            self.logger.warning("Could not connect to hosted cluster API server (this is normal until worker nodes are ready)")

        # Always return True since we successfully extracted the kubeconfig, even if we can't connect yet
        return True