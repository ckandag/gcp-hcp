#!/bin/bash

# GCP Private Service Connect Demo - Step 3: Deploy Test VMs
# This script creates VMs in both VPCs for testing

set -e

# Variables
PROJECT_ID=${PROJECT_ID:-"your-project-id"}
REGION=${REGION:-"us-central1"}
ZONE=${ZONE:-"us-central1-a"}

# VPC Configuration
PROVIDER_VPC="hypershift-redhat"
PROVIDER_SUBNET="hypershift-redhat-subnet"
CONSUMER_VPC="hypershift-customer"
CONSUMER_SUBNET="hypershift-customer-subnet"

# VM Configuration
PROVIDER_VM="redhat-service-vm"
CONSUMER_VM="customer-client-vm"
MACHINE_TYPE="e2-micro"
IMAGE_FAMILY="ubuntu-2404-lts-amd64"
IMAGE_PROJECT="ubuntu-os-cloud"

echo "Deploying test VMs in both VPCs..."

# Set the project
gcloud config set project $PROJECT_ID

# Create cloud-init user-data for the service provider VM
cat > service-cloud-init.yaml << 'EOF'
#cloud-config
package_update: true
packages:
  - nginx
  - python3

write_files:
  - path: /var/www/html/index.html
    content: |
      <!DOCTYPE html>
      <html>
      <head>
          <title>Private Service Connect Demo</title>
      </head>
      <body>
          <h1>Hello from hypershift-redhat!</h1>
          <p>This service is running in the provider VPC and accessible via Private Service Connect.</p>
          <p>Server: $(hostname)</p>
          <p>Time: $(date)</p>
      </body>
      </html>
    owner: root:root
    permissions: '0644'

  - path: /home/demo-api.py
    content: |
      #!/usr/bin/env python3
      import http.server
      import socketserver
      import json
      import socket
      import datetime

      class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
          def do_GET(self):
              if self.path == '/':
                  self.send_response(200)
                  self.send_header('Content-type', 'application/json')
                  self.end_headers()
                  response = {
                      "message": "Hello from hypershift-redhat Private Service Connect Demo!",
                      "hostname": socket.gethostname(),
                      "timestamp": datetime.datetime.now().isoformat()
                  }
                  self.wfile.write(json.dumps(response).encode())
              elif self.path == '/health':
                  self.send_response(200)
                  self.send_header('Content-type', 'application/json')
                  self.end_headers()
                  response = {"status": "healthy"}
                  self.wfile.write(json.dumps(response).encode())
              else:
                  self.send_response(404)
                  self.end_headers()

      if __name__ == "__main__":
          PORT = 8080
          with socketserver.TCPServer(("0.0.0.0", PORT), MyHTTPRequestHandler) as httpd:
              print(f"Starting server on 0.0.0.0:{PORT}")
              httpd.serve_forever()
    owner: root:root
    permissions: '0755'

  - path: /etc/systemd/system/demo-api.service
    content: |
      [Unit]
      Description=Demo API Service
      After=network.target

      [Service]
      Type=simple
      User=root
      WorkingDirectory=/home
      ExecStart=/usr/bin/python3 /home/demo-api.py
      Restart=always
      RestartSec=5
      StandardOutput=journal
      StandardError=journal
      SyslogIdentifier=demo-api

      [Install]
      WantedBy=multi-user.target
    owner: root:root
    permissions: '0644'

runcmd:
  - systemctl enable nginx
  - systemctl start nginx
  - systemctl enable demo-api
  - systemctl start demo-api
  - echo "Service VM setup completed" > /var/log/startup-complete.log

power_state:
  mode: reboot
  condition: true
EOF

# Create cloud-init user-data for the consumer VM
cat > client-cloud-init.yaml << 'EOF'
#cloud-config
package_update: true
packages:
  - curl
  - wget
  - netcat-openbsd
  - dnsutils
  - iputils-ping
  - traceroute

runcmd:
  - echo "Client VM setup completed" > /var/log/startup-complete.log
EOF

# Deploy the service provider VM
echo "Creating service provider VM: $PROVIDER_VM"
if ! gcloud compute instances describe $PROVIDER_VM --zone=$ZONE >/dev/null 2>&1; then
    gcloud compute instances create $PROVIDER_VM \
        --zone=$ZONE \
        --machine-type=$MACHINE_TYPE \
        --network-interface=subnet=$PROVIDER_SUBNET,no-address \
        --image-family=$IMAGE_FAMILY \
        --image-project=$IMAGE_PROJECT \
        --metadata-from-file=user-data=service-cloud-init.yaml \
        --tags=service-vm
    echo "Service provider VM $PROVIDER_VM created"
else
    echo "Service provider VM $PROVIDER_VM already exists, skipping"
fi

# Deploy the consumer VM
echo "Creating consumer VM: $CONSUMER_VM"
if ! gcloud compute instances describe $CONSUMER_VM --zone=$ZONE >/dev/null 2>&1; then
    gcloud compute instances create $CONSUMER_VM \
        --zone=$ZONE \
        --machine-type=$MACHINE_TYPE \
        --network-interface=subnet=$CONSUMER_SUBNET,no-address \
        --image-family=$IMAGE_FAMILY \
        --image-project=$IMAGE_PROJECT \
        --metadata-from-file=user-data=client-cloud-init.yaml \
        --tags=client-vm
    echo "Consumer VM $CONSUMER_VM created"
else
    echo "Consumer VM $CONSUMER_VM already exists, skipping"
fi

# Clean up cloud-init files
rm -f service-cloud-init.yaml client-cloud-init.yaml

echo "VM deployment completed successfully!"
echo "Service Provider VM: $PROVIDER_VM (in $PROVIDER_VPC)"
echo "Service Consumer VM: $CONSUMER_VM (in $CONSUMER_VPC)"
echo ""
echo "Wait a few minutes for the startup scripts to complete, then verify with:"
echo "gcloud compute instances list --filter='name:($PROVIDER_VM OR $CONSUMER_VM)'"