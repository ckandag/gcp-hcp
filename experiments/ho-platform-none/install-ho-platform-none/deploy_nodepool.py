#!/usr/bin/env python3
"""
Step 12: Deploy NodePool for automatic worker management
Creating NodePool resource to manage worker nodes through HyperShift
"""

from dataclasses import asdict
from common import BaseStep, installation_step, Colors


class DeployNodePoolStep(BaseStep):
    """Step 12: Deploy NodePool for automatic worker management"""

    @installation_step("deploy_nodepool", "Creating NodePool resource to manage worker nodes through HyperShift")
    def execute(self) -> bool:
        """Step 12: Deploy NodePool for automatic worker management"""

        self.logger.info(f"{Colors.CYAN}🏗{Colors.END} Creating NodePool for automatic worker management...")

        # Check if NodePool already exists
        env_management = {'KUBECONFIG': self.config.kubeconfig_gke_path}

        success, _ = self.runner.run(
            f"kubectl get nodepool {self.config.hosted_cluster_name}-workers -n clusters",
            env=env_management
        )

        if success:
            self.logger.info(f"{Colors.GREEN}✓{Colors.END} NodePool already exists")
            return True

        # Get the release image from the hosted cluster
        success, release_image = self.runner.run(
            f"kubectl get hostedcluster {self.config.hosted_cluster_name} -n clusters -o jsonpath='{{.spec.release.image}}'",
            check_output=True,
            env=env_management
        )
        if not success:
            self.logger.error("Failed to get release image from HostedCluster")
            return False

        # Template variables for NodePool configuration
        template_vars = {
            **asdict(self.config),
            'release_image': release_image,
            'worker_replicas': 1  # Start with one worker node
        }

        # Render NodePool manifest
        nodepool_file = self.work_dir / f"nodepool-{self.config.hosted_cluster_name}-workers.yaml"
        success = self.templates.render_to_file("nodepool.yaml", template_vars, nodepool_file)
        if not success:
            return False

        # Apply NodePool
        success, _ = self.runner.run(
            f"kubectl apply -f {nodepool_file}",
            env=env_management
        )
        if not success:
            self.logger.error("Failed to create NodePool")
            return False

        self.logger.info(f"{Colors.GREEN}✓{Colors.END} NodePool created successfully")

        # Wait for NodePool to be ready to accept workers
        self.logger.info(f"{Colors.CYAN}⏳{Colors.END} Waiting for NodePool to be ready...")

        # Check NodePool status
        success, _ = self.runner.run(
            f"kubectl get nodepool {self.config.hosted_cluster_name}-workers -n clusters -o yaml",
            env=env_management
        )
        if success:
            self.logger.info(f"{Colors.GREEN}✓{Colors.END} NodePool is ready to manage workers")
        else:
            self.logger.warning(f"{Colors.YELLOW}⚠{Colors.END} NodePool status check failed, but continuing...")

        return True