# GCP Infrastructure Manager Component Architecture (L3)

## Component Information
- **Component**: GCP Infrastructure Manager
- **Level**: L3 Component Architecture
- **Repository**: `github.com/openshift/hypershift`
- **Location**: `hypershift-operator/controllers/hostedcluster/internal/platform/gcp/infrastructure/`
- **Status**: ❌ **COMPLETELY NEW COMPONENT**
- **Version**: 1.0

## Implementation Status
- **Infrastructure Manager Pattern**: ✅ **EXISTS** - Can follow existing patterns from AWS/Azure infrastructure managers
- **GCP Infrastructure Manager**: ❌ **NEW** - Complete new implementation required
- **Internal Load Balancer Management**: ❌ **NEW** - No existing ILB management in any platform
- **Health Check Management**: ❌ **NEW** - New health check orchestration required
- **Firewall Rules Management**: ❌ **NEW** - New automated firewall rule management
- **DNS Zone Management**: ❌ **NEW** - New private DNS zone management
- **Resource Lifecycle Management**: ❌ **NEW** - New GCP-specific resource cleanup logic

## Required New Files
- `infrastructure/gcp_infrastructure_manager.go` - Main infrastructure manager
- `infrastructure/ilb_manager.go` - Internal Load Balancer management
- `infrastructure/health_check_manager.go` - Health check orchestration
- `infrastructure/firewall_manager.go` - Firewall rule management
- `infrastructure/dns_manager.go` - DNS zone management
- `infrastructure/resource_monitor.go` - Resource health monitoring

## Component Overview

The GCP Infrastructure Manager is a specialized component responsible for managing low-level GCP infrastructure resources including Internal Load Balancers, health checks, firewall rules, and DNS configurations that support the PSC architecture for HyperShift clusters.

## Component Responsibilities

### Primary Functions
1. **Internal Load Balancer Management**: Creates and manages dedicated ILBs per HostedCluster
2. **Health Check Orchestration**: Configures and monitors API server health checks
3. **Firewall Rule Management**: Automates firewall rule creation for cluster communication
4. **DNS Zone Management**: Manages private DNS zones for cluster endpoints
5. **Resource Lifecycle**: Handles creation, update, and cleanup of GCP infrastructure

### Secondary Functions
- Network configuration validation
- Resource quota monitoring
- Operation status tracking
- Cross-project resource coordination
- Error recovery and retry logic

## Detailed Architecture

### Manager Structure
```go
// Main infrastructure manager
type GCPInfrastructureManager struct {
    computeClient *compute.InstancesClient
    dnsClient     *dns.Client
    project       string
    region        string
    logger        logr.Logger
}

// Resource-specific managers
type InternalLoadBalancerManager struct {
    computeClient *compute.InstancesClient
    project       string
    region        string
}

type HealthCheckManager struct {
    computeClient *compute.InstancesClient
    project       string
}

type FirewallManager struct {
    computeClient *compute.InstancesClient
    project       string
}

type DNSManager struct {
    dnsClient *dns.Client
    project   string
}
```

### Infrastructure Resource Definitions
```go
// Infrastructure configuration for a HostedCluster
type GCPInfrastructureConfig struct {
    HostedCluster   *hyperv1.HostedCluster
    InternalLoadBalancer *InternalLoadBalancerConfig
    HealthChecks    []HealthCheckConfig
    FirewallRules   []FirewallRuleConfig
    DNSZones        []DNSZoneConfig
}

type InternalLoadBalancerConfig struct {
    Name            string
    Description     string
    BackendService  *BackendServiceConfig
    ForwardingRule  *ForwardingRuleConfig
    HealthChecks    []string
}

type BackendServiceConfig struct {
    Name               string
    LoadBalancingScheme string
    Protocol           string
    HealthChecks       []string
    Backends           []BackendConfig
}
```

### Internal Load Balancer Management

#### ILB Creation and Configuration
```go
func (m *InternalLoadBalancerManager) ReconcileInternalLoadBalancer(ctx context.Context,
    hc *hyperv1.HostedCluster) (*InternalLoadBalancerResult, error) {

    log := m.logger.WithValues("cluster", hc.Name, "operation", "reconcileILB")

    // 1. Create health check
    healthCheck, err := m.reconcileHealthCheck(ctx, hc)
    if err != nil {
        return nil, fmt.Errorf("failed to reconcile health check: %w", err)
    }

    // 2. Create backend service
    backendService, err := m.reconcileBackendService(ctx, hc, healthCheck)
    if err != nil {
        return nil, fmt.Errorf("failed to reconcile backend service: %w", err)
    }

    // 3. Create forwarding rule
    forwardingRule, err := m.reconcileForwardingRule(ctx, hc, backendService)
    if err != nil {
        return nil, fmt.Errorf("failed to reconcile forwarding rule: %w", err)
    }

    // 4. Update backend targets
    if err := m.reconcileBackendTargets(ctx, hc, backendService); err != nil {
        return nil, fmt.Errorf("failed to reconcile backend targets: %w", err)
    }

    result := &InternalLoadBalancerResult{
        HealthCheck:    healthCheck,
        BackendService: backendService,
        ForwardingRule: forwardingRule,
        Status:         "Ready",
    }

    log.Info("Internal Load Balancer reconciled successfully",
        "ilb", forwardingRule.Name,
        "ip", *forwardingRule.IPAddress)

    return result, nil
}

func (m *InternalLoadBalancerManager) reconcileHealthCheck(ctx context.Context,
    hc *hyperv1.HostedCluster) (*computepb.HealthCheck, error) {

    healthCheckName := fmt.Sprintf("hypershift-%s-api-hc", hc.Name)

    // Check if health check exists
    existing, err := m.computeClient.HealthChecks.Get(ctx, &computepb.GetHealthCheckRequest{
        Project:     m.project,
        HealthCheck: healthCheckName,
    })
    if err == nil {
        return existing, nil // Already exists
    }

    // Create new health check
    healthCheck := &computepb.HealthCheck{
        Name:        proto.String(healthCheckName),
        Description: proto.String(fmt.Sprintf("Health check for HostedCluster %s API server", hc.Name)),
        Type:        proto.String("TCP"),
        TcpHealthCheck: &computepb.TCPHealthCheck{
            Port: proto.Int32(6443),
        },
        CheckIntervalSec:   proto.Int32(10),
        TimeoutSec:        proto.Int32(5),
        HealthyThreshold:  proto.Int32(2),
        UnhealthyThreshold: proto.Int32(3),
    }

    operation, err := m.computeClient.HealthChecks.Insert(ctx, &computepb.InsertHealthCheckRequest{
        Project:           m.project,
        HealthCheckResource: healthCheck,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to create health check: %w", err)
    }

    if err := m.waitForGlobalOperation(ctx, operation.GetName()); err != nil {
        return nil, fmt.Errorf("failed waiting for health check creation: %w", err)
    }

    created, err := m.computeClient.HealthChecks.Get(ctx, &computepb.GetHealthCheckRequest{
        Project:     m.project,
        HealthCheck: healthCheckName,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to get created health check: %w", err)
    }

    return created, nil
}

func (m *InternalLoadBalancerManager) reconcileBackendService(ctx context.Context,
    hc *hyperv1.HostedCluster, healthCheck *computepb.HealthCheck) (*computepb.BackendService, error) {

    backendServiceName := fmt.Sprintf("hypershift-%s-api-backend", hc.Name)

    // Check if backend service exists
    existing, err := m.computeClient.BackendServices.Get(ctx, &computepb.GetBackendServiceRequest{
        Project:        m.project,
        BackendService: backendServiceName,
    })
    if err == nil {
        return existing, nil // Already exists
    }

    // Create new backend service
    backendService := &computepb.BackendService{
        Name:        proto.String(backendServiceName),
        Description: proto.String(fmt.Sprintf("Backend service for HostedCluster %s API server", hc.Name)),
        Protocol:    proto.String("TCP"),
        LoadBalancingScheme: proto.String("INTERNAL"),
        HealthChecks: []string{*healthCheck.SelfLink},
        SessionAffinity: proto.String("NONE"),
        TimeoutSec:     proto.Int32(30),
    }

    operation, err := m.computeClient.BackendServices.Insert(ctx, &computepb.InsertBackendServiceRequest{
        Project:               m.project,
        BackendServiceResource: backendService,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to create backend service: %w", err)
    }

    if err := m.waitForGlobalOperation(ctx, operation.GetName()); err != nil {
        return nil, fmt.Errorf("failed waiting for backend service creation: %w", err)
    }

    created, err := m.computeClient.BackendServices.Get(ctx, &computepb.GetBackendServiceRequest{
        Project:        m.project,
        BackendService: backendServiceName,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to get created backend service: %w", err)
    }

    return created, nil
}

func (m *InternalLoadBalancerManager) reconcileForwardingRule(ctx context.Context,
    hc *hyperv1.HostedCluster, backendService *computepb.BackendService) (*computepb.ForwardingRule, error) {

    forwardingRuleName := fmt.Sprintf("hypershift-%s-api-ilb", hc.Name)

    // Check if forwarding rule exists
    existing, err := m.computeClient.ForwardingRules.Get(ctx, &computepb.GetForwardingRuleRequest{
        Project:        m.project,
        Region:         m.region,
        ForwardingRule: forwardingRuleName,
    })
    if err == nil {
        return existing, nil // Already exists
    }

    // Create new forwarding rule
    forwardingRule := &computepb.ForwardingRule{
        Name:        proto.String(forwardingRuleName),
        Description: proto.String(fmt.Sprintf("Internal Load Balancer for HostedCluster %s", hc.Name)),
        IPProtocol:  proto.String("TCP"),
        Ports:       []string{"6443", "443", "22623"},
        LoadBalancingScheme: proto.String("INTERNAL"),
        BackendService: backendService.SelfLink,
        Network:     proto.String(fmt.Sprintf("projects/%s/global/networks/%s",
                       m.project, hc.Spec.Platform.GCP.Network.Name)),
        Subnetwork:  proto.String(fmt.Sprintf("projects/%s/regions/%s/subnetworks/%s",
                       m.project, m.region, hc.Spec.Platform.GCP.Network.Subnet)),
    }

    operation, err := m.computeClient.ForwardingRules.Insert(ctx, &computepb.InsertForwardingRuleRequest{
        Project:               m.project,
        Region:                m.region,
        ForwardingRuleResource: forwardingRule,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to create forwarding rule: %w", err)
    }

    if err := m.waitForRegionalOperation(ctx, operation.GetName()); err != nil {
        return nil, fmt.Errorf("failed waiting for forwarding rule creation: %w", err)
    }

    created, err := m.computeClient.ForwardingRules.Get(ctx, &computepb.GetForwardingRuleRequest{
        Project:        m.project,
        Region:         m.region,
        ForwardingRule: forwardingRuleName,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to get created forwarding rule: %w", err)
    }

    return created, nil
}
```

#### Backend Target Management
```go
func (m *InternalLoadBalancerManager) reconcileBackendTargets(ctx context.Context,
    hc *hyperv1.HostedCluster, backendService *computepb.BackendService) error {

    // Get GKE cluster node pool instances
    nodeInstances, err := m.getGKENodeInstances(ctx, hc)
    if err != nil {
        return fmt.Errorf("failed to get GKE node instances: %w", err)
    }

    // Create backend configurations for each node
    var backends []*computepb.Backend
    for _, instance := range nodeInstances {
        backend := &computepb.Backend{
            Group: proto.String(fmt.Sprintf("projects/%s/zones/%s/instanceGroups/%s",
                m.project, instance.Zone, instance.InstanceGroup)),
            BalancingMode: proto.String("UTILIZATION"),
            MaxUtilization: proto.Float64(0.8),
        }
        backends = append(backends, backend)
    }

    // Update backend service with new backends
    updateRequest := &computepb.UpdateBackendServiceRequest{
        Project:        m.project,
        BackendService: *backendService.Name,
        BackendServiceResource: &computepb.BackendService{
            Name:        backendService.Name,
            Description: backendService.Description,
            Protocol:    backendService.Protocol,
            LoadBalancingScheme: backendService.LoadBalancingScheme,
            HealthChecks: backendService.HealthChecks,
            Backends:    backends,
        },
    }

    operation, err := m.computeClient.BackendServices.Update(ctx, updateRequest)
    if err != nil {
        return fmt.Errorf("failed to update backend service: %w", err)
    }

    if err := m.waitForGlobalOperation(ctx, operation.GetName()); err != nil {
        return fmt.Errorf("failed waiting for backend service update: %w", err)
    }

    return nil
}
```

### Firewall Rules Management

#### Automated Firewall Rule Creation
```go
func (m *FirewallManager) ReconcileFirewallRules(ctx context.Context,
    hc *hyperv1.HostedCluster) error {

    log := m.logger.WithValues("cluster", hc.Name, "operation", "reconcileFirewall")

    // Define required firewall rules for the cluster
    firewallRules := []FirewallRuleSpec{
        {
            Name:        fmt.Sprintf("hypershift-%s-allow-api-server", hc.Name),
            Description: fmt.Sprintf("Allow API server traffic for HostedCluster %s", hc.Name),
            Direction:   "INGRESS",
            Priority:    1000,
            Allowed: []FirewallAllowed{
                {
                    IPProtocol: "tcp",
                    Ports:      []string{"6443", "443", "22623"},
                },
            },
            SourceRanges: []string{"10.0.0.0/8"}, // Adjust based on network configuration
            TargetTags:   []string{fmt.Sprintf("hypershift-%s-control-plane", hc.Name)},
        },
        {
            Name:        fmt.Sprintf("hypershift-%s-allow-worker-to-api", hc.Name),
            Description: fmt.Sprintf("Allow worker nodes to communicate with API server for HostedCluster %s", hc.Name),
            Direction:   "INGRESS",
            Priority:    1000,
            Allowed: []FirewallAllowed{
                {
                    IPProtocol: "tcp",
                    Ports:      []string{"6443", "10250", "10256"},
                },
            },
            SourceTags: []string{fmt.Sprintf("hypershift-%s-worker", hc.Name)},
            TargetTags: []string{fmt.Sprintf("hypershift-%s-control-plane", hc.Name)},
        },
        {
            Name:        fmt.Sprintf("hypershift-%s-allow-etcd", hc.Name),
            Description: fmt.Sprintf("Allow etcd communication for HostedCluster %s", hc.Name),
            Direction:   "INGRESS",
            Priority:    1000,
            Allowed: []FirewallAllowed{
                {
                    IPProtocol: "tcp",
                    Ports:      []string{"2379", "2380"},
                },
            },
            SourceTags: []string{fmt.Sprintf("hypershift-%s-control-plane", hc.Name)},
            TargetTags: []string{fmt.Sprintf("hypershift-%s-control-plane", hc.Name)},
        },
    }

    // Create or update each firewall rule
    for _, ruleSpec := range firewallRules {
        if err := m.reconcileFirewallRule(ctx, ruleSpec); err != nil {
            return fmt.Errorf("failed to reconcile firewall rule %s: %w", ruleSpec.Name, err)
        }
    }

    log.Info("Firewall rules reconciled successfully", "count", len(firewallRules))
    return nil
}

func (m *FirewallManager) reconcileFirewallRule(ctx context.Context,
    ruleSpec FirewallRuleSpec) error {

    // Check if firewall rule exists
    existing, err := m.computeClient.Firewalls.Get(ctx, &computepb.GetFirewallRequest{
        Project:  m.project,
        Firewall: ruleSpec.Name,
    })
    if err == nil {
        // Update existing rule if needed
        return m.updateFirewallRuleIfNeeded(ctx, existing, ruleSpec)
    }

    // Create new firewall rule
    firewall := &computepb.Firewall{
        Name:        proto.String(ruleSpec.Name),
        Description: proto.String(ruleSpec.Description),
        Direction:   proto.String(ruleSpec.Direction),
        Priority:    proto.Int32(int32(ruleSpec.Priority)),
        Network:     proto.String("global/networks/default"), // Adjust based on network
        SourceRanges: ruleSpec.SourceRanges,
        SourceTags:   ruleSpec.SourceTags,
        TargetTags:   ruleSpec.TargetTags,
    }

    // Convert allowed protocols and ports
    var allowed []*computepb.Allowed
    for _, allow := range ruleSpec.Allowed {
        allowed = append(allowed, &computepb.Allowed{
            IPProtocol: proto.String(allow.IPProtocol),
            Ports:      allow.Ports,
        })
    }
    firewall.Allowed = allowed

    operation, err := m.computeClient.Firewalls.Insert(ctx, &computepb.InsertFirewallRequest{
        Project:          m.project,
        FirewallResource: firewall,
    })
    if err != nil {
        return fmt.Errorf("failed to create firewall rule: %w", err)
    }

    if err := m.waitForGlobalOperation(ctx, operation.GetName()); err != nil {
        return fmt.Errorf("failed waiting for firewall rule creation: %w", err)
    }

    return nil
}
```

### DNS Zone Management

#### Private DNS Zone Configuration
```go
func (m *DNSManager) ReconcileDNSZones(ctx context.Context,
    hc *hyperv1.HostedCluster, ilbIP string) error {

    log := m.logger.WithValues("cluster", hc.Name, "operation", "reconcileDNS")

    // Create private DNS zone for the cluster
    zoneName := fmt.Sprintf("hypershift-%s-private", hc.Name)
    dnsName := fmt.Sprintf("%s.hypershift.local.", hc.Name)

    zone := &dns.ManagedZone{
        Name:        zoneName,
        DnsName:     dnsName,
        Description: fmt.Sprintf("Private DNS zone for HostedCluster %s", hc.Name),
        Visibility:  "private",
        PrivateVisibilityConfig: &dns.ManagedZonePrivateVisibilityConfig{
            Networks: []*dns.ManagedZonePrivateVisibilityConfigNetwork{
                {
                    NetworkUrl: fmt.Sprintf("projects/%s/global/networks/%s",
                        m.project, hc.Spec.Platform.GCP.Network.Name),
                },
            },
        },
    }

    // Create or get the managed zone
    existingZone, err := m.dnsClient.ManagedZones.Get(m.project, zoneName).Do()
    if err != nil {
        // Create new zone
        createdZone, err := m.dnsClient.ManagedZones.Create(m.project, zone).Do()
        if err != nil {
            return fmt.Errorf("failed to create DNS zone: %w", err)
        }
        existingZone = createdZone
    }

    // Create A record for API server
    apiRecord := &dns.ResourceRecordSet{
        Name:    fmt.Sprintf("api.%s", dnsName),
        Type:    "A",
        Ttl:     300,
        Rrdatas: []string{ilbIP},
    }

    // Create CNAME record for API server (alternative)
    apiInternalRecord := &dns.ResourceRecordSet{
        Name:    fmt.Sprintf("api-int.%s", dnsName),
        Type:    "A",
        Ttl:     300,
        Rrdatas: []string{ilbIP},
    }

    // Add records to the zone
    change := &dns.Change{
        Additions: []*dns.ResourceRecordSet{apiRecord, apiInternalRecord},
    }

    _, err = m.dnsClient.Changes.Create(m.project, existingZone.Name, change).Do()
    if err != nil {
        return fmt.Errorf("failed to create DNS records: %w", err)
    }

    log.Info("DNS zone reconciled successfully",
        "zone", zoneName,
        "dnsName", dnsName,
        "apiIP", ilbIP)

    return nil
}
```

### Resource Status Monitoring

#### Infrastructure Health Monitoring
```go
func (m *GCPInfrastructureManager) MonitorInfrastructureHealth(ctx context.Context,
    hc *hyperv1.HostedCluster) (*InfrastructureHealthStatus, error) {

    status := &InfrastructureHealthStatus{
        ClusterName: hc.Name,
        Timestamp:   time.Now(),
    }

    // Check ILB health
    ilbHealth, err := m.checkInternalLoadBalancerHealth(ctx, hc)
    if err != nil {
        status.Errors = append(status.Errors, fmt.Sprintf("ILB health check failed: %v", err))
    }
    status.InternalLoadBalancer = ilbHealth

    // Check health check status
    healthCheckStatus, err := m.checkHealthCheckStatus(ctx, hc)
    if err != nil {
        status.Errors = append(status.Errors, fmt.Sprintf("Health check status failed: %v", err))
    }
    status.HealthChecks = healthCheckStatus

    // Check firewall rules
    firewallStatus, err := m.checkFirewallRules(ctx, hc)
    if err != nil {
        status.Errors = append(status.Errors, fmt.Sprintf("Firewall check failed: %v", err))
    }
    status.FirewallRules = firewallStatus

    // Check DNS resolution
    dnsStatus, err := m.checkDNSResolution(ctx, hc)
    if err != nil {
        status.Errors = append(status.Errors, fmt.Sprintf("DNS check failed: %v", err))
    }
    status.DNS = dnsStatus

    // Overall health determination
    status.OverallHealth = "Healthy"
    if len(status.Errors) > 0 {
        status.OverallHealth = "Degraded"
    }

    return status, nil
}

func (m *GCPInfrastructureManager) checkInternalLoadBalancerHealth(ctx context.Context,
    hc *hyperv1.HostedCluster) (*ILBHealthStatus, error) {

    forwardingRuleName := fmt.Sprintf("hypershift-%s-api-ilb", hc.Name)

    // Get forwarding rule status
    forwardingRule, err := m.computeClient.ForwardingRules.Get(ctx, &computepb.GetForwardingRuleRequest{
        Project:        m.project,
        Region:         m.region,
        ForwardingRule: forwardingRuleName,
    })
    if err != nil {
        return &ILBHealthStatus{Status: "Error", Message: err.Error()}, err
    }

    // Get backend service health
    backendServiceName := fmt.Sprintf("hypershift-%s-api-backend", hc.Name)
    backendHealth, err := m.computeClient.BackendServices.GetHealth(ctx, &computepb.GetHealthBackendServiceRequest{
        Project:        m.project,
        BackendService: backendServiceName,
    })
    if err != nil {
        return &ILBHealthStatus{Status: "Error", Message: err.Error()}, err
    }

    // Analyze backend health
    healthyBackends := 0
    totalBackends := len(backendHealth.HealthStatus)
    for _, health := range backendHealth.HealthStatus {
        if health.HealthState != nil && *health.HealthState == "HEALTHY" {
            healthyBackends++
        }
    }

    status := &ILBHealthStatus{
        Name:            *forwardingRule.Name,
        IPAddress:       *forwardingRule.IPAddress,
        TotalBackends:   totalBackends,
        HealthyBackends: healthyBackends,
    }

    if healthyBackends == 0 {
        status.Status = "Critical"
        status.Message = "No healthy backends"
    } else if healthyBackends < totalBackends {
        status.Status = "Warning"
        status.Message = fmt.Sprintf("%d of %d backends healthy", healthyBackends, totalBackends)
    } else {
        status.Status = "Healthy"
        status.Message = "All backends healthy"
    }

    return status, nil
}
```

### Resource Cleanup

#### Infrastructure Cleanup Logic
```go
func (m *GCPInfrastructureManager) CleanupInfrastructure(ctx context.Context,
    hc *hyperv1.HostedCluster) error {

    log := m.logger.WithValues("cluster", hc.Name, "operation", "cleanup")

    var errors []error

    // Delete in reverse order to handle dependencies

    // 1. Delete DNS records and zones
    if err := m.cleanupDNSResources(ctx, hc); err != nil {
        errors = append(errors, fmt.Errorf("failed to cleanup DNS: %w", err))
    }

    // 2. Delete firewall rules
    if err := m.cleanupFirewallRules(ctx, hc); err != nil {
        errors = append(errors, fmt.Errorf("failed to cleanup firewall rules: %w", err))
    }

    // 3. Delete forwarding rules (ILB)
    if err := m.cleanupForwardingRules(ctx, hc); err != nil {
        errors = append(errors, fmt.Errorf("failed to cleanup forwarding rules: %w", err))
    }

    // 4. Delete backend services
    if err := m.cleanupBackendServices(ctx, hc); err != nil {
        errors = append(errors, fmt.Errorf("failed to cleanup backend services: %w", err))
    }

    // 5. Delete health checks
    if err := m.cleanupHealthChecks(ctx, hc); err != nil {
        errors = append(errors, fmt.Errorf("failed to cleanup health checks: %w", err))
    }

    if len(errors) > 0 {
        return fmt.Errorf("cleanup errors: %v", errors)
    }

    log.Info("Infrastructure cleanup completed successfully")
    return nil
}

func (m *GCPInfrastructureManager) cleanupForwardingRules(ctx context.Context,
    hc *hyperv1.HostedCluster) error {

    forwardingRuleName := fmt.Sprintf("hypershift-%s-api-ilb", hc.Name)

    // Check if forwarding rule exists
    _, err := m.computeClient.ForwardingRules.Get(ctx, &computepb.GetForwardingRuleRequest{
        Project:        m.project,
        Region:         m.region,
        ForwardingRule: forwardingRuleName,
    })
    if err != nil {
        // Already deleted or doesn't exist
        return nil
    }

    // Delete forwarding rule
    operation, err := m.computeClient.ForwardingRules.Delete(ctx, &computepb.DeleteForwardingRuleRequest{
        Project:        m.project,
        Region:         m.region,
        ForwardingRule: forwardingRuleName,
    })
    if err != nil {
        return fmt.Errorf("failed to delete forwarding rule: %w", err)
    }

    if err := m.waitForRegionalOperation(ctx, operation.GetName()); err != nil {
        return fmt.Errorf("failed waiting for forwarding rule deletion: %w", err)
    }

    return nil
}
```

## Configuration and Deployment

### Manager Configuration
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: gcp-infrastructure-config
  namespace: hypershift
data:
  config.yaml: |
    gcp:
      project: "management-project-id"
      region: "us-central1"
      networkTags:
        controlPlane: "hypershift-control-plane"
        worker: "hypershift-worker"
      healthCheck:
        intervalSec: 10
        timeoutSec: 5
        healthyThreshold: 2
        unhealthyThreshold: 3
      firewallPriority: 1000
      dnsConfig:
        ttl: 300
        visibility: "private"
```

### Service Account Permissions
```yaml
apiVersion: iam.cnrm.cloud.google.com/v1beta1
kind: IAMPolicy
metadata:
  name: gcp-infrastructure-manager-policy
spec:
  resourceRef:
    kind: Project
    external: "management-project-id"
  bindings:
  - role: roles/compute.loadBalancerAdmin
    members:
    - serviceAccount:gcp-infrastructure-manager@management-project-id.iam.gserviceaccount.com
  - role: roles/compute.securityAdmin
    members:
    - serviceAccount:gcp-infrastructure-manager@management-project-id.iam.gserviceaccount.com
  - role: roles/dns.admin
    members:
    - serviceAccount:gcp-infrastructure-manager@management-project-id.iam.gserviceaccount.com
```

## Testing Strategy

### Component Testing
```go
func TestGCPInfrastructureManager_ReconcileILB(t *testing.T) {
    tests := []struct {
        name         string
        hostedCluster *hyperv1.HostedCluster
        mockSetup    func(*MockGCPComputeClient)
        expectError  bool
        expectResult string
    }{
        {
            name:         "successful ILB creation",
            hostedCluster: testutil.GCPHostedCluster("test", "test-ns"),
            mockSetup: func(mockClient *MockGCPComputeClient) {
                // Mock health check creation
                mockClient.EXPECT().HealthChecks.Get(gomock.Any(), gomock.Any()).
                    Return(nil, &googleapi.Error{Code: 404})
                mockClient.EXPECT().HealthChecks.Insert(gomock.Any(), gomock.Any()).
                    Return(&compute.Operation{Name: "op-hc", Status: "DONE"}, nil)

                // Mock backend service creation
                mockClient.EXPECT().BackendServices.Get(gomock.Any(), gomock.Any()).
                    Return(nil, &googleapi.Error{Code: 404})
                mockClient.EXPECT().BackendServices.Insert(gomock.Any(), gomock.Any()).
                    Return(&compute.Operation{Name: "op-bs", Status: "DONE"}, nil)

                // Mock forwarding rule creation
                mockClient.EXPECT().ForwardingRules.Get(gomock.Any(), gomock.Any()).
                    Return(nil, &googleapi.Error{Code: 404})
                mockClient.EXPECT().ForwardingRules.Insert(gomock.Any(), gomock.Any()).
                    Return(&compute.Operation{Name: "op-fr", Status: "DONE"}, nil)
            },
            expectError:  false,
            expectResult: "10.0.0.100",
        },
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            // Test implementation
        })
    }
}
```

## Security Considerations

### Access Control
- Workload Identity for all GCP API access
- Least privilege IAM permissions
- Network policies restricting component access
- Audit logging for all infrastructure changes

### Resource Security
- Private internal load balancers only
- Firewall rules with minimal required access
- DNS zones with private visibility
- TLS encryption for all health checks

This component provides the essential infrastructure foundation that enables the PSC architecture for HyperShift, managing the low-level GCP resources that support secure and scalable hosted OpenShift clusters.