package config

import (
	"fmt"
	"os"
)

// Config holds the configuration for the GCP PSC demo
type Config struct {
	ProjectID string
	Region    string
	Zone      string

	// Provider VPC Configuration
	ProviderVPC         string
	ProviderSubnet      string
	ProviderSubnetRange string
	PSCNATSubnet        string
	PSCNATSubnetRange   string

	// Consumer VPC Configuration
	ConsumerVPC         string
	ConsumerSubnet      string
	ConsumerSubnetRange string

	// VM Configuration
	ProviderVM   string
	ConsumerVM   string
	ImageFamily  string
	ImageProject string
	MachineType  string

	// Load Balancer Configuration
	HealthCheck       string
	BackendService    string
	ForwardingRule    string
	ServiceAttachment string

	// PSC Configuration
	PSCEndpoint       string
	PSCForwardingRule string
}

// NewConfig creates a new configuration with default values
func NewConfig() *Config {
	return &Config{
		ProjectID: getEnvWithDefault("PROJECT_ID", ""),
		Region:    getEnvWithDefault("REGION", "us-central1"),
		Zone:      getEnvWithDefault("ZONE", "us-central1-a"),

		// Provider VPC Configuration
		ProviderVPC:         "hypershift-redhat",
		ProviderSubnet:      "hypershift-redhat-subnet",
		ProviderSubnetRange: "10.1.0.0/24",
		PSCNATSubnet:        "hypershift-redhat-psc-nat",
		PSCNATSubnetRange:   "10.1.1.0/24",

		// Consumer VPC Configuration
		ConsumerVPC:         "hypershift-customer",
		ConsumerSubnet:      "hypershift-customer-subnet",
		ConsumerSubnetRange: "10.2.0.0/24",

		// VM Configuration
		ProviderVM:   "redhat-service-vm",
		ConsumerVM:   "customer-client-vm",
		ImageFamily:  "ubuntu-2404-lts-amd64",
		ImageProject: "ubuntu-os-cloud",
		MachineType:  "e2-micro",

		// Load Balancer Configuration
		HealthCheck:       "redhat-service-health-check",
		BackendService:    "redhat-backend-service",
		ForwardingRule:    "redhat-forwarding-rule",
		ServiceAttachment: "redhat-service-attachment",

		// PSC Configuration
		PSCEndpoint:       "customer-psc-endpoint",
		PSCForwardingRule: "customer-psc-forwarding-rule",
	}
}

// Validate checks if all required configuration values are set
func (c *Config) Validate() error {
	if c.ProjectID == "" {
		return fmt.Errorf("PROJECT_ID environment variable is required")
	}
	return nil
}

// getEnvWithDefault returns the value of an environment variable or a default value
func getEnvWithDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}
