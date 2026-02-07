#!/usr/bin/env python3
"""
Step 3b: Install cert-manager
Installing cert-manager
"""

from common import BaseStep, installation_step, Colors


class InstallCertManagerStep(BaseStep):
    """Step 3b: Install cert-manager"""

    @installation_step("install_cert_manager", "Installing cert-manager")
    def execute(self) -> bool:
        """Step 3b: Install cert-manager"""
        # Use GKE management cluster kubeconfig
        env_gke = {'KUBECONFIG': self.config.kubeconfig_gke_path}

        # Check if cert-manager namespace exists and has running pods
        success, output = self.runner.run("kubectl get namespace cert-manager", check_output=True, env=env_gke)
        if success:
            # Check if cert-manager pods are running
            success, pods_output = self.runner.run(
                "kubectl get pods -n cert-manager --field-selector=status.phase=Running",
                check_output=True,
                env=env_gke
            )
            if success and "cert-manager" in pods_output:
                self.logger.info("cert-manager already installed and running")
                return True
            else:
                self.logger.info("cert-manager namespace exists but pods not running, reinstalling...")

        # Install cert-manager
        self.logger.info("Installing cert-manager...")
        success, _ = self.runner.run(
            "kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml",
            timeout=300,
            env=env_gke
        )
        if not success:
            return False

        # Wait for cert-manager to be ready
        self.logger.info("Waiting for cert-manager to be ready...")
        success, _ = self.runner.run(
            "kubectl wait --for=condition=ready pod -l app=cert-manager -n cert-manager --timeout=300s",
            env=env_gke
        )
        return success