#!/usr/bin/env python3
"""
Step 10: Create Red Hat CoreOS Worker Node
Creating Red Hat CoreOS worker node
"""

import time
from dataclasses import asdict
from common import BaseStep, installation_step, Colors


class CreateWorkerNodeStep(BaseStep):
    """Step 10: Create Red Hat CoreOS Worker Node"""

    @installation_step("create_worker_node", "Creating Red Hat CoreOS worker node")
    def execute(self) -> bool:
        """Step 10: Create Red Hat CoreOS Worker Node"""
        # Check if worker node already exists
        success, _ = self.runner.run(
            f"gcloud compute instances describe {self.config.worker_node_name} --zone={self.config.zone}"
        )
        if success:
            self.logger.info(f"Worker node {self.config.worker_node_name} already exists")
        else:
            # Create worker node
            create_cmd = f"""
            gcloud compute instances create {self.config.worker_node_name} \
              --zone={self.config.zone} \
              --machine-type={self.config.worker_machine_type} \
              --image={self.config.rhcos_image_name} \
              --image-project={self.config.rhcos_image_project} \
              --boot-disk-size={self.config.worker_disk_size} \
              --boot-disk-type=pd-standard \
              --subnet=default \
              --tags=hypershift-worker
            """
            success, _ = self.runner.run(create_cmd, timeout=300)
            if not success:
                return False

        # Render worker setup script from template
        template_vars = asdict(self.config)
        setup_script_path = self.work_dir / "worker-setup.sh"

        success = self.templates.render_to_file("worker-setup.sh", template_vars, setup_script_path)
        if not success:
            return False

        # Wait for SSH to be ready on worker node
        self.logger.info(f"{Colors.YELLOW}⏳{Colors.END} Waiting for SSH to be ready on worker node...")
        max_ssh_wait = 300  # 5 minutes
        ssh_wait_time = 0
        ssh_ready = False

        while ssh_wait_time < max_ssh_wait:
            # Test SSH connectivity
            success, _ = self.runner.run(
                f'gcloud compute ssh {self.config.worker_node_name} --zone={self.config.zone} --command="echo SSH Ready" --ssh-flag="-o ConnectTimeout=10"'
            )
            if success:
                ssh_ready = True
                self.logger.info(f"{Colors.GREEN}✓{Colors.END} SSH is ready on worker node")
                break

            ssh_wait_time += 15
            if ssh_wait_time % 60 == 0:
                self.logger.info(f"  Still waiting for SSH... ({ssh_wait_time//60} minutes)")
            time.sleep(15)

        if not ssh_ready:
            self.logger.error(f"SSH failed to become ready within {max_ssh_wait//60} minutes")
            return False

        # Copy and execute setup script on worker node
        success, _ = self.runner.run(
            f"gcloud compute scp {setup_script_path} {self.config.worker_node_name}:/tmp/worker-setup.sh --zone={self.config.zone}"
        )
        if not success:
            return False

        # Execute setup script
        success, _ = self.runner.run(
            f'gcloud compute ssh {self.config.worker_node_name} --zone={self.config.zone} --command="chmod +x /tmp/worker-setup.sh && sudo /tmp/worker-setup.sh"',
            timeout=900
        )
        return success