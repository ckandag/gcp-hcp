#!/usr/bin/env python3
"""
Step 8: Wait for Control Plane
Waiting for control plane to be available
"""

import time
from common import BaseStep, installation_step, Colors


class WaitControlPlaneStep(BaseStep):
    """Step 8: Wait for Control Plane"""

    @installation_step("wait_control_plane", "Waiting for control plane to be available")
    def execute(self) -> bool:
        """Step 8: Wait for Control Plane"""
        # Use GKE management cluster kubeconfig
        env_gke = {'KUBECONFIG': self.config.kubeconfig_gke_path}

        self.logger.info("Waiting for HostedCluster to become available (this may take 20-30 minutes)...")

        # Monitor progress with periodic status updates
        max_wait_time = 1800  # 30 minutes
        check_interval = 30   # 30 seconds
        elapsed_time = 0

        while elapsed_time < max_wait_time:
            # Check HostedCluster status
            success, output = self.runner.run(
                f"kubectl get hostedcluster {self.config.hosted_cluster_name} -n clusters -o jsonpath='{{.status.conditions[?(@.type==\"Available\")].status}}'",
                check_output=True,
                env=env_gke
            )

            if success and output.strip() == "True":
                self.logger.info("HostedCluster is now available!")
                return True

            # Show detailed progress update every 2 minutes
            if elapsed_time % 120 == 0:
                self.logger.info(f"{Colors.YELLOW}⏳{Colors.END} Waiting for control plane... ({elapsed_time//60} minutes elapsed)")
                # Show current status
                success, status_output = self.runner.run(
                    f"kubectl get hostedcluster {self.config.hosted_cluster_name} -n clusters -o jsonpath='{{.status.conditions[?(@.type==\"Available\")].reason}}'",
                    check_output=True,
                    env=env_gke
                )
                if success and status_output.strip():
                    self.logger.info(f"  Current status: {status_output.strip()}")

                # Check for Pod Security violations and fix them
                if elapsed_time == 120:  # Check once after 2 minutes
                    control_plane_namespace = f"clusters-{self.config.hosted_cluster_name}"
                    success, events = self.runner.run(
                        f"kubectl get events -n {control_plane_namespace} --field-selector type=Warning --no-headers | grep 'violates PodSecurity' | head -1",
                        check_output=True,
                        env=env_gke
                    )
                    if success and events.strip():
                        self.logger.info(f"  {Colors.YELLOW}⚠{Colors.END} Detected Pod Security violations, applying fixes...")
                        self.fix_pod_security_violations(control_plane_namespace, env_gke)

                # Show pod status every 5 minutes
                if elapsed_time % 300 == 0:
                    self.logger.info(f"  {Colors.CYAN}Checking control plane pods...{Colors.END}")
                    self.runner.run(f"kubectl get pods -n clusters-{self.config.hosted_cluster_name} --no-headers | head -10", env=env_gke)

            time.sleep(check_interval)
            elapsed_time += check_interval

        self.logger.error("Timeout waiting for HostedCluster to become available")
        # Show final status for debugging
        self.runner.run(f"kubectl describe hostedcluster {self.config.hosted_cluster_name} -n clusters", env=env_gke)
        return False

    def fix_pod_security_violations(self, namespace: str, env_gke: dict) -> bool:
        """Fix Pod Security violations in control plane namespace"""
        self.logger.info(f"{Colors.YELLOW}🔒{Colors.END} Checking for Pod Security violations in {namespace}...")

        # Get deployments that might have security issues
        deployments_to_fix = ["control-plane-operator", "cluster-api"]

        for deployment in deployments_to_fix:
            success, _ = self.runner.run(f"kubectl get deployment {deployment} -n {namespace}", env=env_gke)
            if success:
                self.logger.info(f"Fixing Pod Security context for {deployment}...")

                # Apply security context patch
                patch = '''[
                  {"op": "add", "path": "/spec/template/spec/securityContext", "value": {"runAsNonRoot": true, "runAsUser": 1001}},
                  {"op": "add", "path": "/spec/template/spec/containers/0/securityContext", "value": {"allowPrivilegeEscalation": false, "capabilities": {"drop": ["ALL"]}, "runAsNonRoot": true, "runAsUser": 1001, "seccompProfile": {"type": "RuntimeDefault"}}}
                ]'''

                success, _ = self.runner.run(
                    f"kubectl patch deployment {deployment} -n {namespace} --type='json' -p '{patch}'",
                    env=env_gke
                )
                if success:
                    self.logger.info(f"  {Colors.GREEN}✓{Colors.END} Fixed {deployment}")
                else:
                    self.logger.warning(f"  {Colors.YELLOW}⚠{Colors.END} Could not patch {deployment}, may already be fixed")

        return True