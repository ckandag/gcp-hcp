#!/usr/bin/env python3
"""
Resilient Kubeconfig Manager

Provides robust kubeconfig creation, validation, and recovery mechanisms
for the HyperShift installer.
"""

import os
import time
import json
import base64
import tempfile
import hashlib
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
import yaml

from common import Colors

@dataclass
class KubeconfigInfo:
    """Information about a kubeconfig file"""
    path: str
    cluster_name: str
    cluster_type: str  # 'gke' or 'hosted'
    created_at: float
    checksum: str
    backup_path: Optional[str] = None


class KubeconfigManager:
    """Resilient kubeconfig manager with retry, validation, and backup capabilities"""

    def __init__(self, config, logger, runner):
        self.config = config
        self.logger = logger
        self.runner = runner
        self.max_retries = 3
        self.retry_delay = 5
        self.kubeconfig_info: Dict[str, KubeconfigInfo] = {}

    def create_gke_kubeconfig(self, force_recreate: bool = False) -> bool:
        """
        Create and validate GKE management cluster kubeconfig with resilience features

        Args:
            force_recreate: Force recreation even if valid kubeconfig exists

        Returns:
            bool: True if successful, False otherwise
        """
        self.logger.info(f"{Colors.CYAN}🔧{Colors.END} Creating resilient GKE kubeconfig...")

        kubeconfig_path = self.config.kubeconfig_gke_path

        # Check if valid kubeconfig already exists
        if not force_recreate and self._is_kubeconfig_valid(kubeconfig_path, 'gke'):
            self.logger.info(f"{Colors.GREEN}✓{Colors.END} Valid GKE kubeconfig already exists")
            return True

        # Ensure directory exists
        if not self._ensure_directory_exists(kubeconfig_path):
            return False

        # Create backup if existing file exists
        if Path(kubeconfig_path).exists():
            backup_path = self._create_backup(kubeconfig_path)
            self.logger.info(f"📦 Backed up existing kubeconfig to {backup_path}")

        # Attempt to create kubeconfig with retry logic
        for attempt in range(1, self.max_retries + 1):
            try:
                self.logger.info(f"📡 Attempt {attempt}/{self.max_retries}: Getting GKE credentials...")

                # Get credentials and save to specific path
                success, output = self.runner.run(
                    f"gcloud container clusters get-credentials {self.config.gke_cluster_name} "
                    f"--zone={self.config.zone} --project={self.config.project_id}",
                    env={'KUBECONFIG': kubeconfig_path},
                    timeout=120
                )

                if not success:
                    self.logger.warning(f"⚠️ Attempt {attempt} failed: {output}")
                    if attempt < self.max_retries:
                        self.logger.info(f"🔄 Retrying in {self.retry_delay} seconds...")
                        time.sleep(self.retry_delay)
                        continue
                    else:
                        self.logger.error("❌ All retry attempts failed")
                        return self._attempt_recovery(kubeconfig_path, 'gke')

                # Validate the created kubeconfig
                if self._validate_kubeconfig_file(kubeconfig_path, 'gke'):
                    # Set proper permissions
                    self._set_secure_permissions(kubeconfig_path)

                    # Store kubeconfig info
                    checksum = self._calculate_file_checksum(kubeconfig_path)
                    self.kubeconfig_info[kubeconfig_path] = KubeconfigInfo(
                        path=kubeconfig_path,
                        cluster_name=self.config.gke_cluster_name,
                        cluster_type='gke',
                        created_at=time.time(),
                        checksum=checksum
                    )

                    self.logger.info(f"{Colors.GREEN}✓{Colors.END} GKE kubeconfig created and validated successfully")
                    return True
                else:
                    self.logger.warning(f"⚠️ Kubeconfig validation failed on attempt {attempt}")
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay)
                        continue

            except Exception as e:
                self.logger.error(f"❌ Exception during attempt {attempt}: {e}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                    continue

        return self._attempt_recovery(kubeconfig_path, 'gke')

    def create_hosted_kubeconfig(self, force_recreate: bool = False) -> bool:
        """
        Create and validate hosted cluster kubeconfig with resilience features

        Args:
            force_recreate: Force recreation even if valid kubeconfig exists

        Returns:
            bool: True if successful, False otherwise
        """
        self.logger.info(f"{Colors.CYAN}🔧{Colors.END} Creating resilient hosted cluster kubeconfig...")

        kubeconfig_path = self.config.kubeconfig_hosted_path

        # Check if valid kubeconfig already exists
        if not force_recreate and self._is_kubeconfig_valid(kubeconfig_path, 'hosted'):
            self.logger.info(f"{Colors.GREEN}✓{Colors.END} Valid hosted kubeconfig already exists")
            return True

        # Ensure directory exists
        if not self._ensure_directory_exists(kubeconfig_path):
            return False

        # Create backup if existing file exists
        if Path(kubeconfig_path).exists():
            backup_path = self._create_backup(kubeconfig_path)
            self.logger.info(f"📦 Backed up existing kubeconfig to {backup_path}")

        # Use GKE kubeconfig environment for extraction
        env_gke = {'KUBECONFIG': self.config.kubeconfig_gke_path}

        # Attempt to extract hosted kubeconfig with retry logic
        for attempt in range(1, self.max_retries + 1):
            try:
                self.logger.info(f"📡 Attempt {attempt}/{self.max_retries}: Extracting hosted cluster credentials...")

                # Get hosted cluster kubeconfig secret
                success, kubeconfig_b64 = self.runner.run(
                    f"kubectl get secret admin-kubeconfig -n clusters-{self.config.hosted_cluster_name} "
                    f"-o jsonpath='{{.data.kubeconfig}}'",
                    check_output=True,
                    env=env_gke,
                    timeout=60
                )

                if not success or not kubeconfig_b64.strip():
                    self.logger.warning(f"⚠️ Attempt {attempt} failed: Could not retrieve secret")
                    if attempt < self.max_retries:
                        self.logger.info(f"🔄 Retrying in {self.retry_delay} seconds...")
                        time.sleep(self.retry_delay)
                        continue
                    else:
                        self.logger.error("❌ All retry attempts failed")
                        return self._attempt_recovery(kubeconfig_path, 'hosted')

                # Decode and validate kubeconfig content
                try:
                    kubeconfig_data = base64.b64decode(kubeconfig_b64).decode('utf-8')

                    # Validate that it's valid YAML/JSON
                    config_obj = yaml.safe_load(kubeconfig_data)
                    if not isinstance(config_obj, dict) or 'clusters' not in config_obj:
                        raise ValueError("Invalid kubeconfig structure")

                except Exception as e:
                    self.logger.warning(f"⚠️ Attempt {attempt} failed: Invalid kubeconfig data: {e}")
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay)
                        continue
                    else:
                        return self._attempt_recovery(kubeconfig_path, 'hosted')

                # Save kubeconfig securely
                if not self.config.dry_run:
                    # Write to temporary file first
                    temp_path = f"{kubeconfig_path}.tmp"
                    try:
                        with open(temp_path, 'w', encoding='utf-8') as f:
                            f.write(kubeconfig_data)

                        # Set permissions before moving
                        os.chmod(temp_path, 0o600)

                        # Atomic move
                        os.rename(temp_path, kubeconfig_path)

                    except Exception as e:
                        self.logger.error(f"❌ Failed to write kubeconfig: {e}")
                        if Path(temp_path).exists():
                            os.unlink(temp_path)
                        continue

                # Validate the created kubeconfig
                if self._validate_kubeconfig_file(kubeconfig_path, 'hosted'):
                    # Store kubeconfig info
                    checksum = self._calculate_file_checksum(kubeconfig_path)
                    self.kubeconfig_info[kubeconfig_path] = KubeconfigInfo(
                        path=kubeconfig_path,
                        cluster_name=self.config.hosted_cluster_name,
                        cluster_type='hosted',
                        created_at=time.time(),
                        checksum=checksum
                    )

                    self.logger.info(f"{Colors.GREEN}✓{Colors.END} Hosted kubeconfig created and validated successfully")
                    return True
                else:
                    self.logger.warning(f"⚠️ Kubeconfig validation failed on attempt {attempt}")
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay)
                        continue

            except Exception as e:
                self.logger.error(f"❌ Exception during attempt {attempt}: {e}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                    continue

        return self._attempt_recovery(kubeconfig_path, 'hosted')

    def validate_all_kubeconfigs(self) -> bool:
        """
        Validate all kubeconfig files are present and functional

        Returns:
            bool: True if all kubeconfigs are valid, False otherwise
        """
        self.logger.info(f"{Colors.CYAN}🔍{Colors.END} Validating all kubeconfig files...")

        gke_valid = self._is_kubeconfig_valid(self.config.kubeconfig_gke_path, 'gke')
        hosted_valid = self._is_kubeconfig_valid(self.config.kubeconfig_hosted_path, 'hosted')

        if gke_valid and hosted_valid:
            self.logger.info(f"{Colors.GREEN}✓{Colors.END} All kubeconfig files are valid")
            return True

        if not gke_valid:
            self.logger.error(f"❌ GKE kubeconfig invalid: {self.config.kubeconfig_gke_path}")
        if not hosted_valid:
            self.logger.error(f"❌ Hosted kubeconfig invalid: {self.config.kubeconfig_hosted_path}")

        return False

    def refresh_kubeconfigs(self) -> bool:
        """
        Refresh both kubeconfig files to ensure fresh tokens

        Returns:
            bool: True if successful, False otherwise
        """
        self.logger.info(f"{Colors.CYAN}🔄{Colors.END} Refreshing all kubeconfig files...")

        gke_success = self.create_gke_kubeconfig(force_recreate=True)
        if not gke_success:
            self.logger.error("❌ Failed to refresh GKE kubeconfig")
            return False

        hosted_success = self.create_hosted_kubeconfig(force_recreate=True)
        if not hosted_success:
            self.logger.error("❌ Failed to refresh hosted kubeconfig")
            return False

        self.logger.info(f"{Colors.GREEN}✓{Colors.END} All kubeconfig files refreshed successfully")
        return True

    def _is_kubeconfig_valid(self, path: str, cluster_type: str) -> bool:
        """
        Check if kubeconfig file exists and is functional

        Args:
            path: Path to kubeconfig file
            cluster_type: Type of cluster ('gke' or 'hosted')

        Returns:
            bool: True if valid and functional, False otherwise
        """
        if not Path(path).exists():
            return False

        # Check file permissions
        try:
            stat_info = os.stat(path)
            if stat_info.st_mode & 0o077:
                self.logger.warning(f"⚠️ Kubeconfig {path} has overly permissive permissions")
        except Exception:
            pass

        # Validate file structure
        if not self._validate_kubeconfig_file(path, cluster_type):
            return False

        # Test connectivity
        return self._test_kubeconfig_connectivity(path, cluster_type)

    def _validate_kubeconfig_file(self, path: str, cluster_type: str) -> bool:
        """
        Validate kubeconfig file structure and content

        Args:
            path: Path to kubeconfig file
            cluster_type: Type of cluster ('gke' or 'hosted')

        Returns:
            bool: True if valid structure, False otherwise
        """
        try:
            with open(path, 'r') as f:
                config_data = yaml.safe_load(f)

            if not isinstance(config_data, dict):
                self.logger.warning(f"⚠️ Kubeconfig {path} is not a valid YAML object")
                return False

            required_keys = ['clusters', 'contexts', 'users']
            for key in required_keys:
                if key not in config_data:
                    self.logger.warning(f"⚠️ Kubeconfig {path} missing required key: {key}")
                    return False

            # Check that we have at least one cluster, context, and user
            if not all(isinstance(config_data[key], list) and len(config_data[key]) > 0
                      for key in required_keys):
                self.logger.warning(f"⚠️ Kubeconfig {path} has empty required sections")
                return False

            return True

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to validate kubeconfig {path}: {e}")
            return False

    def _test_kubeconfig_connectivity(self, path: str, cluster_type: str) -> bool:
        """
        Test connectivity using the kubeconfig

        Args:
            path: Path to kubeconfig file
            cluster_type: Type of cluster ('gke' or 'hosted')

        Returns:
            bool: True if connectivity works, False otherwise
        """
        env = {'KUBECONFIG': path}

        # Try a simple kubectl command
        success, _ = self.runner.run(
            "kubectl cluster-info --request-timeout=10s",
            env=env,
            timeout=15
        )

        if not success:
            self.logger.warning(f"⚠️ Kubeconfig {path} failed connectivity test")
            return False

        return True

    def _ensure_directory_exists(self, file_path: str) -> bool:
        """
        Ensure the directory for the kubeconfig file exists

        Args:
            file_path: Full path to the kubeconfig file

        Returns:
            bool: True if directory exists or was created, False otherwise
        """
        try:
            directory = Path(file_path).parent
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to create directory for {file_path}: {e}")
            return False

    def _set_secure_permissions(self, path: str) -> bool:
        """
        Set secure permissions on kubeconfig file (600)

        Args:
            path: Path to kubeconfig file

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            os.chmod(path, 0o600)
            return True
        except Exception as e:
            self.logger.warning(f"⚠️ Failed to set secure permissions on {path}: {e}")
            return False

    def _create_backup(self, path: str) -> Optional[str]:
        """
        Create a backup of existing kubeconfig file

        Args:
            path: Path to original kubeconfig file

        Returns:
            str: Path to backup file, or None if failed
        """
        try:
            timestamp = int(time.time())
            backup_path = f"{path}.backup.{timestamp}"

            # Copy file
            with open(path, 'rb') as src, open(backup_path, 'wb') as dst:
                dst.write(src.read())

            # Set same permissions
            original_stat = os.stat(path)
            os.chmod(backup_path, original_stat.st_mode)

            return backup_path

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to create backup of {path}: {e}")
            return None

    def _calculate_file_checksum(self, path: str) -> str:
        """
        Calculate SHA256 checksum of kubeconfig file

        Args:
            path: Path to kubeconfig file

        Returns:
            str: SHA256 checksum
        """
        try:
            with open(path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return ""

    def _attempt_recovery(self, path: str, cluster_type: str) -> bool:
        """
        Attempt to recover from kubeconfig creation failure

        Args:
            path: Path to kubeconfig file
            cluster_type: Type of cluster ('gke' or 'hosted')

        Returns:
            bool: True if recovery successful, False otherwise
        """
        self.logger.warning(f"🔄 Attempting recovery for {cluster_type} kubeconfig...")

        # Look for backup files
        backup_files = list(Path(path).parent.glob(f"{Path(path).name}.backup.*"))
        backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        for backup_file in backup_files:
            self.logger.info(f"📦 Trying backup: {backup_file}")
            if self._is_kubeconfig_valid(str(backup_file), cluster_type):
                try:
                    # Restore from backup
                    os.rename(str(backup_file), path)
                    self.logger.info(f"{Colors.GREEN}✓{Colors.END} Recovered from backup: {backup_file}")
                    return True
                except Exception as e:
                    self.logger.warning(f"⚠️ Failed to restore from backup {backup_file}: {e}")
                    continue

        self.logger.error(f"❌ Recovery failed for {cluster_type} kubeconfig")
        return False