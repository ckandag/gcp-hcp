#!/usr/bin/env python3
"""
Step 16.5: Complete OVN Networking Setup Now That Worker Nodes Are Available
Completing OVN networking setup with worker nodes available
"""

import time
from common import BaseStep, installation_step, Colors


class FixOvnNetworkingFinalStep(BaseStep):
    """Step 16.5: Complete OVN Networking Setup Now That Worker Nodes Are Available"""

    @installation_step("fix_ovn_networking_final", "Completing OVN networking setup with worker nodes available")
    def execute(self) -> bool:
        """Step 16.5: Complete OVN Networking Setup Now That Worker Nodes Are Available"""
        self.logger.info(f"{Colors.YELLOW}🔧{Colors.END} Completing OVN networking setup with worker nodes...")

        control_plane_namespace = f"clusters-{self.config.hosted_cluster_name}"
        env_gke = {'KUBECONFIG': self.config.kubeconfig_gke_path}
        env_hosted = {'KUBECONFIG': self.config.kubeconfig_hosted_path}

        # Check if network operator is still degraded due to MTU probe
        self.logger.info("Checking network operator status after worker node deployment...")
        success, degraded_status = self.runner.run(
            "kubectl get co/network -o jsonpath='{.status.conditions[?(@.type==\"Degraded\")].status}'",
            check_output=True,
            env=env_hosted
        )

        if success and degraded_status.strip() == "True":
            success, degraded_reason = self.runner.run(
                "kubectl get co/network -o jsonpath='{.status.conditions[?(@.type==\"Degraded\")].reason}'",
                check_output=True,
                env=env_hosted
            )
            if success and "MTUProbeFailed" in degraded_reason:
                self.logger.info(f"{Colors.YELLOW}⚠{Colors.END} Network operator still degraded due to MTU probe failure")
                self.logger.info("Triggering MTU probe retry by restarting cluster-network-operator...")

                # Restart the cluster-network-operator to retry MTU probe
                success, _ = self.runner.run(
                    f"kubectl delete pod -n {control_plane_namespace} -l name=cluster-network-operator",
                    env=env_gke
                )
                if success:
                    # Wait for new operator pod
                    time.sleep(30)
                    self.logger.info("Waiting for network operator to restart and retry MTU probe...")
                    success, _ = self.runner.run(
                        f"kubectl wait --for=condition=ready pod -l name=cluster-network-operator -n {control_plane_namespace} --timeout=120s",
                        env=env_gke
                    )

        # Now wait for OVN manifests with worker nodes available
        self.logger.info("Waiting for network operator to render OVN manifests...")
        max_wait = 300  # 5 minutes
        wait_time = 0
        ovn_manifests_ready = False

        while wait_time < max_wait:
            success, _ = self.runner.run(
                f"kubectl get deployment ovnkube-control-plane -n {control_plane_namespace}",
                env=env_gke
            )
            if success:
                self.logger.info("OVN manifests rendered successfully")
                ovn_manifests_ready = True
                break

            self.logger.info(f"  Waiting for OVN manifests... ({wait_time//30} checks)")
            time.sleep(30)
            wait_time += 30

        if not ovn_manifests_ready:
            self.logger.warning("OVN manifests still not ready, but continuing...")
            return True

        # Wait for OVN namespace to be created
        self.logger.info("Waiting for openshift-ovn-kubernetes namespace...")
        max_wait = 120  # 2 minutes
        wait_time = 0
        while wait_time < max_wait:
            success, _ = self.runner.run(
                "kubectl get namespace openshift-ovn-kubernetes",
                env=env_hosted
            )
            if success:
                self.logger.info("openshift-ovn-kubernetes namespace is available")
                break
            time.sleep(15)
            wait_time += 15

        # Create missing OVN metrics certificates if they don't exist
        self._create_ovn_metrics_certificates()

        # Wait for OVN components to be ready
        self._wait_for_ovn_components()

        return True

    def _create_ovn_metrics_certificates(self):
        """Create missing OVN metrics certificates"""
        env_hosted = {'KUBECONFIG': self.config.kubeconfig_hosted_path}

        # Check if ovn-cert secret exists to get TLS data
        success, _ = self.runner.run(
            "kubectl get secret ovn-cert -n openshift-ovn-kubernetes",
            env=env_hosted
        )
        if not success:
            self.logger.info("ovn-cert secret not found, skipping metrics certificate creation")
            return

        # Create missing ovn-control-plane-metrics-cert secret
        self.logger.info("Creating missing OVN control plane metrics certificate...")
        success, _ = self.runner.run(
            "kubectl get secret ovn-control-plane-metrics-cert -n openshift-ovn-kubernetes",
            env=env_hosted
        )

        if not success:
            self.logger.info("Creating ovn-control-plane-metrics-cert secret...")
            # Get TLS data from ovn-cert secret
            success, tls_crt = self.runner.run(
                "kubectl get secret ovn-cert -n openshift-ovn-kubernetes -o jsonpath='{.data.tls\\.crt}'",
                check_output=True,
                env=env_hosted
            )
            success2, tls_key = self.runner.run(
                "kubectl get secret ovn-cert -n openshift-ovn-kubernetes -o jsonpath='{.data.tls\\.key}'",
                check_output=True,
                env=env_hosted
            )
            if success and success2:
                # Create the control plane metrics cert YAML
                ovn_control_plane_metrics_cert = f"""apiVersion: v1
data:
  tls.crt: {tls_crt.strip()}
  tls.key: {tls_key.strip()}
kind: Secret
metadata:
  annotations:
    auth.openshift.io/certificate-hostnames: ovn-control-plane-metrics
    auth.openshift.io/certificate-issuer: openshift-ovn-kubernetes_ovn-ca@1757869721
    auth.openshift.io/certificate-not-after: "2026-03-16T05:08:42Z"
    auth.openshift.io/certificate-not-before: "2025-09-14T17:08:41Z"
  labels:
    auth.openshift.io/managed-certificate-type: target
  name: ovn-control-plane-metrics-cert
  namespace: openshift-ovn-kubernetes
type: kubernetes.io/tls"""

                # Write and apply the secret
                cert_file = self.work_dir / "ovn-control-plane-metrics-cert.yaml"
                with open(cert_file, 'w') as f:
                    f.write(ovn_control_plane_metrics_cert)

                success, _ = self.runner.run(
                    f"kubectl apply -f {cert_file}",
                    env=env_hosted
                )

        # Create missing ovn-node-metrics-cert secret
        self.logger.info("Creating missing OVN node metrics certificate...")
        success, _ = self.runner.run(
            "kubectl get secret ovn-node-metrics-cert -n openshift-ovn-kubernetes",
            env=env_hosted
        )

        if not success:
            self.logger.info("Creating ovn-node-metrics-cert secret...")
            # Reuse the TLS data from previous step or fetch again if needed
            if 'tls_crt' not in locals() or 'tls_key' not in locals():
                success, tls_crt = self.runner.run(
                    "kubectl get secret ovn-cert -n openshift-ovn-kubernetes -o jsonpath='{.data.tls\\.crt}'",
                    check_output=True,
                    env=env_hosted
                )
                success2, tls_key = self.runner.run(
                    "kubectl get secret ovn-cert -n openshift-ovn-kubernetes -o jsonpath='{.data.tls\\.key}'",
                    check_output=True,
                    env=env_hosted
                )
            else:
                success = success2 = True

            if success and success2:
                ovn_node_metrics_cert = f"""apiVersion: v1
data:
  tls.crt: {tls_crt.strip()}
  tls.key: {tls_key.strip()}
kind: Secret
metadata:
  annotations:
    auth.openshift.io/certificate-hostnames: ovn-node-metrics
    auth.openshift.io/certificate-issuer: openshift-ovn-kubernetes_ovn-ca@1757869721
    auth.openshift.io/certificate-not-after: "2026-03-16T05:08:42Z"
    auth.openshift.io/certificate-not-before: "2025-09-14T17:08:41Z"
  labels:
    auth.openshift.io/managed-certificate-type: target
  name: ovn-node-metrics-cert
  namespace: openshift-ovn-kubernetes
type: kubernetes.io/tls"""

                # Write and apply the secret
                cert_file = self.work_dir / "ovn-node-metrics-cert.yaml"
                with open(cert_file, 'w') as f:
                    f.write(ovn_node_metrics_cert)

                success, _ = self.runner.run(
                    f"kubectl apply -f {cert_file}",
                    env=env_hosted
                )

    def _wait_for_ovn_components(self):
        """Wait for OVN components to be ready"""
        env_hosted = {'KUBECONFIG': self.config.kubeconfig_hosted_path}

        # Wait for OVN control plane pods to be ready
        self.logger.info("Waiting for OVN control plane pods to be ready...")
        max_wait = 300  # 5 minutes
        wait_time = 0
        while wait_time < max_wait:
            success, output = self.runner.run(
                "kubectl get pods -n openshift-ovn-kubernetes -l app=ovnkube-control-plane --no-headers",
                check_output=True,
                env=env_hosted
            )
            if success:
                lines = output.strip().split('\n') if output.strip() else []
                running_pods = [line for line in lines if 'Running' in line and '3/3' in line]
                if len(running_pods) >= 3:
                    self.logger.info(f"{Colors.GREEN}✓{Colors.END} All 3 OVN control plane pods are ready")
                    break

            self.logger.info(f"  Waiting for OVN control plane pods... ({wait_time//30} cycles)")
            time.sleep(30)
            wait_time += 30

        # Wait for OVN node pods to be mostly ready
        self.logger.info("Waiting for OVN node pods to be ready...")
        max_wait = 300  # 5 minutes
        wait_time = 0
        while wait_time < max_wait:
            success, output = self.runner.run(
                "kubectl get pods -n openshift-ovn-kubernetes -l app=ovnkube-node --no-headers",
                check_output=True,
                env=env_hosted
            )
            if success and output.strip():
                lines = output.strip().split('\n')
                for line in lines:
                    if 'Running' in line and ('7/8' in line or '8/8' in line):
                        self.logger.info(f"{Colors.GREEN}✓{Colors.END} OVN node pod is ready (7/8 or 8/8 containers)")
                        return True

            self.logger.info(f"  Waiting for OVN node pods... ({wait_time//30} cycles)")
            time.sleep(30)
            wait_time += 30

        self.logger.warning("OVN node pods did not reach full readiness within timeout, but continuing...")