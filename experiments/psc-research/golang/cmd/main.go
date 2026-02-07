package main

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	"gcp-psc-demo/pkg/config"
	"gcp-psc-demo/pkg/psc"
	"gcp-psc-demo/pkg/testing"
	"gcp-psc-demo/pkg/vm"
	"gcp-psc-demo/pkg/vpc"
	"github.com/fatih/color"
)

func main() {
	// Create configuration
	cfg := config.NewConfig()
	if err := cfg.Validate(); err != nil {
		printError(fmt.Sprintf("Configuration error: %v", err))
		fmt.Println("Please set the PROJECT_ID environment variable:")
		fmt.Println("export PROJECT_ID=your-project-id")
		os.Exit(1)
	}

	// Print banner
	printBanner(cfg)

	// Ask for confirmation
	if !askForConfirmation() {
		fmt.Println("Demo cancelled.")
		os.Exit(0)
	}

	ctx := context.Background()

	// Run the demo
	if err := runDemo(ctx, cfg); err != nil {
		printError(fmt.Sprintf("Demo failed: %v", err))
		os.Exit(1)
	}

	printSuccess()
}

func printBanner(cfg *config.Config) {
	color.Blue("==================================================")
	color.Blue("  GCP Private Service Connect Demo")
	color.Blue("  Connecting hypershift-redhat ↔ hypershift-customer")
	color.Blue("==================================================")

	fmt.Printf("Configuration:\n")
	fmt.Printf("  Project ID: %s\n", cfg.ProjectID)
	fmt.Printf("  Region: %s\n", cfg.Region)
	fmt.Printf("  Zone: %s\n", cfg.Zone)
	fmt.Printf("\n")
}

func askForConfirmation() bool {
	reader := bufio.NewReader(os.Stdin)
	fmt.Print("Do you want to proceed with the demo? (y/N): ")

	response, err := reader.ReadString('\n')
	if err != nil {
		return false
	}

	response = strings.TrimSpace(strings.ToLower(response))
	return response == "y" || response == "yes"
}

func runDemo(ctx context.Context, cfg *config.Config) error {
	// Step 1: Setup Provider VPC
	if err := runStep(ctx, cfg, "1", "Setup hypershift-redhat VPC (Service Provider)", setupProviderVPC); err != nil {
		return err
	}

	// Step 2: Setup Consumer VPC
	if err := runStep(ctx, cfg, "2", "Setup hypershift-customer VPC (Service Consumer)", setupConsumerVPC); err != nil {
		return err
	}

	// Step 3: Deploy VMs
	if err := runStep(ctx, cfg, "3", "Deploy Test VMs", deployVMs); err != nil {
		return err
	}

	// Wait for VMs to be ready
	if err := waitForVMs(ctx, cfg); err != nil {
		return err
	}

	// Step 3b: Test VPC isolation
	if err := runStep(ctx, cfg, "3b", "Test VPC Isolation (Before PSC)", testIsolation); err != nil {
		return err
	}

	// Step 4: Setup Private Service Connect
	if err := runStep(ctx, cfg, "4", "Setup Private Service Connect", setupPSC); err != nil {
		return err
	}

	// PSC operations complete when API returns - no additional wait needed
	// Resource readiness is validated during connectivity testing

	// Step 5: Test connectivity
	if err := runStep(ctx, cfg, "5", "Test Connectivity", testConnectivity); err != nil {
		return err
	}

	return nil
}

func runStep(ctx context.Context, cfg *config.Config, stepNum, stepName string, stepFunc func(context.Context, *config.Config) error) error {
	printStep(stepNum, stepName)

	if err := stepFunc(ctx, cfg); err != nil {
		printError(fmt.Sprintf("Step %s failed: %v", stepNum, err))
		return err
	}

	printStepSuccess(stepNum)
	waitBetweenSteps()
	return nil
}

func setupProviderVPC(ctx context.Context, cfg *config.Config) error {
	vpcManager, err := vpc.NewVPCManager(cfg)
	if err != nil {
		return err
	}
	defer vpcManager.Close()

	return vpcManager.CreateProviderVPC(ctx)
}

func setupConsumerVPC(ctx context.Context, cfg *config.Config) error {
	vpcManager, err := vpc.NewVPCManager(cfg)
	if err != nil {
		return err
	}
	defer vpcManager.Close()

	return vpcManager.CreateConsumerVPC(ctx)
}

func deployVMs(ctx context.Context, cfg *config.Config) error {
	vmManager, err := vm.NewVMManager(cfg)
	if err != nil {
		return err
	}
	defer vmManager.Close()

	return vmManager.DeployVMs(ctx)
}

func waitForVMs(ctx context.Context, cfg *config.Config) error {
	vmManager, err := vm.NewVMManager(cfg)
	if err != nil {
		return err
	}
	defer vmManager.Close()

	return vmManager.WaitForVMsReady(ctx)
}

func setupPSC(ctx context.Context, cfg *config.Config) error {
	pscManager, err := psc.NewPSCManager(cfg)
	if err != nil {
		return err
	}
	defer pscManager.Close()

	return pscManager.SetupPrivateServiceConnect(ctx)
}

func printStep(stepNum, stepName string) {
	color.Blue("=== Step %s: %s ===", stepNum, stepName)
}

func printStepSuccess(stepNum string) {
	color.Green("✓ Step %s completed successfully", stepNum)
}

func printError(message string) {
	color.Red("✗ %s", message)
}

func printSuccess() {
	printStep("", "Demo Completed Successfully!")
	fmt.Println("")
	color.Green("🎉 Private Service Connect demo is now running!")
	fmt.Println("")
	fmt.Println("What was demonstrated:")
	fmt.Println("✓ Two isolated VPCs: hypershift-redhat and hypershift-customer")
	fmt.Println("✓ Service in hypershift-redhat VPC behind internal load balancer")
	fmt.Println("✓ Private Service Connect endpoint in hypershift-customer VPC")
	fmt.Println("✓ Secure cross-VPC communication without VPC peering")
	fmt.Println("✓ Service discovery and load balancing")
	fmt.Println("")
	fmt.Println("Next steps:")
	fmt.Println("• Review the connectivity test results above")
	fmt.Println("• Explore the GCP Console to see the created resources")
	fmt.Println("• Run additional tests if needed")
	fmt.Println("• When finished, run the cleanup script")
	fmt.Println("")
	color.Yellow("⚠ Remember to clean up resources when done to avoid charges!")
}

func waitBetweenSteps() {
	// Reduced wait time - GCP operations are completed when API calls return
	fmt.Println("Waiting 5 seconds for resource propagation...")
	time.Sleep(5 * time.Second)
}

func testIsolation(ctx context.Context, cfg *config.Config) error {
	testManager, err := testing.NewTestManager(cfg)
	if err != nil {
		return err
	}
	defer testManager.Close()

	return testManager.TestIsolation(ctx)
}

func testConnectivity(ctx context.Context, cfg *config.Config) error {
	testManager, err := testing.NewTestManager(cfg)
	if err != nil {
		return err
	}
	defer testManager.Close()

	return testManager.TestConnectivity(ctx)
}
