#!/usr/bin/env python3
"""
Step 12b: Apply CRDs
Applying all CRDs from crds/ directory to hosted cluster
"""

from pathlib import Path
from common import BaseStep, installation_step, Colors


class ApplyCrdsStep(BaseStep):
    """Step 12b: Apply all CRDs to hosted cluster"""

    @installation_step("apply_crds", "Applying CRDs to hosted cluster")
    def execute(self) -> bool:
        """Step 12b: Apply all CRDs from crds/ directory to hosted cluster"""
        # Use hosted cluster kubeconfig
        env_hosted = {'KUBECONFIG': self.config.kubeconfig_hosted_path}

        # Check if hosted cluster is accessible
        success, _ = self.runner.run("kubectl cluster-info", env=env_hosted)
        if not success:
            self.logger.error("Cannot access hosted cluster")
            return False

        # Find crds directory
        crds_dir = Path("crds")
        if not crds_dir.exists():
            self.logger.error(f"CRDs directory not found: {crds_dir}")
            return False

        # Find all CRD YAML files
        crd_files = list(crds_dir.glob("*.crd.yaml")) + list(crds_dir.glob("*.yaml"))

        if not crd_files:
            self.logger.warning("No CRD files found in crds/ directory")
            return True

        self.logger.info(f"Found {len(crd_files)} CRD files to apply")

        # Apply each CRD file
        failed_crds = []
        essential_crds = [
            "mco-machineconfigs.crd.yaml",
            "mco-machineconfigpools.crd.yaml",
            "mco-kubeletconfigs.crd.yaml"
        ]
        essential_failed = []

        for crd_file in sorted(crd_files):
            self.logger.info(f"Applying CRD: {crd_file.name}")
            success, _ = self.runner.run(f"kubectl apply -f {crd_file}", env=env_hosted)
            if not success:
                self.logger.warning(f"Failed to apply CRD: {crd_file.name}")
                failed_crds.append(crd_file.name)
                if crd_file.name in essential_crds:
                    essential_failed.append(crd_file.name)

        if essential_failed:
            self.logger.error(f"Failed to apply essential machine config CRDs: {', '.join(essential_failed)}")
            return False

        if failed_crds:
            self.logger.warning(f"Some CRDs failed to apply ({len(failed_crds)}): {', '.join(failed_crds)}")
            self.logger.info("Continuing since essential machine config CRDs were applied successfully")

        self.logger.info(f"{Colors.GREEN}✓{Colors.END} All CRDs applied successfully")
        return True