#!/usr/bin/env python3
"""
Step 2: Create GKE Cluster
Creating Standard GKE cluster
"""

from common import BaseStep, installation_step, Colors


class CreateGkeClusterStep(BaseStep):
    """Step 2: Create Standard GKE Cluster"""

    @installation_step("create_gke_cluster", "Creating Standard GKE cluster")
    def execute(self) -> bool:
        """Step 2: Create Standard GKE Cluster"""
        # Check if cluster already exists
        success, _ = self.runner.run(
            f"gcloud container clusters describe {self.config.gke_cluster_name} --zone={self.config.zone}"
        )
        if success:
            self.logger.info(f"GKE cluster {self.config.gke_cluster_name} already exists")
        else:
            # Create multi-zone cluster to support kube-apiserver anti-affinity rules
            create_cmd = f"""
            gcloud container clusters create {self.config.gke_cluster_name} \\
              --zone={self.config.zone} \\
              --node-locations={self.config.zone},{self.config.region}-b,{self.config.region}-c \\
              --num-nodes=1 \\
              --machine-type=e2-standard-4 \\
              --enable-autoscaling \\
              --min-nodes=1 \\
              --max-nodes=10 \\
              --enable-autorepair \\
              --enable-autoupgrade
            """
            success, _ = self.runner.run(create_cmd, timeout=900)  # 15 minutes timeout
            if not success:
                return False

        # Create resilient kubeconfig using the kubeconfig manager
        success = self.kubeconfig_manager.create_gke_kubeconfig()
        if not success:
            self.logger.error("Failed to create resilient GKE kubeconfig")
            return False

        # Verify cluster access using GKE kubeconfig
        env_gke = {'KUBECONFIG': self.config.kubeconfig_gke_path}
        success, _ = self.runner.run("kubectl cluster-info", env=env_gke)
        return success