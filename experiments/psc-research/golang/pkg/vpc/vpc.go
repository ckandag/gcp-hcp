package vpc

import (
	"context"
	"fmt"
	"time"

	compute "cloud.google.com/go/compute/apiv1"
	"cloud.google.com/go/compute/apiv1/computepb"
	"gcp-psc-demo/pkg/config"
	"github.com/fatih/color"
)

// VPCManager handles VPC operations
type VPCManager struct {
	client         *compute.NetworksClient
	subnetClient   *compute.SubnetworksClient
	firewallClient *compute.FirewallsClient
	config         *config.Config
}

// NewVPCManager creates a new VPC manager
func NewVPCManager(cfg *config.Config) (*VPCManager, error) {
	ctx := context.Background()

	client, err := compute.NewNetworksRESTClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create networks client: %v", err)
	}

	subnetClient, err := compute.NewSubnetworksRESTClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create subnetworks client: %v", err)
	}

	firewallClient, err := compute.NewFirewallsRESTClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create firewall client: %v", err)
	}

	return &VPCManager{
		client:         client,
		subnetClient:   subnetClient,
		firewallClient: firewallClient,
		config:         cfg,
	}, nil
}

// Close closes all clients
func (vm *VPCManager) Close() {
	vm.client.Close()
	vm.subnetClient.Close()
	vm.firewallClient.Close()
}

// CreateProviderVPC creates the hypershift-redhat VPC (service provider)
func (vm *VPCManager) CreateProviderVPC(ctx context.Context) error {
	color.Blue("=== Setting up hypershift-redhat VPC (Service Provider) ===")

	// Create VPC
	if err := vm.createVPC(ctx, vm.config.ProviderVPC); err != nil {
		return err
	}

	// Create main subnet
	if err := vm.createSubnet(ctx, vm.config.ProviderVPC, vm.config.ProviderSubnet, vm.config.ProviderSubnetRange, ""); err != nil {
		return err
	}

	// Create PSC NAT subnet
	if err := vm.createSubnet(ctx, vm.config.ProviderVPC, vm.config.PSCNATSubnet, vm.config.PSCNATSubnetRange, "PRIVATE_SERVICE_CONNECT"); err != nil {
		return err
	}

	// Create firewall rules
	if err := vm.createProviderFirewallRules(ctx); err != nil {
		return err
	}

	color.Green("✓ hypershift-redhat VPC setup completed successfully!")
	return nil
}

// CreateConsumerVPC creates the hypershift-customer VPC (service consumer)
func (vm *VPCManager) CreateConsumerVPC(ctx context.Context) error {
	color.Blue("=== Setting up hypershift-customer VPC (Service Consumer) ===")

	// Create VPC
	if err := vm.createVPC(ctx, vm.config.ConsumerVPC); err != nil {
		return err
	}

	// Create main subnet
	if err := vm.createSubnet(ctx, vm.config.ConsumerVPC, vm.config.ConsumerSubnet, vm.config.ConsumerSubnetRange, ""); err != nil {
		return err
	}

	// Create firewall rules
	if err := vm.createConsumerFirewallRules(ctx); err != nil {
		return err
	}

	color.Green("✓ hypershift-customer VPC setup completed successfully!")
	return nil
}

// createVPC creates a VPC network
func (vm *VPCManager) createVPC(ctx context.Context, name string) error {
	// Check if VPC already exists
	if exists, err := vm.vpcExists(ctx, name); err != nil {
		return err
	} else if exists {
		fmt.Printf("VPC %s already exists, skipping\n", name)
		return nil
	}

	fmt.Printf("Creating VPC: %s\n", name)

	req := &computepb.InsertNetworkRequest{
		Project: vm.config.ProjectID,
		NetworkResource: &computepb.Network{
			Name:                  &name,
			AutoCreateSubnetworks: boolPtr(false),
			RoutingConfig: &computepb.NetworkRoutingConfig{
				RoutingMode: stringPtr("REGIONAL"),
			},
		},
	}

	op, err := vm.client.Insert(ctx, req)
	if err != nil {
		return fmt.Errorf("failed to create VPC %s: %v", name, err)
	}

	if err := vm.waitForOperation(ctx, op.Name(), "global"); err != nil {
		return fmt.Errorf("failed to wait for VPC creation: %v", err)
	}

	fmt.Printf("VPC %s created\n", name)
	return nil
}

// createSubnet creates a subnet
func (vm *VPCManager) createSubnet(ctx context.Context, vpcName, subnetName, ipRange, purpose string) error {
	// Check if subnet already exists
	if exists, err := vm.subnetExists(ctx, subnetName); err != nil {
		return err
	} else if exists {
		fmt.Printf("Subnet %s already exists, skipping\n", subnetName)
		return nil
	}

	fmt.Printf("Creating subnet: %s\n", subnetName)

	subnet := &computepb.Subnetwork{
		Name:                  &subnetName,
		Network:               stringPtr(fmt.Sprintf("projects/%s/global/networks/%s", vm.config.ProjectID, vpcName)),
		IpCidrRange:           &ipRange,
		PrivateIpGoogleAccess: boolPtr(true),
	}

	if purpose != "" {
		subnet.Purpose = &purpose
	}

	req := &computepb.InsertSubnetworkRequest{
		Project:            vm.config.ProjectID,
		Region:             vm.config.Region,
		SubnetworkResource: subnet,
	}

	op, err := vm.subnetClient.Insert(ctx, req)
	if err != nil {
		return fmt.Errorf("failed to create subnet %s: %v", subnetName, err)
	}

	if err := vm.waitForRegionalOperation(ctx, op.Name()); err != nil {
		return fmt.Errorf("failed to wait for subnet creation: %v", err)
	}

	fmt.Printf("Subnet %s created\n", subnetName)
	return nil
}

// createProviderFirewallRules creates firewall rules for the provider VPC
func (vm *VPCManager) createProviderFirewallRules(ctx context.Context) error {
	rules := []struct {
		name         string
		description  string
		sourceRanges []string
		targetTags   []string
		allowed      []*computepb.Allowed
	}{
		{
			name:         vm.config.ProviderVPC + "-allow-health-checks",
			description:  "Allow health checks from Google's health check ranges",
			sourceRanges: []string{"130.211.0.0/22", "35.191.0.0/16"},
			allowed: []*computepb.Allowed{
				{IPProtocol: stringPtr("tcp")},
			},
		},
		{
			name:         vm.config.ProviderVPC + "-allow-http",
			description:  "Allow HTTP traffic for the demo service",
			sourceRanges: []string{vm.config.ProviderSubnetRange},
			allowed: []*computepb.Allowed{
				{
					IPProtocol: stringPtr("tcp"),
					Ports:      []string{"80", "8080"},
				},
			},
		},
		{
			name:         vm.config.ProviderVPC + "-allow-ssh",
			description:  "Allow SSH for management",
			sourceRanges: []string{"0.0.0.0/0"},
			allowed: []*computepb.Allowed{
				{
					IPProtocol: stringPtr("tcp"),
					Ports:      []string{"22"},
				},
			},
		},
		{
			name:         vm.config.ProviderVPC + "-allow-egress",
			description:  "Allow all egress traffic",
			sourceRanges: []string{}, // Empty for egress rules
			allowed: []*computepb.Allowed{
				{IPProtocol: stringPtr("all")},
			},
		},
		{
			name:         vm.config.ProviderVPC + "-allow-psc-nat",
			description:  "Allow PSC NAT subnet traffic to reach service",
			sourceRanges: []string{vm.config.PSCNATSubnetRange},
			allowed: []*computepb.Allowed{
				{
					IPProtocol: stringPtr("tcp"),
					Ports:      []string{"8080"},
				},
			},
		},
	}

	for _, rule := range rules {
		if err := vm.createFirewallRule(ctx, rule.name, rule.description, vm.config.ProviderVPC, rule.sourceRanges, rule.targetTags, rule.allowed, "INGRESS"); err != nil {
			return err
		}
	}

	// Create egress rule separately
	if err := vm.createFirewallRule(ctx, vm.config.ProviderVPC+"-allow-egress", "Allow all egress traffic", vm.config.ProviderVPC, []string{"0.0.0.0/0"}, []string{}, []*computepb.Allowed{{IPProtocol: stringPtr("all")}}, "EGRESS"); err != nil {
		return err
	}

	return nil
}

// createConsumerFirewallRules creates firewall rules for the consumer VPC
func (vm *VPCManager) createConsumerFirewallRules(ctx context.Context) error {
	rules := []struct {
		name         string
		description  string
		sourceRanges []string
		allowed      []*computepb.Allowed
	}{
		{
			name:         vm.config.ConsumerVPC + "-allow-internal",
			description:  "Allow internal communication within consumer VPC",
			sourceRanges: []string{vm.config.ConsumerSubnetRange},
			allowed: []*computepb.Allowed{
				{IPProtocol: stringPtr("all")},
			},
		},
		{
			name:         vm.config.ConsumerVPC + "-allow-ssh",
			description:  "Allow SSH for management",
			sourceRanges: []string{"0.0.0.0/0"},
			allowed: []*computepb.Allowed{
				{
					IPProtocol: stringPtr("tcp"),
					Ports:      []string{"22"},
				},
			},
		},
	}

	for _, rule := range rules {
		if err := vm.createFirewallRule(ctx, rule.name, rule.description, vm.config.ConsumerVPC, rule.sourceRanges, []string{}, rule.allowed, "INGRESS"); err != nil {
			return err
		}
	}

	// Create egress rule
	if err := vm.createFirewallRule(ctx, vm.config.ConsumerVPC+"-allow-egress", "Allow all egress traffic", vm.config.ConsumerVPC, []string{"0.0.0.0/0"}, []string{}, []*computepb.Allowed{{IPProtocol: stringPtr("all")}}, "EGRESS"); err != nil {
		return err
	}

	return nil
}

// createFirewallRule creates a firewall rule
func (vm *VPCManager) createFirewallRule(ctx context.Context, name, description, vpcName string, sourceRanges, targetTags []string, allowed []*computepb.Allowed, direction string) error {
	// Check if firewall rule already exists
	if exists, err := vm.firewallRuleExists(ctx, name); err != nil {
		return err
	} else if exists {
		fmt.Printf("Firewall rule %s already exists, skipping\n", name)
		return nil
	}

	fmt.Printf("Creating firewall rule: %s\n", name)

	firewall := &computepb.Firewall{
		Name:        &name,
		Description: &description,
		Network:     stringPtr(fmt.Sprintf("projects/%s/global/networks/%s", vm.config.ProjectID, vpcName)),
		Direction:   &direction,
		Allowed:     allowed,
	}

	if len(sourceRanges) > 0 {
		if direction == "INGRESS" {
			firewall.SourceRanges = sourceRanges
		} else {
			firewall.DestinationRanges = sourceRanges
		}
	}

	if len(targetTags) > 0 {
		firewall.TargetTags = targetTags
	}

	req := &computepb.InsertFirewallRequest{
		Project:          vm.config.ProjectID,
		FirewallResource: firewall,
	}

	op, err := vm.firewallClient.Insert(ctx, req)
	if err != nil {
		return fmt.Errorf("failed to create firewall rule %s: %v", name, err)
	}

	if err := vm.waitForOperation(ctx, op.Name(), "global"); err != nil {
		return fmt.Errorf("failed to wait for firewall rule creation: %v", err)
	}

	fmt.Printf("Firewall rule %s created\n", name)
	return nil
}

// Helper functions for checking existence

// vpcExists checks if a VPC exists
func (vm *VPCManager) vpcExists(ctx context.Context, name string) (bool, error) {
	req := &computepb.GetNetworkRequest{
		Project: vm.config.ProjectID,
		Network: name,
	}

	_, err := vm.client.Get(ctx, req)
	if err != nil {
		// Check if it's a "not found" error
		if isNotFoundError(err) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

// subnetExists checks if a subnet exists
func (vm *VPCManager) subnetExists(ctx context.Context, name string) (bool, error) {
	req := &computepb.GetSubnetworkRequest{
		Project:    vm.config.ProjectID,
		Region:     vm.config.Region,
		Subnetwork: name,
	}

	_, err := vm.subnetClient.Get(ctx, req)
	if err != nil {
		if isNotFoundError(err) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

// firewallRuleExists checks if a firewall rule exists
func (vm *VPCManager) firewallRuleExists(ctx context.Context, name string) (bool, error) {
	req := &computepb.GetFirewallRequest{
		Project:  vm.config.ProjectID,
		Firewall: name,
	}

	_, err := vm.firewallClient.Get(ctx, req)
	if err != nil {
		if isNotFoundError(err) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

// waitForOperation waits for a global operation to complete
func (vm *VPCManager) waitForOperation(ctx context.Context, operationName, operationType string) error {
	operationsClient, err := compute.NewGlobalOperationsRESTClient(ctx)
	if err != nil {
		return err
	}
	defer operationsClient.Close()

	// Smart polling with exponential backoff
	pollInterval := 1 * time.Second
	maxInterval := 10 * time.Second

	for {
		req := &computepb.GetGlobalOperationRequest{
			Project:   vm.config.ProjectID,
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

// waitForRegionalOperation waits for a regional operation to complete
func (vm *VPCManager) waitForRegionalOperation(ctx context.Context, operationName string) error {
	operationsClient, err := compute.NewRegionOperationsRESTClient(ctx)
	if err != nil {
		return err
	}
	defer operationsClient.Close()

	// Smart polling with exponential backoff
	pollInterval := 1 * time.Second
	maxInterval := 10 * time.Second

	for {
		req := &computepb.GetRegionOperationRequest{
			Project:   vm.config.ProjectID,
			Region:    vm.config.Region,
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
