package main

import (
	"context"
	"fmt"
	"os"

	"gcp-psc-demo/pkg/config"
	"gcp-psc-demo/pkg/testing"
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
	color.Blue("  GCP Private Service Connect Demo - Connectivity Test")
	color.Blue("==================================================")

	fmt.Printf("Project ID: %s\n", cfg.ProjectID)
	fmt.Printf("Region: %s\n", cfg.Region)
	fmt.Printf("Zone: %s\n", cfg.Zone)
	fmt.Printf("\n")

	ctx := context.Background()

	// Create test manager
	testManager, err := testing.NewTestManager(cfg)
	if err != nil {
		color.Red("Failed to create test manager: %v", err)
		os.Exit(1)
	}
	defer testManager.Close()

	// Run connectivity tests
	if err := testManager.TestConnectivity(ctx); err != nil {
		color.Red("Connectivity test failed: %v", err)
		os.Exit(1)
	}

	color.Green("🎉 All connectivity tests passed!")
}
