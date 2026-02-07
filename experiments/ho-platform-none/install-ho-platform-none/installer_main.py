#!/usr/bin/env python3
"""
HyperShift GKE Standard Installation Script - Modular Version

Main orchestrator that imports and executes individual installation steps.
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from typing import List

# Import common infrastructure
from common import InstallConfig, StepTracker, CommandRunner, TemplateManager, Colors

# Import individual step classes
from setup_environment import SetupEnvironmentStep
from create_gke_cluster import CreateGkeClusterStep
from install_prometheus_operator import InstallPrometheusOperatorStep
from install_cert_manager import InstallCertManagerStep
from build_hypershift import BuildHyperShiftStep
from deploy_webhook import DeployWebhookStep
from create_namespace_secrets import CreateNamespaceSecretsStep
from deploy_hosted_cluster import DeployHostedClusterStep
from wait_control_plane import WaitControlPlaneStep
from fix_service_ca import FixServiceCaStep
from fix_ovn_networking import FixOvnNetworkingStep
from extract_hosted_access import ExtractHostedAccessStep
from deploy_nodepool import DeployNodePoolStep
from apply_crds import ApplyCrdsStep
from create_ignition_worker import CreateIgnitionWorkerStep
from fix_ovn_networking_final import FixOvnNetworkingFinalStep
from verify_installation import VerifyInstallationStep


class HyperShiftInstaller:
    """Main installer class that orchestrates individual steps"""

    def __init__(self, config: InstallConfig, templates_dir: Path):
        self.config = config
        self.logger = self._setup_logging()
        self.runner = CommandRunner(dry_run=config.dry_run)
        self.templates = TemplateManager(templates_dir)

        # Setup state tracking
        state_file = Path(f".hypershift_install_state_{config.hosted_cluster_name}.json")
        self.tracker = StepTracker(state_file)

        # Create working directory for temporary files
        self.work_dir = Path(f"./work_{config.hosted_cluster_name}")
        self.work_dir.mkdir(exist_ok=True)

        # Initialize step instances
        self._initialize_steps()

    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        log_file = log_dir / f"hypershift_install_{self.config.hosted_cluster_name}.log"

        logging.basicConfig(
            level=logging.INFO,
            format=f'{Colors.CYAN}%(asctime)s{Colors.END} - {Colors.WHITE}%(levelname)s{Colors.END} - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler(log_file)
            ]
        )
        return logging.getLogger(__name__)

    def _initialize_steps(self):
        """Initialize all step instances"""
        step_args = (self.config, self.logger, self.runner, self.templates, self.tracker, self.work_dir)

        self.steps = [
            SetupEnvironmentStep(*step_args),
            CreateGkeClusterStep(*step_args),
            InstallPrometheusOperatorStep(*step_args),
            InstallCertManagerStep(*step_args),
            BuildHyperShiftStep(*step_args),
            DeployWebhookStep(*step_args),
            CreateNamespaceSecretsStep(*step_args),
            DeployHostedClusterStep(*step_args),
            WaitControlPlaneStep(*step_args),
            FixServiceCaStep(*step_args),
            FixOvnNetworkingStep(*step_args),
            ExtractHostedAccessStep(*step_args),
            ApplyCrdsStep(*step_args),
            DeployNodePoolStep(*step_args),
            CreateIgnitionWorkerStep(*step_args),
            FixOvnNetworkingFinalStep(*step_args),
            VerifyInstallationStep(*step_args),
        ]

    def verify_prerequisites(self) -> bool:
        """Verify all prerequisites are met"""
        self.logger.info(f"{Colors.BOLD}Verifying Prerequisites{Colors.END}")

        # Check required commands
        required_commands = ['gcloud', 'kubectl', 'helm', 'git', 'ssh-keygen', 'openssl']
        for cmd in required_commands:
            success, _ = self.runner.run(f"which {cmd}")
            if not success:
                self.logger.error(f"{Colors.RED}✗{Colors.END} Required command not found: {cmd}")
                return False

        # Check gcloud authentication
        success, output = self.runner.run("gcloud auth list --filter=status:ACTIVE", check_output=True)
        if not success or not output.strip():
            self.logger.error(f"{Colors.RED}✗{Colors.END} gcloud not authenticated. Run 'gcloud auth login'")
            return False

        # Check pull secret file
        if not Path(self.config.pull_secret_path).exists():
            self.logger.error(f"{Colors.RED}✗{Colors.END} Pull secret file not found: {self.config.pull_secret_path}")
            return False

        # Check templates directory
        templates_dir = Path("templates")
        if not templates_dir.exists():
            self.logger.error(f"{Colors.RED}✗{Colors.END} Templates directory not found: {templates_dir}")
            return False

        self.logger.info(f"{Colors.GREEN}✓{Colors.END} All prerequisites verified")
        return True

    def run_installation(self) -> bool:
        """Run the complete installation process"""
        self.logger.info(f"{Colors.BOLD}{Colors.CYAN}Starting HyperShift GKE Installation{Colors.END}")
        self.logger.info(f"Project: {Colors.YELLOW}{self.config.project_id}{Colors.END}")
        self.logger.info(f"Cluster: {Colors.YELLOW}{self.config.hosted_cluster_name}{Colors.END}")
        self.logger.info(f"Dry run: {Colors.YELLOW}{self.config.dry_run}{Colors.END}")

        if not self.verify_prerequisites():
            return False

        # Execute steps
        for step in self.steps:
            if not step.execute():
                self.logger.error(f"{Colors.RED}✗{Colors.END} Installation failed at step: {step.__class__.__name__}")
                self._print_debug_info()
                return False

        self.logger.info(f"{Colors.BOLD}{Colors.GREEN}✓ HyperShift GKE Installation completed successfully!{Colors.END}")
        self._print_summary()
        return True

    def _print_debug_info(self):
        """Print debug information for troubleshooting"""
        self.logger.info(f"{Colors.BOLD}Debug Information:{Colors.END}")

        # Show HostedCluster status if it exists (use management cluster kubeconfig)
        env = {'KUBECONFIG': self.config.kubeconfig_gke_path}
        self.runner.run(f"kubectl describe hostedcluster {self.config.hosted_cluster_name} -n clusters", env=env)

        # Show recent events
        self.runner.run("kubectl get events --sort-by=.metadata.creationTimestamp -n clusters", env=env)

    def _print_summary(self):
        """Print installation summary"""
        summary = f"""
{Colors.BOLD}{Colors.GREEN}Installation Summary{Colors.END}
{Colors.CYAN}{'=' * 50}{Colors.END}

{Colors.BOLD}Management Cluster:{Colors.END}
  Project: {self.config.project_id}
  GKE Cluster: {self.config.gke_cluster_name}
  Zone: {self.config.zone}
  Kubeconfig: {self.config.kubeconfig_gke_path}

{Colors.BOLD}Hosted Cluster:{Colors.END}
  Name: {self.config.hosted_cluster_name}
  Domain: {self.config.hosted_cluster_domain}
  Kubeconfig: {self.config.kubeconfig_hosted_path}

{Colors.BOLD}Worker Node:{Colors.END}
  Name: {self.config.worker_node_name}
  Zone: {self.config.zone}
  Type: {self.config.worker_machine_type}

{Colors.BOLD}Next Steps:{Colors.END}
  1. Access hosted cluster: export KUBECONFIG={self.config.kubeconfig_hosted_path}
  2. View nodes: kubectl get nodes
  3. Deploy workloads: kubectl create deployment <name> --image=<image>
  4. Scale worker nodes: Create additional NodePool resources

{Colors.BOLD}Important Files:{Colors.END}
  - Installation log: logs/hypershift_install_{self.config.hosted_cluster_name}.log
  - State file: .hypershift_install_state_{self.config.hosted_cluster_name}.json
  - Working directory: {self.work_dir}
  - SSH key: {self.work_dir}/ssh-key (save this for worker access)

{Colors.BOLD}Cleanup (when done):{Colors.END}
  python3 installer_main.py --cleanup
"""
        print(summary)


def get_config_from_env(args) -> InstallConfig:
    """Get configuration from environment variables"""
    required_env_vars = {
        "PROJECT_ID": "GCP project ID",
        "GKE_CLUSTER_NAME": "Name for the GKE management cluster",
        "HOSTED_CLUSTER_NAME": "Name for the hosted OpenShift cluster",
        "HOSTED_CLUSTER_DOMAIN": "Base domain for the hosted cluster",
        "PULL_SECRET_PATH": "Path to Red Hat pull secret file"
    }

    optional_env_vars = {
        "REGION": "us-central1",
        "ZONE": "",  # Will be set to {region}-a if not provided
        "WORKER_NODE_NAME": "hypershift-worker-1",
        "WORKER_MACHINE_TYPE": "e2-standard-4",
        "WORKER_DISK_SIZE": "50GB",
        "RHCOS_IMAGE_NAME": "redhat-coreos-osd-418-x86-64-202508060022",
        "RHCOS_IMAGE_PROJECT": "redhat-marketplace-dev",
        "INFRAID": "",  # Will be generated if not provided
        "KUBECONFIG_GKE_PATH": "/tmp/kubeconfig-gke",
        "KUBECONFIG_HOSTED_PATH": "/tmp/kubeconfig-hosted",
        "WEBHOOK_IMAGE_TAG": "latest"
    }

    # Check required variables
    missing_vars = []
    for var, description in required_env_vars.items():
        if not os.getenv(var):
            missing_vars.append(f"  {var}: {description}")

    if missing_vars:
        print(f"{Colors.RED}Error: Missing required environment variables:{Colors.END}")
        print("\n".join(missing_vars))
        print(f"\nSee --help for details on environment variables")
        sys.exit(1)

    # Get values with defaults
    region = os.getenv("REGION", optional_env_vars["REGION"])
    zone = os.getenv("ZONE") or f"{region}-a"

    return InstallConfig(
        project_id=os.getenv("PROJECT_ID"),
        region=region,
        zone=zone,
        gke_cluster_name=os.getenv("GKE_CLUSTER_NAME"),
        hosted_cluster_name=os.getenv("HOSTED_CLUSTER_NAME"),
        hosted_cluster_domain=os.getenv("HOSTED_CLUSTER_DOMAIN"),
        pull_secret_path=os.getenv("PULL_SECRET_PATH"),
        kubeconfig_gke_path=os.getenv("KUBECONFIG_GKE_PATH", optional_env_vars["KUBECONFIG_GKE_PATH"]),
        kubeconfig_hosted_path=os.getenv("KUBECONFIG_HOSTED_PATH", optional_env_vars["KUBECONFIG_HOSTED_PATH"]),
        worker_node_name=os.getenv("WORKER_NODE_NAME", optional_env_vars["WORKER_NODE_NAME"]),
        worker_machine_type=os.getenv("WORKER_MACHINE_TYPE", optional_env_vars["WORKER_MACHINE_TYPE"]),
        worker_disk_size=os.getenv("WORKER_DISK_SIZE", optional_env_vars["WORKER_DISK_SIZE"]),
        rhcos_image_name=os.getenv("RHCOS_IMAGE_NAME", optional_env_vars["RHCOS_IMAGE_NAME"]),
        rhcos_image_project=os.getenv("RHCOS_IMAGE_PROJECT", optional_env_vars["RHCOS_IMAGE_PROJECT"]),
        infraid=os.getenv("INFRAID", optional_env_vars["INFRAID"]),
        dry_run=args.dry_run,
        webhook_image_tag=os.getenv("WEBHOOK_IMAGE_TAG", optional_env_vars["WEBHOOK_IMAGE_TAG"])
    )


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="HyperShift GKE Standard Installation Script - Modular Version",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
{Colors.BOLD}Environment Variables (required):{Colors.END}
  PROJECT_ID                 GCP project ID
  GKE_CLUSTER_NAME          Name for the GKE management cluster
  HOSTED_CLUSTER_NAME       Name for the hosted OpenShift cluster
  HOSTED_CLUSTER_DOMAIN     Base domain for the hosted cluster
  PULL_SECRET_PATH          Path to Red Hat pull secret file

{Colors.BOLD}Environment Variables (optional):{Colors.END}
  REGION                    GCP region (default: us-central1)
  ZONE                      GCP zone (default: {{region}}-a)
  WORKER_NODE_NAME          Worker node name (default: hypershift-worker-1)
  WORKER_MACHINE_TYPE       Worker machine type (default: e2-standard-4)
  WORKER_DISK_SIZE          Worker disk size (default: 50GB)
  RHCOS_IMAGE_NAME          Red Hat CoreOS image name (default: redhat-coreos-osd-418-x86-64-202508060022)
  RHCOS_IMAGE_PROJECT       RHCOS image project (default: redhat-marketplace-dev)
  INFRAID                   Infrastructure ID (default: {{cluster}}-a1b2c3d4)
  KUBECONFIG_GKE_PATH       GKE kubeconfig path (default: /tmp/kubeconfig-gke)
  KUBECONFIG_HOSTED_PATH    Hosted kubeconfig path (default: /tmp/kubeconfig-hosted)
  WEBHOOK_IMAGE_TAG         Webhook container image tag (default: latest)

{Colors.BOLD}Example:{Colors.END}
  export PROJECT_ID="my-project"
  export GKE_CLUSTER_NAME="hypershift-standard"
  export HOSTED_CLUSTER_NAME="my-cluster"
  export HOSTED_CLUSTER_DOMAIN="example.com"
  export PULL_SECRET_PATH="./pull-secret.txt"

  python3 installer_main.py

{Colors.BOLD}Resume interrupted installation:{Colors.END}
  python3 installer_main.py --continue

{Colors.BOLD}Clean up all resources:{Colors.END}
  python3 installer_main.py --cleanup
        """
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing commands"
    )


    parser.add_argument(
        "--continue",
        action="store_true",
        help="Continue from previous installation state"
    )

    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Clean up all resources created by the installer and reset state"
    )

    return parser.parse_args()


def main():
    """Main entry point"""
    args = parse_arguments()

    try:
        config = get_config_from_env(args)
        templates_dir = Path("templates")

        if not templates_dir.exists():
            print(f"{Colors.RED}Error: Templates directory not found: {templates_dir}{Colors.END}")
            print("Make sure you're running the script from the install-ho-platform-none directory")
            sys.exit(1)

        installer = HyperShiftInstaller(config, templates_dir)
        success = installer.run_installation()
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Installation interrupted by user{Colors.END}")
        sys.exit(1)
    except Exception as e:
        print(f"{Colors.RED}Unexpected error: {e}{Colors.END}")
        sys.exit(1)


if __name__ == "__main__":
    main()