#!/usr/bin/env python3
"""
Ignition-Based Worker Node Creation
Creates worker nodes that bootstrap using HyperShift's ignition server
"""

import base64
import json
import tempfile
import time
from pathlib import Path
from dataclasses import asdict
from common import BaseStep, installation_step, Colors


class CreateIgnitionWorkerStep(BaseStep):
    """Creates worker nodes using ignition-based bootstrap"""

    @installation_step("create_ignition_worker", "Creating ignition-based worker node")
    def execute(self) -> bool:
        """Create worker node with ignition bootstrap"""

        # Step 1: Extract authentication token from TokenSecret
        token_secret_name = self._get_token_secret_name()
        if not token_secret_name:
            self.logger.error("Failed to find NodePool TokenSecret")
            return False

        token = self._extract_auth_token(token_secret_name)
        if not token:
            self.logger.error("Failed to extract authentication token")
            return False

        # Step 2: Get ignition server endpoint
        ignition_server_ip = self._get_ignition_server_ip()
        if not ignition_server_ip:
            self.logger.error("Failed to get ignition server IP")
            return False

        # Step 2.5: Ensure firewall rules allow access to ignition endpoint
        if not self._ensure_ignition_firewall_rules():
            self.logger.error("Failed to configure firewall rules for ignition endpoint")
            return False

        # Step 3: Create ignition user-data for Red Hat CoreOS
        user_data = self._create_ignition_userdata(token, ignition_server_ip, token_secret_name)
        if not user_data:
            self.logger.error("Failed to create ignition user-data")
            return False

        # Step 4: Create GCE instance with ignition bootstrap
        return self._create_gce_instance_with_ignition(user_data)

    def _get_token_secret_name(self) -> str:
        """Find the TokenSecret created by our NodePool"""
        self.logger.info("🔍 Finding NodePool TokenSecret...")

        # List secrets in the hosted cluster namespace
        success, output = self.runner.run(
            f"KUBECONFIG=/tmp/kubeconfig-gke kubectl get secrets -n clusters-{self.config.hosted_cluster_name} --no-headers",
            check_output=True
        )
        if not success:
            return ""

        # Find token secret that starts with our pattern
        token_secret_pattern = f"token-{self.config.hosted_cluster_name}-workers-"

        for line in output.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) > 0:
                secret_name = parts[0]
                if secret_name.startswith(token_secret_pattern):
                    # Verify it has the ignition-config annotation
                    success, annotation_value = self.runner.run(
                        f'KUBECONFIG=/tmp/kubeconfig-gke kubectl get secret {secret_name} -n clusters-{self.config.hosted_cluster_name} -o jsonpath="{{.metadata.annotations.hypershift\\.openshift\\.io/ignition-config}}"',
                        check_output=True
                    )
                    if success and annotation_value.strip() == "true":
                        self.logger.info(f"✓ Found TokenSecret: {secret_name}")
                        return secret_name

        self.logger.error("No valid TokenSecret found with ignition-config annotation")
        return ""

    def _extract_auth_token(self, secret_name: str) -> str:
        """Extract the base64-encoded authentication token"""
        self.logger.info("🔑 Extracting authentication token...")

        success, output = self.runner.run(
            f'KUBECONFIG=/tmp/kubeconfig-gke kubectl get secret {secret_name} -n clusters-{self.config.hosted_cluster_name} -o jsonpath="{{.data.token}}"',
            check_output=True
        )
        if not success:
            return ""

        # Token is already base64 encoded in the secret
        token = output.strip()
        if token:
            self.logger.info("✓ Extracted authentication token")
            return token

        return ""

    def _get_ignition_server_ip(self) -> str:
        """Get the ignition server IP that matches the certificate"""
        self.logger.info("🌐 Getting ignition server endpoint...")

        # Get all GKE node external IPs
        success, output = self.runner.run(
            f'KUBECONFIG=/tmp/kubeconfig-gke kubectl get nodes -o jsonpath="{{.items[*].status.addresses[?(@.type==\\"ExternalIP\\")].address}}"',
            check_output=True
        )
        if not success or not output.strip():
            return ""

        node_ips = output.strip().split()
        if not node_ips:
            return ""

        # Try to find the IP that matches the ignition server certificate
        certificate_valid_ip = self._get_certificate_valid_ip(node_ips)
        if certificate_valid_ip:
            self.logger.info(f"✓ Ignition server IP (certificate-valid): {certificate_valid_ip}")
            return certificate_valid_ip

        # Fallback: test each IP with connectivity (using -k for firewall check)
        for ip in node_ips:
            success, _ = self.runner.run(
                f"curl -k --connect-timeout 5 https://{ip}:30080/healthz"
            )
            if success:
                self.logger.info(f"✓ Ignition server IP: {ip}")
                return ip

        # Final fallback to first IP if none work
        ip = node_ips[0]
        self.logger.info(f"✓ Ignition server IP (fallback): {ip}")
        return ip

    def _get_ignition_ca_certificate(self) -> str:
        """Get the base64-encoded CA certificate for the ignition server"""
        self.logger.info("🔐 Getting ignition server CA certificate...")

        success, output = self.runner.run(
            f'KUBECONFIG=/tmp/kubeconfig-gke kubectl get secret ignition-server-ca-cert -n clusters-{self.config.hosted_cluster_name} -o jsonpath="{{.data.tls\\.crt}}"',
            check_output=True
        )
        if success and output.strip():
            ca_cert_b64 = output.strip()
            self.logger.info("✓ Retrieved ignition server CA certificate")
            return ca_cert_b64

        self.logger.error("Failed to get ignition server CA certificate")
        return ""

    def _create_ignition_userdata(self, token: str, server_ip: str, token_secret_name: str) -> str:
        """Create Red Hat CoreOS ignition user-data from template"""
        self.logger.info("📝 Creating ignition user-data from template...")

        # Extract target config version hash from secret name (part after last dash)
        target_config_hash = token_secret_name.split('-')[-1]

        # Get the CA certificate for the ignition server
        ca_cert = self._get_ignition_ca_certificate()
        if not ca_cert:
            self.logger.error("Failed to get ignition server CA certificate")
            return ""

        # Prepare template variables
        template_vars = {
            'ignition_server_ip': server_ip,
            'auth_token': token,
            'hosted_cluster_name': self.config.hosted_cluster_name,
            'target_config_hash': target_config_hash,
            'ignition_ca_cert': ca_cert
        }

        # Render template to temporary file
        user_data_path = self.work_dir / "ignition-userdata.json"
        success = self.templates.render_to_file("ignition-userdata.yaml", template_vars, user_data_path)
        if not success:
            return ""

        # Read the rendered template
        try:
            with open(user_data_path, 'r') as f:
                user_data = f.read()
            self.logger.info("✓ Created ignition user-data from template")
            return user_data
        except Exception as e:
            self.logger.error(f"Failed to read rendered template: {e}")
            return ""

    def _create_gce_instance_with_ignition(self, user_data: str) -> bool:
        """Create GCE instance with ignition bootstrap"""
        worker_name = f"{self.config.hosted_cluster_name}-worker-ignition-1"

        # Check if worker node already exists
        success, _ = self.runner.run(
            f"gcloud compute instances describe {worker_name} --zone={self.config.zone}"
        )
        if success:
            self.logger.info(f"Worker node {worker_name} already exists")
            return True

        self.logger.info(f"🚀 Creating worker node: {worker_name}")

        # Write user-data to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(user_data)
            user_data_file = f.name

        try:
            # Create GCE instance with ignition user-data using Red Hat CoreOS
            create_cmd = f"""
            gcloud compute instances create {worker_name} \
              --zone={self.config.zone} \
              --machine-type={self.config.worker_machine_type} \
              --image={self.config.rhcos_image_name} \
              --image-project={self.config.rhcos_image_project} \
              --boot-disk-size={self.config.worker_disk_size} \
              --boot-disk-type=pd-standard \
              --subnet=default \
              --tags=hypershift-worker \
              --metadata-from-file=user-data={user_data_file}
            """

            success, output = self.runner.run(create_cmd, timeout=300)
            if success:
                self.logger.info(f"✓ Created worker node with ignition bootstrap")
                self._wait_for_worker_registration(worker_name)
                return True
            else:
                self.logger.error(f"Failed to create worker node: {output}")
                return False

        finally:
            # Clean up temporary file
            Path(user_data_file).unlink(missing_ok=True)

    def _wait_for_worker_registration(self, worker_name: str) -> bool:
        """Wait for worker node to register with the hosted cluster"""
        self.logger.info(f"⏳ Waiting for worker node to join hosted cluster...")

        max_wait = 600  # 10 minutes
        wait_time = 0

        while wait_time < max_wait:
            # Check if node appears in hosted cluster
            success, output = self.runner.run(
                f"KUBECONFIG=/tmp/kubeconfig-hosted kubectl get nodes -o name"
            )
            if success and worker_name in output:
                self.logger.info(f"✓ Worker node {worker_name} joined hosted cluster")
                return True

            wait_time += 30
            if wait_time % 120 == 0:
                self.logger.info(f"  Still waiting for worker registration... ({wait_time//60} minutes)")
            time.sleep(30)

        self.logger.warning(f"Worker node did not register within {max_wait//60} minutes")
        return False

    def _ensure_ignition_firewall_rules(self) -> bool:
        """Ensure firewall rules allow access to ignition endpoint on NodePort 30080"""
        self.logger.info("🔥 Configuring firewall rules for ignition endpoint...")

        # Step 1: Get the actual GKE node tags
        gke_node_tags = self._get_gke_node_tags()
        if not gke_node_tags:
            self.logger.error("Failed to get GKE node tags")
            return False

        # Step 2: Check if firewall rule exists and update it
        firewall_rule_name = "allow-ignition-endpoint"

        # Check if rule exists
        success, _ = self.runner.run(
            f"gcloud compute firewall-rules describe {firewall_rule_name}"
        )

        if success:
            # Update existing rule with correct target tags
            self.logger.info(f"Updating existing firewall rule: {firewall_rule_name}")
            success, _ = self.runner.run(
                f"gcloud compute firewall-rules update {firewall_rule_name} --target-tags {','.join(gke_node_tags)}"
            )
        else:
            # Create new firewall rule
            self.logger.info(f"Creating firewall rule: {firewall_rule_name}")
            success, _ = self.runner.run(
                f"gcloud compute firewall-rules create {firewall_rule_name} "
                f"--allow tcp:30080 "
                f"--source-ranges 0.0.0.0/0 "
                f"--target-tags {','.join(gke_node_tags)} "
                f"--description 'Allow access to HyperShift ignition server NodePort'"
            )

        if success:
            self.logger.info("✓ Firewall rules configured for ignition endpoint")
            return True
        else:
            self.logger.error("Failed to configure firewall rules")
            return False

    def _get_gke_node_tags(self) -> list:
        """Get the network tags used by GKE nodes"""
        # Get the first GKE node name
        success, output = self.runner.run(
            f'KUBECONFIG=/tmp/kubeconfig-gke kubectl get nodes -o jsonpath="{{.items[0].metadata.name}}"',
            check_output=True
        )
        if not success or not output.strip():
            return []

        node_name = output.strip()

        # Get the zone from node info
        success, output = self.runner.run(
            f'KUBECONFIG=/tmp/kubeconfig-gke kubectl get node {node_name} -o jsonpath="{{.metadata.labels.topology\\.kubernetes\\.io/zone}}"',
            check_output=True
        )
        if not success or not output.strip():
            # Fall back to default zone
            zone = self.config.zone
        else:
            zone = output.strip()

        # Get network tags from the GCE instance
        success, output = self.runner.run(
            f"gcloud compute instances describe {node_name} --zone={zone} --format='value(tags.items)'",
            check_output=True
        )
        if success and output.strip():
            # Parse tags (they come as a semicolon-separated list)
            tags = [tag.strip() for tag in output.strip().split(';') if tag.strip()]
            self.logger.info(f"✓ Found GKE node tags: {tags}")
            return tags

        return []

    def _get_certificate_valid_ip(self, node_ips: list) -> str:
        """Extract valid IP addresses from ignition server certificate and find match with node IPs"""
        # Get certificate from any node IP (using -k to bypass validation for analysis)
        for ip in node_ips:
            success, output = self.runner.run(
                f"echo | openssl s_client -connect {ip}:30080 -servername {ip} 2>/dev/null | openssl x509 -text -noout",
                check_output=True
            )
            if success and output.strip():
                # Parse certificate for Subject Alternative Names (SANs)
                lines = output.split('\n')
                for i, line in enumerate(lines):
                    if 'Subject Alternative Name' in line and i + 1 < len(lines):
                        san_line = lines[i + 1].strip()
                        # Extract IP addresses from SAN line (format: "IP Address:1.2.3.4")
                        import re
                        ip_matches = re.findall(r'IP Address:(\d+\.\d+\.\d+\.\d+)', san_line)

                        # Find intersection between certificate IPs and available node IPs
                        for cert_ip in ip_matches:
                            if cert_ip in node_ips:
                                self.logger.info(f"✓ Found certificate-valid IP: {cert_ip}")
                                return cert_ip
                break

        return ""