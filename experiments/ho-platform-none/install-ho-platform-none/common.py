#!/usr/bin/env python3
"""
Common infrastructure classes and utilities for HyperShift GKE installation steps.
"""

import os
import sys
import json
import time
import subprocess
import logging
import base64
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class InstallConfig:
    """Configuration for HyperShift GKE installation"""
    # Required environment variables
    project_id: str
    region: str
    zone: str
    gke_cluster_name: str
    hosted_cluster_name: str
    hosted_cluster_domain: str
    pull_secret_path: str

    # Optional with defaults
    kubeconfig_gke_path: str = "/tmp/kubeconfig-gke"
    kubeconfig_hosted_path: str = "/tmp/kubeconfig-hosted"
    worker_node_name: str = "hypershift-worker-1"
    worker_machine_type: str = "e2-standard-4"
    worker_disk_size: str = "50GB"
    rhcos_image_name: str = "redhat-coreos-osd-418-x86-64-202508060022"
    rhcos_image_project: str = "redhat-marketplace-dev"
    infraid: str = ""

    # Runtime options
    dry_run: bool = False
    webhook_image_tag: str = "latest"
    podman_path: str = "podman"

    def __post_init__(self):
        """Generate default values after initialization"""
        if not self.infraid:
            self.infraid = f"{self.hosted_cluster_name}-a1b2c3d4"


class Colors:
    """Terminal color codes for output formatting"""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    END = '\033[0m'


class TemplateManager:
    """Manages loading and templating of configuration files"""

    def __init__(self, templates_dir: Path):
        self.templates_dir = templates_dir

    def load_template(self, template_name: str, variables: Dict[str, Any]) -> str:
        """Load and template a configuration file"""
        template_path = self.templates_dir / template_name

        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")

        with open(template_path, 'r') as f:
            template_content = f.read()

        # Simple variable substitution using string.Template-like syntax
        for key, value in variables.items():
            template_content = template_content.replace(f"${{{key}}}", str(value))

        return template_content

    def render_to_file(self, template_name: str, variables: Dict[str, Any], output_path: Path) -> bool:
        """Render template to a file"""
        try:
            rendered_content = self.load_template(template_name, variables)
            with open(output_path, 'w') as f:
                f.write(rendered_content)
            return True
        except Exception as e:
            logging.error(f"Failed to render template {template_name}: {e}")
            return False


class StepTracker:
    """Tracks completion status of installation steps"""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.completed_steps = set()
        self.step_metadata = {}
        self._load_state()

    def _load_state(self):
        """Load previous installation state if exists"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    self.completed_steps = set(state.get('completed_steps', []))
                    self.step_metadata = state.get('step_metadata', {})
                logging.info(f"✓ Loaded previous state: {len(self.completed_steps)} steps completed")
            except Exception as e:
                logging.warning(f"⚠ Could not load state file: {e}")

    def _save_state(self):
        """Save current installation state"""
        try:
            state = {
                'completed_steps': list(self.completed_steps),
                'step_metadata': self.step_metadata,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logging.warning(f"⚠ Could not save state: {e}")

    def is_step_completed(self, step_name: str) -> bool:
        """Check if a step has been completed"""
        return step_name in self.completed_steps

    def mark_step_completed(self, step_name: str, metadata: Dict[str, Any] = None):
        """Mark a step as completed"""
        self.completed_steps.add(step_name)
        if metadata:
            self.step_metadata[step_name] = metadata
        self._save_state()

    def get_step_metadata(self, step_name: str) -> Dict[str, Any]:
        """Get metadata for a completed step"""
        return self.step_metadata.get(step_name, {})


class CommandRunner:
    """Handles command execution with proper error handling and logging"""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.logger = logging.getLogger(__name__)

    def run(self, command: str, check_output: bool = False, timeout: int = 300,
            env: Dict[str, str] = None, cwd: str = None, show_progress: bool = False) -> Tuple[bool, str]:
        """Run shell command with error handling"""
        if self.dry_run:
            self.logger.info(f"{Colors.BLUE}[DRY RUN]{Colors.END} Would execute: {command}")
            return True, "dry-run-output"

        try:
            # Show command for long-running operations
            if timeout > 60 or show_progress:
                self.logger.info(f"{Colors.CYAN}◉{Colors.END} Executing: {command[:100]}{'...' if len(command) > 100 else ''}")
            else:
                self.logger.debug(f"Executing: {command}")

            # Prepare environment
            cmd_env = os.environ.copy()
            if env:
                cmd_env.update(env)

            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=cmd_env,
                cwd=cwd
            )

            if result.returncode == 0:
                if timeout > 60 or show_progress:
                    self.logger.info(f"{Colors.GREEN}✓{Colors.END} Command completed successfully")
                if check_output:
                    return True, result.stdout.strip()
                return True, ""
            else:
                self.logger.error(f"{Colors.RED}✗{Colors.END} Command failed: {command}")
                if result.stderr.strip():
                    self.logger.error(f"Error: {result.stderr.strip()}")
                if result.stdout.strip():
                    self.logger.error(f"Output: {result.stdout.strip()}")
                return False, result.stderr

        except subprocess.TimeoutExpired:
            self.logger.error(f"{Colors.RED}✗{Colors.END} Command timed out after {timeout}s: {command}")
            return False, "Command timed out"
        except Exception as e:
            self.logger.error(f"{Colors.RED}✗{Colors.END} Exception running command: {e}")
            return False, str(e)


def installation_step(step_name: str, description: str):
    """Decorator for installation steps with verification and resumability"""
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            if self.tracker.is_step_completed(step_name):
                self.logger.info(f"{Colors.GREEN}✓{Colors.END} Step already completed: {description}")
                return True

            self.logger.info(f"{Colors.BOLD}{Colors.YELLOW}▶{Colors.END} {description}")

            try:
                result = func(self, *args, **kwargs)
                if result:
                    metadata = kwargs.get('metadata', {})
                    self.tracker.mark_step_completed(step_name, metadata)
                    self.logger.info(f"{Colors.GREEN}✓{Colors.END} Completed: {description}")
                else:
                    self.logger.error(f"{Colors.RED}✗{Colors.END} Failed: {description}")
                return result
            except Exception as e:
                self.logger.error(f"{Colors.RED}✗{Colors.END} Exception in {description}: {e}")
                return False

        wrapper.step_name = step_name
        wrapper.description = description
        return wrapper
    return decorator


class BaseStep:
    """Base class for installation steps"""

    def __init__(self, config: InstallConfig, logger: logging.Logger,
                 runner: CommandRunner, templates: TemplateManager,
                 tracker: StepTracker, work_dir: Path):
        self.config = config
        self.logger = logger
        self.runner = runner
        self.templates = templates
        self.tracker = tracker
        self.work_dir = work_dir

        # Initialize resilient kubeconfig manager
        from kubeconfig_manager import KubeconfigManager
        self.kubeconfig_manager = KubeconfigManager(config, logger, runner)

    def _run_on_worker(self, command: str, description: str = None, check_output: bool = False, timeout: int = 300) -> Tuple[bool, str]:
        """Helper method to run commands on worker node via SSH"""
        full_command = f'gcloud compute ssh {self.config.worker_node_name} --zone={self.config.zone} --command="{command}"'
        if description:
            self.logger.debug(f"Worker: {description}")
        return self.runner.run(full_command, check_output=check_output, timeout=timeout)

    def _upload_and_execute_script(self, script_content: str, remote_path: str, description: str, timeout: int = 600) -> bool:
        """Upload a script to worker node and execute it"""
        local_script = self.work_dir / f"temp_{remote_path.split('/')[-1]}"

        # Write script locally
        with open(local_script, 'w') as f:
            f.write(script_content)

        # Upload script
        upload_success, _ = self.runner.run(
            f'gcloud compute scp {local_script} {self.config.worker_node_name}:{remote_path} --zone={self.config.zone}'
        )
        if not upload_success:
            self.logger.error(f"Failed to upload script: {description}")
            return False

        # Execute script
        self.logger.info(f"Executing: {description}")
        success, _ = self._run_on_worker(f'chmod +x {remote_path} && sudo {remote_path}', description, timeout=timeout)

        # Cleanup local script
        local_script.unlink(missing_ok=True)

        return success