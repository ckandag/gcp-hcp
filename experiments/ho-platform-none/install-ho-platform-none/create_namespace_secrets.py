#!/usr/bin/env python3
"""
Step 6: Create HostedCluster namespace and secrets
Creating HostedCluster namespace and secrets
"""

from common import BaseStep, installation_step, Colors


class CreateNamespaceSecretsStep(BaseStep):
    """Step 6: Create HostedCluster Secrets"""

    @installation_step("create_namespace_secrets", "Creating HostedCluster namespace and secrets")
    def execute(self) -> bool:
        """Step 6: Create HostedCluster Secrets"""
        # Use GKE management cluster kubeconfig
        env_gke = {'KUBECONFIG': self.config.kubeconfig_gke_path}

        # Create namespace
        success, _ = self.runner.run("kubectl create namespace clusters --dry-run=client -o yaml | kubectl apply -f -", env=env_gke)
        if not success:
            return False

        # Check if pull secret exists
        success, _ = self.runner.run("kubectl get secret pull-secret -n clusters", env=env_gke)
        if not success:
            # Create pull secret
            success, _ = self.runner.run(
                f"kubectl create secret generic pull-secret "
                f"--from-file=.dockerconfigjson={self.config.pull_secret_path} "
                f"--type=kubernetes.io/dockerconfigjson -n clusters",
                env=env_gke
            )
            if not success:
                return False

        # Check if SSH key exists
        success, _ = self.runner.run("kubectl get secret ssh-key -n clusters", env=env_gke)
        if not success:
            # Generate SSH key if it doesn't exist
            ssh_key_path = self.work_dir / "ssh-key"
            if not ssh_key_path.exists():
                success, _ = self.runner.run(f'ssh-keygen -t rsa -b 4096 -f {ssh_key_path} -N ""')
                if not success:
                    return False

            # Create SSH key secret
            success, _ = self.runner.run(
                f"kubectl create secret generic ssh-key --from-file=id_rsa.pub={ssh_key_path}.pub -n clusters",
                env=env_gke
            )
            if not success:
                return False

        return True