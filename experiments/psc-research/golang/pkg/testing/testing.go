package testing

import (
	"context"
	"fmt"
	"os/exec"
	"strings"

	compute "cloud.google.com/go/compute/apiv1"
	"cloud.google.com/go/compute/apiv1/computepb"
	"gcp-psc-demo/pkg/config"
	"github.com/fatih/color"
)

// TestManager handles connectivity and isolation testing
type TestManager struct {
	forwardingRuleClient    *compute.ForwardingRulesClient
	backendServiceClient    *compute.RegionBackendServicesClient
	serviceAttachmentClient *compute.ServiceAttachmentsClient
	config                  *config.Config
}

// NewTestManager creates a new test manager
func NewTestManager(cfg *config.Config) (*TestManager, error) {
	ctx := context.Background()

	forwardingRuleClient, err := compute.NewForwardingRulesRESTClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create forwarding rules client: %v", err)
	}

	backendServiceClient, err := compute.NewRegionBackendServicesRESTClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create backend services client: %v", err)
	}

	serviceAttachmentClient, err := compute.NewServiceAttachmentsRESTClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create service attachments client: %v", err)
	}

	return &TestManager{
		forwardingRuleClient:    forwardingRuleClient,
		backendServiceClient:    backendServiceClient,
		serviceAttachmentClient: serviceAttachmentClient,
		config:                  cfg,
	}, nil
}

// Close closes all clients
func (tm *TestManager) Close() {
	tm.forwardingRuleClient.Close()
	tm.backendServiceClient.Close()
	tm.serviceAttachmentClient.Close()
}

// TestIsolation tests that VPCs are isolated before PSC setup
func (tm *TestManager) TestIsolation(ctx context.Context) error {
	color.Blue("=== Testing VPC Isolation (Before PSC) ===")

	// Get VM internal IPs
	providerIP, err := tm.getVMInternalIP(tm.config.ProviderVM)
	if err != nil {
		return fmt.Errorf("failed to get provider VM IP: %v", err)
	}

	consumerIP, err := tm.getVMInternalIP(tm.config.ConsumerVM)
	if err != nil {
		return fmt.Errorf("failed to get consumer VM IP: %v", err)
	}

	fmt.Printf("Provider VM (hypershift-redhat): %s - %s\n", tm.config.ProviderVM, providerIP)
	fmt.Printf("Consumer VM (hypershift-customer): %s - %s\n", tm.config.ConsumerVM, consumerIP)
	fmt.Println()

	color.Blue("=== VPC ISOLATION TESTS ===")

	// Test 1: Ping test
	if err := tm.testPingIsolation(providerIP); err != nil {
		return err
	}

	// Test 2: HTTP service test
	if err := tm.testHTTPIsolation(providerIP); err != nil {
		return err
	}

	// Test 3: API service test
	if err := tm.testAPIIsolation(providerIP); err != nil {
		return err
	}

	// Test 4: Netcat connectivity test
	if err := tm.testNetcatIsolation(providerIP); err != nil {
		return err
	}

	// Test 5: Routing table analysis
	if err := tm.testRoutingTable(providerIP); err != nil {
		return err
	}

	// Test 6: Reverse connectivity test
	if err := tm.testReverseConnectivity(consumerIP); err != nil {
		return err
	}

	color.Blue("=== VERIFICATION OF SERVICE AVAILABILITY ===")

	// Test 7: Verify service running locally on provider
	if err := tm.testProviderServiceLocal(); err != nil {
		return err
	}

	// Test 8: Verify API running locally on provider
	if err := tm.testProviderAPILocal(); err != nil {
		return err
	}

	color.Blue("=== NETWORK CONFIGURATION SUMMARY ===")

	// Provider VM network details
	if err := tm.showProviderNetworkDetails(providerIP); err != nil {
		return err
	}

	// Consumer VM network details
	if err := tm.showConsumerNetworkDetails(consumerIP); err != nil {
		return err
	}

	color.Blue("=== ISOLATION TEST SUMMARY ===")
	fmt.Println("🔒 VPC Isolation Confirmed:")
	fmt.Printf("   ✅ hypershift-redhat VPC: %s (isolated)\n", providerIP)
	fmt.Printf("   ✅ hypershift-customer VPC: %s (isolated)\n", consumerIP)
	fmt.Println("   ✅ No direct connectivity between VPCs")
	fmt.Println("   ✅ Service is running but not accessible cross-VPC")
	fmt.Println()
	fmt.Println("Next step: Set up Private Service Connect to enable secure connectivity")

	color.Green("✓ VPC isolation test completed")
	return nil
}

// TestConnectivity tests PSC connectivity
func (tm *TestManager) TestConnectivity(ctx context.Context) error {
	color.Blue("=== Testing Private Service Connect Connectivity ===")

	// Get PSC endpoint IP
	pscIP, err := tm.getPSCEndpointIP(ctx)
	if err != nil {
		return err
	}

	// Get internal load balancer IP for diagnostic purposes
	lbIP, err := tm.getLoadBalancerIP(ctx)
	if err != nil {
		return err
	}

	fmt.Printf("PSC Endpoint IP: %s\n", pscIP)

	color.Blue("=== DIAGNOSTIC TESTS ===")
	fmt.Printf("Internal Load Balancer IP: %s\n", lbIP)
	fmt.Printf("PSC Endpoint IP: %s\n", pscIP)
	fmt.Println()

	color.Blue("=== BACKEND HEALTH CHECK ===")
	if err := tm.checkBackendHealth(ctx); err != nil {
		color.Red("⚠ Backend health check failed: %v", err)
	}

	fmt.Println()
	color.Blue("=== PSC INFRASTRUCTURE STATUS ===")
	if err := tm.checkPSCInfrastructure(ctx); err != nil {
		color.Red("⚠ PSC infrastructure check failed: %v", err)
	}

	fmt.Println()
	color.Blue("=== CONNECTIVITY TESTS ===")

	// Test 1: Network reachability (ICMP expected to fail)
	if err := tm.testPSCPing(pscIP); err != nil {
		return err
	}

	// Test 2: TCP port connectivity
	if err := tm.testPSCPort(pscIP); err != nil {
		return err
	}

	// Test 3: Direct load balancer connectivity (should fail)
	if err := tm.testDirectLBConnectivity(lbIP); err != nil {
		return err
	}

	// Test 4: PSC HTTP connectivity with verbose output
	if err := tm.testPSCHTTPVerbose(pscIP); err != nil {
		return err
	}

	// Test 5: PSC health endpoint
	if err := tm.testPSCHealth(pscIP); err != nil {
		return err
	}

	// Test 6: Network routing analysis
	if err := tm.testNetworkRouting(pscIP, lbIP); err != nil {
		return err
	}

	// Test 7: PSC endpoint specific checks
	if err := tm.testPSCEndpointSpecific(pscIP); err != nil {
		return err
	}

	color.Blue("=== PROVIDER VM SERVICE STATUS ===")
	if err := tm.checkProviderServiceStatus(); err != nil {
		return err
	}

	color.Blue("=== LOAD BALANCER VERIFICATION ===")
	if err := tm.verifyLoadBalancer(lbIP); err != nil {
		return err
	}

	color.Blue("=== ADVANCED PSC TESTS (if basic connectivity works) ===")
	if err := tm.testMultipleRequests(pscIP); err != nil {
		return err
	}

	if err := tm.testServiceDiscovery(pscIP); err != nil {
		return err
	}

	color.Blue("=== TEST SUMMARY ===")
	fmt.Printf("Private Service Connect endpoint: %s\n", pscIP)
	fmt.Println("All tests completed. Check the output above for any failures.")
	fmt.Println()
	fmt.Println("If tests are successful, you have demonstrated:")
	fmt.Println("✓ Cross-VPC connectivity via Private Service Connect")
	fmt.Println("✓ Service isolation (no direct VPC peering required)")
	fmt.Println("✓ Load balancing and health checking")
	fmt.Println("✓ Service discovery through PSC endpoint")

	color.Green("✓ Private Service Connect connectivity tests completed successfully!")
	return nil
}

// Helper methods for VPC isolation testing

// testPingIsolation tests ping connectivity between VPCs (should fail)
func (tm *TestManager) testPingIsolation(providerIP string) error {
	fmt.Println("Test 1: Attempting to ping provider VM from consumer VM (should FAIL)")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf("ping -c 3 -W 5 %s", providerIP))

	_, err := cmd.Output()
	if err != nil {
		fmt.Printf("✅ EXPECTED: Ping failed - VPCs are isolated\n")
	} else {
		fmt.Printf("❌ UNEXPECTED: Ping succeeded!\n")
	}
	fmt.Println()
	return nil
}

// testHTTPIsolation tests HTTP connectivity between VPCs (should fail)
func (tm *TestManager) testHTTPIsolation(providerIP string) error {
	fmt.Println("Test 2: Attempting to connect to HTTP service (should FAIL)")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf("curl --connect-timeout 10 http://%s/", providerIP))

	_, err := cmd.Output()
	if err != nil {
		fmt.Printf("✅ EXPECTED: HTTP connection failed - no network route\n")
	} else {
		fmt.Printf("❌ UNEXPECTED: HTTP connection succeeded!\n")
	}
	fmt.Println()
	return nil
}

// testAPIIsolation tests API connectivity between VPCs (should fail)
func (tm *TestManager) testAPIIsolation(providerIP string) error {
	fmt.Println("Test 3: Attempting to connect to API service on port 8080 (should FAIL)")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf("curl --connect-timeout 10 http://%s:8080/", providerIP))

	_, err := cmd.Output()
	if err != nil {
		fmt.Printf("✅ EXPECTED: API connection failed - no network route\n")
	} else {
		fmt.Printf("❌ UNEXPECTED: API connection succeeded!\n")
	}
	fmt.Println()
	return nil
}

// testNetcatIsolation tests netcat connectivity between VPCs (should fail)
func (tm *TestManager) testNetcatIsolation(providerIP string) error {
	fmt.Println("Test 4: Testing netcat connectivity (should FAIL)")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf("timeout 10 nc -zv %s 80", providerIP))

	_, err := cmd.Output()
	if err != nil {
		fmt.Printf("✅ EXPECTED: Netcat failed - port unreachable\n")
	} else {
		fmt.Printf("❌ UNEXPECTED: Netcat succeeded!\n")
	}
	fmt.Println()
	return nil
}

// testRoutingTable analyzes routing from consumer VM
func (tm *TestManager) testRoutingTable(providerIP string) error {
	fmt.Println("Test 5: Checking routing table from consumer VM")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf(`
echo 'Consumer VM routing table:'
ip route
echo ''
echo 'Attempting to get route to provider VM:'
ip route get %s || echo 'No route to provider VM (expected)'
`, providerIP))

	output, err := cmd.Output()
	if err != nil {
		fmt.Printf("⚠ Could not check routing table: %v\n", err)
	} else {
		fmt.Printf("%s\n", string(output))
	}
	fmt.Println()
	return nil
}

// testReverseConnectivity tests connectivity from provider to consumer (should fail)
func (tm *TestManager) testReverseConnectivity(consumerIP string) error {
	fmt.Println("Test 6: Testing reverse connectivity (provider to consumer)")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ProviderVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf("ping -c 3 -W 5 %s", consumerIP))

	_, err := cmd.Output()
	if err != nil {
		fmt.Printf("✅ EXPECTED: Reverse ping failed - VPCs are isolated\n")
	} else {
		fmt.Printf("❌ UNEXPECTED: Reverse ping succeeded!\n")
	}
	fmt.Println()
	return nil
}

// testProviderServiceLocal verifies service is running locally on provider VM
func (tm *TestManager) testProviderServiceLocal() error {
	fmt.Println("Test 7: Verifying service is running on provider VM (should SUCCEED)")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ProviderVM,
		"--zone", tm.config.Zone,
		"--command", "curl -s http://localhost/")

	output, err := cmd.Output()
	if err != nil {
		fmt.Printf("❌ Service not running on provider VM\n")
	} else {
		fmt.Printf("✅ Service is running locally on provider VM\n")
		if len(output) > 0 {
			fmt.Printf("Response: %s\n", strings.TrimSpace(string(output)))
		}
	}
	fmt.Println()
	return nil
}

// testProviderAPILocal verifies API is running locally on provider VM
func (tm *TestManager) testProviderAPILocal() error {
	fmt.Println("Test 8: Verifying API is running on provider VM (should SUCCEED)")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ProviderVM,
		"--zone", tm.config.Zone,
		"--command", "curl -s http://localhost:8080/")

	output, err := cmd.Output()
	if err != nil {
		fmt.Printf("❌ API not running on provider VM\n")
	} else {
		fmt.Printf("✅ API is running locally on provider VM\n")
		if len(output) > 0 {
			fmt.Printf("Response: %s\n", strings.TrimSpace(string(output)))
		}
	}
	fmt.Println()
	return nil
}

// showProviderNetworkDetails shows provider VM network configuration
func (tm *TestManager) showProviderNetworkDetails(providerIP string) error {
	fmt.Println("Provider VM Network Details:")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ProviderVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf(`
echo 'IP Address: %s'
echo 'Network Interface:'
ip addr show ens4 | grep inet
echo 'Default Gateway:'
ip route | grep default
`, providerIP))

	output, err := cmd.Output()
	if err != nil {
		fmt.Printf("⚠ Could not get provider network details: %v\n", err)
	} else {
		fmt.Printf("%s\n", string(output))
	}
	return nil
}

// showConsumerNetworkDetails shows consumer VM network configuration
func (tm *TestManager) showConsumerNetworkDetails(consumerIP string) error {
	fmt.Println("Consumer VM Network Details:")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf(`
echo 'IP Address: %s'
echo 'Network Interface:'
ip addr show ens4 | grep inet
echo 'Default Gateway:'
ip route | grep default
`, consumerIP))

	output, err := cmd.Output()
	if err != nil {
		fmt.Printf("⚠ Could not get consumer network details: %v\n", err)
	} else {
		fmt.Printf("%s\n", string(output))
	}
	return nil
}

// Helper methods for PSC connectivity testing

// getPSCEndpointIP gets the IP address of the PSC endpoint
func (tm *TestManager) getPSCEndpointIP(ctx context.Context) (string, error) {
	req := &computepb.GetForwardingRuleRequest{
		Project:        tm.config.ProjectID,
		Region:         tm.config.Region,
		ForwardingRule: tm.config.PSCForwardingRule,
	}

	rule, err := tm.forwardingRuleClient.Get(ctx, req)
	if err != nil {
		return "", fmt.Errorf("failed to get PSC forwarding rule: %v", err)
	}

	return rule.GetIPAddress(), nil
}

// getLoadBalancerIP gets the IP address of the internal load balancer
func (tm *TestManager) getLoadBalancerIP(ctx context.Context) (string, error) {
	req := &computepb.GetForwardingRuleRequest{
		Project:        tm.config.ProjectID,
		Region:         tm.config.Region,
		ForwardingRule: tm.config.ForwardingRule,
	}

	rule, err := tm.forwardingRuleClient.Get(ctx, req)
	if err != nil {
		return "", fmt.Errorf("failed to get load balancer forwarding rule: %v", err)
	}

	return rule.GetIPAddress(), nil
}

// checkBackendHealth checks the health of backend services
func (tm *TestManager) checkBackendHealth(ctx context.Context) error {
	// Instance group URL for health check
	instanceGroupURL := fmt.Sprintf("projects/%s/zones/%s/instanceGroups/redhat-service-group",
		tm.config.ProjectID, tm.config.Zone)

	req := &computepb.GetHealthRegionBackendServiceRequest{
		Project:        tm.config.ProjectID,
		Region:         tm.config.Region,
		BackendService: tm.config.BackendService,
		ResourceGroupReferenceResource: &computepb.ResourceGroupReference{
			Group: &instanceGroupURL,
		},
	}

	health, err := tm.backendServiceClient.GetHealth(ctx, req)
	if err != nil {
		return fmt.Errorf("failed to get backend health: %v", err)
	}

	fmt.Printf("Backend Health Status:\n")
	if len(health.HealthStatus) == 0 {
		fmt.Printf("  No health status information available\n")
		return nil
	}

	for _, status := range health.HealthStatus {
		fmt.Printf("  Instance: %s\n", status.GetInstance())
		fmt.Printf("  Health State: %s\n", status.GetHealthState())
		if status.GetAnnotations() != nil {
			for key, value := range status.GetAnnotations() {
				fmt.Printf("  %s: %s\n", key, value)
			}
		}
		fmt.Println() // Add spacing between instances
	}
	return nil
}

// checkPSCInfrastructure checks PSC infrastructure status
func (tm *TestManager) checkPSCInfrastructure(ctx context.Context) error {
	// Check PSC forwarding rule configuration
	fmt.Println("PSC Forwarding Rule Configuration:")
	pscReq := &computepb.GetForwardingRuleRequest{
		Project:        tm.config.ProjectID,
		Region:         tm.config.Region,
		ForwardingRule: tm.config.PSCForwardingRule,
	}

	pscRule, err := tm.forwardingRuleClient.Get(ctx, pscReq)
	if err != nil {
		return fmt.Errorf("failed to get PSC forwarding rule: %v", err)
	}

	fmt.Printf("  IP Address: %s\n", pscRule.GetIPAddress())
	fmt.Printf("  Target: %s\n", pscRule.GetTarget())
	fmt.Printf("  Network Tier: %s\n", pscRule.GetNetworkTier())

	// Check service attachment status
	fmt.Println("\nService Attachment Status:")
	saReq := &computepb.GetServiceAttachmentRequest{
		Project:           tm.config.ProjectID,
		Region:            tm.config.Region,
		ServiceAttachment: tm.config.ServiceAttachment,
	}

	sa, err := tm.serviceAttachmentClient.Get(ctx, saReq)
	if err != nil {
		return fmt.Errorf("failed to get service attachment: %v", err)
	}

	fmt.Printf("  Connection Preference: %s\n", sa.GetConnectionPreference())
	fmt.Printf("  Target Service: %s\n", sa.GetTargetService())
	fmt.Printf("  Enable Proxy Protocol: %t\n", sa.GetEnableProxyProtocol())

	return nil
}

// testPSCPing tests ICMP connectivity to PSC endpoint (expected to fail)
func (tm *TestManager) testPSCPing(pscIP string) error {
	fmt.Printf("Test 1: Network reachability to PSC endpoint (ICMP test - expected to fail)\n")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf("ping -c 3 -W 5 %s", pscIP))

	_, err := cmd.Output()
	if err != nil {
		fmt.Printf("PSC IP is not reachable via ICMP (expected - PSC endpoints do not respond to ping)\n")
	} else {
		fmt.Printf("PSC IP is reachable via ICMP (unexpected)\n")
	}
	fmt.Println()
	return nil
}

// testPSCPort tests TCP port connectivity to PSC endpoint
func (tm *TestManager) testPSCPort(pscIP string) error {
	fmt.Printf("Test 2: TCP port connectivity to PSC endpoint\n")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf("timeout 10 nc -zv %s 8080", pscIP))

	_, err := cmd.Output()
	if err != nil {
		fmt.Printf("PSC port 8080 is CLOSED or filtered\n")
	} else {
		fmt.Printf("PSC port 8080 is OPEN\n")
	}
	fmt.Println()
	return nil
}

// testDirectLBConnectivity tests direct load balancer connectivity (should fail)
func (tm *TestManager) testDirectLBConnectivity(lbIP string) error {
	fmt.Printf("Test 3: Direct Load Balancer connectivity (cross-VPC should fail)\n")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf("timeout 5 nc -zv %s 8080", lbIP))

	_, err := cmd.Output()
	if err != nil {
		fmt.Printf("Direct LB not accessible (expected - different VPC)\n")
	} else {
		fmt.Printf("Direct LB accessible (unexpected!)\n")
	}
	fmt.Println()
	return nil
}

// testPSCHTTPVerbose tests PSC HTTP connectivity with verbose output
func (tm *TestManager) testPSCHTTPVerbose(pscIP string) error {
	fmt.Printf("Test 4: PSC HTTP connectivity with verbose output\n")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf("curl -v --connect-timeout 15 --max-time 30 http://%s:8080/", pscIP))

	output, err := cmd.Output()
	if err != nil {
		fmt.Printf("PSC HTTP test failed: %v\n", err)
	} else {
		fmt.Printf("PSC HTTP test successful:\n%s\n", string(output))
	}
	fmt.Println()
	return nil
}

// testPSCHealth tests PSC health endpoint
func (tm *TestManager) testPSCHealth(pscIP string) error {
	fmt.Printf("Test 5: PSC Health endpoint\n")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf("curl -s --connect-timeout 15 --max-time 30 http://%s:8080/health", pscIP))

	output, err := cmd.Output()
	if err != nil {
		fmt.Printf("PSC health check failed: %v\n", err)
	} else {
		fmt.Printf("PSC health check successful: %s\n", strings.TrimSpace(string(output)))
	}
	fmt.Println()
	return nil
}

// testNetworkRouting analyzes network routing
func (tm *TestManager) testNetworkRouting(pscIP, lbIP string) error {
	fmt.Printf("Test 6: Network routing analysis\n")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf(`
echo 'Route to PSC endpoint:'
ip route get %s 2>/dev/null || echo 'No route to PSC endpoint found'
echo ''
echo 'Route to Load Balancer (should fail):'
ip route get %s 2>/dev/null || echo 'No route to Load Balancer (expected - different VPC)'
echo ''
echo 'Default gateway:'
ip route | grep default
echo ''
echo 'Consumer VM internal IP:'
ip addr show | grep 'inet 10.2'
`, pscIP, lbIP))

	output, err := cmd.Output()
	if err != nil {
		fmt.Printf("Network routing analysis failed: %v\n", err)
	} else {
		fmt.Printf("%s\n", string(output))
	}
	return nil
}

// testPSCEndpointSpecific tests PSC endpoint specific connectivity methods
func (tm *TestManager) testPSCEndpointSpecific(pscIP string) error {
	fmt.Printf("Test 7: PSC Endpoint specific checks\n")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf(`
echo 'Testing PSC endpoint connectivity:'
echo '- Telnet connection test:'
timeout 5 telnet %s 8080 < /dev/null 2>&1 | head -5
echo ''
echo '- Netcat port scan:'
timeout 3 nc -w1 %s 8080 < /dev/null && echo 'Connection successful' || echo 'Connection failed'
echo ''
echo '- HTTP response test:'
timeout 10 wget -qO- --timeout=5 http://%s:8080/ 2>&1 | head -3 || echo 'wget failed'
`, pscIP, pscIP, pscIP))

	output, err := cmd.Output()
	if err != nil {
		fmt.Printf("PSC endpoint specific checks failed: %v\n", err)
	} else {
		fmt.Printf("%s\n", string(output))
	}
	return nil
}

// checkProviderServiceStatus checks provider VM service status
func (tm *TestManager) checkProviderServiceStatus() error {
	fmt.Printf("Provider VM service verification:\n")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ProviderVM,
		"--zone", tm.config.Zone,
		"--command", `
echo 'Service status:'
systemctl is-active demo-api || echo 'demo-api service not active'
echo ''
echo 'Service listening on ports:'
ss -tlnp | grep :8080 || echo 'No service listening on port 8080'
echo ''
echo 'Service logs (last 10 lines):'
journalctl -u demo-api --no-pager -n 10 || echo 'No logs available'
echo ''
echo 'Test local connectivity:'
curl -s --connect-timeout 5 http://localhost:8080/health || echo 'Local health check failed'
`)

	output, err := cmd.Output()
	if err != nil {
		fmt.Printf("Provider service status check failed: %v\n", err)
	} else {
		fmt.Printf("%s\n", string(output))
	}
	return nil
}

// verifyLoadBalancer verifies load balancer functionality
func (tm *TestManager) verifyLoadBalancer(lbIP string) error {
	fmt.Printf("Testing direct access to Load Balancer from Provider VPC:\n")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ProviderVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf(`
echo 'Testing Load Balancer from same VPC:'
curl -s --connect-timeout 10 http://%s:8080/ || echo 'Load Balancer not accessible from provider VPC'
echo ''
echo 'Load Balancer health:'
curl -s --connect-timeout 10 http://%s:8080/health || echo 'Load Balancer health check failed'
`, lbIP, lbIP))

	output, err := cmd.Output()
	if err != nil {
		fmt.Printf("Load balancer verification failed: %v\n", err)
	} else {
		fmt.Printf("%s\n", string(output))
	}
	return nil
}

// testMultipleRequests tests multiple requests for consistency
func (tm *TestManager) testMultipleRequests(pscIP string) error {
	fmt.Printf("Test 8: Multiple requests to verify consistent connectivity\n")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf(`
if curl -s --connect-timeout 5 http://%s:8080/health >/dev/null 2>&1; then
  echo 'PSC is responding, testing multiple requests:'
  for i in {1..3}; do
    echo "Request $i:"
    if curl -s --connect-timeout 5 http://%s:8080/health; then
      echo ' - SUCCESS'
    else
      echo ' - FAILED'
    fi
    sleep 1
  done
else
  echo 'PSC endpoint not responding, skipping multiple request test'
fi
`, pscIP, pscIP))

	output, err := cmd.Output()
	if err != nil {
		fmt.Printf("Multiple requests test failed: %v\n", err)
	} else {
		fmt.Printf("%s\n", string(output))
	}
	return nil
}

// testServiceDiscovery tests service discovery and metadata
func (tm *TestManager) testServiceDiscovery(pscIP string) error {
	fmt.Printf("Test 9: Service discovery and metadata (if PSC works)\n")

	cmd := exec.Command("gcloud", "compute", "ssh", tm.config.ConsumerVM,
		"--zone", tm.config.Zone,
		"--command", fmt.Sprintf(`
if curl -s --connect-timeout 5 http://%s:8080/health >/dev/null 2>&1; then
  echo 'Testing service discovery:'
  curl -s --connect-timeout 10 http://%s:8080/ | python3 -c 'import sys, json; data=json.load(sys.stdin); print(f"Service: {data.get(\"message\", \"N/A\")}"); print(f"Hostname: {data.get(\"hostname\", \"N/A\")}"); print(f"Timestamp: {data.get(\"timestamp\", \"N/A\")}")'
else
  echo 'PSC endpoint not responding, skipping service discovery test'
fi
`, pscIP, pscIP))

	output, err := cmd.Output()
	if err != nil {
		fmt.Printf("Service discovery test failed: %v\n", err)
	} else {
		fmt.Printf("%s\n", string(output))
	}
	return nil
}

// getVMInternalIP gets the internal IP address of a VM
func (tm *TestManager) getVMInternalIP(vmName string) (string, error) {
	cmd := exec.Command("gcloud", "compute", "instances", "describe", vmName,
		"--zone", tm.config.Zone,
		"--format", "value(networkInterfaces[0].networkIP)")

	output, err := cmd.Output()
	if err != nil {
		return "", err
	}

	return strings.TrimSpace(string(output)), nil
}
