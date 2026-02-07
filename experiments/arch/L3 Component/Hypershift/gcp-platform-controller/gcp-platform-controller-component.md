# GCP Platform Controller Component Architecture (L3)

## Component Information
- **Component**: GCP Platform Controller
- **Level**: L3 Component Architecture
- **Repository**: `github.com/openshift/hypershift`
- **Location**: `hypershift-operator/controllers/hostedcluster/internal/platform/gcp/`
- **Status**: ❌ **COMPLETELY NEW COMPONENT**
- **Version**: 1.0

## Implementation Status
- **Platform Interface Pattern**: ✅ **EXISTS** - Follow existing AWS/Azure platform implementations
- **GCP Platform Implementation**: ❌ **NEW** - Complete new implementation required
- **PSC Management**: ❌ **NEW** - No existing PSC support in any platform
- **Cross-Project Operations**: ❌ **NEW** - Unique to GCP implementation
- **GCP API Integration**: ❌ **NEW** - New GCP client integrations required

## Required New Files
- `platform/gcp/gcp.go` - Main platform implementation
- `platform/gcp/psc_manager.go` - PSC Service Attachment management
- `platform/gcp/ilb_manager.go` - Internal Load Balancer management
- `platform/gcp/cross_project.go` - Cross-project operations
- `platform/gcp/credentials.go` - Workload Identity management

## Component Overview

The GCP Platform Controller implements the HyperShift Platform interface specifically for Google Cloud Platform, handling PSC infrastructure management, cross-project operations, and GCP-specific resource lifecycle.

## Component Responsibilities

### Primary Functions
1. **PSC Infrastructure Management**: Creates and manages Private Service Connect Service Attachments
2. **Internal Load Balancer Operations**: Provisions dedicated ILB per HostedCluster
3. **Cross-Project Resource Coordination**: Manages resources across management and customer projects
4. **CAPI Integration**: Creates GCPCluster resources for Cluster API
5. **Platform Interface Implementation**: Implements all required Platform interface methods

### Secondary Functions
- Health check configuration for load balancers
- Firewall rule automation
- DNS zone management for clusters
- Workload Identity credential management
- GCP API error handling and retry logic

## Detailed Architecture

### Platform Interface Implementation
```go
// Core platform implementation struct
type GCPPlatform struct {
    client.Client
    computeClient *compute.InstancesClient
    region        string
    project       string
    utilitiesImage   string
    capiProviderImage string
}

// Platform interface methods - all must be implemented
func (p *GCPPlatform) ReconcileCAPIInfraCR(ctx context.Context, c client.Client,
    createOrUpdate upsert.CreateOrUpdateFN, hcluster *hyperv1.HostedCluster,
    controlPlaneNamespace string, apiEndpoint hyperv1.APIEndpoint) (client.Object, error)

func (p *GCPPlatform) CAPIProviderDeploymentSpec(hcluster *hyperv1.HostedCluster,
    hcp *hyperv1.HostedControlPlane) (*appsv1.DeploymentSpec, error)

func (p *GCPPlatform) ReconcileCredentials(ctx context.Context, c client.Client,
    createOrUpdate upsert.CreateOrUpdateFN, hcluster *hyperv1.HostedCluster,
    controlPlaneNamespace string) error

func (p *GCPPlatform) ReconcileSecretEncryption(ctx context.Context, c client.Client,
    createOrUpdate upsert.CreateOrUpdateFN, hcluster *hyperv1.HostedCluster,
    controlPlaneNamespace string) error

func (p *GCPPlatform) CAPIProviderPolicyRules() []rbacv1.PolicyRule

func (p *GCPPlatform) DeleteCredentials(ctx context.Context, c client.Client,
    hcluster *hyperv1.HostedCluster, controlPlaneNamespace string) error
```

### PSC Infrastructure Management

#### Service Attachment Creation
```go
func (p *GCPPlatform) reconcilePSCServiceAttachment(ctx context.Context,
    hc *hyperv1.HostedCluster, forwardingRule *computepb.ForwardingRule) (*computepb.ServiceAttachment, error) {

    serviceAttachmentName := fmt.Sprintf("hypershift-%s-psc-producer", hc.Name)

    // Check if service attachment already exists
    existing, err := p.computeClient.ServiceAttachments.Get(ctx, &computepb.GetServiceAttachmentRequest{
        Project:           p.project,
        Region:            p.region,
        ServiceAttachment: serviceAttachmentName,
    })
    if err == nil {
        return existing, nil // Already exists
    }

    // Create NAT subnet for PSC if needed
    natSubnet, err := p.reconcilePSCNATSubnet(ctx, hc)
    if err != nil {
        return nil, fmt.Errorf("failed to reconcile PSC NAT subnet: %w", err)
    }

    // Create service attachment
    serviceAttachment := &computepb.ServiceAttachment{
        Name:                 proto.String(serviceAttachmentName),
        Description:          proto.String(fmt.Sprintf("PSC producer for HostedCluster %s", hc.Name)),
        TargetService:        forwardingRule.SelfLink,
        ConnectionPreference: proto.String("ACCEPT_AUTOMATIC"),
        NatSubnets:          []string{*natSubnet.SelfLink},
        ConsumerAcceptLists: p.buildConsumerAcceptLists(hc),
        ConsumerRejectLists: p.buildConsumerRejectLists(hc),
    }

    operation, err := p.computeClient.ServiceAttachments.Insert(ctx, &computepb.InsertServiceAttachmentRequest{
        Project:                   p.project,
        Region:                    p.region,
        ServiceAttachmentResource: serviceAttachment,
    })
    if err != nil {
        return nil, HandleGCPAPIError(err, "create PSC service attachment")
    }

    // Wait for operation completion
    if err := p.waitForRegionalOperation(ctx, operation.GetName()); err != nil {
        return nil, fmt.Errorf("failed waiting for service attachment creation: %w", err)
    }

    // Retrieve created service attachment
    created, err := p.computeClient.ServiceAttachments.Get(ctx, &computepb.GetServiceAttachmentRequest{
        Project:           p.project,
        Region:            p.region,
        ServiceAttachment: serviceAttachmentName,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to get created service attachment: %w", err)
    }

    log := ctrl.LoggerFrom(ctx)
    log.Info("PSC Service Attachment created",
        "name", serviceAttachmentName,
        "uri", *created.SelfLink)

    return created, nil
}
```

#### Internal Load Balancer Management
```go
func (p *GCPPlatform) reconcileInternalLoadBalancer(ctx context.Context,
    hc *hyperv1.HostedCluster) (*computepb.ForwardingRule, error) {

    // 1. Create health check for API server
    healthCheck, err := p.reconcileAPIServerHealthCheck(ctx, hc)
    if err != nil {
        return nil, fmt.Errorf("failed to reconcile health check: %w", err)
    }

    // 2. Create backend service
    backendService, err := p.reconcileBackendService(ctx, hc, healthCheck)
    if err != nil {
        return nil, fmt.Errorf("failed to reconcile backend service: %w", err)
    }

    // 3. Create forwarding rule (Internal Load Balancer)
    forwardingRuleName := fmt.Sprintf("hypershift-%s-api-ilb", hc.Name)

    forwardingRule := &computepb.ForwardingRule{
        Name:                proto.String(forwardingRuleName),
        Description:         proto.String(fmt.Sprintf("ILB for HostedCluster %s API server", hc.Name)),
        IPProtocol:          proto.String("TCP"),
        Ports:               []string{"6443", "443", "22623"},
        LoadBalancingScheme: proto.String("INTERNAL"),
        BackendService:      backendService.SelfLink,
        Network:             proto.String(fmt.Sprintf("projects/%s/global/networks/%s",
                               p.project, hc.Spec.Platform.GCP.Network.Name)),
        Subnetwork:          proto.String(fmt.Sprintf("projects/%s/regions/%s/subnetworks/%s",
                               p.project, p.region, hc.Spec.Platform.GCP.Network.Subnet)),
    }

    // Check if forwarding rule exists
    existing, err := p.computeClient.ForwardingRules.Get(ctx, &computepb.GetForwardingRuleRequest{
        Project:        p.project,
        Region:         p.region,
        ForwardingRule: forwardingRuleName,
    })
    if err == nil {
        return existing, nil // Already exists
    }

    // Create forwarding rule
    operation, err := p.computeClient.ForwardingRules.Insert(ctx, &computepb.InsertForwardingRuleRequest{
        Project:               p.project,
        Region:                p.region,
        ForwardingRuleResource: forwardingRule,
    })
    if err != nil {
        return nil, HandleGCPAPIError(err, "create internal load balancer")
    }

    if err := p.waitForRegionalOperation(ctx, operation.GetName()); err != nil {
        return nil, fmt.Errorf("failed waiting for ILB creation: %w", err)
    }

    created, err := p.computeClient.ForwardingRules.Get(ctx, &computepb.GetForwardingRuleRequest{
        Project:        p.project,
        Region:         p.region,
        ForwardingRule: forwardingRuleName,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to get created forwarding rule: %w", err)
    }

    return created, nil
}
```

### CAPI Integration

#### GCPCluster Resource Creation
```go
func (p *GCPPlatform) ReconcileCAPIInfraCR(ctx context.Context, c client.Client,
    createOrUpdate upsert.CreateOrUpdateFN, hcluster *hyperv1.HostedCluster,
    controlPlaneNamespace string, apiEndpoint hyperv1.APIEndpoint) (client.Object, error) {

    // 1. Create/reconcile Internal Load Balancer
    forwardingRule, err := p.reconcileInternalLoadBalancer(ctx, hcluster)
    if err != nil {
        return nil, fmt.Errorf("failed to reconcile ILB: %w", err)
    }

    // 2. Create/reconcile PSC Service Attachment
    serviceAttachment, err := p.reconcilePSCServiceAttachment(ctx, hcluster, forwardingRule)
    if err != nil {
        return nil, fmt.Errorf("failed to reconcile PSC attachment: %w", err)
    }

    // 3. Create GCPCluster resource
    gcpCluster := &capgv1.GCPCluster{
        ObjectMeta: metav1.ObjectMeta{
            Name:      hcluster.Name,
            Namespace: controlPlaneNamespace,
        },
        Spec: capgv1.GCPClusterSpec{
            Project: hcluster.Spec.Platform.GCP.Project,
            Region:  hcluster.Spec.Platform.GCP.Region,
            Network: capgv1.NetworkSpec{
                Name: hcluster.Spec.Platform.GCP.Network.Name,
            },
            ControlPlaneEndpoint: &capgv1.APIEndpoint{
                Host: *forwardingRule.IPAddress,
                Port: 6443,
            },
            PrivateServiceConnect: &capgv1.PSCConfig{
                Enabled:              true,
                ServiceAttachmentURI: *serviceAttachment.SelfLink,
            },
        },
    }

    // 4. Create or update the resource
    if err := createOrUpdate(ctx, c, gcpCluster); err != nil {
        return nil, fmt.Errorf("failed to create/update GCPCluster: %w", err)
    }

    // 5. Update HostedCluster status with PSC information
    if err := p.updatePSCStatus(ctx, c, hcluster, serviceAttachment, forwardingRule); err != nil {
        return nil, fmt.Errorf("failed to update PSC status: %w", err)
    }

    return gcpCluster, nil
}
```

### Cross-Project Operations

#### PSC Consumer Management
```go
func (p *GCPPlatform) reconcileCrossProjectPSCConsumer(ctx context.Context,
    hc *hyperv1.HostedCluster, customerProject string,
    serviceAttachmentURI string) (*computepb.GlobalAddress, error) {

    // Create cross-project client using service account impersonation
    customerClient, err := p.NewCrossProjectClient(ctx, customerProject, hc)
    if err != nil {
        return nil, fmt.Errorf("failed to create cross-project client: %w", err)
    }

    consumerEndpointName := fmt.Sprintf("hypershift-%s-consumer", hc.Name)

    // Create PSC consumer endpoint in customer project
    consumerEndpoint := &computepb.GlobalAddress{
        Name:        proto.String(consumerEndpointName),
        Description: proto.String(fmt.Sprintf("PSC consumer for HostedCluster %s", hc.Name)),
        Purpose:     proto.String("PRIVATE_SERVICE_CONNECT"),
        AddressType: proto.String("INTERNAL"),
        PscTarget:   proto.String(serviceAttachmentURI),
        Network:     proto.String(fmt.Sprintf("projects/%s/global/networks/%s",
                       customerProject, hc.Spec.Platform.GCP.Network.Name)),
    }

    // Check if consumer endpoint exists
    existing, err := customerClient.globalAddresses.Get(ctx, &computepb.GetGlobalAddressRequest{
        Project: customerProject,
        Address: consumerEndpointName,
    })
    if err == nil {
        return existing, nil // Already exists
    }

    // Create consumer endpoint
    operation, err := customerClient.globalAddresses.Insert(ctx, &computepb.InsertGlobalAddressRequest{
        Project:               customerProject,
        GlobalAddressResource: consumerEndpoint,
    })
    if err != nil {
        return nil, HandleGCPAPIError(err, "create PSC consumer endpoint")
    }

    if err := p.waitForGlobalOperation(ctx, customerClient, operation.GetName()); err != nil {
        return nil, fmt.Errorf("failed waiting for consumer endpoint creation: %w", err)
    }

    created, err := customerClient.globalAddresses.Get(ctx, &computepb.GetGlobalAddressRequest{
        Project: customerProject,
        Address: consumerEndpointName,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to get created consumer endpoint: %w", err)
    }

    return created, nil
}
```

### Workload Identity Management

#### Credential Reconciliation
```go
func (p *GCPPlatform) ReconcileCredentials(ctx context.Context, c client.Client,
    createOrUpdate upsert.CreateOrUpdateFN, hcluster *hyperv1.HostedCluster,
    controlPlaneNamespace string) error {

    // Note: With Terraform automation, this becomes validation-focused
    // rather than creation-focused

    // 1. Validate that required service accounts exist
    requiredSAs := []string{
        "hypershift-operator",
        "cluster-api-provider-gcp",
        "control-plane-operator",
        "gcp-cloud-controller-manager",
        "gcp-csi-driver",
    }

    for _, sa := range requiredSAs {
        if err := p.validateServiceAccountExists(ctx, sa); err != nil {
            return fmt.Errorf("required service account %s not found: %w", sa, err)
        }
    }

    // 2. Validate cross-project permissions if enabled
    if hcluster.Spec.Platform.GCP.CrossProjectWorkers != nil {
        for _, customerProject := range hcluster.Spec.Platform.GCP.CrossProjectWorkers.AllowedProjects {
            if err := p.validateCrossProjectAccess(ctx, customerProject); err != nil {
                return fmt.Errorf("insufficient access to customer project %s: %w", customerProject, err)
            }
        }
    }

    // 3. Create any cluster-specific secrets needed
    if err := p.createClusterSpecificSecrets(ctx, c, createOrUpdate, hcluster, controlPlaneNamespace); err != nil {
        return fmt.Errorf("failed to create cluster secrets: %w", err)
    }

    return nil
}
```

### CAPI Provider Configuration

#### Provider Deployment Specification
```go
func (p *GCPPlatform) CAPIProviderDeploymentSpec(hcluster *hyperv1.HostedCluster,
    hcp *hyperv1.HostedControlPlane) (*appsv1.DeploymentSpec, error) {

    return &appsv1.DeploymentSpec{
        Replicas: ptr.To(int32(1)),
        Selector: &metav1.LabelSelector{
            MatchLabels: map[string]string{
                "app": "cluster-api-provider-gcp",
            },
        },
        Template: corev1.PodTemplateSpec{
            ObjectMeta: metav1.ObjectMeta{
                Labels: map[string]string{
                    "app": "cluster-api-provider-gcp",
                },
            },
            Spec: corev1.PodSpec{
                ServiceAccountName: "cluster-api-provider-gcp",
                Containers: []corev1.Container{
                    {
                        Name:    "cluster-api-provider-gcp",
                        Image:   p.capiProviderImage,
                        Command: []string{"/manager"},
                        Args: []string{
                            "--namespace=" + hcp.Namespace,
                            "--v=2",
                        },
                        Env: []corev1.EnvVar{
                            {
                                Name:  "GCP_PROJECT",
                                Value: hcluster.Spec.Platform.GCP.Project,
                            },
                            {
                                Name:  "GCP_REGION",
                                Value: hcluster.Spec.Platform.GCP.Region,
                            },
                            {
                                Name:  "PSC_ENABLED",
                                Value: "true",
                            },
                        },
                        Resources: corev1.ResourceRequirements{
                            Requests: corev1.ResourceList{
                                corev1.ResourceCPU:    resource.MustParse("100m"),
                                corev1.ResourceMemory: resource.MustParse("128Mi"),
                            },
                            Limits: corev1.ResourceList{
                                corev1.ResourceCPU:    resource.MustParse("500m"),
                                corev1.ResourceMemory: resource.MustParse("512Mi"),
                            },
                        },
                    },
                },
            },
        },
    }, nil
}
```

### Error Handling and Retry Logic

#### GCP API Error Classification
```go
func HandleGCPAPIError(err error, operation string) error {
    if apiErr, ok := err.(*googleapi.Error); ok {
        switch apiErr.Code {
        case 403:
            if strings.Contains(apiErr.Message, "quota") {
                return NewGCPQuotaError(operation, apiErr.Message)
            }
            return NewGCPPermissionError(operation, apiErr.Message)
        case 409:
            if strings.Contains(apiErr.Message, "already exists") {
                return NewGCPConflictError(operation, apiErr.Message)
            }
        case 404:
            return NewGCPNotFoundError(operation, apiErr.Message)
        case 400:
            return NewGCPValidationError(operation, apiErr.Message)
        }
    }
    return fmt.Errorf("GCP API error during %s: %w", operation, err)
}

type GCPQuotaError struct {
    Operation string
    Message   string
}

func (e *GCPQuotaError) Error() string {
    return fmt.Sprintf("GCP quota exceeded for %s: %s", e.Operation, e.Message)
}

func (e *GCPQuotaError) Temporary() bool {
    return true // Quota errors might be temporary
}
```

#### Operation Waiting Logic
```go
func (p *GCPPlatform) waitForRegionalOperation(ctx context.Context, operationName string) error {
    timeout := time.Minute * 10
    interval := time.Second * 5

    return wait.PollImmediate(interval, timeout, func() (bool, error) {
        op, err := p.computeClient.RegionOperations.Get(ctx, &computepb.GetRegionOperationRequest{
            Project:   p.project,
            Region:    p.region,
            Operation: operationName,
        })
        if err != nil {
            return false, err
        }

        if op.Status != nil && *op.Status == "DONE" {
            if op.Error != nil {
                return false, fmt.Errorf("operation failed: %s", op.Error.Errors[0].Message)
            }
            return true, nil
        }

        return false, nil // Continue polling
    })
}
```

## Testing Strategy

### Unit Testing
```go
func TestGCPPlatform_ReconcilePSCServiceAttachment(t *testing.T) {
    tests := []struct {
        name          string
        hostedCluster *hyperv1.HostedCluster
        forwardingRule *computepb.ForwardingRule
        mockSetup     func(*MockGCPComputeClient)
        expectError   bool
        expectResult  string
    }{
        {
            name:          "successful service attachment creation",
            hostedCluster: testutil.GCPHostedCluster("test", "test-ns"),
            forwardingRule: &computepb.ForwardingRule{
                SelfLink: ptr.String("projects/test/regions/us-central1/forwardingRules/test-ilb"),
            },
            mockSetup: func(mockClient *MockGCPComputeClient) {
                mockClient.EXPECT().ServiceAttachments.Get(gomock.Any(), gomock.Any()).
                    Return(nil, &googleapi.Error{Code: 404})
                mockClient.EXPECT().ServiceAttachments.Insert(gomock.Any(), gomock.Any()).
                    Return(&compute.Operation{Name: "op-123", Status: "RUNNING"}, nil)
                mockClient.EXPECT().RegionOperations.Get(gomock.Any(), gomock.Any()).
                    Return(&compute.Operation{Name: "op-123", Status: "DONE"}, nil)
                mockClient.EXPECT().ServiceAttachments.Get(gomock.Any(), gomock.Any()).
                    Return(&computepb.ServiceAttachment{
                        Name: ptr.String("hypershift-test-psc-producer"),
                        SelfLink: ptr.String("projects/test/regions/us-central1/serviceAttachments/hypershift-test-psc-producer"),
                    }, nil)
            },
            expectError: false,
            expectResult: "hypershift-test-psc-producer",
        },
        // Additional test cases for error scenarios
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            ctrl := gomock.NewController(t)
            defer ctrl.Finish()

            mockClient := NewMockGCPComputeClient(ctrl)
            tt.mockSetup(mockClient)

            platform := &GCPPlatform{
                computeClient: mockClient,
                project:       "test-project",
                region:        "us-central1",
            }

            result, err := platform.reconcilePSCServiceAttachment(context.Background(), tt.hostedCluster, tt.forwardingRule)

            if tt.expectError {
                assert.Error(t, err)
            } else {
                assert.NoError(t, err)
                assert.Equal(t, tt.expectResult, *result.Name)
            }
        })
    }
}
```

## Component Configuration

### Platform Factory Registration
```go
// In platform/platform.go
func GetPlatform(ctx context.Context, hcluster *hyperv1.HostedCluster,
    releaseProvider releaseinfo.Provider, utilitiesImage string,
    pullSecretBytes []byte) (Platform, error) {

    switch hcluster.Spec.Platform.Type {
    case hyperv1.GCPPlatform:
        capiImageProvider, err := imgUtil.GetPayloadImage(ctx, releaseProvider,
            hcluster, GCPCAPIProvider, pullSecretBytes)
        if err != nil {
            return nil, fmt.Errorf("failed to retrieve CAPI image: %w", err)
        }
        payloadVersion, err := imgUtil.GetPayloadVersion(ctx, releaseProvider,
            hcluster, pullSecretBytes)
        if err != nil {
            return nil, fmt.Errorf("failed to fetch payload version: %w", err)
        }
        platform = gcp.New(utilitiesImage, capiImageProvider, payloadVersion)
    // ... other platforms
    }

    return platform, nil
}
```

## Security Considerations

### Authentication and Authorization
- Workload Identity for all GCP API access
- Cross-project service account impersonation
- Least privilege IAM role assignments
- No service account keys stored or transmitted

### Network Security
- Private Service Connect for secure cross-project networking
- Internal Load Balancers only (no public IPs)
- Automated firewall rules with minimal required access
- TLS encryption for all API communication

This component serves as the core GCP-specific implementation that enables HyperShift to manage infrastructure resources on Google Cloud Platform while maintaining security and isolation between different HostedClusters.