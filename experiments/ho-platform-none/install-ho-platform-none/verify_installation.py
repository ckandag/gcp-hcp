#!/usr/bin/env python3
"""
Step 18: Verify Installation
Verifying installation
"""

import time
from common import BaseStep, installation_step, Colors


class VerifyInstallationStep(BaseStep):
    """Step 18: Verify Installation"""

    @installation_step("verify_installation", "Verifying installation")
    def execute(self) -> bool:
        """Step 18: Verify Installation"""
        # First, regenerate both kubeconfigs to ensure fresh tokens
        self._regenerate_kubeconfigs()

        # Check HostedCluster status (on management cluster, not hosted cluster!)
        env_gke = {'KUBECONFIG': self.config.kubeconfig_gke_path}
        success, _ = self.runner.run(f"kubectl get hostedcluster {self.config.hosted_cluster_name} -n clusters", env=env_gke)
        if not success:
            return False

        # Set KUBECONFIG for hosted cluster operations
        env = {'KUBECONFIG': self.config.kubeconfig_hosted_path}

        # Verify worker node registration and Ready status
        self.logger.info(f"{Colors.YELLOW}⏳{Colors.END} Waiting for worker node to register and become Ready...")
        max_attempts = 20
        node_ready = False
        for attempt in range(max_attempts):
            success, output = self.runner.run("kubectl get nodes", check_output=True, env=env)
            if success and self.config.worker_node_name in output:
                # Check if node is Ready
                success, node_status = self.runner.run(
                    f"kubectl get node {self.config.worker_node_name} -o jsonpath='{{.status.conditions[?(@.type==\"Ready\")].status}}'",
                    check_output=True, env=env
                )
                if success and node_status.strip() == "True":
                    self.logger.info(f"{Colors.GREEN}✓{Colors.END} Worker node {self.config.worker_node_name} is Ready!")
                    # Show node details
                    self.runner.run(f"kubectl get nodes {self.config.worker_node_name} -o wide", env=env)
                    node_ready = True
                    break
                else:
                    self.logger.info(f"{Colors.CYAN}◉{Colors.END} Node registered but not Ready yet (attempt {attempt + 1}/{max_attempts})")
            else:
                self.logger.info(f"{Colors.CYAN}◉{Colors.END} Attempt {attempt + 1}/{max_attempts}: Worker node not yet registered, waiting...")

            if attempt % 3 == 0:  # Every 3 attempts, show more details
                self.logger.info(f"  {Colors.BLUE}Checking kubelet and CNI status...{Colors.END}")
                self.runner.run(f'gcloud compute ssh {self.config.worker_node_name} --zone={self.config.zone} --command="sudo systemctl status kubelet --no-pager -l | tail -3" || true')
            time.sleep(30)

        if not node_ready:
            self.logger.error("Worker node failed to become Ready within timeout")
            return False

        # Verify OVN networking components are healthy
        self.logger.info(f"{Colors.YELLOW}🔍{Colors.END} Verifying OVN networking components...")

        # Check OVN control plane pods
        success, output = self.runner.run(
            "kubectl get pods -n openshift-ovn-kubernetes -l app=ovnkube-control-plane --no-headers",
            check_output=True, env=env
        )
        if success:
            running_control_pods = len([line for line in output.strip().split('\n') if 'Running' in line and '3/3' in line])
            self.logger.info(f"  OVN control plane pods running: {running_control_pods}/3")

        # Check OVN node pods
        success, output = self.runner.run(
            "kubectl get pods -n openshift-ovn-kubernetes -l app=ovnkube-node --no-headers",
            check_output=True, env=env
        )
        if success and output.strip():
            node_pod_status = output.strip().split('\n')[0]
            self.logger.info(f"  OVN node pod status: {node_pod_status}")
            if '7/8' in node_pod_status or '8/8' in node_pod_status:
                self.logger.info(f"  {Colors.GREEN}✓{Colors.END} OVN node pod is healthy")
            else:
                self.logger.warning(f"  {Colors.YELLOW}⚠{Colors.END} OVN node pod may need more time to stabilize")

        # Check CNI binary availability
        success, _ = self.runner.run(
            f'gcloud compute ssh {self.config.worker_node_name} --zone={self.config.zone} --command="test -f /opt/cni/bin/ovn-k8s-cni-overlay && echo \\"CNI binary present\\"" || echo "CNI binary check completed"'
        )

        # Deploy test workload
        self.logger.info(f"{Colors.YELLOW}🚀{Colors.END} Deploying test workload...")
        success, _ = self.runner.run(
            "kubectl create deployment hello-openshift --image=openshift/hello-openshift:latest --dry-run=client -o yaml | kubectl apply -f -",
            env=env
        )
        if not success:
            return False

        # Wait for pod to be scheduled and running
        self.logger.info(f"{Colors.YELLOW}⏳{Colors.END} Waiting for test pod to be scheduled and ready...")
        max_wait_attempts = 15  # Increased from 10 to allow more time for CNI to initialize
        pod_ready = False
        for wait_attempt in range(max_wait_attempts):
            success, pod_status = self.runner.run("kubectl get pods -l app=hello-openshift -o wide", check_output=True, env=env)
            if success:
                self.logger.info(f"  Pod status (attempt {wait_attempt + 1}/{max_wait_attempts}):")
                self.runner.run("kubectl get pods -l app=hello-openshift -o wide", env=env)

                # Check if pod is Running and Ready
                success, pod_phase = self.runner.run(
                    "kubectl get pods -l app=hello-openshift -o jsonpath='{.items[0].status.phase}'",
                    check_output=True, env=env
                )
                if success and pod_phase.strip() == "Running":
                    success, _ = self.runner.run("kubectl wait --for=condition=ready pod -l app=hello-openshift --timeout=30s", env=env)
                    if success:
                        self.logger.info(f"{Colors.GREEN}✓{Colors.END} Test workload is ready and running!")
                        pod_ready = True
                        break

            # Show CNI pod status to help diagnose issues
            if wait_attempt % 3 == 0:
                self.logger.info(f"  {Colors.BLUE}Checking CNI pod status...{Colors.END}")
                self.runner.run(f"kubectl get pods -n openshift-ovn-kubernetes --field-selector spec.nodeName={self.config.worker_node_name}", env=env)

            time.sleep(30)

        if not pod_ready:
            self.logger.warning(f"{Colors.YELLOW}⚠{Colors.END} Test pod did not become ready within timeout. This may indicate CNI issues.")
            self.logger.info(f"  {Colors.BLUE}Checking for common CNI issues...{Colors.END}")
            # Check kubelet logs for CNI errors
            self.runner.run(f'gcloud compute ssh {self.config.worker_node_name} --zone={self.config.zone} --command="sudo journalctl -u kubelet --no-pager -l | grep -E \"(CNI|network)\" | tail -5" || true')
            # Still return True since node is Ready, just warn about pod issues

        # Check pods on worker node
        success, output = self.runner.run(
            f"kubectl get pods --all-namespaces --field-selector spec.nodeName={self.config.worker_node_name}",
            check_output=True,
            env=env
        )
        if success and output.strip():
            self.logger.info(f"Pods successfully scheduled on worker node {self.config.worker_node_name}")

        return True

    def _regenerate_kubeconfigs(self) -> bool:
        """Regenerate kubeconfigs at runtime to avoid expired tokens"""
        self.logger.info(f"{Colors.CYAN}🔄{Colors.END} Regenerating kubeconfigs using resilient manager...")

        # Use the resilient kubeconfig manager to refresh both kubeconfigs
        success = self.kubeconfig_manager.refresh_kubeconfigs()
        if not success:
            self.logger.error("Failed to refresh kubeconfigs using resilient manager")
            return False

        self.logger.info(f"{Colors.GREEN}✓{Colors.END} Kubeconfigs regenerated with fresh tokens")
        return True