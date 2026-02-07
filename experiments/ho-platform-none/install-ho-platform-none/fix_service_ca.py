#!/usr/bin/env python3
"""
Step 8.5: Fix Service CA ConfigMap for CNI Deployment
Fixing service CA configmap for CNI deployment
"""

import json
import base64
from common import BaseStep, installation_step, Colors


class FixServiceCaStep(BaseStep):
    """Step 8.5: Fix Service CA ConfigMap for CNI Deployment"""

    @installation_step("fix_service_ca", "Fixing service CA configmap for CNI deployment")
    def execute(self) -> bool:
        """Step 8.5: Fix Service CA ConfigMap for CNI Deployment"""
        self.logger.info(f"{Colors.YELLOW}🔧{Colors.END} Checking and fixing service CA configmap...")

        control_plane_namespace = f"clusters-{self.config.hosted_cluster_name}"

        # Use the GKE management cluster kubeconfig (not the hosted cluster kubeconfig)
        env_gke = {'KUBECONFIG': self.config.kubeconfig_gke_path}

        # First check if the service CA configmap exists in the control plane namespace
        success, _ = self.runner.run(
            f"kubectl get configmap openshift-service-ca.crt -n {control_plane_namespace}",
            env=env_gke
        )

        if not success:
            self.logger.info("Service CA configmap does not exist, creating it...")
            # Create the configmap with annotation for service CA injection
            success, _ = self.runner.run(
                f"""kubectl create configmap openshift-service-ca.crt -n {control_plane_namespace} \
                --dry-run=client -o yaml | \
                kubectl annotate --local=true -f - service.beta.openshift.io/inject-cabundle=true -o yaml | \
                kubectl apply -f -""",
                env=env_gke
            )
            if not success:
                self.logger.warning("Could not create service CA configmap")
                return False

        # Get the root CA certificate from the GKE cluster's kubeconfig instead of trying to connect to hosted cluster
        success, ca_cert = self.runner.run(
            f"kubectl config view --raw -o jsonpath='{{.clusters[?(@.name==\"{self.config.gke_cluster_name}\")].cluster.certificate-authority-data}}'",
            check_output=True,
            env=env_gke
        )

        if not success or not ca_cert.strip():
            self.logger.warning("Could not get root CA certificate from GKE cluster kubeconfig")
            # Try alternative approach - get CA from cluster info
            success, cluster_info = self.runner.run(
                "kubectl cluster-info dump --output-directory=/tmp/cluster-info",
                env=env_gke
            )
            if success:
                success, ca_cert = self.runner.run(
                    "kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}'",
                    check_output=True,
                    env=env_gke
                )

            if not success or not ca_cert.strip():
                self.logger.warning("Could not extract CA certificate, skipping service CA configmap update")
                return True  # Don't fail the installation for this step

        # Decode the base64 CA certificate
        try:
            decoded_ca = base64.b64decode(ca_cert).decode('utf-8')
        except Exception as e:
            self.logger.warning(f"Could not decode CA certificate: {e}")
            return True  # Don't fail the installation for this step

        # Extract just the first certificate (root CA)
        ca_lines = decoded_ca.strip().split('\n')
        root_ca_lines = []
        in_cert = False
        for line in ca_lines:
            if '-----BEGIN CERTIFICATE-----' in line:
                in_cert = True
                root_ca_lines.append(line)
            elif '-----END CERTIFICATE-----' in line:
                root_ca_lines.append(line)
                break  # Take only the first certificate
            elif in_cert:
                root_ca_lines.append(line)

        root_ca = '\n'.join(root_ca_lines)

        if not root_ca or '-----BEGIN CERTIFICATE-----' not in root_ca:
            self.logger.warning("Could not extract valid root CA certificate, skipping configmap update")
            return True  # Don't fail the installation for this step

        # Update the service CA configmap with both ca-bundle.crt and service-ca.crt
        self.logger.info("Updating service CA configmap with root certificate...")

        # Use kubectl patch to update both keys
        patch_data = {
            "data": {
                "ca-bundle.crt": root_ca,
                "service-ca.crt": root_ca
            }
        }

        patch_json = json.dumps(patch_data)

        success, _ = self.runner.run(
            f"""kubectl patch configmap openshift-service-ca.crt -n {control_plane_namespace} --type='merge' -p '{patch_json}'""",
            env=env_gke
        )

        if not success:
            self.logger.warning("Could not update service CA configmap")
            return True  # Don't fail the installation for this step

        # Restart the cluster-network-operator to pick up the new CA
        self.logger.info("Restarting cluster-network-operator to pick up CA changes...")
        success, _ = self.runner.run(
            f"kubectl delete pod -n {control_plane_namespace} -l name=cluster-network-operator",
            env=env_gke
        )

        if success:
            # Wait for new pod to be ready
            self.logger.info("Waiting for cluster-network-operator to restart...")
            success, _ = self.runner.run(
                f"kubectl wait --for=condition=ready pod -l name=cluster-network-operator -n {control_plane_namespace} --timeout=120s",
                env=env_gke
            )
            if success:
                self.logger.info(f"{Colors.GREEN}✓{Colors.END} Service CA configmap fixed and network operator restarted")
            else:
                self.logger.warning("Network operator restart took longer than expected")

        return True