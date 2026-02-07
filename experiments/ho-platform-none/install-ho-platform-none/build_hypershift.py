#!/usr/bin/env python3
"""
Step 4: Build and Install HyperShift
Building and installing HyperShift
"""

import time
from pathlib import Path
from common import BaseStep, installation_step, Colors


class BuildHyperShiftStep(BaseStep):
    """Step 4: Build and Install HyperShift"""

    @installation_step("build_hypershift", "Building and installing HyperShift")
    def execute(self) -> bool:
        """Step 4: Build and Install HyperShift"""
        # Use GKE management cluster kubeconfig
        env_gke = {'KUBECONFIG': self.config.kubeconfig_gke_path}

        # Check if hypershift binary exists and HyperShift operator is installed
        binary_exists, _ = self.runner.run("which hypershift")
        operator_exists, _ = self.runner.run("kubectl get deployment operator -n hypershift", env=env_gke)
        operator_ready = False

        if operator_exists:
            # Check if operator is actually ready
            success, ready_output = self.runner.run(
                "kubectl get deployment operator -n hypershift -o jsonpath='{.status.readyReplicas}'",
                check_output=True,
                env=env_gke
            )
            if success and ready_output.strip() and int(ready_output.strip()) > 0:
                operator_ready = True

        if binary_exists and operator_ready:
            self.logger.info("HyperShift already installed and ready")
            return True

        # Install or fix HyperShift
        if not binary_exists:
            self.logger.info(f"{Colors.YELLOW}📦{Colors.END} Installing HyperShift binary...")
            # Clone HyperShift repository if it doesn't exist
            if not Path("hypershift").exists():
                self.logger.info("Cloning HyperShift repository...")
                success, _ = self.runner.run("git clone https://github.com/openshift/hypershift.git", timeout=300)
                if not success:
                    return False

            # Build HyperShift
            self.logger.info("Building HyperShift (this may take several minutes)...")
            success, _ = self.runner.run("make build", timeout=600, cwd="hypershift", show_progress=True)
            if not success:
                return False

            # Install HyperShift binary
            self.logger.info("Installing HyperShift binary...")
            success, _ = self.runner.run("sudo install -m 0755 bin/hypershift /usr/local/bin/hypershift", cwd="hypershift")
            if not success:
                return False

        # Install or fix HyperShift operator
        if not operator_ready:
            self.logger.info(f"{Colors.YELLOW}🚀{Colors.END} Installing HyperShift operator...")
            success, _ = self.runner.run("hypershift install --development", timeout=600, show_progress=True)
            if not success:
                return False

            # Ensure operator deployment is scaled correctly
            self.logger.info("Ensuring operator deployment is properly scaled...")
            success, replicas = self.runner.run(
                "kubectl get deployment operator -n hypershift -o jsonpath='{.spec.replicas}'",
                check_output=True,
                env=env_gke
            )
            if success and (not replicas.strip() or int(replicas.strip()) == 0):
                self.logger.info("Scaling operator deployment to 1 replica...")
                success, _ = self.runner.run("kubectl scale deployment operator -n hypershift --replicas=1", env=env_gke)
                if not success:
                    return False

            # Create serving certificate if missing
            self.logger.info("Ensuring serving certificate exists...")
            success, _ = self.runner.run("kubectl get secret manager-serving-cert -n hypershift", env=env_gke)
            if not success:
                self.logger.info("Creating self-signed serving certificate...")
                success, _ = self.runner.run(
                    'openssl req -x509 -newkey rsa:2048 -keyout /tmp/tls.key -out /tmp/tls.crt -days 365 -nodes -subj "/CN=hypershift-operator"'
                )
                if not success:
                    return False
                success, _ = self.runner.run(
                    "kubectl create secret tls manager-serving-cert -n hypershift --cert=/tmp/tls.crt --key=/tmp/tls.key",
                    env=env_gke
                )
                if not success:
                    return False

                # Restart operator pod to pick up certificate
                self.logger.info("Restarting operator pod to pick up certificate...")
                success, _ = self.runner.run("kubectl delete pod -l name=operator -n hypershift", env=env_gke)
                if not success:
                    return False

            # Wait for operator to be ready with progress updates
            self.logger.info(f"{Colors.YELLOW}⏳{Colors.END} Waiting for HyperShift operator to be ready...")
            max_wait_time = 300  # 5 minutes
            check_interval = 15   # 15 seconds
            elapsed_time = 0

            while elapsed_time < max_wait_time:
                success, _ = self.runner.run("kubectl wait --for=condition=ready pod -l name=operator -n hypershift --timeout=15s", env=env_gke)
                if success:
                    self.logger.info(f"{Colors.GREEN}✓{Colors.END} HyperShift operator is ready!")
                    break

                elapsed_time += check_interval
                self.logger.info(f"  Still waiting for operator... ({elapsed_time} seconds elapsed)")

                # Show pod status every 45 seconds
                if elapsed_time % 45 == 0:
                    self.logger.info(f"  {Colors.CYAN}Current pod status:{Colors.END}")
                    self.runner.run("kubectl get pods -n hypershift", env=env_gke)
                    self.runner.run("kubectl get events -n hypershift --sort-by='.lastTimestamp' --tail=3", env=env_gke)
            else:
                self.logger.error("Timeout waiting for HyperShift operator to be ready")
                return False

        return True