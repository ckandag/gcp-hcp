#!/usr/bin/env python3
"""
Test script for ignition-based worker creation
"""

import os
import sys
import logging
import argparse
from pathlib import Path
from common import InstallConfig, StepTracker, CommandRunner, TemplateManager, Colors
from create_ignition_worker import CreateIgnitionWorkerStep
from fix_ovn_networking import FixOvnNetworkingStep

def get_config_from_env():
    """Get configuration from environment variables (simplified for testing)"""
    required_env_vars = ["PROJECT_ID", "GKE_CLUSTER_NAME", "HOSTED_CLUSTER_NAME",
                        "HOSTED_CLUSTER_DOMAIN", "PULL_SECRET_PATH"]

    missing_vars = []
    for var in required_env_vars:
        if not os.getenv(var):
            missing_vars.append(var)

    if missing_vars:
        print(f"{Colors.RED}Error: Missing required environment variables: {missing_vars}{Colors.END}")
        print("Make sure to source your environment file first: source my-cluster.env")
        sys.exit(1)

    # Get values with defaults
    region = os.getenv("REGION", "us-central1")
    zone = os.getenv("ZONE") or f"{region}-a"

    return InstallConfig(
        project_id=os.getenv("PROJECT_ID"),
        region=region,
        zone=zone,
        gke_cluster_name=os.getenv("GKE_CLUSTER_NAME"),
        hosted_cluster_name=os.getenv("HOSTED_CLUSTER_NAME"),
        hosted_cluster_domain=os.getenv("HOSTED_CLUSTER_DOMAIN"),
        pull_secret_path=os.getenv("PULL_SECRET_PATH"),
        kubeconfig_gke_path=os.getenv("KUBECONFIG_GKE_PATH", "/tmp/kubeconfig-gke"),
        kubeconfig_hosted_path=os.getenv("KUBECONFIG_HOSTED_PATH", "/tmp/kubeconfig-hosted"),
        worker_node_name=os.getenv("WORKER_NODE_NAME", "hypershift-worker-1"),
        worker_machine_type=os.getenv("WORKER_MACHINE_TYPE", "e2-standard-4"),
        worker_disk_size=os.getenv("WORKER_DISK_SIZE", "50GB"),
        infraid=os.getenv("INFRAID", ""),
        dry_run=False,  # Can be changed for testing
        webhook_image_tag=os.getenv("WEBHOOK_IMAGE_TAG", "latest")
    )

def setup_common_infrastructure():
    """Setup common infrastructure for all test functions"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format=f'{Colors.CYAN}%(asctime)s{Colors.END} - {Colors.WHITE}%(levelname)s{Colors.END} - %(message)s'
    )
    logger = logging.getLogger(__name__)

    # Load environment configuration
    config = get_config_from_env()

    # Set up working directory
    work_dir = Path(f"work_{config.hosted_cluster_name}")
    work_dir.mkdir(exist_ok=True)

    # Initialize step infrastructure
    state_file = Path(f".hypershift_install_state_{config.hosted_cluster_name}.json")
    tracker = StepTracker(state_file)
    runner = CommandRunner(dry_run=config.dry_run)
    templates = TemplateManager(Path("templates"))

    return config, logger, runner, templates, tracker, work_dir

def test_ignition_worker():
    """Test the ignition worker creation"""
    config, logger, runner, templates, tracker, work_dir = setup_common_infrastructure()

    # Create and execute the ignition worker step
    step = CreateIgnitionWorkerStep(config, logger, runner, templates, tracker, work_dir)

    print("🚀 Testing ignition-based worker creation...")
    success = step.execute()

    if success:
        print("✅ Ignition worker creation test completed successfully!")
    else:
        print("❌ Ignition worker creation test failed!")
        sys.exit(1)

def fix_ovn_only():
    """Fix OVN networking issues only"""
    config, logger, runner, templates, tracker, work_dir = setup_common_infrastructure()

    print("🔧 Fixing OVN networking issues...")

    # Step 1: Run the standard OVN networking fix (hosted cluster certificates)
    step = FixOvnNetworkingStep(config, logger, runner, templates, tracker, work_dir)
    success = step.execute()

    if not success:
        print("❌ OVN networking fix failed!")
        sys.exit(1)

    # Step 2: Fix the critical management cluster certificate issue
    print("🔧 Creating missing ovn-control-plane-metrics-cert in management cluster...")
    success = fix_management_cluster_certificates(config, logger, runner, work_dir)

    if not success:
        print("❌ Management cluster certificate fix failed!")
        sys.exit(1)

    # Step 3: Restart OVN control plane pods to pick up the certificates
    print("🔄 Restarting OVN control plane pods...")
    env_gke = {'KUBECONFIG': config.kubeconfig_gke_path}
    control_plane_namespace = f"clusters-{config.hosted_cluster_name}"

    success, _ = runner.run(
        f"kubectl delete pod -n {control_plane_namespace} -l app=ovnkube-control-plane",
        env=env_gke
    )

    if success:
        print("✅ OVN networking fixes completed successfully!")
        print("📋 Next steps:")
        print("   1. Approve pending CSRs: kubectl get csr --no-headers | grep Pending | awk '{print $1}' | xargs -I {} oc adm certificate approve {}")
        print("   2. Monitor worker node: kubectl wait --for=condition=Ready node/[worker-name] --timeout=600s")
        print("   3. Restart ovnkube-node if needed: kubectl delete pod -n openshift-ovn-kubernetes -l app=ovnkube-node")
    else:
        print("❌ Failed to restart OVN control plane pods!")
        sys.exit(1)

def fix_management_cluster_certificates(config, logger, runner, work_dir):
    """Fix the critical management cluster certificate issue"""
    env_gke = {'KUBECONFIG': config.kubeconfig_gke_path}
    env_hosted = {'KUBECONFIG': config.kubeconfig_hosted_path}
    control_plane_namespace = f"clusters-{config.hosted_cluster_name}"

    # Check if the certificate already exists in management cluster
    success, _ = runner.run(
        f"kubectl get secret ovn-control-plane-metrics-cert -n {control_plane_namespace}",
        env=env_gke
    )

    if success:
        logger.info("ovn-control-plane-metrics-cert already exists in management cluster")
        return True

    # Extract certificate data from hosted cluster
    logger.info("Extracting certificate data from hosted cluster...")
    success, tls_crt = runner.run(
        "kubectl get secret ovn-cert -n openshift-ovn-kubernetes -o jsonpath='{.data.tls\\.crt}'",
        check_output=True,
        env=env_hosted
    )
    success2, tls_key = runner.run(
        "kubectl get secret ovn-cert -n openshift-ovn-kubernetes -o jsonpath='{.data.tls\\.key}'",
        check_output=True,
        env=env_hosted
    )

    if not (success and success2):
        logger.error("Failed to extract certificate data from hosted cluster")
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
    cert_file = work_dir / "ovn-control-plane-metrics-cert-mgmt.yaml"
    with open(cert_file, 'w') as f:
        f.write(ovn_control_plane_metrics_cert_mgmt)

    success, _ = runner.run(
        f"kubectl apply -f {cert_file}",
        env=env_gke
    )

    if success:
        logger.info("✅ Created ovn-control-plane-metrics-cert in management cluster")
        return True
    else:
        logger.error("❌ Failed to create ovn-control-plane-metrics-cert in management cluster")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test ignition-based worker creation and OVN networking")
    parser.add_argument("--fix-ovn-only", action="store_true",
                        help="Only fix OVN networking issues, skip worker creation")

    args = parser.parse_args()

    if args.fix_ovn_only:
        fix_ovn_only()
    else:
        test_ignition_worker()