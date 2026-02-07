#!/usr/bin/env python3
"""
Step 11: Generate Worker Node Certificates
Generating worker node certificates
"""

import os
import base64
from dataclasses import asdict
from common import BaseStep, installation_step, Colors


class GenerateWorkerCertsStep(BaseStep):
    """Step 11: Generate Worker Node Certificates"""

    @installation_step("generate_worker_certs", "Generating worker node certificates")
    def execute(self) -> bool:
        """Step 11: Generate Worker Node Certificates"""
        # Regenerate kubeconfigs to ensure fresh tokens
        if not self._regenerate_kubeconfigs():
            return False

        # Set KUBECONFIG for hosted cluster
        env = {'KUBECONFIG': self.config.kubeconfig_hosted_path}

        # Create bootstrap RBAC (if not exists)
        rbac_commands = [
            "kubectl create clusterrolebinding kubelet-bootstrap --clusterrole=system:node-bootstrapper --group=system:bootstrappers --dry-run=client -o yaml | kubectl apply -f -",
            "kubectl create clusterrolebinding node-client-auto-approve-csr --clusterrole=system:certificates.k8s.io:certificatesigningrequests:nodeclient --group=system:bootstrappers --dry-run=client -o yaml | kubectl apply -f -",
            "kubectl create clusterrolebinding node-server-auto-approve-csr --clusterrole=system:certificates.k8s.io:certificatesigningrequests:selfnodeclient --group=system:nodes --dry-run=client -o yaml | kubectl apply -f -"
        ]

        for cmd in rbac_commands:
            success, _ = self.runner.run(cmd, env=env)
            if not success:
                return False

        # Generate worker node certificate if not exists
        worker_key_path = self.work_dir / "worker-node.key"
        worker_csr_path = self.work_dir / "worker-node.csr"

        if not worker_key_path.exists():
            success, _ = self.runner.run(f"openssl genrsa -out {worker_key_path} 2048")
            if not success:
                return False

            success, _ = self.runner.run(
                f'openssl req -new -key {worker_key_path} -out {worker_csr_path} '
                f'-subj "/CN=system:node:{self.config.worker_node_name}/O=system:nodes"'
            )
            if not success:
                return False

        # Create and approve CSR using template
        template_vars = {
            **asdict(self.config),
            'csr_request': base64.b64encode(open(worker_csr_path, 'rb').read()).decode() if not self.config.dry_run else 'dry-run-csr'
        }

        csr_file = self.work_dir / f"worker-csr-{self.config.worker_node_name}.yaml"
        success = self.templates.render_to_file("worker-csr.yaml", template_vars, csr_file)
        if not success:
            return False

        success, _ = self.runner.run(f"kubectl apply -f {csr_file}", env=env)
        if not success:
            return False

        success, _ = self.runner.run(f"kubectl certificate approve worker-node-{self.config.worker_node_name}", env=env)
        if not success:
            return False

        # Extract certificate
        worker_cert_path = self.work_dir / "worker-node.crt"
        success, _ = self.runner.run(
            f"kubectl get csr worker-node-{self.config.worker_node_name} "
            f"-o jsonpath='{{.status.certificate}}' | base64 -d > {worker_cert_path}",
            env=env
        )
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