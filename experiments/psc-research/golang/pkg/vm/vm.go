package vm

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
	"time"

	"gcp-psc-demo/pkg/config"

	compute "cloud.google.com/go/compute/apiv1"
	"cloud.google.com/go/compute/apiv1/computepb"
	"github.com/fatih/color"
)

// VMManager handles VM operations
type VMManager struct {
	client *compute.InstancesClient
	config *config.Config
}

// NewVMManager creates a new VM manager
func NewVMManager(cfg *config.Config) (*VMManager, error) {
	ctx := context.Background()

	client, err := compute.NewInstancesRESTClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create instances client: %v", err)
	}

	return &VMManager{
		client: client,
		config: cfg,
	}, nil
}

// Close closes the client
func (vm *VMManager) Close() {
	vm.client.Close()
}

// DeployVMs deploys both the service provider and consumer VMs
func (vm *VMManager) DeployVMs(ctx context.Context) error {
	color.Blue("=== Deploying Test VMs ===")

	// Deploy service provider VM
	if err := vm.deployProviderVM(ctx); err != nil {
		return err
	}

	// Deploy consumer VM
	if err := vm.deployConsumerVM(ctx); err != nil {
		return err
	}

	color.Green("✓ VM deployment completed successfully!")
	return nil
}

// deployProviderVM deploys the service provider VM
func (vm *VMManager) deployProviderVM(ctx context.Context) error {
	vmName := vm.config.ProviderVM

	// Check if VM already exists
	if exists, err := vm.vmExists(ctx, vmName); err != nil {
		return err
	} else if exists {
		fmt.Printf("Service provider VM %s already exists, skipping\n", vmName)
		return nil
	}

	fmt.Printf("Creating service provider VM: %s\n", vmName)

	cloudInit := vm.getServiceCloudInit()

	req := &computepb.InsertInstanceRequest{
		Project: vm.config.ProjectID,
		Zone:    vm.config.Zone,
		InstanceResource: &computepb.Instance{
			Name:        &vmName,
			MachineType: stringPtr(fmt.Sprintf("zones/%s/machineTypes/%s", vm.config.Zone, vm.config.MachineType)),
			NetworkInterfaces: []*computepb.NetworkInterface{
				{
					Subnetwork: stringPtr(fmt.Sprintf("projects/%s/regions/%s/subnetworks/%s",
						vm.config.ProjectID, vm.config.Region, vm.config.ProviderSubnet)),
					// No external IP
					AccessConfigs: []*computepb.AccessConfig{},
				},
			},
			Disks: []*computepb.AttachedDisk{
				{
					Boot:       boolPtr(true),
					AutoDelete: boolPtr(true),
					InitializeParams: &computepb.AttachedDiskInitializeParams{
						SourceImage: stringPtr(fmt.Sprintf("projects/%s/global/images/family/%s",
							vm.config.ImageProject, vm.config.ImageFamily)),
						DiskSizeGb: int64Ptr(20),
					},
				},
			},
			Metadata: &computepb.Metadata{
				Items: []*computepb.Items{
					{
						Key:   stringPtr("user-data"),
						Value: &cloudInit,
					},
				},
			},
			Tags: &computepb.Tags{
				Items: []string{"service-vm"},
			},
		},
	}

	op, err := vm.client.Insert(ctx, req)
	if err != nil {
		return fmt.Errorf("failed to create service provider VM: %v", err)
	}

	if err := vm.waitForZonalOperation(ctx, op.Name()); err != nil {
		return fmt.Errorf("failed to wait for service provider VM creation: %v", err)
	}

	fmt.Printf("Service provider VM %s created\n", vmName)
	return nil
}

// deployConsumerVM deploys the consumer VM
func (vm *VMManager) deployConsumerVM(ctx context.Context) error {
	vmName := vm.config.ConsumerVM

	// Check if VM already exists
	if exists, err := vm.vmExists(ctx, vmName); err != nil {
		return err
	} else if exists {
		fmt.Printf("Consumer VM %s already exists, skipping\n", vmName)
		return nil
	}

	fmt.Printf("Creating consumer VM: %s\n", vmName)

	cloudInit := vm.getClientCloudInit()

	req := &computepb.InsertInstanceRequest{
		Project: vm.config.ProjectID,
		Zone:    vm.config.Zone,
		InstanceResource: &computepb.Instance{
			Name:        &vmName,
			MachineType: stringPtr(fmt.Sprintf("zones/%s/machineTypes/%s", vm.config.Zone, vm.config.MachineType)),
			NetworkInterfaces: []*computepb.NetworkInterface{
				{
					Subnetwork: stringPtr(fmt.Sprintf("projects/%s/regions/%s/subnetworks/%s",
						vm.config.ProjectID, vm.config.Region, vm.config.ConsumerSubnet)),
					// No external IP
					AccessConfigs: []*computepb.AccessConfig{},
				},
			},
			Disks: []*computepb.AttachedDisk{
				{
					Boot:       boolPtr(true),
					AutoDelete: boolPtr(true),
					InitializeParams: &computepb.AttachedDiskInitializeParams{
						SourceImage: stringPtr(fmt.Sprintf("projects/%s/global/images/family/%s",
							vm.config.ImageProject, vm.config.ImageFamily)),
						DiskSizeGb: int64Ptr(20),
					},
				},
			},
			Metadata: &computepb.Metadata{
				Items: []*computepb.Items{
					{
						Key:   stringPtr("user-data"),
						Value: &cloudInit,
					},
				},
			},
			Tags: &computepb.Tags{
				Items: []string{"client-vm"},
			},
		},
	}

	op, err := vm.client.Insert(ctx, req)
	if err != nil {
		return fmt.Errorf("failed to create consumer VM: %v", err)
	}

	if err := vm.waitForZonalOperation(ctx, op.Name()); err != nil {
		return fmt.Errorf("failed to wait for consumer VM creation: %v", err)
	}

	fmt.Printf("Consumer VM %s created\n", vmName)
	return nil
}

// getServiceCloudInit returns the cloud-init configuration for the service VM
func (vm *VMManager) getServiceCloudInit() string {
	return `#cloud-config
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
  condition: true`
}

// getClientCloudInit returns the cloud-init configuration for the client VM
func (vm *VMManager) getClientCloudInit() string {
	return `#cloud-config
package_update: true
packages:
  - curl
  - wget
  - netcat-openbsd
  - dnsutils
  - iputils-ping
  - traceroute

runcmd:
  - echo "Client VM setup completed" > /var/log/startup-complete.log`
}

// vmExists checks if a VM exists
func (vm *VMManager) vmExists(ctx context.Context, name string) (bool, error) {
	req := &computepb.GetInstanceRequest{
		Project:  vm.config.ProjectID,
		Zone:     vm.config.Zone,
		Instance: name,
	}

	_, err := vm.client.Get(ctx, req)
	if err != nil {
		if isNotFoundError(err) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

// WaitForVMsReady waits for VMs to be ready and services to start
func (vm *VMManager) WaitForVMsReady(ctx context.Context) error {
	color.Blue("=== Waiting for VMs to be ready ===")

	fmt.Println("Checking VM readiness and startup script completion...")

	// Poll for both VMs to be ready with smart waiting
	maxWaitTime := 5 * time.Minute
	checkInterval := 10 * time.Second
	startTime := time.Now()

	for time.Since(startTime) < maxWaitTime {
		// Check VM status
		providerStatus, err := vm.getVMStatus(ctx, vm.config.ProviderVM)
		if err != nil {
			fmt.Printf("⚠ Error checking provider VM status: %v\n", err)
		}

		consumerStatus, err := vm.getVMStatus(ctx, vm.config.ConsumerVM)
		if err != nil {
			fmt.Printf("⚠ Error checking consumer VM status: %v\n", err)
		}

		// Check if both VMs are running
		if providerStatus == "RUNNING" && consumerStatus == "RUNNING" {
			// Check if startup scripts completed (for provider VM with services)
			startupComplete := vm.checkStartupCompletion(vm.config.ProviderVM)
			if startupComplete {
				color.Green("✓ VMs are ready and startup scripts completed")
				return nil
			} else {
				fmt.Printf("VMs running, waiting for startup scripts... (%v elapsed)\n", time.Since(startTime).Round(time.Second))
			}
		} else {
			fmt.Printf("Waiting for VMs to start (Provider: %s, Consumer: %s)... (%v elapsed)\n",
				providerStatus, consumerStatus, time.Since(startTime).Round(time.Second))
		}

		time.Sleep(checkInterval)
	}

	// If we reach here, VMs took longer than expected but may still work
	color.Yellow("⚠ VMs took longer than expected to be ready. Continuing anyway...")
	return nil
}

// checkStartupCompletion checks if VM startup script has completed
func (vm *VMManager) checkStartupCompletion(vmName string) bool {
	// Use gcloud to check for startup completion file
	cmd := exec.Command("gcloud", "compute", "ssh", vmName,
		"--zone", vm.config.Zone,
		"--command", "test -f /var/log/startup-complete.log && echo 'COMPLETE' || echo 'PENDING'")

	output, err := cmd.Output()
	if err != nil {
		return false // SSH not ready or other error
	}

	return strings.TrimSpace(string(output)) == "COMPLETE"
}

// getVMStatus gets the status of a VM
func (vm *VMManager) getVMStatus(ctx context.Context, name string) (string, error) {
	req := &computepb.GetInstanceRequest{
		Project:  vm.config.ProjectID,
		Zone:     vm.config.Zone,
		Instance: name,
	}

	instance, err := vm.client.Get(ctx, req)
	if err != nil {
		if isNotFoundError(err) {
			return "NOT_FOUND", nil
		}
		return "", err
	}

	return instance.GetStatus(), nil
}

// waitForZonalOperation waits for a zonal operation to complete
func (vm *VMManager) waitForZonalOperation(ctx context.Context, operationName string) error {
	operationsClient, err := compute.NewZoneOperationsRESTClient(ctx)
	if err != nil {
		return err
	}
	defer operationsClient.Close()

	// Smart polling with exponential backoff
	pollInterval := 1 * time.Second
	maxInterval := 10 * time.Second

	for {
		req := &computepb.GetZoneOperationRequest{
			Project:   vm.config.ProjectID,
			Zone:      vm.config.Zone,
			Operation: operationName,
		}

		op, err := operationsClient.Get(ctx, req)
		if err != nil {
			return err
		}

		if op.GetStatus() == computepb.Operation_DONE {
			if op.Error != nil {
				return fmt.Errorf("operation failed: %v", op.Error)
			}
			return nil
		}

		time.Sleep(pollInterval)

		// Exponential backoff capped at maxInterval
		pollInterval = pollInterval * 2
		if pollInterval > maxInterval {
			pollInterval = maxInterval
		}
	}
}

// Helper utility functions
func stringPtr(s string) *string {
	return &s
}

func boolPtr(b bool) *bool {
	return &b
}

func int64Ptr(i int64) *int64 {
	return &i
}

func isNotFoundError(err error) bool {
	// Simple check - in a real implementation you'd want more robust error checking
	return err != nil && (containsString(err.Error(), "notFound") || containsString(err.Error(), "not found"))
}

func containsString(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || (len(s) > len(substr) && containsHelper(s, substr)))
}

func containsHelper(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
