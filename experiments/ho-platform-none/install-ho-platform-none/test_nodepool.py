#!/usr/bin/env python3
"""
Test script for NodePool deployment
"""

import os
import sys
import logging
from pathlib import Path
from deploy_nodepool import DeployNodePoolStep
from common import InstallConfig, CommandRunner, TemplateManager, StepTracker, Colors

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

def main():
    """Test NodePool deployment"""

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format=f'{Colors.CYAN}%(asctime)s{Colors.END} - {Colors.WHITE}%(levelname)s{Colors.END} - %(message)s'
    )
    logger = logging.getLogger(__name__)

    print("🚀 Testing NodePool deployment...")

    # Load configuration from environment
    config = get_config_from_env()

    # Set up working directory
    work_dir = Path(f"work_{config.hosted_cluster_name}")
    work_dir.mkdir(exist_ok=True)

    # Initialize step infrastructure
    state_file = Path(f".hypershift_install_state_{config.hosted_cluster_name}.json")
    tracker = StepTracker(state_file)
    runner = CommandRunner(dry_run=config.dry_run)
    templates = TemplateManager(Path("templates"))

    # Create step instance
    step = DeployNodePoolStep(config, logger, runner, templates, tracker, work_dir)

    # Execute the step
    try:
        success = step.execute()
        if success:
            print("✅ NodePool deployment completed successfully!")
        else:
            print("❌ NodePool deployment failed!")
    except Exception as e:
        print(f"❌ Error during NodePool deployment: {e}")

if __name__ == "__main__":
    main()