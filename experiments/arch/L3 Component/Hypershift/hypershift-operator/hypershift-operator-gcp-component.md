# HyperShift Operator GCP Component Architecture (L3)

## Component Information
- **Component**: HyperShift Operator with GCP Platform Support
- **Level**: L3 Component Architecture
- **Repository**: `github.com/openshift/hypershift`
- **Location**: `hypershift-operator/controllers/hostedcluster/`
- **Status**: 🔄 **EXISTING COMPONENT - REQUIRES EXTENSION**
- **Version**: 1.0

## Implementation Status
- **Core HyperShift Operator**: ✅ **EXISTS** - No changes required to core reconciliation logic
- **Platform Factory**: ✅ **EXISTS** - Requires adding GCP platform case in `platform/platform.go:GetPlatform()`
- **HostedCluster Controller**: ✅ **EXISTS** - Requires adding GCP platform handling
- **GCP Platform Interface**: ❌ **NEW** - Complete new implementation required in `platform/gcp/gcp.go`
- **GCP API Types**: ❌ **NEW** - New file `api/hypershift/v1beta1/gcp.go` required

## Component Overview

The HyperShift Operator GCP component is responsible for the core orchestration of HostedCluster lifecycle management on Google Cloud Platform, including PSC infrastructure provisioning and cross-project resource coordination.

## Component Responsibilities

### Primary Functions
1. **HostedCluster Reconciliation**: Manages the complete lifecycle of GCP-based HostedClusters
2. **PSC Orchestration**: Coordinates Private Service Connect infrastructure creation
3. **CAPI Integration**: Creates and manages Cluster API resources for GCP
4. **Cross-Project Management**: Orchestrates resources across management and customer projects
5. **Platform Abstraction**: Implements the HyperShift Platform interface for GCP

### Secondary Functions
- Workload Identity configuration validation
- GCP quota and permission validation
- Error aggregation and status reporting
- Finalizer management for cleanup orchestration

## Detailed Architecture

### Controller Structure
```go
// Core controller implementing the HostedCluster reconciliation loop
type HostedClusterReconciler struct {
    client.Client
    Scheme        *runtime.Scheme
    ManagementDNS hyperv1.DNSSpec
    // GCP-specific platform instances
    PlatformOperators map[hyperv1.PlatformType]controllerutil.Platform
}

// GCP-specific reconciliation logic
func (r *HostedClusterReconciler) reconcileGCPHostedCluster(
    ctx context.Context,
    req ctrl.Request,
    hcluster *hyperv1.HostedCluster,
) (ctrl.Result, error)
```

### Component Interfaces

#### Input Interfaces
```go
// Primary resource watched by the controller
type HostedCluster struct {
    Spec HostedClusterSpec {
        Platform PlatformSpec {
            Type PlatformType // Must be "GCP"
            GCP  *GCPPlatformSpec {
                Project                 string
                Region                  string
                Network                 *GCPNetworkSpec
                PrivateServiceConnect   *GCPPSCSpec
                CrossProjectWorkers     *GCPCrossProjectConfig
                KMS                     *GCPKMSSpec
                ServiceAccounts         *GCPServiceAccountsRef
            }
        }
    }
}

// Secondary resources
type NodePool struct {
    Spec NodePoolSpec {
        Platform NodePoolPlatform {
            GCP *GCPNodePoolPlatform {
                Project      string
                Zone         string
                InstanceType string
                DiskSizeGB   int32
                Subnet       string
                PSCConsumer  *GCPNodePoolPSCConsumer
            }
        }
    }
}
```

#### Output Interfaces
```go
// CAPI resources created by the component
type GCPCluster struct {
    Spec GCPClusterSpec {
        Project              string
        Region               string
        Network              NetworkSpec
        ControlPlaneEndpoint *APIEndpoint
        PrivateServiceConnect *PSCConfig {
            Enabled             bool
            ServiceAttachmentURI string
        }
    }
}

// Control plane namespace resources
type HostedControlPlane struct {
    Spec HostedControlPlaneSpec {
        Platform PlatformSpec // Propagated from HostedCluster
        // GCP-specific control plane configuration
    }
}
```

### Reconciliation Logic Flow

#### Phase 1: Validation and Preparation
```go
func (r *HostedClusterReconciler) validateGCPSpec(
    ctx context.Context,
    hcluster *hyperv1.HostedCluster,
) error {
    gcpSpec := hcluster.Spec.Platform.GCP

    // 1. Validate project ID format and existence
    if err := r.validateGCPProject(ctx, gcpSpec.Project); err != nil {
        return fmt.Errorf("invalid GCP project: %w", err)
    }

    // 2. Validate region availability
    if err := r.validateGCPRegion(ctx, gcpSpec.Region); err != nil {
        return fmt.Errorf("invalid GCP region: %w", err)
    }

    // 3. Validate network configuration
    if gcpSpec.Network != nil {
        if err := r.validateGCPNetwork(ctx, gcpSpec); err != nil {
            return fmt.Errorf("invalid network config: %w", err)
        }
    }

    // 4. Validate cross-project permissions
    if gcpSpec.CrossProjectWorkers != nil {
        if err := r.validateCrossProjectPermissions(ctx, gcpSpec); err != nil {
            return fmt.Errorf("insufficient cross-project permissions: %w", err)
        }
    }

    return nil
}
```

#### Phase 2: PSC Infrastructure Orchestration
```go
func (r *HostedClusterReconciler) reconcilePSCInfrastructure(
    ctx context.Context,
    hcluster *hyperv1.HostedCluster,
) error {
    platform := r.PlatformOperators[hyperv1.GCPPlatform]

    // 1. Create Internal Load Balancer
    ilb, err := platform.ReconcileInternalLoadBalancer(ctx, hcluster)
    if err != nil {
        return fmt.Errorf("failed to reconcile ILB: %w", err)
    }

    // 2. Create PSC Service Attachment
    pscAttachment, err := platform.ReconcilePSCServiceAttachment(ctx, hcluster, ilb)
    if err != nil {
        return fmt.Errorf("failed to reconcile PSC attachment: %w", err)
    }

    // 3. Update HostedCluster status with PSC information
    if err := r.updatePSCStatus(ctx, hcluster, pscAttachment); err != nil {
        return fmt.Errorf("failed to update PSC status: %w", err)
    }

    return nil
}
```

#### Phase 3: CAPI Resource Creation
```go
func (r *HostedClusterReconciler) reconcileCAPIResources(
    ctx context.Context,
    hcluster *hyperv1.HostedCluster,
) error {
    platform := r.PlatformOperators[hyperv1.GCPPlatform]

    // 1. Create GCPCluster with PSC configuration
    gcpCluster, err := platform.ReconcileCAPIInfraCR(
        ctx, r.Client, r.createOrUpdate, hcluster,
        hcluster.Namespace, hcluster.Spec.Networking.APIServer,
    )
    if err != nil {
        return fmt.Errorf("failed to reconcile CAPI infrastructure: %w", err)
    }

    // 2. Set controller reference for cleanup
    if err := controllerutil.SetControllerReference(hcluster, gcpCluster, r.Scheme); err != nil {
        return fmt.Errorf("failed to set controller reference: %w", err)
    }

    return nil
}
```

#### Phase 4: Control Plane Deployment
```go
func (r *HostedClusterReconciler) reconcileControlPlane(
    ctx context.Context,
    hcluster *hyperv1.HostedCluster,
) error {
    // 1. Create control plane namespace
    controlPlaneNamespace := fmt.Sprintf("clusters-%s", hcluster.Name)
    if err := r.reconcileControlPlaneNamespace(ctx, hcluster, controlPlaneNamespace); err != nil {
        return fmt.Errorf("failed to reconcile control plane namespace: %w", err)
    }

    // 2. Create HostedControlPlane resource
    hcp := &hyperv1.HostedControlPlane{
        ObjectMeta: metav1.ObjectMeta{
            Name:      hcluster.Name,
            Namespace: controlPlaneNamespace,
        },
        Spec: hyperv1.HostedControlPlaneSpec{
            Platform: hcluster.Spec.Platform, // Propagate GCP configuration
            // Additional control plane configuration
        },
    }

    if err := r.createOrUpdate(ctx, r.Client, hcp); err != nil {
        return fmt.Errorf("failed to reconcile HostedControlPlane: %w", err)
    }

    return nil
}
```

### Status Management

#### Status Structure
```go
type HostedClusterStatus struct {
    Platform *PlatformStatus {
        GCP *GCPPlatformStatus {
            InternalLoadBalancer *GCPInternalLoadBalancerStatus {
                Name      string
                IPAddress string
                Status    string
            }
            PrivateServiceConnect *GCPPSCStatus {
                ServiceAttachmentURI  string
                ServiceAttachmentName string
                Status                string
                ConnectionEndpoint    string
                ConsumerEndpoints     []GCPPSCConsumerEndpoint
            }
            WorkloadIdentity *GCPWorkloadIdentityStatus {
                ServiceAccounts map[string]string
                Status          string
            }
        }
    }
    Conditions []metav1.Condition
}
```

#### Status Update Logic
```go
func (r *HostedClusterReconciler) updateGCPStatus(
    ctx context.Context,
    hcluster *hyperv1.HostedCluster,
    pscAttachment *computepb.ServiceAttachment,
) error {
    // Initialize platform status if needed
    if hcluster.Status.Platform == nil {
        hcluster.Status.Platform = &hyperv1.PlatformStatus{}
    }
    if hcluster.Status.Platform.GCP == nil {
        hcluster.Status.Platform.GCP = &hyperv1.GCPPlatformStatus{}
    }

    // Update PSC status
    hcluster.Status.Platform.GCP.PrivateServiceConnect = &hyperv1.GCPPSCStatus{
        ServiceAttachmentURI:  *pscAttachment.SelfLink,
        ServiceAttachmentName: *pscAttachment.Name,
        Status:                "Ready",
        ConnectionEndpoint:    fmt.Sprintf("%s.%s.psc.gcp.hypershift.io",
                                hcluster.Name, hcluster.Spec.Platform.GCP.Region),
    }

    // Update conditions
    meta.SetStatusCondition(&hcluster.Status.Conditions, metav1.Condition{
        Type:    "GCPInfrastructureReady",
        Status:  metav1.ConditionTrue,
        Reason:  "PSCInfrastructureCreated",
        Message: "GCP PSC infrastructure successfully created",
    })

    return r.Status().Update(ctx, hcluster)
}
```

### Error Handling and Recovery

#### Error Categories
```go
type GCPErrorType string

const (
    GCPErrorPermissions  GCPErrorType = "InsufficientPermissions"
    GCPErrorQuotas       GCPErrorType = "QuotaExceeded"
    GCPErrorNetworking   GCPErrorType = "NetworkingError"
    GCPErrorValidation   GCPErrorType = "ValidationError"
    GCPErrorAPI          GCPErrorType = "APIError"
)

func (r *HostedClusterReconciler) handleGCPError(
    ctx context.Context,
    hcluster *hyperv1.HostedCluster,
    err error,
) (ctrl.Result, error) {
    gcpErr := classifyGCPError(err)

    switch gcpErr.Type {
    case GCPErrorPermissions:
        // Set condition and requeue with backoff
        meta.SetStatusCondition(&hcluster.Status.Conditions, metav1.Condition{
            Type:    "GCPInfrastructureReady",
            Status:  metav1.ConditionFalse,
            Reason:  "InsufficientPermissions",
            Message: gcpErr.Message,
        })
        return ctrl.Result{RequeueAfter: time.Minute * 5}, nil

    case GCPErrorQuotas:
        // Set condition and requeue with longer backoff
        return ctrl.Result{RequeueAfter: time.Minute * 15}, nil

    case GCPErrorAPI:
        // Retry with exponential backoff
        return ctrl.Result{RequeueAfter: time.Second * 30}, nil

    default:
        // Unknown error, propagate up
        return ctrl.Result{}, err
    }
}
```

### Cleanup and Finalization

#### Finalizer Management
```go
const GCPClusterFinalizer = "hypershift.openshift.io/gcp-cluster"

func (r *HostedClusterReconciler) reconcileGCPFinalization(
    ctx context.Context,
    hcluster *hyperv1.HostedCluster,
) error {
    if hcluster.DeletionTimestamp == nil {
        // Add finalizer if not present
        if !controllerutil.ContainsFinalizer(hcluster, GCPClusterFinalizer) {
            controllerutil.AddFinalizer(hcluster, GCPClusterFinalizer)
            return r.Update(ctx, hcluster)
        }
        return nil
    }

    // Handle deletion
    if controllerutil.ContainsFinalizer(hcluster, GCPClusterFinalizer) {
        if err := r.cleanupGCPResources(ctx, hcluster); err != nil {
            return fmt.Errorf("failed to cleanup GCP resources: %w", err)
        }

        controllerutil.RemoveFinalizer(hcluster, GCPClusterFinalizer)
        return r.Update(ctx, hcluster)
    }

    return nil
}
```

#### Resource Cleanup Logic
```go
func (r *HostedClusterReconciler) cleanupGCPResources(
    ctx context.Context,
    hcluster *hyperv1.HostedCluster,
) error {
    platform := r.PlatformOperators[hyperv1.GCPPlatform]

    var errs []error

    // 1. Delete PSC Service Attachment
    if err := platform.DeletePSCServiceAttachment(ctx, hcluster); err != nil {
        errs = append(errs, fmt.Errorf("failed to delete PSC attachment: %w", err))
    }

    // 2. Delete Internal Load Balancer
    if err := platform.DeleteInternalLoadBalancer(ctx, hcluster); err != nil {
        errs = append(errs, fmt.Errorf("failed to delete ILB: %w", err))
    }

    // 3. Delete cross-project resources
    if hcluster.Spec.Platform.GCP.CrossProjectWorkers != nil {
        if err := platform.DeleteCrossProjectResources(ctx, hcluster); err != nil {
            errs = append(errs, fmt.Errorf("failed to delete cross-project resources: %w", err))
        }
    }

    if len(errs) > 0 {
        return fmt.Errorf("cleanup errors: %v", errs)
    }

    return nil
}
```

## Component Configuration

### Controller Manager Integration
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hypershift-operator
spec:
  template:
    spec:
      serviceAccountName: hypershift-operator
      containers:
      - name: hypershift-operator
        image: hypershift-operator:latest
        env:
        - name: GCP_PROJECT_ID
          value: "management-project-id"
        - name: GCP_REGION
          value: "us-central1"
        args:
        - --namespace=hypershift
        - --platform=gcp
        - --enable-gcp-platform=true
```

### RBAC Requirements
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: hypershift-operator-gcp
rules:
- apiGroups: ["hypershift.openshift.io"]
  resources: ["hostedclusters", "nodepools", "hostedcontrolplanes"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["infrastructure.cluster.x-k8s.io"]
  resources: ["gcpclusters", "gcpmachines", "gcpmachinetemplates"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["secrets", "configmaps", "services", "namespaces"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

## Component Dependencies

### Internal Dependencies
- **Platform Interface**: `hypershift-operator/controllers/hostedcluster/internal/platform/platform.go`
- **GCP Platform Implementation**: `hypershift-operator/controllers/hostedcluster/internal/platform/gcp/`
- **CAPI Integration**: `hypershift-operator/controllers/hostedcluster/manifests/`
- **Utility Functions**: `support/upsert/`, `support/util/`

### External Dependencies
- **Kubernetes APIs**: `client-go`, `controller-runtime`
- **Cluster API**: `sigs.k8s.io/cluster-api`, `sigs.k8s.io/cluster-api-provider-gcp`
- **GCP SDKs**: `cloud.google.com/go/compute`, `cloud.google.com/go/iam`
- **OpenShift APIs**: `github.com/openshift/api`

## Testing Strategy

### Unit Testing
```go
func TestHostedClusterReconciler_ReconcileGCP(t *testing.T) {
    tests := []struct {
        name           string
        hostedCluster  *hyperv1.HostedCluster
        existingObjs   []client.Object
        expectedResult ctrl.Result
        expectedError  string
        validate       func(t *testing.T, client client.Client)
    }{
        {
            name: "successful GCP cluster creation",
            hostedCluster: testutil.GCPHostedCluster("test-cluster", "test-ns"),
            expectedResult: ctrl.Result{},
            validate: func(t *testing.T, client client.Client) {
                // Verify GCPCluster was created
                // Verify PSC status was updated
                // Verify conditions are set correctly
            },
        },
        // Additional test cases...
    }
}
```

### Integration Testing
- End-to-end HostedCluster lifecycle
- PSC connectivity validation
- Cross-project resource management
- Error recovery scenarios

## Metrics and Observability

### Prometheus Metrics
```go
var (
    hostedClusterReconciliations = prometheus.NewCounterVec(
        prometheus.CounterOpts{
            Name: "hypershift_hostedcluster_reconciliations_total",
            Help: "Total number of HostedCluster reconciliations",
        },
        []string{"platform", "result"},
    )

    gcpInfrastructureCreationDuration = prometheus.NewHistogramVec(
        prometheus.HistogramOpts{
            Name: "hypershift_gcp_infrastructure_creation_duration_seconds",
            Help: "Time taken to create GCP infrastructure",
        },
        []string{"resource_type"},
    )
)
```

### Logging
- Structured logging with cluster name, namespace, and operation context
- Debug logs for GCP API interactions
- Error logs with actionable error messages
- Audit logs for cross-project operations

## Security Considerations

### Access Control
- Workload Identity integration for GCP authentication
- Least privilege RBAC permissions
- Cross-project IAM boundary enforcement
- Secret management for sensitive configuration

### Network Security
- Private networking only (no public IPs)
- PSC-based isolation between clusters
- Firewall rule automation with minimal access
- TLS encryption for all communication

This component is the core orchestrator of the HyperShift GCP implementation, responsible for coordinating all other components and managing the complete lifecycle of GCP-based HostedClusters.