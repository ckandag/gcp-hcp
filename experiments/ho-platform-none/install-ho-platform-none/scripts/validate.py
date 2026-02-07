#!/usr/bin/env python3
"""
HyperShift GKE Installation Validation Script

Validates environment and prerequisites before running the installer.
"""

import os
import sys
import subprocess
import json
from pathlib import Path
from typing import List, Tuple


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


class PrerequisiteValidator:
    """Validates prerequisites for HyperShift installation"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = []
    
    def _run_command(self, command: str) -> Tuple[bool, str]:
        """Run a command and return success status and output"""
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            return result.returncode == 0, result.stdout.strip()
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)
    
    def check_required_tools(self) -> bool:
        """Check if required command-line tools are available"""
        print(f"{Colors.BOLD}Checking Required Tools{Colors.END}")
        
        required_tools = {
            'gcloud': 'Google Cloud CLI',
            'kubectl': 'Kubernetes CLI',
            'helm': 'Helm package manager',
            'git': 'Git version control',
            'ssh-keygen': 'SSH key generation',
            'openssl': 'OpenSSL cryptography',
            'python3': 'Python 3.7+',
            '/opt/podman/bin/podman': 'Podman container tool (for webhook)'
        }
        
        all_present = True
        
        for tool, description in required_tools.items():
            success, output = self._run_command(f"which {tool}")
            if success:
                print(f"  {Colors.GREEN}✓{Colors.END} {tool} - {description}")
                if tool == 'python3':
                    # Check Python version
                    success, version = self._run_command("python3 --version")
                    if success:
                        print(f"    Version: {version}")
                    
                elif tool == 'gcloud':
                    # Check gcloud version
                    success, version = self._run_command("gcloud version --format='value(Google Cloud SDK)'")
                    if success:
                        print(f"    Version: {version}")
            else:
                print(f"  {Colors.RED}✗{Colors.END} {tool} - {description} (missing)")
                if tool == '/opt/podman/bin/podman':
                    self.warnings.append(f"Podman not found - webhook deployment will be skipped")
                else:
                    self.errors.append(f"Required tool missing: {tool}")
                    all_present = False
        
        return all_present
    
    def check_gcloud_authentication(self) -> bool:
        """Check if gcloud is authenticated"""
        print(f"\n{Colors.BOLD}Checking GCloud Authentication{Colors.END}")
        
        success, output = self._run_command("gcloud auth list --filter=status:ACTIVE --format='value(account)'")
        if success and output.strip():
            print(f"  {Colors.GREEN}✓{Colors.END} Authenticated as: {output}")
            
            # Check current project
            success, project = self._run_command("gcloud config get-value project")
            if success and project:
                print(f"  {Colors.GREEN}✓{Colors.END} Current project: {project}")
            else:
                print(f"  {Colors.YELLOW}⚠{Colors.END} No default project set")
                self.warnings.append("No default gcloud project set - ensure PROJECT_ID is set")
            
            return True
        else:
            print(f"  {Colors.RED}✗{Colors.END} Not authenticated")
            self.errors.append("gcloud not authenticated - run 'gcloud auth login'")
            return False
    
    def check_environment_variables(self) -> bool:
        """Check if required environment variables are set"""
        print(f"\n{Colors.BOLD}Checking Environment Variables{Colors.END}")
        
        required_vars = {
            'PROJECT_ID': 'GCP project ID',
            'GKE_CLUSTER_NAME': 'GKE cluster name',
            'HOSTED_CLUSTER_NAME': 'Hosted cluster name',
            'HOSTED_CLUSTER_DOMAIN': 'Hosted cluster domain',
            'PULL_SECRET_PATH': 'Red Hat pull secret path'
        }
        
        optional_vars = {
            'REGION': 'GCP region (default: us-central1)',
            'ZONE': 'GCP zone (default: {region}-a)',
            'WORKER_NODE_NAME': 'Worker node name (default: hypershift-worker-1)',
            'WORKER_MACHINE_TYPE': 'Worker machine type (default: e2-standard-4)'
        }
        
        all_set = True
        
        # Check required variables
        for var, description in required_vars.items():
            value = os.getenv(var)
            if value:
                print(f"  {Colors.GREEN}✓{Colors.END} {var} = {value}")
            else:
                print(f"  {Colors.RED}✗{Colors.END} {var} - {description} (not set)")
                self.errors.append(f"Required environment variable not set: {var}")
                all_set = False
        
        # Check optional variables
        print(f"\n  {Colors.BOLD}Optional Variables:{Colors.END}")
        for var, description in optional_vars.items():
            value = os.getenv(var)
            if value:
                print(f"  {Colors.GREEN}✓{Colors.END} {var} = {value}")
            else:
                print(f"  {Colors.CYAN}○{Colors.END} {var} - {description} (using default)")
        
        return all_set
    
    def check_pull_secret(self) -> bool:
        """Check if pull secret file exists and is valid"""
        print(f"\n{Colors.BOLD}Checking Pull Secret{Colors.END}")
        
        pull_secret_path = os.getenv('PULL_SECRET_PATH')
        if not pull_secret_path:
            print(f"  {Colors.RED}✗{Colors.END} PULL_SECRET_PATH not set")
            return False
        
        secret_file = Path(pull_secret_path)
        if not secret_file.exists():
            print(f"  {Colors.RED}✗{Colors.END} Pull secret file not found: {pull_secret_path}")
            self.errors.append(f"Pull secret file not found: {pull_secret_path}")
            return False
        
        # Try to validate JSON format
        try:
            with open(secret_file, 'r') as f:
                secret_data = json.load(f)
                if 'auths' in secret_data:
                    print(f"  {Colors.GREEN}✓{Colors.END} Pull secret file valid: {pull_secret_path}")
                    
                    # Check for Red Hat registry
                    redhat_registries = {
                        "quay.io",
                        "registry.redhat.io",
                        "registry.connect.redhat.com",
                        "cloud.openshift.com",
                    }
                    if any(auth in redhat_registries for auth in secret_data['auths']):
                        print(f"  {Colors.GREEN}✓{Colors.END} Contains Red Hat registry credentials")
                    else:
                        print(f"  {Colors.YELLOW}⚠{Colors.END} May not contain Red Hat registry credentials")
                        self.warnings.append("Pull secret may not contain Red Hat registry credentials")
                    
                    return True
                else:
                    print(f"  {Colors.RED}✗{Colors.END} Pull secret invalid format (missing 'auths')")
                    self.errors.append("Pull secret invalid format")
                    return False
        except json.JSONDecodeError:
            print(f"  {Colors.RED}✗{Colors.END} Pull secret is not valid JSON")
            self.errors.append("Pull secret is not valid JSON")
            return False
        except Exception as e:
            print(f"  {Colors.RED}✗{Colors.END} Error reading pull secret: {e}")
            self.errors.append(f"Error reading pull secret: {e}")
            return False
    
    def check_gcp_quotas(self) -> bool:
        """Check GCP quotas (basic check)"""
        print(f"\n{Colors.BOLD}Checking GCP Quotas{Colors.END}")
        
        project_id = os.getenv('PROJECT_ID')
        region = os.getenv('REGION', 'us-central1')
        
        if not project_id:
            print(f"  {Colors.YELLOW}⚠{Colors.END} Cannot check quotas - PROJECT_ID not set")
            return True
        
        # Check if we can list quotas (requires project access)
        success, output = self._run_command(f"gcloud compute project-info describe --project={project_id} --format='value(quotas[].limit)' --filter='quotas.metric=INSTANCES'")
        if success:
            print(f"  {Colors.GREEN}✓{Colors.END} Can access project quotas")
            
            # Basic quota warnings
            self.info.append("Ensure sufficient quotas for:")
            self.info.append("  - Compute instances (need ~5)")
            self.info.append("  - CPUs (need ~20)")
            self.info.append("  - Load balancers (need ~2)")
            self.info.append("  - Persistent disks (need ~200GB)")
            
        else:
            print(f"  {Colors.YELLOW}⚠{Colors.END} Cannot check quotas - ensure sufficient GCP quotas")
            self.warnings.append("Could not verify GCP quotas - ensure sufficient quotas are available")
        
        return True
    
    def check_network_connectivity(self) -> bool:
        """Check network connectivity to required services"""
        print(f"\n{Colors.BOLD}Checking Network Connectivity{Colors.END}")
        
        endpoints = {
            'github.com': 'GitHub (for HyperShift source)',
            'quay.io': 'Quay.io (for OpenShift images)',
            'gcr.io': 'Google Container Registry',
            'console.redhat.com': 'Red Hat Console'
        }
        
        all_reachable = True
        
        for endpoint, description in endpoints.items():
            success, _ = self._run_command(f"curl -s --connect-timeout 5 https://{endpoint} >/dev/null")
            if success:
                print(f"  {Colors.GREEN}✓{Colors.END} {endpoint} - {description}")
            else:
                print(f"  {Colors.YELLOW}⚠{Colors.END} {endpoint} - {description} (unreachable)")
                self.warnings.append(f"Cannot reach {endpoint} - may affect installation")
        
        return all_reachable
    
    def check_disk_space(self) -> bool:
        """Check available disk space"""
        print(f"\n{Colors.BOLD}Checking Disk Space{Colors.END}")
        
        # Check current directory space
        success, output = self._run_command("df -h . | awk 'NR==2 {print $4}'")
        if success:
            print(f"  {Colors.GREEN}✓{Colors.END} Available space: {output}")
            
            # Parse space (rough check)
            if 'G' in output:
                try:
                    space_gb = float(output.replace('G', ''))
                    if space_gb < 5:
                        self.warnings.append(f"Low disk space: {output} (recommend 5GB+)")
                except:
                    pass
        else:
            print(f"  {Colors.YELLOW}⚠{Colors.END} Could not check disk space")
        
        return True
    
    def run_validation(self) -> bool:
        """Run all validation checks"""
        print(f"{Colors.BOLD}{Colors.CYAN}HyperShift GKE Installation Validation{Colors.END}\n")
        
        checks = [
            self.check_required_tools,
            self.check_gcloud_authentication,
            self.check_environment_variables,
            self.check_pull_secret,
            self.check_gcp_quotas,
            self.check_network_connectivity,
            self.check_disk_space
        ]
        
        all_passed = True
        for check in checks:
            try:
                if not check():
                    all_passed = False
            except Exception as e:
                print(f"  {Colors.RED}✗{Colors.END} Check failed: {e}")
                self.errors.append(f"Validation check failed: {check.__name__}")
                all_passed = False
        
        # Print summary
        print(f"\n{Colors.BOLD}Validation Summary{Colors.END}")
        
        if self.errors:
            print(f"\n{Colors.RED}Errors ({len(self.errors)}):{Colors.END}")
            for error in self.errors:
                print(f"  ✗ {error}")
        
        if self.warnings:
            print(f"\n{Colors.YELLOW}Warnings ({len(self.warnings)}):{Colors.END}")
            for warning in self.warnings:
                print(f"  ⚠ {warning}")
        
        if self.info:
            print(f"\n{Colors.CYAN}Information:{Colors.END}")
            for info in self.info:
                print(f"  ○ {info}")
        
        if all_passed and not self.errors:
            print(f"\n{Colors.BOLD}{Colors.GREEN}✓ All validations passed! Ready to install.{Colors.END}")
        elif not self.errors:
            print(f"\n{Colors.BOLD}{Colors.YELLOW}⚠ Validation passed with warnings. Installation may proceed.{Colors.END}")
        else:
            print(f"\n{Colors.BOLD}{Colors.RED}✗ Validation failed. Please fix errors before installation.{Colors.END}")
        
        return all_passed and not self.errors


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Validate environment for HyperShift GKE installation"
    )
    parser.add_argument(
        "--env-file",
        help="Load environment variables from file before validation"
    )
    
    args = parser.parse_args()
    
    # Load environment file if specified
    if args.env_file:
        env_file = Path(args.env_file)
        if env_file.exists():
            print(f"Loading environment from: {env_file}")
            # Simple sourcing of environment file
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and line.startswith('export '):
                        var_assignment = line.replace('export ', '', 1)
                        if '=' in var_assignment:
                            key, value = var_assignment.split('=', 1)
                            # Remove quotes if present
                            value = value.strip('"\'')
                            os.environ[key] = value
        else:
            print(f"{Colors.RED}Error: Environment file not found: {env_file}{Colors.END}")
            sys.exit(1)
    
    try:
        validator = PrerequisiteValidator()
        success = validator.run_validation()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Validation interrupted by user{Colors.END}")
        sys.exit(1)
    except Exception as e:
        print(f"{Colors.RED}Unexpected error: {e}{Colors.END}")
        sys.exit(1)


if __name__ == "__main__":
    main()