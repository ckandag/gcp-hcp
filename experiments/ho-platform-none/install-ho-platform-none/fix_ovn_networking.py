#!/usr/bin/env python3
"""
Step 8.6: Fix OVN Networking Components
Fixing OVN networking components and certificates
"""

import time
from common import BaseStep, installation_step, Colors


class FixOvnNetworkingStep(BaseStep):
    """Step 8.6: Fix OVN Networking Components"""

    @installation_step("fix_ovn_networking", "Fixing OVN networking components and certificates")
    def execute(self) -> bool:
        """Step 8.6: Fix OVN Networking Components"""
        self.logger.info(f"{Colors.YELLOW}🔧{Colors.END} Checking OVN networking components...")

        control_plane_namespace = f"clusters-{self.config.hosted_cluster_name}"
        env_gke = {'KUBECONFIG': self.config.kubeconfig_gke_path}
        env_hosted = {'KUBECONFIG': self.config.kubeconfig_hosted_path}

        # Check network operator status first
        self.logger.info("Checking network operator status...")
        success, _ = self.runner.run(
            "kubectl get co/network -o jsonpath='{.status.conditions[?(@.type==\"Degraded\")].status}'",
            env=env_hosted
        )

        if success:
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
                    self.logger.info(f"{Colors.YELLOW}⚠{Colors.END} Network operator is degraded due to MTU probe failure (no worker nodes yet)")
                    self.logger.info("Skipping OVN networking fixes until worker nodes are available")
                    return True

        # Step 1: Wait for network operator to render OVN manifests (reduced timeout)
        self.logger.info("Waiting for network operator to render OVN manifests...")
        max_wait = 120  # Reduced to 2 minutes
        wait_time = 0
        while wait_time < max_wait:
            success, _ = self.runner.run(
                f"kubectl get deployment ovnkube-control-plane -n {control_plane_namespace}",
                env=env_gke
            )
            if success:
                self.logger.info("OVN manifests rendered successfully")
                break

            self.logger.info(f"  Waiting for OVN manifests... ({wait_time//30} checks)")
            time.sleep(30)
            wait_time += 30

        if wait_time >= max_wait:
            self.logger.info(f"{Colors.YELLOW}⏳{Colors.END} OVN manifests not ready yet, will be handled after worker node deployment")
            return True

        # Step 2: Create missing ovn-control-plane-metrics-cert secret in HOSTED cluster
        self.logger.info("Creating missing OVN control plane metrics certificate in hosted cluster...")
        success, _ = self.runner.run(
            "kubectl get secret ovn-control-plane-metrics-cert -n openshift-ovn-kubernetes",
            env=env_hosted
        )

        tls_crt = tls_key = None
        if not success:
            self.logger.info("Creating ovn-control-plane-metrics-cert secret in hosted cluster...")
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
                # Create the control plane metrics cert YAML for hosted cluster
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

                # Write and apply the secret to hosted cluster
                cert_file = self.work_dir / "ovn-control-plane-metrics-cert-hosted.yaml"
                with open(cert_file, 'w') as f:
                    f.write(ovn_control_plane_metrics_cert)

                success, _ = self.runner.run(
                    f"kubectl apply -f {cert_file}",
                    env=env_hosted
                )

        # Step 2b: CRITICAL FIX - Create missing ovn-control-plane-metrics-cert secret in MANAGEMENT cluster
        self.logger.info(f"{Colors.YELLOW}🔧{Colors.END} Creating missing OVN control plane metrics certificate in management cluster...")
        success, _ = self.runner.run(
            f"kubectl get secret ovn-control-plane-metrics-cert -n {control_plane_namespace}",
            env=env_gke
        )

        if not success:
            self.logger.info("Creating ovn-control-plane-metrics-cert secret in management cluster...")
            # Extract certificate data if not already available
            if not tls_crt or not tls_key:
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
                if not (success and success2):
                    self.logger.error("Failed to extract certificate data from hosted cluster")
                    return False

            # Create the certificate secret in management cluster namespace
            ovn_control_plane_metrics_cert_mgmt = f"""apiVersion: v1
kind: Secret
metadata:
  name: ovn-control-plane-metrics-cert
  namespace: {control_plane_namespace}
  annotations:
    auth.openshift.io/certificate-hostnames: ovn-control-plane-metrics
    auth.openshift.io/certificate-issuer: openshift-ovn-kubernetes_ovn-ca@1757869721
    auth.openshift.io/certificate-not-after: "2026-03-16T05:08:42Z"
    auth.openshift.io/certificate-not-before: "2025-09-14T17:08:41Z"
  labels:
    auth.openshift.io/managed-certificate-type: target
type: kubernetes.io/tls
data:
  tls.crt: {tls_crt.strip()}
  tls.key: {tls_key.strip()}
"""

            # Write and apply the secret to management cluster
            cert_file = self.work_dir / "ovn-control-plane-metrics-cert-mgmt.yaml"
            with open(cert_file, 'w') as f:
                f.write(ovn_control_plane_metrics_cert_mgmt)

            success, _ = self.runner.run(
                f"kubectl apply -f {cert_file}",
                env=env_gke
            )

            if success:
                self.logger.info(f"{Colors.GREEN}✓{Colors.END} Created ovn-control-plane-metrics-cert in management cluster")
            else:
                self.logger.error(f"{Colors.RED}✗{Colors.END} Failed to create ovn-control-plane-metrics-cert in management cluster")
                return False

        # Step 3: Create missing ovn-node-metrics-cert secret
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

        # Step 4: Wait for OVN control plane pods to be ready
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

        # Step 5: Wait for OVN node pods to be mostly ready
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
        return True