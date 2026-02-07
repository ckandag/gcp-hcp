package main

import (
	"fmt"
	"os"
	"os/exec"

	"gcp-psc-demo/pkg/config"
	"github.com/fatih/color"
)

func main() {
	// Create configuration
	cfg := config.NewConfig()
	if err := cfg.Validate(); err != nil {
		color.Red("Configuration error: %v", err)
		fmt.Println("Please set the PROJECT_ID environment variable:")
		fmt.Println("export PROJECT_ID=your-project-id")
		os.Exit(1)
	}

	color.Blue("==================================================")
	color.Blue("  GCP Private Service Connect Demo - Cleanup")
	color.Blue("==================================================")

	fmt.Printf("Project ID: %s\n", cfg.ProjectID)
	fmt.Printf("Region: %s\n", cfg.Region)
	fmt.Printf("Zone: %s\n", cfg.Zone)
	fmt.Printf("\n")

	color.Yellow("⚠ This will delete all demo resources. This action cannot be undone.")
	fmt.Print("Do you want to proceed with cleanup? (y/N): ")

	var response string
	fmt.Scanln(&response)

	if response != "y" && response != "Y" && response != "yes" && response != "Yes" {
		fmt.Println("Cleanup cancelled.")
		os.Exit(0)
	}

	runCleanup(cfg)
}

func runCleanup(cfg *config.Config) {
	color.Blue("=== Starting cleanup process ===")

	// Set the project
	runCommand("gcloud", "config", "set", "project", cfg.ProjectID)

	// Delete PSC components
	cleanupPSCComponents(cfg)

	// Delete load balancer components
	cleanupLoadBalancerComponents(cfg)

	// Delete VMs
	cleanupVMs(cfg)

	// Delete VPCs and associated resources
	cleanupVPCs(cfg)

	color.Green("✓ Cleanup completed successfully!")
	fmt.Println("All demo resources have been deleted.")
}

func cleanupPSCComponents(cfg *config.Config) {
	color.Blue("=== Cleaning up PSC components ===")

	// Delete PSC forwarding rule
	deleteResource("forwarding-rules", cfg.PSCForwardingRule, "--region", cfg.Region)

	// Delete PSC endpoint address
	deleteResource("addresses", cfg.PSCEndpoint+"-ip", "--region", cfg.Region)

	// Delete service attachment
	deleteResource("service-attachments", cfg.ServiceAttachment, "--region", cfg.Region)
}

func cleanupLoadBalancerComponents(cfg *config.Config) {
	color.Blue("=== Cleaning up load balancer components ===")

	// Delete forwarding rule
	deleteResource("forwarding-rules", cfg.ForwardingRule, "--region", cfg.Region)

	// Delete backend service
	deleteResource("backend-services", cfg.BackendService, "--region", cfg.Region)

	// Delete instance group
	deleteResource("instance-groups", "redhat-service-group", "--zone", cfg.Zone)

	// Delete health check
	deleteResource("health-checks", cfg.HealthCheck)
}

func cleanupVMs(cfg *config.Config) {
	color.Blue("=== Cleaning up VMs ===")

	// Delete VMs
	deleteResource("instances", cfg.ProviderVM, "--zone", cfg.Zone)
	deleteResource("instances", cfg.ConsumerVM, "--zone", cfg.Zone)
}

func cleanupVPCs(cfg *config.Config) {
	color.Blue("=== Cleaning up VPCs and networking ===")

	// Delete firewall rules
	firewallRules := []string{
		cfg.ProviderVPC + "-allow-health-checks",
		cfg.ProviderVPC + "-allow-http",
		cfg.ProviderVPC + "-allow-ssh",
		cfg.ProviderVPC + "-allow-egress",
		cfg.ProviderVPC + "-allow-psc-nat",
		cfg.ConsumerVPC + "-allow-internal",
		cfg.ConsumerVPC + "-allow-ssh",
		cfg.ConsumerVPC + "-allow-egress",
	}

	for _, rule := range firewallRules {
		deleteResource("firewall-rules", rule)
	}

	// Delete subnets
	deleteSubnet(cfg.ProviderSubnet, cfg.Region)
	deleteSubnet(cfg.PSCNATSubnet, cfg.Region)
	deleteSubnet(cfg.ConsumerSubnet, cfg.Region)

	// Delete VPCs
	deleteResource("networks", cfg.ProviderVPC)
	deleteResource("networks", cfg.ConsumerVPC)
}

func deleteResource(resourceType, resourceName string, extraArgs ...string) {
	args := []string{"compute", resourceType, "delete", resourceName, "--quiet"}
	args = append(args, extraArgs...)

	fmt.Printf("Deleting %s: %s\n", resourceType, resourceName)
	runCommand("gcloud", args...)
}

func deleteSubnet(subnetName, region string) {
	fmt.Printf("Deleting subnet: %s\n", subnetName)
	runCommand("gcloud", "compute", "networks", "subnets", "delete", subnetName, "--region", region, "--quiet")
}

func runCommand(command string, args ...string) {
	cmd := exec.Command(command, args...)
	if err := cmd.Run(); err != nil {
		// Don't fail on individual resource deletion errors
		color.Yellow("⚠ Warning: %v", err)
	}
}
