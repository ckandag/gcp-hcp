#!/usr/bin/env python3
"""
HyperShift GKE Installation Cleanup Script

Cleans up resources created by the HyperShift installer.
"""

import os
import sys
import argparse
import subprocess
import json
import logging
from pathlib import Path
from typing import List, Optional


class Colors:
    """Terminal color codes"""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    END = '\033[0m'


class HyperShiftCleanup:
    """Cleanup utility for HyperShift GKE installations"""
    
    def __init__(self, cluster_name: str, project_id: str, zone: str, dry_run: bool = False):
        self.cluster_name = cluster_name
        self.project_id = project_id
        self.zone = zone
        self.dry_run = dry_run
        self.logger = self._setup_logging()
        
        # Load configuration from state file if available
        self.state_file = Path(f".hypershift_install_state_{cluster_name}.json")
        self.config = self._load_config()
    
    def _setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format=f'{Colors.CYAN}%(asctime)s{Colors.END} - {Colors.WHITE}%(levelname)s{Colors.END} - %(message)s'
        )
        return logging.getLogger(__name__)
    
    def _load_config(self) -> dict:
        """Load configuration from state file"""
        if not self.state_file.exists():
            return {}
        
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                return state.get('config', {})
        except Exception as e:
            self.logger.warning(f"Could not load state file: {e}")
            return {}
    
    def _run_command(self, command: str, check: bool = True) -> bool:
        """Run a command with optional dry-run mode"""
        if self.dry_run:
            self.logger.info(f"{Colors.BLUE}[DRY RUN]{Colors.END} Would execute: {command}")
            return True
        
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            if result.returncode == 0 or not check:
                return True
            else:
                self.logger.error(f"Command failed: {command}")
                self.logger.error(f"Error: {result.stderr}")
                return False
        except Exception as e:
            self.logger.error(f"Exception running command: {e}")
            return False
    
    def cleanup_hosted_cluster(self) -> bool:
        """Clean up the HostedCluster resource"""
        self.logger.info(f"{Colors.YELLOW}▶{Colors.END} Cleaning up HostedCluster...")
        
        # Try to delete the HostedCluster
        success = self._run_command(f"kubectl delete hostedcluster {self.cluster_name} -n clusters --timeout=300s", check=False)
        
        # Clean up the namespace if it's empty
        self._run_command("kubectl delete namespace clusters --timeout=60s", check=False)
        
        return success
    
    def cleanup_worker_nodes(self) -> bool:
        """Clean up worker node instances"""
        self.logger.info(f"{Colors.YELLOW}▶{Colors.END} Cleaning up worker nodes...")
        
        # Get worker node name from config or use default
        worker_name = self.config.get('worker_node_name', f'hypershift-worker-1')
        
        # Delete worker instances
        success = self._run_command(
            f"gcloud compute instances delete {worker_name} --zone={self.zone} --quiet",
            check=False
        )
        
        # Clean up any additional worker nodes
        list_cmd = f"gcloud compute instances list --filter='name~hypershift-worker.*' --format='value(name)' --zones={self.zone}"
        if not self.dry_run:
            try:
                result = subprocess.run(list_cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0 and result.stdout.strip():
                    worker_instances = result.stdout.strip().split('\n')
                    for instance in worker_instances:
                        if instance.strip():
                            self._run_command(
                                f"gcloud compute instances delete {instance.strip()} --zone={self.zone} --quiet",
                                check=False
                            )
            except Exception as e:
                self.logger.warning(f"Could not list worker instances: {e}")
        
        return success
    
    def cleanup_gke_cluster(self) -> bool:
        """Clean up the GKE management cluster"""
        self.logger.info(f"{Colors.YELLOW}▶{Colors.END} Cleaning up GKE cluster...")
        
        # Get GKE cluster name from config or use default
        gke_cluster_name = self.config.get('gke_cluster_name', 'hypershift-standard')
        
        # Delete GKE cluster
        success = self._run_command(
            f"gcloud container clusters delete {gke_cluster_name} --zone={self.zone} --quiet",
            check=False
        )
        
        return success
    
    def cleanup_container_images(self) -> bool:
        """Clean up container images"""
        self.logger.info(f"{Colors.YELLOW}▶{Colors.END} Cleaning up container images...")
        
        # Delete webhook container images
        image_name = f"gcr.io/{self.project_id}/hypershift-gke-autopilot-webhook"
        success = self._run_command(
            f"gcloud container images delete {image_name} --quiet",
            check=False
        )
        
        return success
    
    def cleanup_local_files(self) -> bool:
        """Clean up local files and state"""
        self.logger.info(f"{Colors.YELLOW}▶{Colors.END} Cleaning up local files...")
        
        files_to_remove = [
            self.state_file,
            Path(f"work_{self.cluster_name}"),
            Path(f"hosted-cluster-{self.cluster_name}.yaml"),
            Path(f"worker-csr-{self.cluster_name}.yaml"),
            Path("/tmp/ssh-key"),
            Path("/tmp/ssh-key.pub"),
            Path("/tmp/worker-node.key"),
            Path("/tmp/worker-node.csr"),
            Path("/tmp/worker-node.crt"),
            Path("/tmp/worker-kubeconfig.yaml")
        ]
        
        for file_path in files_to_remove:
            if file_path.exists():
                if self.dry_run:
                    self.logger.info(f"{Colors.BLUE}[DRY RUN]{Colors.END} Would remove: {file_path}")
                else:
                    try:
                        if file_path.is_dir():
                            import shutil
                            shutil.rmtree(file_path)
                        else:
                            file_path.unlink()
                        self.logger.info(f"Removed: {file_path}")
                    except Exception as e:
                        self.logger.warning(f"Could not remove {file_path}: {e}")
        
        return True
    
    def cleanup_kubeconfig_files(self) -> bool:
        """Clean up kubeconfig files"""
        self.logger.info(f"{Colors.YELLOW}▶{Colors.END} Cleaning up kubeconfig files...")
        
        # Get kubeconfig paths from config or use defaults
        gke_kubeconfig = self.config.get('kubeconfig_gke_path', '/tmp/kubeconfig-gke')
        hosted_kubeconfig = self.config.get('kubeconfig_hosted_path', '/tmp/kubeconfig-hosted')
        
        for kubeconfig in [gke_kubeconfig, hosted_kubeconfig]:
            if Path(kubeconfig).exists():
                if self.dry_run:
                    self.logger.info(f"{Colors.BLUE}[DRY RUN]{Colors.END} Would remove: {kubeconfig}")
                else:
                    try:
                        Path(kubeconfig).unlink()
                        self.logger.info(f"Removed: {kubeconfig}")
                    except Exception as e:
                        self.logger.warning(f"Could not remove {kubeconfig}: {e}")
        
        return True
    
    def run_cleanup(self, skip_gke: bool = False, skip_workers: bool = False, 
                   local_only: bool = False) -> bool:
        """Run the complete cleanup process"""
        self.logger.info(f"{Colors.BOLD}{Colors.CYAN}Starting HyperShift Cleanup{Colors.END}")
        self.logger.info(f"Cluster: {Colors.YELLOW}{self.cluster_name}{Colors.END}")
        self.logger.info(f"Project: {Colors.YELLOW}{self.project_id}{Colors.END}")
        self.logger.info(f"Dry run: {Colors.YELLOW}{self.dry_run}{Colors.END}")
        
        if local_only:
            self.logger.info("Local files cleanup only")
            cleanup_steps = [
                self.cleanup_local_files,
                self.cleanup_kubeconfig_files
            ]
        else:
            cleanup_steps = [
                self.cleanup_hosted_cluster,
            ]
            
            if not skip_workers:
                cleanup_steps.append(self.cleanup_worker_nodes)
            
            if not skip_gke:
                cleanup_steps.append(self.cleanup_gke_cluster)
            
            cleanup_steps.extend([
                self.cleanup_container_images,
                self.cleanup_local_files,
                self.cleanup_kubeconfig_files
            ])
        
        success_count = 0
        total_steps = len(cleanup_steps)
        
        for step in cleanup_steps:
            try:
                if step():
                    success_count += 1
                    self.logger.info(f"{Colors.GREEN}✓{Colors.END} Completed: {step.__name__}")
                else:
                    self.logger.warning(f"{Colors.YELLOW}⚠{Colors.END} Partial success: {step.__name__}")
            except Exception as e:
                self.logger.error(f"{Colors.RED}✗{Colors.END} Failed: {step.__name__}: {e}")
        
        if success_count == total_steps:
            self.logger.info(f"{Colors.BOLD}{Colors.GREEN}✓ Cleanup completed successfully!{Colors.END}")
            return True
        else:
            self.logger.warning(f"{Colors.YELLOW}⚠ Cleanup completed with warnings ({success_count}/{total_steps} successful){Colors.END}")
            return False


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="HyperShift GKE Installation Cleanup Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full cleanup
  python3 cleanup.py --cluster-name my-cluster --project-id my-project --zone us-central1-a
  
  # Cleanup without deleting GKE cluster
  python3 cleanup.py --cluster-name my-cluster --project-id my-project --zone us-central1-a --skip-gke
  
  # Local files only
  python3 cleanup.py --cluster-name my-cluster --local-only
  
  # Dry run
  python3 cleanup.py --cluster-name my-cluster --project-id my-project --zone us-central1-a --dry-run
        """
    )
    
    parser.add_argument(
        "--cluster-name",
        required=True,
        help="Name of the hosted cluster to clean up"
    )
    
    parser.add_argument(
        "--project-id",
        help="GCP project ID (required unless --local-only)"
    )
    
    parser.add_argument(
        "--zone",
        help="GCP zone (required unless --local-only)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing"
    )
    
    parser.add_argument(
        "--skip-gke",
        action="store_true",
        help="Skip GKE cluster deletion"
    )
    
    parser.add_argument(
        "--skip-workers",
        action="store_true",
        help="Skip worker node deletion"
    )
    
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Only clean up local files and state"
    )
    
    return parser.parse_args()


def main():
    """Main entry point"""
    args = parse_arguments()
    
    # Validate required arguments
    if not args.local_only:
        if not args.project_id:
            print(f"{Colors.RED}Error: --project-id is required unless --local-only is specified{Colors.END}")
            sys.exit(1)
        if not args.zone:
            print(f"{Colors.RED}Error: --zone is required unless --local-only is specified{Colors.END}")
            sys.exit(1)
    
    try:
        cleanup = HyperShiftCleanup(
            cluster_name=args.cluster_name,
            project_id=args.project_id or "",
            zone=args.zone or "",
            dry_run=args.dry_run
        )
        
        success = cleanup.run_cleanup(
            skip_gke=args.skip_gke,
            skip_workers=args.skip_workers,
            local_only=args.local_only
        )
        
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Cleanup interrupted by user{Colors.END}")
        sys.exit(1)
    except Exception as e:
        print(f"{Colors.RED}Unexpected error: {e}{Colors.END}")
        sys.exit(1)


if __name__ == "__main__":
    main()