#!/usr/bin/env python3
"""
Step 1: Environment Setup
Setting up environment variables and gcloud configuration
"""

import os
from common import BaseStep, installation_step, Colors


class SetupEnvironmentStep(BaseStep):
    """Step 1: Environment Setup"""

    @installation_step("setup_environment", "Setting up environment variables and gcloud configuration")
    def execute(self) -> bool:
        """Step 1: Environment Setup"""
        # Set gcloud project
        success, _ = self.runner.run(f"gcloud config set project {self.config.project_id}")
        if not success:
            return False

        # Verify project is set correctly
        success, current_project = self.runner.run("gcloud config get-value project", check_output=True)
        if not success or current_project != self.config.project_id:
            self.logger.error(f"Failed to set gcloud project to {self.config.project_id}")
            return False

        # Export environment variables for kubectl
        os.environ['KUBECONFIG'] = self.config.kubeconfig_gke_path

        return True