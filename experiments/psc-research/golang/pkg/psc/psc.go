package psc

import (
	"context"
	"fmt"
	"strings"
	"time"

	compute "cloud.google.com/go/compute/apiv1"
	"cloud.google.com/go/compute/apiv1/computepb"
	"gcp-psc-demo/pkg/config"
	"github.com/fatih/color"
)

// PSCManager handles Private Service Connect operations
type PSCManager struct {
	healthCheckClient       *compute.HealthChecksClient
	instanceGroupClient     *compute.InstanceGroupsClient
	backendServiceClient    *compute.RegionBackendServicesClient
	forwardingRuleClient    *compute.ForwardingRulesClient
	serviceAttachmentClient *compute.ServiceAttachmentsClient
	addressClient           *compute.AddressesClient
	instancesClient         *compute.InstancesClient
	config                  *config.Config
}

// NewPSCManager creates a new PSC manager
func NewPSCManager(cfg *config.Config) (*PSCManager, error) {
	ctx := context.Background()

	healthCheckClient, err := compute.NewHealthChecksRESTClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create health checks client: %v", err)
	}

	instanceGroupClient, err := compute.NewInstanceGroupsRESTClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create instance groups client: %v", err)
	}

	backendServiceClient, err := compute.NewRegionBackendServicesRESTClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create backend services client: %v", err)
	}

	forwardingRuleClient, err := compute.NewForwardingRulesRESTClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create forwarding rules client: %v", err)
	}

	serviceAttachmentClient, err := compute.NewServiceAttachmentsRESTClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create service attachments client: %v", err)
	}

	addressClient, err := compute.NewAddressesRESTClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create addresses client: %v", err)
	}

	instancesClient, err := compute.NewInstancesRESTClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create instances client: %v", err)
	}

	return &PSCManager{
		healthCheckClient:       healthCheckClient,
		instanceGroupClient:     instanceGroupClient,
		backendServiceClient:    backendServiceClient,
		forwardingRuleClient:    forwardingRuleClient,
		serviceAttachmentClient: serviceAttachmentClient,
		addressClient:           addressClient,
		instancesClient:         instancesClient,
		config:                  cfg,
	}, nil
}

// Close closes all clients
func (psc *PSCManager) Close() {
	psc.healthCheckClient.Close()
	psc.instanceGroupClient.Close()
	psc.backendServiceClient.Close()
	psc.forwardingRuleClient.Close()
	psc.serviceAttachmentClient.Close()
	psc.addressClient.Close()
	psc.instancesClient.Close()
}

// SetupPrivateServiceConnect sets up all PSC components
func (psc *PSCManager) SetupPrivateServiceConnect(ctx context.Context) error {
	color.Blue("=== Setting up Private Service Connect ===")

	// Step 1: Create health check
	if err := psc.createHealthCheck(ctx); err != nil {
		return err
	}

	// Step 2: Create instance group and add VM
	if err := psc.createInstanceGroup(ctx); err != nil {
		return err
	}

	// Step 3: Create backend service
	if err := psc.createBackendService(ctx); err != nil {
		return err
	}

	// Step 4: Create internal load balancer forwarding rule
	if err := psc.createForwardingRule(ctx); err != nil {
		return err
	}

	// Step 5: Create service attachment
	if err := psc.createServiceAttachment(ctx); err != nil {
		return err
	}

	// Step 6: Create PSC endpoint in consumer VPC
	if err := psc.createPSCEndpoint(ctx); err != nil {
		return err
	}

	color.Green("✓ Private Service Connect setup completed successfully!")
	return nil
}

// createHealthCheck creates a health check for the internal load balancer
func (psc *PSCManager) createHealthCheck(ctx context.Context) error {
	fmt.Println("Step 1: Creating health check for internal load balancer")

	healthCheckName := psc.config.HealthCheck

	// Check if health check already exists
	if exists, err := psc.healthCheckExists(ctx, healthCheckName); err != nil {
		return err
	} else if exists {
		fmt.Printf("Health check %s already exists, skipping\n", healthCheckName)
		return nil
	}

	req := &computepb.InsertHealthCheckRequest{
		Project: psc.config.ProjectID,
		HealthCheckResource: &computepb.HealthCheck{
			Name: &healthCheckName,
			Type: stringPtr("TCP"),
			TcpHealthCheck: &computepb.TCPHealthCheck{
				Port: int32Ptr(8080),
			},
			CheckIntervalSec:   int32Ptr(10),
			TimeoutSec:         int32Ptr(5),
			HealthyThreshold:   int32Ptr(2),
			UnhealthyThreshold: int32Ptr(3),
		},
	}

	op, err := psc.healthCheckClient.Insert(ctx, req)
	if err != nil {
		return fmt.Errorf("failed to create health check: %v", err)
	}

	if err := psc.waitForGlobalOperation(ctx, op.Name()); err != nil {
		return fmt.Errorf("failed to wait for health check creation: %v", err)
	}

	fmt.Printf("Health check %s created\n", healthCheckName)
	return nil
}

// createInstanceGroup creates an instance group and adds the provider VM
func (psc *PSCManager) createInstanceGroup(ctx context.Context) error {
	fmt.Println("Step 2: Creating instance group for the service VM")

	groupName := "redhat-service-group"

	// Check if instance group already exists
	if exists, err := psc.instanceGroupExists(ctx, groupName); err != nil {
		return err
	} else if exists {
		fmt.Printf("Instance group %s already exists, skipping creation\n", groupName)
	} else {
		// Create instance group
		req := &computepb.InsertInstanceGroupRequest{
			Project: psc.config.ProjectID,
			Zone:    psc.config.Zone,
			InstanceGroupResource: &computepb.InstanceGroup{
				Name: &groupName,
			},
		}

		op, err := psc.instanceGroupClient.Insert(ctx, req)
		if err != nil {
			return fmt.Errorf("failed to create instance group: %v", err)
		}

		if err := psc.waitForZonalOperation(ctx, op.Name()); err != nil {
			return fmt.Errorf("failed to wait for instance group creation: %v", err)
		}

		fmt.Printf("Instance group %s created\n", groupName)
	}

	// Add VM to instance group if not already a member
	if err := psc.addVMToInstanceGroup(ctx, groupName); err != nil {
		return err
	}

	// Set named ports
	if err := psc.setNamedPorts(ctx, groupName); err != nil {
		return err
	}

	return nil
}

// addVMToInstanceGroup adds the provider VM to the instance group
func (psc *PSCManager) addVMToInstanceGroup(ctx context.Context, groupName string) error {
	vmName := psc.config.ProviderVM

	// Check if VM is already in the group
	listReq := &computepb.ListInstancesInstanceGroupsRequest{
		Project:       psc.config.ProjectID,
		Zone:          psc.config.Zone,
		InstanceGroup: groupName,
	}

	iterator := psc.instanceGroupClient.ListInstances(ctx, listReq)
	for {
		instance, err := iterator.Next()
		if err != nil {
			if err.Error() == "no more items in iterator" {
				break
			}
			return fmt.Errorf("failed to list instance group members: %v", err)
		}

		if instance.Instance != nil && containsString(*instance.Instance, vmName) {
			fmt.Printf("VM %s already in instance group, skipping\n", vmName)
			return nil
		}
	}

	// Add VM to instance group
	vmURL := fmt.Sprintf("projects/%s/zones/%s/instances/%s", psc.config.ProjectID, psc.config.Zone, vmName)

	addReq := &computepb.AddInstancesInstanceGroupRequest{
		Project:       psc.config.ProjectID,
		Zone:          psc.config.Zone,
		InstanceGroup: groupName,
		InstanceGroupsAddInstancesRequestResource: &computepb.InstanceGroupsAddInstancesRequest{
			Instances: []*computepb.InstanceReference{
				{
					Instance: &vmURL,
				},
			},
		},
	}

	op, err := psc.instanceGroupClient.AddInstances(ctx, addReq)
	if err != nil {
		return fmt.Errorf("failed to add VM to instance group: %v", err)
	}

	if err := psc.waitForZonalOperation(ctx, op.Name()); err != nil {
		return fmt.Errorf("failed to wait for VM addition: %v", err)
	}

	fmt.Printf("VM %s added to instance group\n", vmName)
	return nil
}

// setNamedPorts sets named ports on the instance group
func (psc *PSCManager) setNamedPorts(ctx context.Context, groupName string) error {
	req := &computepb.SetNamedPortsInstanceGroupRequest{
		Project:       psc.config.ProjectID,
		Zone:          psc.config.Zone,
		InstanceGroup: groupName,
		InstanceGroupsSetNamedPortsRequestResource: &computepb.InstanceGroupsSetNamedPortsRequest{
			NamedPorts: []*computepb.NamedPort{
				{
					Name: stringPtr("http"),
					Port: int32Ptr(8080),
				},
			},
		},
	}

	op, err := psc.instanceGroupClient.SetNamedPorts(ctx, req)
	if err != nil {
		return fmt.Errorf("failed to set named ports: %v", err)
	}

	if err := psc.waitForZonalOperation(ctx, op.Name()); err != nil {
		return fmt.Errorf("failed to wait for named ports update: %v", err)
	}

	fmt.Println("Named ports set on instance group")
	return nil
}

// createBackendService creates a backend service
func (psc *PSCManager) createBackendService(ctx context.Context) error {
	fmt.Println("Step 3: Creating backend service")

	backendServiceName := psc.config.BackendService

	// Check if backend service already exists
	if exists, err := psc.backendServiceExists(ctx, backendServiceName); err != nil {
		return err
	} else if exists {
		fmt.Printf("Backend service %s already exists, skipping creation\n", backendServiceName)
	} else {
		// Create backend service
		req := &computepb.InsertRegionBackendServiceRequest{
			Project: psc.config.ProjectID,
			Region:  psc.config.Region,
			BackendServiceResource: &computepb.BackendService{
				Name:                &backendServiceName,
				LoadBalancingScheme: stringPtr("INTERNAL"),
				Protocol:            stringPtr("TCP"),
				HealthChecks: []string{
					fmt.Sprintf("projects/%s/global/healthChecks/%s", psc.config.ProjectID, psc.config.HealthCheck),
				},
			},
		}

		op, err := psc.backendServiceClient.Insert(ctx, req)
		if err != nil {
			return fmt.Errorf("failed to create backend service: %v", err)
		}

		if err := psc.waitForRegionalOperation(ctx, op.Name()); err != nil {
			return fmt.Errorf("failed to wait for backend service creation: %v", err)
		}

		fmt.Printf("Backend service %s created\n", backendServiceName)
	}

	// Add instance group as backend
	if err := psc.addBackendToService(ctx, backendServiceName); err != nil {
		return err
	}

	return nil
}

// addBackendToService adds the instance group as a backend to the service
func (psc *PSCManager) addBackendToService(ctx context.Context, backendServiceName string) error {
	groupName := "redhat-service-group"
	groupURL := fmt.Sprintf("projects/%s/zones/%s/instanceGroups/%s", psc.config.ProjectID, psc.config.Zone, groupName)

	// Check if backend is already added
	getReq := &computepb.GetRegionBackendServiceRequest{
		Project:        psc.config.ProjectID,
		Region:         psc.config.Region,
		BackendService: backendServiceName,
	}

	service, err := psc.backendServiceClient.Get(ctx, getReq)
	if err != nil {
		return fmt.Errorf("failed to get backend service: %v", err)
	}

	// Check if backend already exists with more thorough checking
	for _, backend := range service.Backends {
		if backend.Group != nil {
			// Compare both exact match and contains check for robustness
			if *backend.Group == groupURL || strings.Contains(*backend.Group, groupName) {
				fmt.Printf("Instance group %s already added to backend service, skipping\n", groupName)
				return nil
			}
		}
	}

	fmt.Printf("Adding instance group %s to backend service...\n", groupName)

	// Create a fresh backend service object to avoid any stale data
	newService := &computepb.BackendService{
		Name:                service.Name,
		LoadBalancingScheme: service.LoadBalancingScheme,
		Protocol:            service.Protocol,
		HealthChecks:        service.HealthChecks,
		Fingerprint:         service.Fingerprint, // Required for updates
		Backends:            make([]*computepb.Backend, len(service.Backends)),
	}

	// Copy existing backends
	copy(newService.Backends, service.Backends)

	// Add the new backend
	newBackend := &computepb.Backend{
		Group: &groupURL,
	}
	newService.Backends = append(newService.Backends, newBackend)

	updateReq := &computepb.UpdateRegionBackendServiceRequest{
		Project:                psc.config.ProjectID,
		Region:                 psc.config.Region,
		BackendService:         backendServiceName,
		BackendServiceResource: newService,
	}

	op, err := psc.backendServiceClient.Update(ctx, updateReq)
	if err != nil {
		return fmt.Errorf("failed to add backend to service: %v", err)
	}

	if err := psc.waitForRegionalOperation(ctx, op.Name()); err != nil {
		return fmt.Errorf("failed to wait for backend addition: %v", err)
	}

	fmt.Printf("Instance group %s added to backend service\n", groupName)
	return nil
}

// createForwardingRule creates an internal load balancer forwarding rule
func (psc *PSCManager) createForwardingRule(ctx context.Context) error {
	fmt.Println("Step 4: Creating internal load balancer forwarding rule")

	forwardingRuleName := psc.config.ForwardingRule

	// Check if forwarding rule already exists
	if exists, err := psc.forwardingRuleExists(ctx, forwardingRuleName); err != nil {
		return err
	} else if exists {
		fmt.Printf("Forwarding rule %s already exists, skipping\n", forwardingRuleName)
		return nil
	}

	backendServiceURL := fmt.Sprintf("projects/%s/regions/%s/backendServices/%s",
		psc.config.ProjectID, psc.config.Region, psc.config.BackendService)

	req := &computepb.InsertForwardingRuleRequest{
		Project: psc.config.ProjectID,
		Region:  psc.config.Region,
		ForwardingRuleResource: &computepb.ForwardingRule{
			Name:                &forwardingRuleName,
			LoadBalancingScheme: stringPtr("INTERNAL"),
			BackendService:      &backendServiceURL,
			Subnetwork: stringPtr(fmt.Sprintf("projects/%s/regions/%s/subnetworks/%s",
				psc.config.ProjectID, psc.config.Region, psc.config.ProviderSubnet)),
			Ports: []string{"8080"},
		},
	}

	op, err := psc.forwardingRuleClient.Insert(ctx, req)
	if err != nil {
		return fmt.Errorf("failed to create forwarding rule: %v", err)
	}

	if err := psc.waitForRegionalOperation(ctx, op.Name()); err != nil {
		return fmt.Errorf("failed to wait for forwarding rule creation: %v", err)
	}

	// Get the load balancer IP
	getReq := &computepb.GetForwardingRuleRequest{
		Project:        psc.config.ProjectID,
		Region:         psc.config.Region,
		ForwardingRule: forwardingRuleName,
	}

	rule, err := psc.forwardingRuleClient.Get(ctx, getReq)
	if err != nil {
		return fmt.Errorf("failed to get forwarding rule: %v", err)
	}

	fmt.Printf("Forwarding rule %s created\n", forwardingRuleName)
	fmt.Printf("Internal Load Balancer IP: %s\n", rule.GetIPAddress())
	return nil
}

// createServiceAttachment creates a service attachment for PSC
func (psc *PSCManager) createServiceAttachment(ctx context.Context) error {
	fmt.Println("Step 5: Creating service attachment for Private Service Connect")

	serviceAttachmentName := psc.config.ServiceAttachment

	// Check if service attachment already exists
	if exists, err := psc.serviceAttachmentExists(ctx, serviceAttachmentName); err != nil {
		return err
	} else if exists {
		fmt.Printf("Service attachment %s already exists, skipping\n", serviceAttachmentName)
		return nil
	}

	forwardingRuleURL := fmt.Sprintf("projects/%s/regions/%s/forwardingRules/%s",
		psc.config.ProjectID, psc.config.Region, psc.config.ForwardingRule)

	req := &computepb.InsertServiceAttachmentRequest{
		Project: psc.config.ProjectID,
		Region:  psc.config.Region,
		ServiceAttachmentResource: &computepb.ServiceAttachment{
			Name:                   &serviceAttachmentName,
			ProducerForwardingRule: &forwardingRuleURL,
			ConnectionPreference:   stringPtr("ACCEPT_AUTOMATIC"),
			NatSubnets: []string{
				fmt.Sprintf("projects/%s/regions/%s/subnetworks/%s",
					psc.config.ProjectID, psc.config.Region, psc.config.PSCNATSubnet),
			},
		},
	}

	op, err := psc.serviceAttachmentClient.Insert(ctx, req)
	if err != nil {
		return fmt.Errorf("failed to create service attachment: %v", err)
	}

	if err := psc.waitForRegionalOperation(ctx, op.Name()); err != nil {
		return fmt.Errorf("failed to wait for service attachment creation: %v", err)
	}

	fmt.Printf("Service attachment %s created\n", serviceAttachmentName)
	return nil
}

// createPSCEndpoint creates a PSC endpoint in the consumer VPC
func (psc *PSCManager) createPSCEndpoint(ctx context.Context) error {
	fmt.Println("Step 6: Creating Private Service Connect endpoint in consumer VPC")

	// Create reserved IP address
	if err := psc.createPSCAddress(ctx); err != nil {
		return err
	}

	// Create PSC forwarding rule
	if err := psc.createPSCForwardingRule(ctx); err != nil {
		return err
	}

	return nil
}

// createPSCAddress creates a reserved IP address for the PSC endpoint
func (psc *PSCManager) createPSCAddress(ctx context.Context) error {
	addressName := psc.config.PSCEndpoint + "-ip"

	// Check if address already exists
	if exists, err := psc.addressExists(ctx, addressName); err != nil {
		return err
	} else if exists {
		fmt.Printf("Address %s already exists, skipping\n", addressName)
		return nil
	}

	req := &computepb.InsertAddressRequest{
		Project: psc.config.ProjectID,
		Region:  psc.config.Region,
		AddressResource: &computepb.Address{
			Name:        &addressName,
			AddressType: stringPtr("INTERNAL"), // Required when specifying Subnetwork
			Subnetwork: stringPtr(fmt.Sprintf("projects/%s/regions/%s/subnetworks/%s",
				psc.config.ProjectID, psc.config.Region, psc.config.ConsumerSubnet)),
		},
	}

	op, err := psc.addressClient.Insert(ctx, req)
	if err != nil {
		return fmt.Errorf("failed to create PSC address: %v", err)
	}

	if err := psc.waitForRegionalOperation(ctx, op.Name()); err != nil {
		return fmt.Errorf("failed to wait for PSC address creation: %v", err)
	}

	fmt.Printf("PSC address %s created\n", addressName)
	return nil
}

// createPSCForwardingRule creates a PSC forwarding rule
func (psc *PSCManager) createPSCForwardingRule(ctx context.Context) error {
	forwardingRuleName := psc.config.PSCForwardingRule

	// Check if PSC forwarding rule already exists
	if exists, err := psc.forwardingRuleExists(ctx, forwardingRuleName); err != nil {
		return err
	} else if exists {
		fmt.Printf("PSC forwarding rule %s already exists, skipping\n", forwardingRuleName)
		return nil
	}

	addressName := psc.config.PSCEndpoint + "-ip"
	serviceAttachmentURL := fmt.Sprintf("projects/%s/regions/%s/serviceAttachments/%s",
		psc.config.ProjectID, psc.config.Region, psc.config.ServiceAttachment)

	req := &computepb.InsertForwardingRuleRequest{
		Project: psc.config.ProjectID,
		Region:  psc.config.Region,
		ForwardingRuleResource: &computepb.ForwardingRule{
			Name: &forwardingRuleName,
			IPAddress: stringPtr(fmt.Sprintf("projects/%s/regions/%s/addresses/%s",
				psc.config.ProjectID, psc.config.Region, addressName)),
			Target: &serviceAttachmentURL,
			Network: stringPtr(fmt.Sprintf("projects/%s/global/networks/%s",
				psc.config.ProjectID, psc.config.ConsumerVPC)),
			Subnetwork: stringPtr(fmt.Sprintf("projects/%s/regions/%s/subnetworks/%s",
				psc.config.ProjectID, psc.config.Region, psc.config.ConsumerSubnet)),
		},
	}

	op, err := psc.forwardingRuleClient.Insert(ctx, req)
	if err != nil {
		return fmt.Errorf("failed to create PSC forwarding rule: %v", err)
	}

	if err := psc.waitForRegionalOperation(ctx, op.Name()); err != nil {
		return fmt.Errorf("failed to wait for PSC forwarding rule creation: %v", err)
	}

	// Get the PSC endpoint IP
	getReq := &computepb.GetForwardingRuleRequest{
		Project:        psc.config.ProjectID,
		Region:         psc.config.Region,
		ForwardingRule: forwardingRuleName,
	}

	rule, err := psc.forwardingRuleClient.Get(ctx, getReq)
	if err != nil {
		return fmt.Errorf("failed to get PSC forwarding rule: %v", err)
	}

	fmt.Printf("PSC forwarding rule %s created\n", forwardingRuleName)
	fmt.Printf("PSC Endpoint IP: %s\n", rule.GetIPAddress())
	return nil
}

// Helper methods for checking resource existence

func (psc *PSCManager) healthCheckExists(ctx context.Context, name string) (bool, error) {
	req := &computepb.GetHealthCheckRequest{
		Project:     psc.config.ProjectID,
		HealthCheck: name,
	}

	_, err := psc.healthCheckClient.Get(ctx, req)
	if err != nil {
		if isNotFoundError(err) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

func (psc *PSCManager) instanceGroupExists(ctx context.Context, name string) (bool, error) {
	req := &computepb.GetInstanceGroupRequest{
		Project:       psc.config.ProjectID,
		Zone:          psc.config.Zone,
		InstanceGroup: name,
	}

	_, err := psc.instanceGroupClient.Get(ctx, req)
	if err != nil {
		if isNotFoundError(err) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

func (psc *PSCManager) backendServiceExists(ctx context.Context, name string) (bool, error) {
	req := &computepb.GetRegionBackendServiceRequest{
		Project:        psc.config.ProjectID,
		Region:         psc.config.Region,
		BackendService: name,
	}

	_, err := psc.backendServiceClient.Get(ctx, req)
	if err != nil {
		if isNotFoundError(err) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

func (psc *PSCManager) forwardingRuleExists(ctx context.Context, name string) (bool, error) {
	req := &computepb.GetForwardingRuleRequest{
		Project:        psc.config.ProjectID,
		Region:         psc.config.Region,
		ForwardingRule: name,
	}

	_, err := psc.forwardingRuleClient.Get(ctx, req)
	if err != nil {
		if isNotFoundError(err) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

func (psc *PSCManager) serviceAttachmentExists(ctx context.Context, name string) (bool, error) {
	req := &computepb.GetServiceAttachmentRequest{
		Project:           psc.config.ProjectID,
		Region:            psc.config.Region,
		ServiceAttachment: name,
	}

	_, err := psc.serviceAttachmentClient.Get(ctx, req)
	if err != nil {
		if isNotFoundError(err) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

func (psc *PSCManager) addressExists(ctx context.Context, name string) (bool, error) {
	req := &computepb.GetAddressRequest{
		Project: psc.config.ProjectID,
		Region:  psc.config.Region,
		Address: name,
	}

	_, err := psc.addressClient.Get(ctx, req)
	if err != nil {
		if isNotFoundError(err) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

// Wait for operations

func (psc *PSCManager) waitForGlobalOperation(ctx context.Context, operationName string) error {
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
			Project:   psc.config.ProjectID,
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

func (psc *PSCManager) waitForRegionalOperation(ctx context.Context, operationName string) error {
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
			Project:   psc.config.ProjectID,
			Region:    psc.config.Region,
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

func (psc *PSCManager) waitForZonalOperation(ctx context.Context, operationName string) error {
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
			Project:   psc.config.ProjectID,
			Zone:      psc.config.Zone,
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

func int32Ptr(i int32) *int32 {
	return &i
}

func isNotFoundError(err error) bool {
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
