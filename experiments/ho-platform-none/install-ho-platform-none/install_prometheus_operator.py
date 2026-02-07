#!/usr/bin/env python3
"""
Step 3a: Install Prometheus Operator
Installing Prometheus Operator
"""

from common import BaseStep, installation_step, Colors


class InstallPrometheusOperatorStep(BaseStep):
    """Step 3a: Install Prometheus Operator"""

    @installation_step("install_prometheus_operator", "Installing Prometheus Operator")
    def execute(self) -> bool:
        """Step 3a: Install Prometheus Operator"""
        # Use GKE management cluster kubeconfig
        env_gke = {'KUBECONFIG': self.config.kubeconfig_gke_path}

        # Check if already installed
        success, _ = self.runner.run("helm list -n default | grep prometheus-operator", env=env_gke)
        if success:
            self.logger.info("Prometheus Operator already installed")
            return True

        # Add helm repo
        success, _ = self.runner.run("helm repo add prometheus-community https://prometheus-community.github.io/helm-charts")
        if not success:
            return False

        success, _ = self.runner.run("helm repo update")
        if not success:
            return False

        # Install Prometheus Operator
        install_cmd = """
        helm install prometheus-operator prometheus-community/kube-prometheus-stack \\
          --set prometheus.enabled=false \\
          --set alertmanager.enabled=false \\
          --set grafana.enabled=false \\
          --set kubeStateMetrics.enabled=false \\
          --set nodeExporter.enabled=false
        """
        success, _ = self.runner.run(install_cmd, timeout=600, env=env_gke)
        return success