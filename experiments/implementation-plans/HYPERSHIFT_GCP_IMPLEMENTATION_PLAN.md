# HyperShift GCP Implementation Plan

## Overview

This document outlines the implementation of Google Cloud Platform (GCP) support for HyperShift using Private Service Connect (PSC) for secure cross-project networking between control planes and worker nodes.

## Architecture Summary

### Core Approach
- **Dedicated PSC per HostedCluster**: Each cluster gets its own PSC Service Attachment + Internal Load Balancer
- **Cross-Project Worker Nodes**: Worker nodes deployed in customer GCP projects
- **Control-Plane-First**: Establish PSC infrastructure before worker node deployment

### Component Flow
```
Management Project (per HostedCluster):
  Control Plane Pods → GKE Nodes → Internal Load Balancer → PSC Service Attachment

Customer Project (per HostedCluster):
  PSC Consumer Endpoint ← Customer VPC ← Worker Nodes
```

### Scale Constraints
- **Per Management Cluster**: 50-500 HostedClusters (limited by PSC Service Attachment quota)
- **Regional Scale**: Multiple management clusters per region for higher capacity
- **Resource Ratio**: 1:1 mapping of HostedClusters to PSC Service Attachments

---

## Implementation Phases

### Phase 1: Foundation
**Goal**: Basic GCP platform integration with minimal PSC functionality

#### Milestone 1.1: API Types and Validation
**Deliverable**: GCP platform API types that validate correctly

**Detailed Technical Tasks**:

**1. Create GCP API Types File** (`api/hypershift/v1beta1/gcp.go`):
```go
// GCPPlatformSpec defines the GCP platform configuration for HostedCluster
type GCPPlatformSpec struct {
    // Project is the GCP project ID for the management cluster infrastructure
    // +kubebuilder:validation:Required
    // +kubebuilder:validation:Pattern:=`^[a-z][a-z0-9-]{4,28}[a-z0-9]$`
    Project string `json:"project"`

    // Region is the GCP region for the HostedCluster infrastructure
    // +kubebuilder:validation:Required
    // +kubebuilder:validation:Enum:=us-central1;us-east1;us-east4;us-west1;us-west2;us-west3;us-west4;europe-west1;europe-west2;europe-west3;europe-west4;europe-west6;europe-north1;europe-central2;asia-east1;asia-east2;asia-northeast1;asia-northeast2;asia-northeast3;asia-south1;asia-southeast1;asia-southeast2;australia-southeast1;australia-southeast2;northamerica-northeast1;northamerica-northeast2;southamerica-east1
    Region string `json:"region"`

    // Network configuration for the HostedCluster
    // +optional
    Network *GCPNetworkSpec `json:"network,omitempty"`

    // PrivateServiceConnect configuration - DEDICATED ONLY
    // +optional
    PrivateServiceConnect *GCPPSCSpec `json:"privateServiceConnect,omitempty"`

    // CrossProjectWorkers enables worker nodes in separate GCP projects
    // +optional
    CrossProjectWorkers *GCPCrossProjectConfig `json:"crossProjectWorkers,omitempty"`

    // KMS configuration for secret encryption
    // +optional
    KMS *GCPKMSSpec `json:"kms,omitempty"`

    // ServiceAccounts references for GCP service accounts
    // +optional
    ServiceAccounts *GCPServiceAccountsRef `json:"serviceAccounts,omitempty"`
}

// Additional types: GCPNetworkSpec, GCPPSCSpec, GCPCrossProjectConfig, etc.
// (Full implementation as detailed in CLAUDE.md)
```

**2. Create GCP NodePool API Types** (`api/hypershift/v1beta1/gcp.go`):
```go
// GCPNodePoolPlatform defines GCP-specific NodePool configuration
type GCPNodePoolPlatform struct {
    // Project is the GCP project for worker nodes (can be different from management project)
    // +kubebuilder:validation:Required
    Project string `json:"project"`

    // Zone is the GCP zone for worker node deployment
    // +kubebuilder:validation:Required
    Zone string `json:"zone"`

    // InstanceType is the GCP machine type for worker nodes
    // +kubebuilder:validation:Required
    // +kubebuilder:default:="e2-standard-4"
    InstanceType string `json:"instanceType"`

    // DiskSizeGB is the boot disk size for worker nodes
    // +kubebuilder:validation:Minimum:=20
    // +kubebuilder:default:=100
    DiskSizeGB int32 `json:"diskSizeGB"`

    // PSCConsumer defines PSC consumer endpoint configuration for worker nodes
    // +optional
    PSCConsumer *GCPNodePoolPSCConsumer `json:"pscConsumer,omitempty"`
}
```

**3. Update PlatformSpec Enum** (`api/hypershift/v1beta1/hostedcluster_types.go`):
```go
const (
    // ... existing platforms
    GCPPlatform PlatformType = "GCP"
)

type PlatformSpec struct {
    // ... existing fields
    // GCP contains GCP-specific settings for the HostedCluster
    // +optional
    GCP *GCPPlatformSpec `json:"gcp,omitempty"`
}
```

**4. Add Platform to NodePool Types** (`api/hypershift/v1beta1/nodepool_types.go`):
```go
type NodePoolPlatform struct {
    // ... existing fields
    // GCP is the configuration used when installing on GCP.
    // +optional
    GCP *GCPNodePoolPlatform `json:"gcp,omitempty"`
}
```

**5. Generate and Validate CRDs**:
```bash
# Generate CRDs
make api
# Validate CRD generation
kubectl apply --dry-run=client -f config/crd/bases/hypershift.openshift.io_hostedclusters.yaml
kubectl apply --dry-run=client -f config/crd/bases/hypershift.openshift.io_nodepools.yaml
```

**6. Add Validation Tests** (`api/hypershift/v1beta1/gcp_test.go`):
```go
func TestGCPPlatformSpecValidation(t *testing.T) {
    tests := []struct {
        name        string
        spec        *GCPPlatformSpec
        expectValid bool
    }{
        {
            name: "valid minimal spec",
            spec: &GCPPlatformSpec{
                Project: "test-project-123",
                Region:  "us-central1",
            },
            expectValid: true,
        },
        {
            name: "invalid project format",
            spec: &GCPPlatformSpec{
                Project: "INVALID-PROJECT", // uppercase not allowed
                Region:  "us-central1",
            },
            expectValid: false,
        },
        // Additional test cases...
    }
    // Test implementation using controller-runtime validation framework
}
```

**Integration Points**:
- **File Dependencies**: Must be imported in `api/hypershift/v1beta1/zz_generated.deepcopy.go` (auto-generated)
- **Controller-Runtime Integration**: Validation markers will be processed by controller-gen
- **CAPG Compatibility**: API types must be compatible with CAPG v1beta1 API

**Acceptance Criteria**:
- [ ] GCP HostedCluster can be created with valid spec
- [ ] Validation rejects missing required fields (project, region)
- [ ] Validation rejects invalid project format (non-RFC1123 compliant)
- [ ] Validation rejects unsupported regions
- [ ] CRD generation works without errors
- [ ] API types implement JSON marshaling/unmarshaling correctly
- [ ] OpenAPI schema generation includes proper validation rules
- [ ] Unit tests cover all validation scenarios with >90% coverage

#### Milestone 1.2: Workload Identity Configuration (3 days)
**Deliverable**: Leverage existing Terraform automation for Workload Identity setup
**Simplified Approach**: The existing Terraform infrastructure in `gcp-hcp-infra/terraform/management-cluster/` already includes a comprehensive `workload_identities` module that automates Google Service Account creation, Kubernetes Service Account annotations, and cross-project IAM bindings.

**Detailed Technical Tasks**:

**1. Configure Terraform Workload Identity Module** (`instances/dev/{user}/{region}/management-cluster/terraform.tfvars`):
```hcl
# Leverage existing workload_identities module for HyperShift controllers
workload_identities = {
  "hypershift-operator" = {
    namespace = "hypershift"
    roles = [
      "roles/compute.networkAdmin",           # PSC Service Attachments
      "roles/compute.loadBalancerAdmin",      # Internal Load Balancers
      "roles/servicenetworking.networksAdmin", # PSC configuration
      "roles/dns.admin"                       # DNS zone management
    ]
    cross_project_service_accounts = {
      "customer-project-1" = ["roles/iam.serviceAccountTokenCreator"]
    }
  }
  "cluster-api-provider-gcp" = {
    namespace = "hypershift"
    roles = [
      "roles/compute.instanceAdmin",          # Worker node instances
      "roles/compute.networkUser",           # Network access
      "roles/iam.serviceAccountUser"         # Service account usage
    ]
    cross_project_service_accounts = {
      "customer-project-1" = ["roles/compute.instanceAdmin", "roles/compute.networkUser"]
    }
  }
  "control-plane-operator" = {
    namespace = "hypershift"
    roles = [
      "roles/compute.viewer",                # Resource discovery
      "roles/dns.reader"                     # DNS resolution
    ]
  }
  "gcp-cloud-controller-manager" = {
    namespace = "hypershift"
    roles = [
      "roles/compute.instanceAdmin.v1",      # Instance management
      "roles/compute.loadBalancerAdmin",     # Load balancer management
      "roles/compute.securityAdmin"          # Firewall rules
    ]
  }
  "gcp-csi-driver" = {
    namespace = "hypershift"
    roles = [
      "roles/compute.storageAdmin",          # Persistent disk management
      "roles/iam.serviceAccountUser"         # Service account usage for disk operations
    ]
  }
}
```

**Note**: Once tested and validated, this workload identity configuration should be added as the default value in the management cluster Terraform module (`terraform/management-cluster/variables.tf`) to eliminate manual configuration for future deployments.

**2. Apply Terraform Configuration**:
```bash
# Create instance directory for your management cluster
mkdir -p gcp-hcp-infra/instances/dev/{user}/{region}/management-cluster

# Copy workload identity configuration to instance directory
cp terraform.tfvars gcp-hcp-infra/instances/dev/{user}/{region}/management-cluster/

# Use tf.sh script to manage separate state files
./scripts/tf.sh instances/dev/{user}/{region}/management-cluster init
./scripts/tf.sh instances/dev/{user}/{region}/management-cluster apply
```

**3. Verify Workload Identity Setup** (`scripts/verify-workload-identity.sh`):
```bash
#!/bin/bash
# Verify that Terraform created all required Google Service Accounts
for SA in hypershift-operator cluster-api-provider-gcp control-plane-operator gcp-cloud-controller-manager gcp-csi-driver; do
    echo "Checking Google Service Account: ${SA}"
    gcloud iam service-accounts describe "${SA}@${PROJECT_ID}.iam.gserviceaccount.com"

    echo "Checking Kubernetes Service Account annotations:"
    kubectl get serviceaccount "${SA}" -n hypershift -o yaml | grep "iam.gke.io/gcp-service-account"
done
```

**Benefits of Terraform Automation**:
- **Zero Manual Setup**: All Google Service Accounts, IAM bindings, and Kubernetes Service Account annotations are created automatically
- **Cross-Project Support**: Terraform module handles complex cross-project IAM impersonation setup
- **Consistency**: Ensures all controllers get exactly the required permissions with no human error
- **Infrastructure as Code**: Workload Identity configuration is versioned and repeatable
- **Multiple Instance Support**: Using `tf.sh` script allows multiple cluster instances without conflicting Terraform state files

// ReconcileCredentials implements Platform.ReconcileCredentials
func (p *GCPPlatform) ReconcileCredentials(ctx context.Context, c client.Client, createOrUpdate upsert.CreateOrUpdateFN, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string) error {
    // 1. Create/update Google Service Accounts for PSC management
    if err := p.reconcilePSCServiceAccount(ctx, hcluster); err != nil {
        return fmt.Errorf("failed to reconcile PSC service account: %w", err)
    }

    // 2. Setup cross-project IAM bindings for customer projects
    if hcluster.Spec.Platform.GCP.CrossProjectWorkers != nil {
        if err := p.reconcileCrossProjectIAM(ctx, hcluster); err != nil {
            return fmt.Errorf("failed to reconcile cross-project IAM: %w", err)
        }
    }

    // 3. Create Kubernetes secrets with Workload Identity configuration
    if err := p.reconcileWorkloadIdentitySecrets(ctx, c, createOrUpdate, hcluster, controlPlaneNamespace); err != nil {
        return fmt.Errorf("failed to reconcile Workload Identity secrets: %w", err)
    }

    return nil
}

func (p *GCPPlatform) reconcilePSCServiceAccount(ctx context.Context, hcluster *hyperv1.HostedCluster) error {
    // Create Google Service Account for PSC operations
    saEmail := fmt.Sprintf("hypershift-%s-psc@%s.iam.gserviceaccount.com",
        hcluster.Name, hcluster.Spec.Platform.GCP.Project)

    // Check if service account exists, create if not
    // Bind required IAM roles
    requiredRoles := []string{
        "roles/compute.networkAdmin",
        "roles/compute.loadBalancerAdmin",
        "roles/servicenetworking.networksAdmin",
        "roles/dns.admin",
    }

    for _, role := range requiredRoles {
        if err := p.bindIAMRole(ctx, saEmail, role); err != nil {
            return fmt.Errorf("failed to bind role %s: %w", role, err)
        }
    }

    return nil
}
```

**4. Create Cross-Project IAM Configuration** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/cross_project_iam.go`):
```go
func (p *GCPPlatform) reconcileCrossProjectIAM(ctx context.Context, hcluster *hyperv1.HostedCluster) error {
    // Configure IAM for each allowed customer project
    for _, customerProject := range hcluster.Spec.Platform.GCP.CrossProjectWorkers.AllowedProjects {
        // Create service account for customer project operations
        customerSAEmail := fmt.Sprintf("hypershift-%s-customer@%s.iam.gserviceaccount.com",
            hcluster.Name, customerProject)

        // Configure IAM role impersonation from management project SA to customer project SA
        if err := p.configureIAMImpersonation(ctx, hcluster, customerProject, customerSAEmail); err != nil {
            return fmt.Errorf("failed to configure IAM impersonation for project %s: %w", customerProject, err)
        }
    }
    return nil
}
```

**5. Add Credential Validation Logic** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/validation.go`):
```go
func (p *GCPPlatform) ValidateCredentials(ctx context.Context, hcluster *hyperv1.HostedCluster) error {
    // Test authentication to management project
    computeClient, err := compute.NewInstancesRESTClient(ctx)
    if err != nil {
        return fmt.Errorf("failed to create compute client: %w", err)
    }
    defer computeClient.Close()

    // Test basic compute API access
    _, err = computeClient.List(ctx, &computepb.ListInstancesRequest{
        Project: hcluster.Spec.Platform.GCP.Project,
        Zone:    hcluster.Spec.Platform.GCP.Region + "-a", // Test zone
    })
    if err != nil {
        return fmt.Errorf("failed to validate compute API access: %w", err)
    }

    // Test PSC-specific permissions
    // Test cross-project access if configured
    return nil
}
```

**Integration Points**:
- **GKE Workload Identity**: Must be enabled on the management GKE cluster
- **CAPI Provider Integration**: Service accounts must be available for CAPG deployment
- **Control Plane Operator**: Credentials must be propagated to control plane namespace
- **Cross-Project Dependencies**: Customer projects must pre-exist and grant required permissions

**Testing Strategy**:
```go
// Test file: hypershift-operator/controllers/hostedcluster/internal/platform/gcp/credentials_test.go
func TestReconcileCredentials(t *testing.T) {
    // Mock GCP IAM API calls
    // Test successful credential reconciliation
    // Test error handling for permission failures
    // Test cross-project scenarios
}
```

**Required IAM Roles**:
```
hypershift-operator:
  - roles/compute.networkAdmin (PSC Service Attachments)
  - roles/compute.loadBalancerAdmin (Internal Load Balancers)
  - roles/iam.serviceAccountTokenCreator (Cross-project impersonation)

cluster-api-provider-gcp:
  - roles/compute.instanceAdmin (Worker node instances)
  - roles/compute.networkUser (Network access)
  - roles/iam.serviceAccountUser (Service account usage)

control-plane-operator:
  - roles/compute.loadBalancerAdmin (ILB backend management)
  - roles/dns.admin (DNS zone management)

gcp-cloud-controller-manager:
  - roles/compute.instanceAdmin (Node management)
  - roles/compute.loadBalancerAdmin (Service LB management)
  - roles/compute.storageAdmin (Persistent volume management)

gcp-csi-driver:
  - roles/compute.storageAdmin (Volume operations)
```

**Acceptance Criteria**:
- [ ] All 5 controllers have properly configured Workload Identity
- [ ] Can authenticate to management project using Workload Identity
- [ ] Can impersonate credentials for customer project operations
- [ ] Each controller has minimum required IAM permissions
- [ ] Clear error messages for authentication failures
- [ ] No service account keys or credential files required
- [ ] Once validated, workload identity configuration is added as default in management cluster module

#### Milestone 1.3: Basic Platform Integration
**Deliverable**: GCP platform registered in HyperShift with stub implementations

**Detailed Technical Tasks**:

**1. Create GCP Platform Implementation** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/gcp.go`):
```go
package gcp

import (
    "context"
    "fmt"

    compute "cloud.google.com/go/compute/apiv1"
    hyperv1 "github.com/openshift/hypershift/api/hypershift/v1beta1"
    "github.com/openshift/hypershift/support/upsert"
    capgv1 "sigs.k8s.io/cluster-api-provider-gcp/api/v1beta1"
    "sigs.k8s.io/controller-runtime/pkg/client"
    appsv1 "k8s.io/api/apps/v1"
    rbacv1 "k8s.io/api/rbac/v1"
)

const (
    GCPCAPIProvider = "gcp-cluster-api-controllers"
    ImageStreamCAPG = "gcp-cluster-api-controllers"
)

// GCPPlatform implements the Platform interface for GCP with dedicated PSC
type GCPPlatform struct {
    client.Client
    computeClient *compute.InstancesClient
    region        string
    project       string

    utilitiesImage    string
    capiProviderImage string
    payloadVersion    *semver.Version
}

func New(utilitiesImage string, capiProviderImage string, payloadVersion *semver.Version) *GCPPlatform {
    return &GCPPlatform{
        utilitiesImage:    utilitiesImage,
        capiProviderImage: capiProviderImage,
        payloadVersion:    payloadVersion,
    }
}

// ReconcileCAPIInfraCR implements Platform.ReconcileCAPIInfraCR
func (p *GCPPlatform) ReconcileCAPIInfraCR(ctx context.Context, c client.Client, createOrUpdate upsert.CreateOrUpdateFN, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string, apiEndpoint hyperv1.APIEndpoint) (client.Object, error) {
    // STUB: Create GCPCluster resource
    log := ctrl.LoggerFrom(ctx).WithValues("platform", "gcp", "hostedCluster", hcluster.Name)
    log.Info("Reconciling CAPI infrastructure CR - STUB IMPLEMENTATION")

    // TODO: Implement full GCPCluster creation with PSC infrastructure
    return nil, fmt.Errorf("GCP platform not fully implemented - milestone 1.3 stub")
}

// CAPIProviderDeploymentSpec implements Platform.CAPIProviderDeploymentSpec
func (p *GCPPlatform) CAPIProviderDeploymentSpec(hcluster *hyperv1.HostedCluster, hcp *hyperv1.HostedControlPlane) (*appsv1.DeploymentSpec, error) {
    // STUB: Return CAPG deployment spec
    return &appsv1.DeploymentSpec{
        Replicas: ptr.To(int32(1)),
        Template: corev1.PodTemplateSpec{
            Spec: corev1.PodSpec{
                ServiceAccountName: "cluster-api-provider-gcp",
                Containers: []corev1.Container{
                    {
                        Name:  "cluster-api-provider-gcp",
                        Image: p.capiProviderImage,
                        // TODO: Add proper container configuration
                    },
                },
            },
        },
    }, nil
}

// ReconcileCredentials implements Platform.ReconcileCredentials (from milestone 1.2)
func (p *GCPPlatform) ReconcileCredentials(ctx context.Context, c client.Client, createOrUpdate upsert.CreateOrUpdateFN, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string) error {
    // Implementation from milestone 1.2
    return nil
}

// ReconcileSecretEncryption implements Platform.ReconcileSecretEncryption
func (p *GCPPlatform) ReconcileSecretEncryption(ctx context.Context, c client.Client, createOrUpdate upsert.CreateOrUpdateFN, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string) error {
    // STUB: Implement Google Cloud KMS integration
    if hcluster.Spec.Platform.GCP.KMS != nil && hcluster.Spec.Platform.GCP.KMS.Enabled {
        return fmt.Errorf("Google Cloud KMS not implemented - milestone 1.3 stub")
    }
    return nil
}

// CAPIProviderPolicyRules implements Platform.CAPIProviderPolicyRules
func (p *GCPPlatform) CAPIProviderPolicyRules() []rbacv1.PolicyRule {
    return []rbacv1.PolicyRule{
        {
            APIGroups: ["infrastructure.cluster.x-k8s.io"],
            Resources: ["gcpclusters", "gcpmachines", "gcpmachinetemplates"],
            Verbs:     ["get", "list", "watch", "create", "update", "patch", "delete"],
        },
        {
            APIGroups: ["bootstrap.cluster.x-k8s.io"],
            Resources: ["kubeadmconfigs", "kubeadmconfigtemplates"],
            Verbs:     ["get", "list", "watch", "create", "update", "patch", "delete"],
        },
        // Additional CAPG-specific RBAC rules
    }
}

// DeleteCredentials implements Platform.DeleteCredentials
func (p *GCPPlatform) DeleteCredentials(ctx context.Context, c client.Client, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string) error {
    // STUB: Cleanup GCP resources and credentials
    log := ctrl.LoggerFrom(ctx).WithValues("platform", "gcp", "hostedCluster", hcluster.Name)
    log.Info("Deleting credentials - STUB IMPLEMENTATION")
    return nil
}
```

**2. Register GCP Platform in Factory** (`hypershift-operator/controllers/hostedcluster/internal/platform/platform.go`):
```go
// Add import
import (
    // ... existing imports
    "github.com/openshift/hypershift/hypershift-operator/controllers/hostedcluster/internal/platform/gcp"
)

// Add constant
const (
    // ... existing providers
    GCPCAPIProvider = "gcp-cluster-api-controllers"
)

// Add interface check
var _ Platform = gcp.GCPPlatform{}

// Update GetPlatform function
func GetPlatform(ctx context.Context, hcluster *hyperv1.HostedCluster, releaseProvider releaseinfo.Provider, utilitiesImage string, pullSecretBytes []byte) (Platform, error) {
    // ... existing cases
    case hyperv1.GCPPlatform:
        if pullSecretBytes != nil {
            capiImageProvider, err = imgUtil.GetPayloadImage(ctx, releaseProvider, hcluster, GCPCAPIProvider, pullSecretBytes)
            if err != nil {
                return nil, fmt.Errorf("failed to retrieve capi image: %w", err)
            }
            payloadVersion, err = imgUtil.GetPayloadVersion(ctx, releaseProvider, hcluster, pullSecretBytes)
            if err != nil {
                return nil, fmt.Errorf("failed to fetch payload version: %w", err)
            }
        }
        platform = gcp.New(utilitiesImage, capiImageProvider, payloadVersion)
    // ... existing default case
}
```

**3. Create GCP NodePool Controller Stub** (`hypershift-operator/controllers/nodepool/gcp.go`):
```go
package nodepool

import (
    "context"
    "fmt"

    hyperv1 "github.com/openshift/hypershift/api/hypershift/v1beta1"
    capiv1 "sigs.k8s.io/cluster-api/api/v1beta1"
    capgv1 "sigs.k8s.io/cluster-api-provider-gcp/api/v1beta1"
)

func (r *NodePoolReconciler) reconcileGCPNodePool(ctx context.Context, nodePool *hyperv1.NodePool, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string) error {
    log := ctrl.LoggerFrom(ctx).WithValues("platform", "gcp", "nodePool", nodePool.Name)
    log.Info("Reconciling GCP NodePool - STUB IMPLEMENTATION")

    // STUB: Create GCPMachineTemplate and MachineDeployment
    // TODO: Implement full NodePool reconciliation with PSC consumer creation
    return fmt.Errorf("GCP NodePool reconciliation not implemented - milestone 1.3 stub")
}
```

**4. Update HostedCluster Controller** (`hypershift-operator/controllers/hostedcluster/hostedcluster_controller.go`):
```go
// Ensure GCP case is handled in platform switch statements
func (r *HostedClusterReconciler) reconcilePlatform(ctx context.Context, hcluster *hyperv1.HostedCluster) error {
    switch hcluster.Spec.Platform.Type {
    // ... existing cases
    case hyperv1.GCPPlatform:
        return r.reconcileGCPPlatform(ctx, hcluster)
    // ... existing default case
    }
}
```

**5. Add Comprehensive Error Handling** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/errors.go`):
```go
package gcp

import (
    "errors"
    "fmt"
    "strings"

    "google.golang.org/api/googleapi"
)

// GCPError wraps GCP API errors with additional context
type GCPError struct {
    Operation string
    Resource  string
    Err       error
}

func (e *GCPError) Error() string {
    return fmt.Sprintf("GCP operation %s failed for resource %s: %v", e.Operation, e.Resource, e.Err)
}

// HandleGCPAPIError provides specific guidance for common GCP API errors
func HandleGCPAPIError(err error, operation string) error {
    if apiErr, ok := err.(*googleapi.Error); ok {
        switch apiErr.Code {
        case 403:
            if strings.Contains(apiErr.Message, "compute.serviceAttachments.create") {
                return fmt.Errorf("insufficient permissions to create PSC producer endpoint. "+
                    "Ensure service account has 'roles/compute.networkAdmin' role: %w", err)
            }
        case 409:
            if strings.Contains(apiErr.Message, "already exists") {
                return fmt.Errorf("resource already exists, check for naming conflicts: %w", err)
            }
        case 400:
            if strings.Contains(apiErr.Message, "Invalid value for field") {
                return fmt.Errorf("invalid configuration for %s. "+
                    "Check resource specifications: %w", operation, err)
            }
        }
    }
    return &GCPError{Operation: operation, Err: err}
}
```

**6. Add Logging Configuration** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/logging.go`):
```go
// Structured logging helpers for GCP operations
func (p *GCPPlatform) logGCPOperation(ctx context.Context, operation, resource string) {
    log := ctrl.LoggerFrom(ctx).WithValues(
        "platform", "gcp",
        "operation", operation,
        "resource", resource,
        "project", p.project,
        "region", p.region,
    )
    log.Info("Executing GCP operation")
}
```

**Integration Points**:
- **CAPG Dependency**: Must import `sigs.k8s.io/cluster-api-provider-gcp/api/v1beta1`
- **Controller Registration**: Platform must be registered in controller startup
- **RBAC Configuration**: Additional permissions needed for GCP resources
- **Webhook Integration**: Platform validation hooks for HostedCluster admission

**Testing Strategy**:
```go
// Test file: hypershift-operator/controllers/hostedcluster/internal/platform/gcp/gcp_test.go
func TestGCPPlatformStubs(t *testing.T) {
    platform := New("", "", nil)

    // Test all Platform interface methods return appropriate errors
    ctx := context.Background()
    hcluster := &hyperv1.HostedCluster{/* test spec */}

    // Test ReconcileCAPIInfraCR returns not implemented error
    _, err := platform.ReconcileCAPIInfraCR(ctx, nil, nil, hcluster, "", hyperv1.APIEndpoint{})
    assert.Contains(t, err.Error(), "stub")

    // Test other interface methods similarly
}
```

---

### Phase 2: PSC Infrastructure

#### Milestone 2.1: Internal Load Balancer Management
**Deliverable**: Create and manage ILBs for HostedClusters

**Detailed Technical Tasks**:

**1. Implement Health Check Management** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/ilb_health_check.go`):
```go
package gcp

import (
    "context"
    "fmt"

    compute "cloud.google.com/go/compute/apiv1"
    "cloud.google.com/go/compute/apiv1/computepb"
    hyperv1 "github.com/openshift/hypershift/api/hypershift/v1beta1"
)

// reconcileHealthCheck creates/updates health check for API server
func (p *GCPPlatform) reconcileHealthCheck(ctx context.Context, hc *hyperv1.HostedCluster) (*computepb.HealthCheck, error) {
    healthCheckName := fmt.Sprintf("hypershift-%s-api-hc", hc.Name)

    healthCheck := &computepb.HealthCheck{
        Name:        &healthCheckName,
        Description: ptr.String(fmt.Sprintf("Health check for HostedCluster %s API server", hc.Name)),
        Type:        ptr.String("TCP"),
        TcpHealthCheck: &computepb.TCPHealthCheck{
            Port: ptr.Int32(6443), // Kubernetes API server port
        },
        CheckIntervalSec:   ptr.Int32(10),  // Check every 10 seconds
        TimeoutSec:        ptr.Int32(5),   // 5 second timeout
        HealthyThreshold:  ptr.Int32(2),   // 2 consecutive successes = healthy
        UnhealthyThreshold: ptr.Int32(3),  // 3 consecutive failures = unhealthy
    }

    // Use exponential backoff for GCP API calls
    operation, err := p.computeClient.HealthChecks.Insert(ctx, &computepb.InsertHealthCheckRequest{
        Project:           p.project,
        HealthCheckResource: healthCheck,
    })
    if err != nil {
        return nil, HandleGCPAPIError(err, "create health check")
    }

    // Wait for operation completion
    if err := p.waitForGlobalOperation(ctx, operation.GetName()); err != nil {
        return nil, fmt.Errorf("failed waiting for health check creation: %w", err)
    }

    // Retrieve the created health check
    return p.computeClient.HealthChecks.Get(ctx, &computepb.GetHealthCheckRequest{
        Project:     p.project,
        HealthCheck: healthCheckName,
    })
}

// deleteHealthCheck removes health check during cleanup
func (p *GCPPlatform) deleteHealthCheck(ctx context.Context, hc *hyperv1.HostedCluster) error {
    healthCheckName := fmt.Sprintf("hypershift-%s-api-hc", hc.Name)

    operation, err := p.computeClient.HealthChecks.Delete(ctx, &computepb.DeleteHealthCheckRequest{
        Project:     p.project,
        HealthCheck: healthCheckName,
    })
    if err != nil {
        // Ignore 404 errors - resource already deleted
        if apiErr, ok := err.(*googleapi.Error); ok && apiErr.Code == 404 {
            return nil
        }
        return HandleGCPAPIError(err, "delete health check")
    }

    return p.waitForGlobalOperation(ctx, operation.GetName())
}
```

**2. Implement Backend Service Management** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/ilb_backend_service.go`):
```go
// reconcileBackendService creates/updates backend service for control plane pods
func (p *GCPPlatform) reconcileBackendService(ctx context.Context, hc *hyperv1.HostedCluster, healthCheck *computepb.HealthCheck) (*computepb.BackendService, error) {
    backendServiceName := fmt.Sprintf("hypershift-%s-api-backend", hc.Name)

    backendService := &computepb.BackendService{
        Name:        &backendServiceName,
        Description: ptr.String(fmt.Sprintf("Backend service for HostedCluster %s API server", hc.Name)),
        Protocol:    ptr.String("TCP"),
        LoadBalancingScheme: ptr.String("INTERNAL"),

        // Session affinity for API server connections
        SessionAffinity: ptr.String("CLIENT_IP"),

        // Health check configuration
        HealthChecks: []string{
            fmt.Sprintf("projects/%s/global/healthChecks/%s", p.project, *healthCheck.Name),
        },

        // Configure backend timeouts
        TimeoutSec: ptr.Int32(30), // 30 second timeout for API calls

        // Backend configuration
        Backends: []*computepb.Backend{
            {
                Description: ptr.String("GKE nodes running control plane pods"),
                Group:       ptr.String(p.getGKEInstanceGroupURL(ctx, hc)),
                BalancingMode: ptr.String("CONNECTION"),
                MaxConnections: ptr.Int32(1000), // Max connections per backend
            },
        },
    }

    operation, err := p.computeClient.BackendServices.Insert(ctx, &computepb.InsertBackendServiceRequest{
        Project:               p.project,
        Region:                p.region,
        BackendServiceResource: backendService,
    })
    if err != nil {
        return nil, HandleGCPAPIError(err, "create backend service")
    }

    if err := p.waitForRegionalOperation(ctx, operation.GetName()); err != nil {
        return nil, fmt.Errorf("failed waiting for backend service creation: %w", err)
    }

    return p.computeClient.BackendServices.Get(ctx, &computepb.GetBackendServiceRequest{
        Project:        p.project,
        Region:         p.region,
        BackendService: backendServiceName,
    })
}

// getGKEInstanceGroupURL returns the instance group URL for GKE nodes
func (p *GCPPlatform) getGKEInstanceGroupURL(ctx context.Context, hc *hyperv1.HostedCluster) string {
    // Get GKE cluster instance group
    // This will target the GKE nodes where control plane pods are running
    gkeClusterName := fmt.Sprintf("hypershift-mgmt-%s", p.region)

    // Instance group URL format for GKE
    return fmt.Sprintf("projects/%s/zones/%s-a/instanceGroups/gke-%s-default-pool",
        p.project, p.region, gkeClusterName)
}
```

**3. Implement Forwarding Rule (ILB) Management** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/ilb_forwarding_rule.go`):
```go
// reconcileForwardingRule creates/updates the Internal Load Balancer
func (p *GCPPlatform) reconcileForwardingRule(ctx context.Context, hc *hyperv1.HostedCluster, backendService *computepb.BackendService) (*computepb.ForwardingRule, error) {
    forwardingRuleName := fmt.Sprintf("hypershift-%s-api-ilb", hc.Name)

    forwardingRule := &computepb.ForwardingRule{
        Name:        &forwardingRuleName,
        Description: ptr.String(fmt.Sprintf("Internal Load Balancer for HostedCluster %s", hc.Name)),

        // ILB configuration
        LoadBalancingScheme: ptr.String("INTERNAL"),
        IPProtocol:          ptr.String("TCP"),

        // Ports for Kubernetes API and other control plane services
        Ports: []string{"6443", "443", "22623"},

        // Backend service reference
        BackendService: ptr.String(fmt.Sprintf("projects/%s/regions/%s/backendServices/%s",
            p.project, p.region, *backendService.Name)),

        // Network configuration
        Network: ptr.String(fmt.Sprintf("projects/%s/global/networks/%s",
            p.project, hc.Spec.Platform.GCP.Network.Name)),
        Subnetwork: ptr.String(fmt.Sprintf("projects/%s/regions/%s/subnetworks/%s",
            p.project, p.region, hc.Spec.Platform.GCP.Network.Subnet)),

        // Let GCP assign an IP automatically
        IPAddress: nil, // Auto-assigned internal IP
    }

    operation, err := p.computeClient.ForwardingRules.Insert(ctx, &computepb.InsertForwardingRuleRequest{
        Project:                p.project,
        Region:                 p.region,
        ForwardingRuleResource: forwardingRule,
    })
    if err != nil {
        return nil, HandleGCPAPIError(err, "create forwarding rule")
    }

    if err := p.waitForRegionalOperation(ctx, operation.GetName()); err != nil {
        return nil, fmt.Errorf("failed waiting for forwarding rule creation: %w", err)
    }

    // Get the created forwarding rule with assigned IP
    createdRule, err := p.computeClient.ForwardingRules.Get(ctx, &computepb.GetForwardingRuleRequest{
        Project:        p.project,
        Region:         p.region,
        ForwardingRule: forwardingRuleName,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to get created forwarding rule: %w", err)
    }

    // Log the assigned IP address
    log := ctrl.LoggerFrom(ctx)
    log.Info("ILB created with assigned IP", "ip", *createdRule.IPAddress, "name", forwardingRuleName)

    return createdRule, nil
}
```

**4. Implement IP Discovery and Status Updates** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/ilb_status.go`):
```go
// updateHostedClusterStatus updates the HostedCluster status with ILB information
func (p *GCPPlatform) updateHostedClusterStatus(ctx context.Context, c client.Client, hc *hyperv1.HostedCluster, forwardingRule *computepb.ForwardingRule) error {
    // Update HostedCluster status with ILB IP
    hc.Status.Platform = &hyperv1.PlatformStatus{
        GCP: &hyperv1.GCPPlatformStatus{
            InternalLoadBalancer: &hyperv1.GCPInternalLoadBalancerStatus{
                Name:      *forwardingRule.Name,
                IPAddress: *forwardingRule.IPAddress,
                Status:    "Ready",
            },
        },
    }

    // Add condition for ILB readiness
    meta.SetStatusCondition(&hc.Status.Conditions, metav1.Condition{
        Type:    "GCPInternalLoadBalancerReady",
        Status:  metav1.ConditionTrue,
        Reason:  "InternalLoadBalancerCreated",
        Message: fmt.Sprintf("Internal Load Balancer created with IP %s", *forwardingRule.IPAddress),
    })

    return c.Status().Update(ctx, hc)
}

// getILBIPAddress retrieves the current IP address of the ILB
func (p *GCPPlatform) getILBIPAddress(ctx context.Context, hc *hyperv1.HostedCluster) (string, error) {
    forwardingRuleName := fmt.Sprintf("hypershift-%s-api-ilb", hc.Name)

    forwardingRule, err := p.computeClient.ForwardingRules.Get(ctx, &computepb.GetForwardingRuleRequest{
        Project:        p.project,
        Region:         p.region,
        ForwardingRule: forwardingRuleName,
    })
    if err != nil {
        return "", HandleGCPAPIError(err, "get forwarding rule")
    }

    if forwardingRule.IPAddress == nil {
        return "", fmt.Errorf("forwarding rule %s has no IP address assigned", forwardingRuleName)
    }

    return *forwardingRule.IPAddress, nil
}
```

**5. Implement Resource Cleanup** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/ilb_cleanup.go`):
```go
// deleteILBResources removes all ILB-related resources during cluster deletion
func (p *GCPPlatform) deleteILBResources(ctx context.Context, hc *hyperv1.HostedCluster) error {
    log := ctrl.LoggerFrom(ctx).WithValues("cluster", hc.Name, "operation", "deleteILB")

    var errs []error

    // Delete in reverse order: forwarding rule, backend service, health check

    // 1. Delete forwarding rule
    if err := p.deleteForwardingRule(ctx, hc); err != nil {
        log.Error(err, "failed to delete forwarding rule")
        errs = append(errs, err)
    }

    // 2. Delete backend service
    if err := p.deleteBackendService(ctx, hc); err != nil {
        log.Error(err, "failed to delete backend service")
        errs = append(errs, err)
    }

    // 3. Delete health check
    if err := p.deleteHealthCheck(ctx, hc); err != nil {
        log.Error(err, "failed to delete health check")
        errs = append(errs, err)
    }

    if len(errs) > 0 {
        return fmt.Errorf("failed to delete ILB resources: %v", errs)
    }

    log.Info("Successfully deleted all ILB resources")
    return nil
}

func (p *GCPPlatform) deleteForwardingRule(ctx context.Context, hc *hyperv1.HostedCluster) error {
    forwardingRuleName := fmt.Sprintf("hypershift-%s-api-ilb", hc.Name)

    operation, err := p.computeClient.ForwardingRules.Delete(ctx, &computepb.DeleteForwardingRuleRequest{
        Project:        p.project,
        Region:         p.region,
        ForwardingRule: forwardingRuleName,
    })
    if err != nil {
        if apiErr, ok := err.(*googleapi.Error); ok && apiErr.Code == 404 {
            return nil // Already deleted
        }
        return HandleGCPAPIError(err, "delete forwarding rule")
    }

    return p.waitForRegionalOperation(ctx, operation.GetName())
}

func (p *GCPPlatform) deleteBackendService(ctx context.Context, hc *hyperv1.HostedCluster) error {
    backendServiceName := fmt.Sprintf("hypershift-%s-api-backend", hc.Name)

    operation, err := p.computeClient.BackendServices.Delete(ctx, &computepb.DeleteBackendServiceRequest{
        Project:        p.project,
        Region:         p.region,
        BackendService: backendServiceName,
    })
    if err != nil {
        if apiErr, ok := err.(*googleapi.Error); ok && apiErr.Code == 404 {
            return nil // Already deleted
        }
        return HandleGCPAPIError(err, "delete backend service")
    }

    return p.waitForRegionalOperation(ctx, operation.GetName())
}
```

**6. Integrate ILB Management into Platform** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/gcp.go`):
```go
// Update ReconcileCAPIInfraCR to include ILB creation
func (p *GCPPlatform) ReconcileCAPIInfraCR(ctx context.Context, c client.Client, createOrUpdate upsert.CreateOrUpdateFN, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string, apiEndpoint hyperv1.APIEndpoint) (client.Object, error) {
    // 1. Create health check
    healthCheck, err := p.reconcileHealthCheck(ctx, hcluster)
    if err != nil {
        return nil, fmt.Errorf("failed to reconcile health check: %w", err)
    }

    // 2. Create backend service
    backendService, err := p.reconcileBackendService(ctx, hcluster, healthCheck)
    if err != nil {
        return nil, fmt.Errorf("failed to reconcile backend service: %w", err)
    }

    // 3. Create forwarding rule (ILB)
    forwardingRule, err := p.reconcileForwardingRule(ctx, hcluster, backendService)
    if err != nil {
        return nil, fmt.Errorf("failed to reconcile forwarding rule: %w", err)
    }

    // 4. Update HostedCluster status with ILB information
    if err := p.updateHostedClusterStatus(ctx, c, hcluster, forwardingRule); err != nil {
        return nil, fmt.Errorf("failed to update cluster status: %w", err)
    }

    // TODO: Continue with PSC Service Attachment creation (Milestone 2.2)
    return nil, nil
}

// Update DeleteCredentials to include ILB cleanup
func (p *GCPPlatform) DeleteCredentials(ctx context.Context, c client.Client, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string) error {
    // Clean up ILB resources
    if err := p.deleteILBResources(ctx, hcluster); err != nil {
        return fmt.Errorf("failed to delete ILB resources: %w", err)
    }

    // TODO: Clean up other resources (PSC, credentials, etc.)
    return nil
}
```

**Integration Points**:
- **GKE Instance Groups**: ILB backends must target GKE node instance groups
- **Network Configuration**: Must use existing VPC/subnet from HostedCluster spec
- **Health Check Integration**: Must properly check API server health on port 6443
- **Status Management**: ILB IP must be propagated to HostedCluster status for PSC usage

**Testing Strategy**:
```go
// Test file: hypershift-operator/controllers/hostedcluster/internal/platform/gcp/ilb_test.go
func TestReconcileILBResources(t *testing.T) {
    tests := []struct {
        name          string
        hostedCluster *hyperv1.HostedCluster
        expectError   bool
        mockCalls     func(*MockGCPComputeClient)
    }{
        {
            name: "successful ILB creation",
            hostedCluster: testutil.MinimalGCPHostedCluster("test-cluster", "test-namespace"),
            expectError: false,
            mockCalls: func(mockGCP *MockGCPComputeClient) {
                // Mock health check creation
                mockGCP.EXPECT().InsertHealthCheck(gomock.Any(), gomock.Any()).Return(&compute.Operation{Status: "DONE"}, nil)
                // Mock backend service creation
                mockGCP.EXPECT().InsertBackendService(gomock.Any(), gomock.Any()).Return(&compute.Operation{Status: "DONE"}, nil)
                // Mock forwarding rule creation
                mockGCP.EXPECT().InsertForwardingRule(gomock.Any(), gomock.Any()).Return(&compute.Operation{Status: "DONE"}, nil)
            },
        },
        // Additional test cases for error scenarios
    }
    // Test implementation...
}
```

#### Milestone 2.2: PSC Service Attachment Creation
**Deliverable**: PSC Service Attachments targeting ILBs

**Detailed Technical Tasks**:

**1. Implement NAT Subnet Management** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/psc_nat_subnet.go`):
```go
package gcp

import (
    "context"
    "fmt"

    compute "cloud.google.com/go/compute/apiv1"
    "cloud.google.com/go/compute/apiv1/computepb"
    hyperv1 "github.com/openshift/hypershift/api/hypershift/v1beta1"
)

// reconcilePSCNATSubnet creates/manages NAT subnet for PSC operations
func (p *GCPPlatform) reconcilePSCNATSubnet(ctx context.Context, hc *hyperv1.HostedCluster) (*computepb.Subnetwork, error) {
    natSubnetName := fmt.Sprintf("hypershift-psc-nat-%s", hc.Name)

    // Check if NAT subnet is specified in spec, otherwise create one
    var natSubnetCIDR string
    if hc.Spec.Platform.GCP.PrivateServiceConnect != nil && hc.Spec.Platform.GCP.PrivateServiceConnect.NATSubnet != "" {
        // Use existing NAT subnet
        return p.getSubnetwork(ctx, hc.Spec.Platform.GCP.PrivateServiceConnect.NATSubnet)
    }

    // Auto-generate NAT subnet CIDR (must not conflict with existing subnets)
    natSubnetCIDR = p.generateNATSubnetCIDR(ctx, hc)

    natSubnet := &computepb.Subnetwork{
        Name:        &natSubnetName,
        Description: ptr.String(fmt.Sprintf("NAT subnet for PSC operations - HostedCluster %s", hc.Name)),
        Network: ptr.String(fmt.Sprintf("projects/%s/global/networks/%s",
            p.project, hc.Spec.Platform.GCP.Network.Name)),
        IpCidrRange: &natSubnetCIDR,
        Region:      &p.region,

        // PSC-specific configuration
        Purpose: ptr.String("PRIVATE_SERVICE_CONNECT"),
        Role:    ptr.String("ACTIVE"), // ACTIVE role for PSC NAT
    }

    operation, err := p.computeClient.Subnetworks.Insert(ctx, &computepb.InsertSubnetworkRequest{
        Project:           p.project,
        Region:            p.region,
        SubnetworkResource: natSubnet,
    })
    if err != nil {
        return nil, HandleGCPAPIError(err, "create PSC NAT subnet")
    }

    if err := p.waitForRegionalOperation(ctx, operation.GetName()); err != nil {
        return nil, fmt.Errorf("failed waiting for NAT subnet creation: %w", err)
    }

    return p.computeClient.Subnetworks.Get(ctx, &computepb.GetSubnetworkRequest{
        Project:    p.project,
        Region:     p.region,
        Subnetwork: natSubnetName,
    })
}

// generateNATSubnetCIDR generates a non-conflicting CIDR for NAT subnet
func (p *GCPPlatform) generateNATSubnetCIDR(ctx context.Context, hc *hyperv1.HostedCluster) string {
    // Use cluster-specific CIDR range to avoid conflicts
    // PSC NAT subnets typically use /28 (16 IPs)
    clusterIndex := p.getClusterIndex(hc.Name) // Hash cluster name to get index

    // Use 192.168.X.0/28 range where X is derived from cluster name
    thirdOctet := 100 + (clusterIndex % 155) // Range: 192.168.100.0/28 to 192.168.255.0/28

    return fmt.Sprintf("192.168.%d.0/28", thirdOctet)
}

func (p *GCPPlatform) getClusterIndex(clusterName string) int {
    // Simple hash function to get cluster index
    hash := 0
    for _, c := range clusterName {
        hash = hash*31 + int(c)
    }
    if hash < 0 {
        hash = -hash
    }
    return hash
}
```

**2. Implement PSC Service Attachment Creation** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/psc_service_attachment.go`):
```go
// reconcilePSCServiceAttachment creates/manages PSC Service Attachment
func (p *GCPPlatform) reconcilePSCServiceAttachment(ctx context.Context, hc *hyperv1.HostedCluster, forwardingRule *computepb.ForwardingRule, natSubnet *computepb.Subnetwork) (*computepb.ServiceAttachment, error) {
    serviceAttachmentName := fmt.Sprintf("hypershift-%s-psc-producer", hc.Name)

    // Override name if specified in spec
    if hc.Spec.Platform.GCP.PrivateServiceConnect != nil && hc.Spec.Platform.GCP.PrivateServiceConnect.ProducerServiceName != "" {
        serviceAttachmentName = hc.Spec.Platform.GCP.PrivateServiceConnect.ProducerServiceName
    }

    serviceAttachment := &computepb.ServiceAttachment{
        Name:        &serviceAttachmentName,
        Description: ptr.String(fmt.Sprintf("PSC Service Attachment for HostedCluster %s", hc.Name)),

        // Target the ILB forwarding rule
        TargetService: ptr.String(fmt.Sprintf("projects/%s/regions/%s/forwardingRules/%s",
            p.project, p.region, *forwardingRule.Name)),

        // Connection configuration
        ConnectionPreference: ptr.String("ACCEPT_AUTOMATIC"), // Auto-accept connections

        // NAT subnets for PSC operations
        NatSubnets: []string{
            fmt.Sprintf("projects/%s/regions/%s/subnetworks/%s",
                p.project, p.region, *natSubnet.Name),
        },

        // Enable proxy protocol for client IP preservation
        EnableProxyProtocol: ptr.Bool(false), // Disable for simplicity initially

        // Consumer project restrictions (if specified)
        ConsumerRejectLists:     p.buildConsumerRejectLists(hc),
        ConsumerAcceptLists:     p.buildConsumerAcceptLists(hc),

        // Domain name for PSC endpoint
        DomainNames: []string{
            fmt.Sprintf("%s.%s.psc.gcp.hypershift.io", hc.Name, p.region),
        },
    }

    operation, err := p.computeClient.ServiceAttachments.Insert(ctx, &computepb.InsertServiceAttachmentRequest{
        Project:                 p.project,
        Region:                  p.region,
        ServiceAttachmentResource: serviceAttachment,
    })
    if err != nil {
        return nil, HandleGCPAPIError(err, "create PSC service attachment")
    }

    if err := p.waitForRegionalOperation(ctx, operation.GetName()); err != nil {
        return nil, fmt.Errorf("failed waiting for service attachment creation: %w", err)
    }

    createdAttachment, err := p.computeClient.ServiceAttachments.Get(ctx, &computepb.GetServiceAttachmentRequest{
        Project:           p.project,
        Region:            p.region,
        ServiceAttachment: serviceAttachmentName,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to get created service attachment: %w", err)
    }

    log := ctrl.LoggerFrom(ctx)
    log.Info("PSC Service Attachment created", "name", serviceAttachmentName, "uri", *createdAttachment.SelfLink)

    return createdAttachment, nil
}

// buildConsumerAcceptLists builds allowed consumer projects list
func (p *GCPPlatform) buildConsumerAcceptLists(hc *hyperv1.HostedCluster) []*computepb.ServiceAttachmentConsumerProjectLimit {
    if hc.Spec.Platform.GCP.PrivateServiceConnect == nil || len(hc.Spec.Platform.GCP.PrivateServiceConnect.ConsumerProjects) == 0 {
        return nil // No restrictions - accept all
    }

    var acceptLists []*computepb.ServiceAttachmentConsumerProjectLimit
    for _, consumerProject := range hc.Spec.Platform.GCP.PrivateServiceConnect.ConsumerProjects {
        acceptLists = append(acceptLists, &computepb.ServiceAttachmentConsumerProjectLimit{
            ProjectIdOrNum: ptr.String(consumerProject.ProjectID),
            ConnectionLimit: ptr.Int32(10), // Max 10 connections per customer project
        })
    }

    return acceptLists
}

// buildConsumerRejectLists builds rejected consumer projects list (if needed)
func (p *GCPPlatform) buildConsumerRejectLists(hc *hyperv1.HostedCluster) []string {
    // For now, no explicit reject lists - rely on accept lists
    return nil
}
```

**3. Implement PSC Status Tracking** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/psc_status.go`):
```go
// updatePSCStatus updates HostedCluster status with PSC information
func (p *GCPPlatform) updatePSCStatus(ctx context.Context, c client.Client, hc *hyperv1.HostedCluster, serviceAttachment *computepb.ServiceAttachment) error {
    // Update platform status with PSC information
    if hc.Status.Platform == nil {
        hc.Status.Platform = &hyperv1.PlatformStatus{}
    }
    if hc.Status.Platform.GCP == nil {
        hc.Status.Platform.GCP = &hyperv1.GCPPlatformStatus{}
    }

    hc.Status.Platform.GCP.PrivateServiceConnect = &hyperv1.GCPPSCStatus{
        ServiceAttachmentURI: *serviceAttachment.SelfLink,
        ServiceAttachmentName: *serviceAttachment.Name,
        Status: "Ready",
        ConnectionEndpoint: fmt.Sprintf("%s.%s.psc.gcp.hypershift.io", hc.Name, p.region),
    }

    // Add condition for PSC readiness
    meta.SetStatusCondition(&hc.Status.Conditions, metav1.Condition{
        Type:    "GCPPrivateServiceConnectReady",
        Status:  metav1.ConditionTrue,
        Reason:  "ServiceAttachmentCreated",
        Message: fmt.Sprintf("PSC Service Attachment %s created and ready", *serviceAttachment.Name),
    })

    return c.Status().Update(ctx, hc)
}

// monitorPSCConnections monitors active PSC connections
func (p *GCPPlatform) monitorPSCConnections(ctx context.Context, hc *hyperv1.HostedCluster) error {
    serviceAttachmentName := fmt.Sprintf("hypershift-%s-psc-producer", hc.Name)

    // Get current service attachment status
    serviceAttachment, err := p.computeClient.ServiceAttachments.Get(ctx, &computepb.GetServiceAttachmentRequest{
        Project:           p.project,
        Region:            p.region,
        ServiceAttachment: serviceAttachmentName,
    })
    if err != nil {
        return HandleGCPAPIError(err, "get service attachment")
    }

    // Check connection status
    connectedEndpoints := serviceAttachment.ConnectedEndpoints

    log := ctrl.LoggerFrom(ctx)
    log.Info("PSC connection status",
        "serviceAttachment", serviceAttachmentName,
        "connectedEndpoints", len(connectedEndpoints),
        "connectionPreference", *serviceAttachment.ConnectionPreference)

    // Update metrics (if implemented)
    // pscConnectionsGauge.WithLabelValues(hc.Name, p.project, p.region).Set(float64(len(connectedEndpoints)))

    return nil
}
```

**4. Implement PSC Resource Cleanup** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/psc_cleanup.go`):
```go
// deletePSCResources removes all PSC-related resources
func (p *GCPPlatform) deletePSCResources(ctx context.Context, hc *hyperv1.HostedCluster) error {
    log := ctrl.LoggerFrom(ctx).WithValues("cluster", hc.Name, "operation", "deletePSC")

    var errs []error

    // Delete in reverse order: service attachment, NAT subnet

    // 1. Delete PSC Service Attachment
    if err := p.deletePSCServiceAttachment(ctx, hc); err != nil {
        log.Error(err, "failed to delete PSC service attachment")
        errs = append(errs, err)
    }

    // 2. Delete NAT subnet (only if auto-created)
    if err := p.deletePSCNATSubnet(ctx, hc); err != nil {
        log.Error(err, "failed to delete PSC NAT subnet")
        errs = append(errs, err)
    }

    if len(errs) > 0 {
        return fmt.Errorf("failed to delete PSC resources: %v", errs)
    }

    log.Info("Successfully deleted all PSC resources")
    return nil
}

func (p *GCPPlatform) deletePSCServiceAttachment(ctx context.Context, hc *hyperv1.HostedCluster) error {
    serviceAttachmentName := fmt.Sprintf("hypershift-%s-psc-producer", hc.Name)

    // Check if service attachment exists
    _, err := p.computeClient.ServiceAttachments.Get(ctx, &computepb.GetServiceAttachmentRequest{
        Project:           p.project,
        Region:            p.region,
        ServiceAttachment: serviceAttachmentName,
    })
    if err != nil {
        if apiErr, ok := err.(*googleapi.Error); ok && apiErr.Code == 404 {
            return nil // Already deleted
        }
        return HandleGCPAPIError(err, "get service attachment for deletion")
    }

    operation, err := p.computeClient.ServiceAttachments.Delete(ctx, &computepb.DeleteServiceAttachmentRequest{
        Project:           p.project,
        Region:            p.region,
        ServiceAttachment: serviceAttachmentName,
    })
    if err != nil {
        return HandleGCPAPIError(err, "delete service attachment")
    }

    return p.waitForRegionalOperation(ctx, operation.GetName())
}
```

**5. Integrate PSC into Platform Reconciliation** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/gcp.go`):
```go
// Update ReconcileCAPIInfraCR to include PSC creation
func (p *GCPPlatform) ReconcileCAPIInfraCR(ctx context.Context, c client.Client, createOrUpdate upsert.CreateOrUpdateFN, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string, apiEndpoint hyperv1.APIEndpoint) (client.Object, error) {
    // ... ILB creation from Milestone 2.1 ...

    // 4. Create PSC NAT subnet
    natSubnet, err := p.reconcilePSCNATSubnet(ctx, hcluster)
    if err != nil {
        return nil, fmt.Errorf("failed to reconcile PSC NAT subnet: %w", err)
    }

    // 5. Create PSC Service Attachment
    serviceAttachment, err := p.reconcilePSCServiceAttachment(ctx, hcluster, forwardingRule, natSubnet)
    if err != nil {
        return nil, fmt.Errorf("failed to reconcile PSC service attachment: %w", err)
    }

    // 6. Update HostedCluster status with PSC information
    if err := p.updatePSCStatus(ctx, c, hcluster, serviceAttachment); err != nil {
        return nil, fmt.Errorf("failed to update PSC status: %w", err)
    }

    // 7. Monitor PSC connections
    if err := p.monitorPSCConnections(ctx, hcluster); err != nil {
        log := ctrl.LoggerFrom(ctx)
        log.Error(err, "failed to monitor PSC connections") // Non-fatal
    }

    // TODO: Continue with GCPCluster creation (Milestone 3.1)
    return nil, nil
}

// Update DeleteCredentials to include PSC cleanup
func (p *GCPPlatform) DeleteCredentials(ctx context.Context, c client.Client, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string) error {
    // Clean up PSC resources
    if err := p.deletePSCResources(ctx, hcluster); err != nil {
        return fmt.Errorf("failed to delete PSC resources: %w", err)
    }

    // Clean up ILB resources (from Milestone 2.1)
    if err := p.deleteILBResources(ctx, hcluster); err != nil {
        return fmt.Errorf("failed to delete ILB resources: %w", err)
    }

    return nil
}
```

**Integration Points**:
- **ILB Dependency**: PSC Service Attachment must target the ILB forwarding rule
- **Network Configuration**: NAT subnet must be in the same VPC as the HostedCluster
- **Consumer Project Management**: Service Attachment must be configured for allowed customer projects
- **DNS Integration**: PSC endpoint domain names must be resolvable by customers

**Testing Strategy**:
```go
// Test file: hypershift-operator/controllers/hostedcluster/internal/platform/gcp/psc_test.go
func TestReconcilePSCServiceAttachment(t *testing.T) {
    tests := []struct {
        name          string
        hostedCluster *hyperv1.HostedCluster
        forwardingRule *computepb.ForwardingRule
        expectError   bool
        mockCalls     func(*MockGCPComputeClient)
    }{
        {
            name: "successful PSC service attachment creation",
            hostedCluster: &hyperv1.HostedCluster{
                ObjectMeta: metav1.ObjectMeta{Name: "test-cluster"},
                Spec: hyperv1.HostedClusterSpec{
                    Platform: hyperv1.PlatformSpec{
                        GCP: &hyperv1.GCPPlatformSpec{
                            Project: "test-project",
                            Region:  "us-central1",
                            PrivateServiceConnect: &hyperv1.GCPPSCSpec{
                                Enabled: true,
                                Type:    "dedicated",
                            },
                        },
                    },
                },
            },
            forwardingRule: &computepb.ForwardingRule{Name: ptr.String("test-ilb")},
            expectError: false,
            mockCalls: func(mockGCP *MockGCPComputeClient) {
                // Mock NAT subnet creation
                mockGCP.EXPECT().InsertSubnetwork(gomock.Any(), gomock.Any()).Return(&compute.Operation{Status: "DONE"}, nil)
                // Mock service attachment creation
                mockGCP.EXPECT().InsertServiceAttachment(gomock.Any(), gomock.Any()).Return(&compute.Operation{Status: "DONE"}, nil)
            },
        },
        // Additional test cases...
    }
    // Test implementation...
}
```

#### Milestone 2.3: Cross-Project PSC Consumer
**Deliverable**: PSC Consumer endpoints in customer projects

**Detailed Technical Tasks**:

**1. Implement Cross-Project Client Creation** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/cross_project_client.go`):
```go
package gcp

import (
    "context"
    "fmt"

    compute "cloud.google.com/go/compute/apiv1"
    "google.golang.org/api/option"
    "google.golang.org/api/impersonate"
    hyperv1 "github.com/openshift/hypershift/api/hypershift/v1beta1"
)

// CrossProjectClient manages GCP clients for customer projects
type CrossProjectClient struct {
    computeClient *compute.InstancesClient
    project       string
    region        string
}

// NewCrossProjectClient creates a GCP client for customer project operations
func (p *GCPPlatform) NewCrossProjectClient(ctx context.Context, customerProject string, hc *hyperv1.HostedCluster) (*CrossProjectClient, error) {
    // Create impersonation credentials for customer project
    targetServiceAccount := fmt.Sprintf("hypershift-%s-customer@%s.iam.gserviceaccount.com",
        hc.Name, customerProject)

    // Create impersonation token source
    tokenSource, err := impersonate.CredentialsTokenSource(ctx, impersonate.CredentialsConfig{
        TargetPrincipal: targetServiceAccount,
        Scopes:         []string{"https://www.googleapis.com/auth/compute"},
        // Include delegates if chained impersonation is needed
    })
    if err != nil {
        return nil, fmt.Errorf("failed to create impersonation token source: %w", err)
    }

    // Create compute client with impersonation
    computeClient, err := compute.NewInstancesRESTClient(ctx, option.WithTokenSource(tokenSource))
    if err != nil {
        return nil, fmt.Errorf("failed to create compute client for customer project: %w", err)
    }

    return &CrossProjectClient{
        computeClient: computeClient,
        project:       customerProject,
        region:        p.region, // Same region as management cluster
    }, nil
}

func (c *CrossProjectClient) Close() error {
    return c.computeClient.Close()
}
```

**2. Implement PSC Consumer Endpoint Creation** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/psc_consumer.go`):
```go
// reconcilePSCConsumerEndpoint creates PSC consumer endpoint in customer project
func (p *GCPPlatform) reconcilePSCConsumerEndpoint(ctx context.Context, hc *hyperv1.HostedCluster, customerProject string, serviceAttachment *computepb.ServiceAttachment) (*computepb.GlobalAddress, error) {
    // Create cross-project client
    crossProjectClient, err := p.NewCrossProjectClient(ctx, customerProject, hc)
    if err != nil {
        return nil, fmt.Errorf("failed to create cross-project client: %w", err)
    }
    defer crossProjectClient.Close()

    consumerEndpointName := fmt.Sprintf("hypershift-%s-consumer", hc.Name)

    // Get customer VPC network name
    customerNetworkName := p.getCustomerNetworkName(ctx, hc, customerProject)

    globalAddress := &computepb.GlobalAddress{
        Name:        &consumerEndpointName,
        Description: ptr.String(fmt.Sprintf("PSC consumer endpoint for HostedCluster %s", hc.Name)),

        // PSC consumer configuration
        Purpose:     ptr.String("PRIVATE_SERVICE_CONNECT"),
        AddressType: ptr.String("INTERNAL"),

        // Target the PSC service attachment
        PscGoogleApiTarget: ptr.String(*serviceAttachment.SelfLink),

        // Network configuration in customer project
        Network: ptr.String(fmt.Sprintf("projects/%s/global/networks/%s",
            customerProject, customerNetworkName)),

        // Let GCP assign an IP automatically within customer VPC
        Address: nil, // Auto-assigned
    }

    // Create the consumer endpoint
    operation, err := crossProjectClient.computeClient.GlobalAddresses.Insert(ctx, &computepb.InsertGlobalAddressRequest{
        Project:              customerProject,
        GlobalAddressResource: globalAddress,
    })
    if err != nil {
        return nil, HandleGCPAPIError(err, "create PSC consumer endpoint")
    }

    if err := p.waitForGlobalOperationCrossProject(ctx, crossProjectClient, operation.GetName()); err != nil {
        return nil, fmt.Errorf("failed waiting for consumer endpoint creation: %w", err)
    }

    // Get the created consumer endpoint with assigned IP
    createdEndpoint, err := crossProjectClient.computeClient.GlobalAddresses.Get(ctx, &computepb.GetGlobalAddressRequest{
        Project:       customerProject,
        GlobalAddress: consumerEndpointName,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to get created consumer endpoint: %w", err)
    }

    log := ctrl.LoggerFrom(ctx)
    log.Info("PSC consumer endpoint created",
        "name", consumerEndpointName,
        "ip", *createdEndpoint.Address,
        "customerProject", customerProject)

    return createdEndpoint, nil
}

// getCustomerNetworkName determines the VPC network name in customer project
func (p *GCPPlatform) getCustomerNetworkName(ctx context.Context, hc *hyperv1.HostedCluster, customerProject string) string {
    // Check if specified in the cross-project configuration
    if hc.Spec.Platform.GCP.CrossProjectWorkers != nil {
        // For Shared VPC scenarios
        if hc.Spec.Platform.GCP.CrossProjectWorkers.SharedVPCHost != "" {
            // Use the shared VPC network
            return hc.Spec.Platform.GCP.Network.Name
        }
    }

    // Default: assume customer has a VPC with standard naming
    return "default" // or discover dynamically
}
```

**3. Implement PSC Consumer Forwarding Rule** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/psc_consumer_forwarding_rule.go`):
```go
// reconcilePSCConsumerForwardingRule creates forwarding rule for PSC consumer
func (p *GCPPlatform) reconcilePSCConsumerForwardingRule(ctx context.Context, hc *hyperv1.HostedCluster, customerProject string, consumerEndpoint *computepb.GlobalAddress) (*computepb.ForwardingRule, error) {
    crossProjectClient, err := p.NewCrossProjectClient(ctx, customerProject, hc)
    if err != nil {
        return nil, fmt.Errorf("failed to create cross-project client: %w", err)
    }
    defer crossProjectClient.Close()

    forwardingRuleName := fmt.Sprintf("hypershift-%s-consumer-fwd", hc.Name)

    forwardingRule := &computepb.ForwardingRule{
        Name:        &forwardingRuleName,
        Description: ptr.String(fmt.Sprintf("PSC consumer forwarding rule for HostedCluster %s", hc.Name)),

        // Target the PSC consumer endpoint
        Target: ptr.String(*consumerEndpoint.SelfLink),

        // Load balancing configuration
        LoadBalancingScheme: ptr.String("INTERNAL"),
        IPProtocol:          ptr.String("TCP"),

        // Ports for Kubernetes API and control plane services
        Ports: []string{"6443", "443", "22623"},

        // Use the assigned IP from consumer endpoint
        IPAddress: consumerEndpoint.Address,

        // Network configuration in customer project
        Network: consumerEndpoint.Network,
        Subnetwork: ptr.String(p.getCustomerSubnetwork(ctx, hc, customerProject)),
    }

    operation, err := crossProjectClient.computeClient.ForwardingRules.Insert(ctx, &computepb.InsertForwardingRuleRequest{
        Project:                customerProject,
        Region:                 p.region,
        ForwardingRuleResource: forwardingRule,
    })
    if err != nil {
        return nil, HandleGCPAPIError(err, "create PSC consumer forwarding rule")
    }

    if err := p.waitForRegionalOperationCrossProject(ctx, crossProjectClient, operation.GetName()); err != nil {
        return nil, fmt.Errorf("failed waiting for consumer forwarding rule creation: %w", err)
    }

    return crossProjectClient.computeClient.ForwardingRules.Get(ctx, &computepb.GetForwardingRuleRequest{
        Project:        customerProject,
        Region:         p.region,
        ForwardingRule: forwardingRuleName,
    })
}

// getCustomerSubnetwork determines the subnet in customer project
func (p *GCPPlatform) getCustomerSubnetwork(ctx context.Context, hc *hyperv1.HostedCluster, customerProject string) string {
    // This should be specified in the NodePool configuration
    // For now, use a default or discover dynamically
    return fmt.Sprintf("projects/%s/regions/%s/subnetworks/default", customerProject, p.region)
}
```

**4. Implement Firewall Rules for Customer Project** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/customer_firewall.go`):
```go
// reconcileCustomerFirewallRules creates firewall rules in customer project
func (p *GCPPlatform) reconcileCustomerFirewallRules(ctx context.Context, hc *hyperv1.HostedCluster, customerProject string) error {
    crossProjectClient, err := p.NewCrossProjectClient(ctx, customerProject, hc)
    if err != nil {
        return fmt.Errorf("failed to create cross-project client: %w", err)
    }
    defer crossProjectClient.Close()

    // Create firewall rules for different traffic types
    firewallRules := []*computepb.Firewall{
        {
            Name:        ptr.String(fmt.Sprintf("hypershift-%s-allow-api", hc.Name)),
            Description: ptr.String(fmt.Sprintf("Allow Kubernetes API access for HostedCluster %s", hc.Name)),
            Direction:   ptr.String("INGRESS"),
            Priority:    ptr.Int32(1000),

            // Allow from worker node tags to PSC consumer IP
            SourceTags: []string{
                fmt.Sprintf("hypershift-%s-worker", hc.Name),
            },

            Allowed: []*computepb.FirewallAllowed{
                {
                    IPProtocol: ptr.String("tcp"),
                    Ports:      []string{"6443", "443"}, // Kubernetes API
                },
            },

            Network: ptr.String(fmt.Sprintf("projects/%s/global/networks/%s",
                customerProject, p.getCustomerNetworkName(ctx, hc, customerProject))),
        },
        {
            Name:        ptr.String(fmt.Sprintf("hypershift-%s-allow-mcs", hc.Name)),
            Description: ptr.String(fmt.Sprintf("Allow Machine Config Server access for HostedCluster %s", hc.Name)),
            Direction:   ptr.String("INGRESS"),
            Priority:    ptr.Int32(1000),

            SourceTags: []string{
                fmt.Sprintf("hypershift-%s-worker", hc.Name),
            },

            Allowed: []*computepb.FirewallAllowed{
                {
                    IPProtocol: ptr.String("tcp"),
                    Ports:      []string{"22623"}, // Machine Config Server
                },
            },

            Network: ptr.String(fmt.Sprintf("projects/%s/global/networks/%s",
                customerProject, p.getCustomerNetworkName(ctx, hc, customerProject))),
        },
    }

    // Create each firewall rule
    for _, firewallRule := range firewallRules {
        if err := p.createFirewallRule(ctx, crossProjectClient, customerProject, firewallRule); err != nil {
            return fmt.Errorf("failed to create firewall rule %s: %w", *firewallRule.Name, err)
        }
    }

    return nil
}

func (p *GCPPlatform) createFirewallRule(ctx context.Context, client *CrossProjectClient, customerProject string, firewallRule *computepb.Firewall) error {
    operation, err := client.computeClient.Firewalls.Insert(ctx, &computepb.InsertFirewallRequest{
        Project:          customerProject,
        FirewallResource: firewallRule,
    })
    if err != nil {
        // Check if rule already exists
        if apiErr, ok := err.(*googleapi.Error); ok && apiErr.Code == 409 {
            log := ctrl.LoggerFrom(ctx)
            log.Info("Firewall rule already exists", "name", *firewallRule.Name)
            return nil // Already exists, continue
        }
        return HandleGCPAPIError(err, "create firewall rule")
    }

    return p.waitForGlobalOperationCrossProject(ctx, client, operation.GetName())
}
```

**5. Implement IP Address Allocation and Tracking** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/psc_ip_management.go`):
```go
// trackPSCConsumerIPs manages IP address allocation and tracking
func (p *GCPPlatform) trackPSCConsumerIPs(ctx context.Context, c client.Client, hc *hyperv1.HostedCluster, customerProject string, consumerEndpoint *computepb.GlobalAddress) error {
    // Update HostedCluster status with consumer endpoint information
    if hc.Status.Platform == nil {
        hc.Status.Platform = &hyperv1.PlatformStatus{}
    }
    if hc.Status.Platform.GCP == nil {
        hc.Status.Platform.GCP = &hyperv1.GCPPlatformStatus{}
    }
    if hc.Status.Platform.GCP.PrivateServiceConnect == nil {
        hc.Status.Platform.GCP.PrivateServiceConnect = &hyperv1.GCPPSCStatus{}
    }

    // Add consumer endpoint information
    hc.Status.Platform.GCP.PrivateServiceConnect.ConsumerEndpoints = append(
        hc.Status.Platform.GCP.PrivateServiceConnect.ConsumerEndpoints,
        hyperv1.GCPPSCConsumerEndpoint{
            ProjectID:        customerProject,
            EndpointName:     *consumerEndpoint.Name,
            IPAddress:        *consumerEndpoint.Address,
            Status:           "Ready",
            ConnectionURI:    *consumerEndpoint.SelfLink,
        },
    )

    // Add condition for consumer endpoint readiness
    meta.SetStatusCondition(&hc.Status.Conditions, metav1.Condition{
        Type:    fmt.Sprintf("GCPPSCConsumerReady-%s", customerProject),
        Status:  metav1.ConditionTrue,
        Reason:  "ConsumerEndpointCreated",
        Message: fmt.Sprintf("PSC consumer endpoint created in project %s with IP %s", customerProject, *consumerEndpoint.Address),
    })

    return c.Status().Update(ctx, hc)
}

// getAllocatedIPs returns all PSC consumer IPs for a HostedCluster
func (p *GCPPlatform) getAllocatedIPs(hc *hyperv1.HostedCluster) []string {
    if hc.Status.Platform == nil || hc.Status.Platform.GCP == nil || hc.Status.Platform.GCP.PrivateServiceConnect == nil {
        return nil
    }

    var ips []string
    for _, endpoint := range hc.Status.Platform.GCP.PrivateServiceConnect.ConsumerEndpoints {
        if endpoint.IPAddress != "" {
            ips = append(ips, endpoint.IPAddress)
        }
    }

    return ips
}
```

**6. Implement End-to-End Connectivity Testing** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/psc_connectivity_test.go`):
```go
// validatePSCConnectivity tests end-to-end connectivity from customer project to management cluster
func (p *GCPPlatform) validatePSCConnectivity(ctx context.Context, hc *hyperv1.HostedCluster, customerProject string, consumerIP string) error {
    // Create a test VM in customer project to validate connectivity
    crossProjectClient, err := p.NewCrossProjectClient(ctx, customerProject, hc)
    if err != nil {
        return fmt.Errorf("failed to create cross-project client: %w", err)
    }
    defer crossProjectClient.Close()

    // Create temporary test instance
    testInstanceName := fmt.Sprintf("hypershift-%s-connectivity-test", hc.Name)

    testInstance := &computepb.Instance{
        Name:        &testInstanceName,
        Description: ptr.String("Temporary instance for PSC connectivity testing"),

        MachineType: ptr.String(fmt.Sprintf("projects/%s/zones/%s-a/machineTypes/e2-micro",
            customerProject, p.region)),

        Disks: []*computepb.AttachedDisk{
            {
                Boot:       ptr.Bool(true),
                AutoDelete: ptr.Bool(true),
                InitializeParams: &computepb.AttachedDiskInitializeParams{
                    SourceImage: ptr.String("projects/ubuntu-os-cloud/global/images/family/ubuntu-2004-lts"),
                    DiskSizeGb:  ptr.Int64(10),
                },
            },
        },

        NetworkInterfaces: []*computepb.NetworkInterface{
            {
                Network: ptr.String(fmt.Sprintf("projects/%s/global/networks/%s",
                    customerProject, p.getCustomerNetworkName(ctx, hc, customerProject))),
                Subnetwork: ptr.String(p.getCustomerSubnetwork(ctx, hc, customerProject)),
            },
        },

        Tags: &computepb.Tags{
            Items: []string{fmt.Sprintf("hypershift-%s-worker", hc.Name)},
        },

        // Startup script to test connectivity
        Metadata: &computepb.Metadata{
            Items: []*computepb.MetadataItems{
                {
                    Key: ptr.String("startup-script"),
                    Value: ptr.String(fmt.Sprintf(`#!/bin/bash
# Test PSC connectivity
curl -k --connect-timeout 10 https://%s:6443/healthz > /tmp/psc-test-result.txt 2>&1
echo "PSC test completed" >> /tmp/psc-test-result.txt`, consumerIP)),
                },
            },
        },
    }

    // Create test instance
    operation, err := crossProjectClient.computeClient.Instances.Insert(ctx, &computepb.InsertInstanceRequest{
        Project:          customerProject,
        Zone:             p.region + "-a",
        InstanceResource: testInstance,
    })
    if err != nil {
        return HandleGCPAPIError(err, "create connectivity test instance")
    }

    if err := p.waitForZoneOperationCrossProject(ctx, crossProjectClient, operation.GetName(), p.region+"-a"); err != nil {
        return fmt.Errorf("failed waiting for test instance creation: %w", err)
    }

    // Wait for startup script to complete and validate connectivity
    time.Sleep(60 * time.Second) // Wait for startup script

    // Check test results by examining instance serial console output
    // (In production, use Cloud Logging or other monitoring)

    // Clean up test instance
    _, err = crossProjectClient.computeClient.Instances.Delete(ctx, &computepb.DeleteInstanceRequest{
        Project:  customerProject,
        Zone:     p.region + "-a",
        Instance: testInstanceName,
    })
    if err != nil {
        log := ctrl.LoggerFrom(ctx)
        log.Error(err, "failed to delete connectivity test instance") // Non-fatal
    }

    return nil
}
```

**Integration Points**:
- **IAM Impersonation**: Must have proper cross-project service account setup
- **Network Configuration**: Customer VPC/subnet must be accessible
- **Firewall Rules**: Must allow traffic from worker nodes to PSC consumer IP
- **DNS Resolution**: Customer DNS must resolve PSC endpoint addresses

**Testing Strategy**:
```go
// Test file: hypershift-operator/controllers/hostedcluster/internal/platform/gcp/psc_consumer_test.go
func TestReconcilePSCConsumerEndpoint(t *testing.T) {
    // Test cross-project PSC consumer creation
    // Mock IAM impersonation
    // Test firewall rule creation
    // Test connectivity validation
}
```

---

### Phase 3: CAPG Integration

#### Milestone 3.1: GCPCluster Resource Management
**Deliverable**: CAPG GCPCluster resources created with PSC endpoints

**Detailed Technical Tasks**:

**1. Complete ReconcileCAPIInfraCR Implementation** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/gcp.go`):
```go
// ReconcileCAPIInfraCR creates GCPCluster resource with PSC configuration
func (p *GCPPlatform) ReconcileCAPIInfraCR(ctx context.Context, c client.Client, createOrUpdate upsert.CreateOrUpdateFN, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string, apiEndpoint hyperv1.APIEndpoint) (client.Object, error) {
    // ... PSC infrastructure creation from Phase 2 ...

    // 8. Create GCPCluster resource for CAPG
    gcpCluster, err := p.reconcileGCPCluster(ctx, c, createOrUpdate, hcluster, controlPlaneNamespace, serviceAttachment)
    if err != nil {
        return nil, fmt.Errorf("failed to reconcile GCPCluster: %w", err)
    }

    return gcpCluster, nil
}

// reconcileGCPCluster creates/updates the CAPG GCPCluster resource
func (p *GCPPlatform) reconcileGCPCluster(ctx context.Context, c client.Client, createOrUpdate upsert.CreateOrUpdateFN, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string, serviceAttachment *computepb.ServiceAttachment) (*capgv1.GCPCluster, error) {
    gcpCluster := &capgv1.GCPCluster{
        ObjectMeta: metav1.ObjectMeta{
            Name:      hcluster.Name,
            Namespace: controlPlaneNamespace,
            Labels: map[string]string{
                "cluster.x-k8s.io/cluster-name": hcluster.Name,
                "hypershift.openshift.io/hosted-cluster": hcluster.Name,
            },
        },
        Spec: capgv1.GCPClusterSpec{
            // Basic cluster configuration
            Project: hcluster.Spec.Platform.GCP.Project,
            Region:  hcluster.Spec.Platform.GCP.Region,

            // Network configuration
            Network: capgv1.NetworkSpec{
                Name: hcluster.Spec.Platform.GCP.Network.Name,
                Subnets: []capgv1.SubnetSpec{
                    {
                        Name:      hcluster.Spec.Platform.GCP.Network.Subnet,
                        CidrBlock: p.getSubnetCIDR(ctx, hcluster), // Discover existing subnet CIDR
                        Region:    hcluster.Spec.Platform.GCP.Region,
                        Purpose:   "PRIVATE",
                    },
                },
                // Firewall rules for PSC traffic
                FirewallRules: p.buildClusterFirewallRules(hcluster),
            },

            // Control plane endpoint configuration
            ControlPlaneEndpoint: &capgv1.APIEndpoint{
                Host: p.getPSCConsumerEndpoint(ctx, hcluster), // PSC consumer IP from customer project
                Port: 6443,
            },

            // Additional cluster configuration
            AdditionalLabels: map[string]string{
                "hypershift.openshift.io/cluster": hcluster.Name,
                "hypershift.openshift.io/psc-enabled": "true",
            },

            // Credentials reference for CAPG
            CredentialsRef: &corev1.ObjectReference{
                Name:      fmt.Sprintf("%s-gcp-credentials", hcluster.Name),
                Namespace: controlPlaneNamespace,
            },

            // PSC-specific configuration
            PrivateServiceConnect: &capgv1.PSCConfig{
                Enabled: true,
                ServiceAttachmentURI: *serviceAttachment.SelfLink,
                ConsumerProjects: p.buildConsumerProjectList(hcluster),
            },
        },
    }

    // Set owner reference for proper cleanup
    if err := controllerutil.SetControllerReference(hcluster, gcpCluster, c.Scheme()); err != nil {
        return nil, fmt.Errorf("failed to set controller reference: %w", err)
    }

    // Create or update the GCPCluster
    if err := createOrUpdate(ctx, c, gcpCluster, func() error {
        // Update logic if needed
        return nil
    }); err != nil {
        return nil, fmt.Errorf("failed to create/update GCPCluster: %w", err)
    }

    log := ctrl.LoggerFrom(ctx)
    log.Info("GCPCluster reconciled", "name", gcpCluster.Name, "namespace", gcpCluster.Namespace)

    return gcpCluster, nil
}

// getSubnetCIDR discovers the CIDR of the existing subnet
func (p *GCPPlatform) getSubnetCIDR(ctx context.Context, hcluster *hyperv1.HostedCluster) string {
    subnetwork, err := p.computeClient.Subnetworks.Get(ctx, &computepb.GetSubnetworkRequest{
        Project:    hcluster.Spec.Platform.GCP.Project,
        Region:     hcluster.Spec.Platform.GCP.Region,
        Subnetwork: hcluster.Spec.Platform.GCP.Network.Subnet,
    })
    if err != nil {
        // Fallback to default CIDR if discovery fails
        return "10.0.0.0/24"
    }
    return *subnetwork.IpCidrRange
}

// getPSCConsumerEndpoint retrieves the PSC consumer IP from the first consumer project
func (p *GCPPlatform) getPSCConsumerEndpoint(ctx context.Context, hcluster *hyperv1.HostedCluster) string {
    // Get PSC consumer IP from HostedCluster status
    if hcluster.Status.Platform != nil && hcluster.Status.Platform.GCP != nil &&
        hcluster.Status.Platform.GCP.PrivateServiceConnect != nil &&
        len(hcluster.Status.Platform.GCP.PrivateServiceConnect.ConsumerEndpoints) > 0 {
        return hcluster.Status.Platform.GCP.PrivateServiceConnect.ConsumerEndpoints[0].IPAddress
    }

    // Fallback: discover from first configured consumer project
    if hcluster.Spec.Platform.GCP.PrivateServiceConnect != nil &&
        len(hcluster.Spec.Platform.GCP.PrivateServiceConnect.ConsumerProjects) > 0 {
        firstProject := hcluster.Spec.Platform.GCP.PrivateServiceConnect.ConsumerProjects[0].ProjectID
        ip, err := p.discoverPSCConsumerIP(ctx, hcluster, firstProject)
        if err == nil {
            return ip
        }
    }

    // Should not reach here in normal operation
    return "" // Will cause validation error
}

// buildClusterFirewallRules creates firewall rules for cluster communication
func (p *GCPPlatform) buildClusterFirewallRules(hcluster *hyperv1.HostedCluster) []capgv1.FirewallRule {
    return []capgv1.FirewallRule{
        {
            Name:      fmt.Sprintf("hypershift-%s-allow-internal", hcluster.Name),
            Direction: "INGRESS",
            Priority:  1000,
            SourceRanges: []string{
                "10.0.0.0/8", // Internal cluster communication
                "172.16.0.0/12",
                "192.168.0.0/16",
            },
            Allowed: []capgv1.FirewallAllowed{
                {
                    IPProtocol: "tcp",
                    Ports:      []string{"0-65535"}, // Allow all TCP
                },
                {
                    IPProtocol: "udp",
                    Ports:      []string{"0-65535"}, // Allow all UDP
                },
                {
                    IPProtocol: "icmp",
                },
            },
        },
        {
            Name:      fmt.Sprintf("hypershift-%s-allow-psc", hcluster.Name),
            Direction: "INGRESS",
            Priority:  900,
            SourceTags: []string{
                fmt.Sprintf("hypershift-%s-worker", hcluster.Name),
            },
            Allowed: []capgv1.FirewallAllowed{
                {
                    IPProtocol: "tcp",
                    Ports:      []string{"6443", "443", "22623"},
                },
            },
        },
    }
}

// buildConsumerProjectList builds the list of consumer projects for PSC
func (p *GCPPlatform) buildConsumerProjectList(hcluster *hyperv1.HostedCluster) []capgv1.PSCConsumerProject {
    if hcluster.Spec.Platform.GCP.PrivateServiceConnect == nil {
        return nil
    }

    var consumerProjects []capgv1.PSCConsumerProject
    for _, project := range hcluster.Spec.Platform.GCP.PrivateServiceConnect.ConsumerProjects {
        consumerProjects = append(consumerProjects, capgv1.PSCConsumerProject{
            ProjectID: project.ProjectID,
            Networks:  project.Networks,
        })
    }

    return consumerProjects
}
```

**2. Implement CAPG Provider Deployment Configuration** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/capg_deployment.go`):
```go
// CAPIProviderDeploymentSpec configures the CAPG provider deployment
func (p *GCPPlatform) CAPIProviderDeploymentSpec(hcluster *hyperv1.HostedCluster, hcp *hyperv1.HostedControlPlane) (*appsv1.DeploymentSpec, error) {
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
                        Name:  "cluster-api-provider-gcp",
                        Image: p.capiProviderImage,
                        Args: []string{
                            "--v=2",
                            "--logtostderr=true",
                            "--leader-elect=true",
                            "--metrics-bind-addr=:8080",
                        },
                        Env: []corev1.EnvVar{
                            {
                                Name:  "GCP_REGION",
                                Value: hcluster.Spec.Platform.GCP.Region,
                            },
                            {
                                Name:  "GCP_PROJECT",
                                Value: hcluster.Spec.Platform.GCP.Project,
                            },
                            {
                                Name:  "GOOGLE_APPLICATION_CREDENTIALS",
                                Value: "/etc/gcp-credentials/credentials.json",
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
                        VolumeMounts: []corev1.VolumeMount{
                            {
                                Name:      "gcp-credentials",
                                MountPath: "/etc/gcp-credentials",
                                ReadOnly:  true,
                            },
                        },
                        LivenessProbe: &corev1.Probe{
                            ProbeHandler: corev1.ProbeHandler{
                                HTTPGet: &corev1.HTTPGetAction{
                                    Path: "/healthz",
                                    Port: intstr.FromInt(8080),
                                },
                            },
                            InitialDelaySeconds: 30,
                            PeriodSeconds:       10,
                        },
                        ReadinessProbe: &corev1.Probe{
                            ProbeHandler: corev1.ProbeHandler{
                                HTTPGet: &corev1.HTTPGetAction{
                                    Path: "/readyz",
                                    Port: intstr.FromInt(8080),
                                },
                            },
                            InitialDelaySeconds: 5,
                            PeriodSeconds:       5,
                        },
                    },
                },
                Volumes: []corev1.Volume{
                    {
                        Name: "gcp-credentials",
                        VolumeSource: corev1.VolumeSource{
                            Secret: &corev1.SecretVolumeSource{
                                SecretName: fmt.Sprintf("%s-gcp-credentials", hcluster.Name),
                            },
                        },
                    },
                },
                Tolerations: []corev1.Toleration{
                    {
                        Key:    "node-role.kubernetes.io/master",
                        Effect: corev1.TaintEffectNoSchedule,
                    },
                },
                NodeSelector: map[string]string{
                    "node-role.kubernetes.io/master": "",
                },
            },
        },
    }, nil
}
```

**3. Update CAPG Provider RBAC** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/rbac.go`):
```go
// CAPIProviderPolicyRules returns the RBAC rules required for CAPG with PSC
func (p *GCPPlatform) CAPIProviderPolicyRules() []rbacv1.PolicyRule {
    return []rbacv1.PolicyRule{
        {
            APIGroups: ["infrastructure.cluster.x-k8s.io"],
            Resources: ["gcpclusters", "gcpmachines", "gcpmachinetemplates"],
            Verbs:     ["get", "list", "watch", "create", "update", "patch", "delete"],
        },
        {
            APIGroups: ["infrastructure.cluster.x-k8s.io"],
            Resources: ["gcpclusters/status", "gcpmachines/status", "gcpmachinetemplates/status"],
            Verbs:     ["get", "update", "patch"],
        },
        {
            APIGroups: ["bootstrap.cluster.x-k8s.io"],
            Resources: ["kubeadmconfigs", "kubeadmconfigtemplates"],
            Verbs:     ["get", "list", "watch", "create", "update", "patch", "delete"],
        },
        {
            APIGroups: ["cluster.x-k8s.io"],
            Resources: ["clusters", "machines", "machinedeployments", "machinepools"],
            Verbs:     ["get", "list", "watch", "create", "update", "patch", "delete"],
        },
        {
            APIGroups: ["cluster.x-k8s.io"],
            Resources: ["clusters/status", "machines/status", "machinedeployments/status"],
            Verbs:     ["get", "update", "patch"],
        },
        // Additional RBAC for PSC operations
        {
            APIGroups: [""],
            Resources: ["secrets", "configmaps"],
            Verbs:     ["get", "list", "watch", "create", "update", "patch", "delete"],
        },
        {
            APIGroups: [""],
            Resources: ["events"],
            Verbs:     ["create", "patch"],
        },
        {
            APIGroups: ["coordination.k8s.io"],
            Resources: ["leases"],
            Verbs:     ["get", "list", "watch", "create", "update", "patch", "delete"],
        },
    }
}
```

**4. Implement Status Management** (`hypershift-operator/controllers/hostedcluster/internal/platform/gcp/cluster_status.go`):
```go
// updateGCPClusterStatus monitors and updates GCPCluster status
func (p *GCPPlatform) updateGCPClusterStatus(ctx context.Context, c client.Client, hcluster *hyperv1.HostedCluster, gcpCluster *capgv1.GCPCluster) error {
    // Get current GCPCluster status
    currentCluster := &capgv1.GCPCluster{}
    if err := c.Get(ctx, client.ObjectKeyFromObject(gcpCluster), currentCluster); err != nil {
        return fmt.Errorf("failed to get current GCPCluster: %w", err)
    }

    // Update HostedCluster status with GCPCluster information
    if hcluster.Status.Platform == nil {
        hcluster.Status.Platform = &hyperv1.PlatformStatus{}
    }
    if hcluster.Status.Platform.GCP == nil {
        hcluster.Status.Platform.GCP = &hyperv1.GCPPlatformStatus{}
    }

    hcluster.Status.Platform.GCP.GCPCluster = &hyperv1.GCPClusterStatus{
        Name:      currentCluster.Name,
        Namespace: currentCluster.Namespace,
        Ready:     currentCluster.Status.Ready,
        Network: &hyperv1.GCPNetworkStatus{
            Name:    currentCluster.Spec.Network.Name,
            SelfLink: currentCluster.Status.Network.SelfLink,
        },
    }

    // Add condition based on GCPCluster readiness
    conditionStatus := metav1.ConditionFalse
    message := "GCPCluster not ready"
    if currentCluster.Status.Ready {
        conditionStatus = metav1.ConditionTrue
        message = "GCPCluster is ready"
    }

    meta.SetStatusCondition(&hcluster.Status.Conditions, metav1.Condition{
        Type:    "GCPClusterReady",
        Status:  conditionStatus,
        Reason:  "GCPClusterStatus",
        Message: message,
    })

    return c.Status().Update(ctx, hcluster)
}
```

**Integration Points**:
- **PSC Dependencies**: GCPCluster must reference PSC Service Attachment URI
- **CAPG Version Compatibility**: Must be compatible with CAPG v1beta1 API
- **Owner References**: Proper cleanup when HostedCluster is deleted
- **Network Configuration**: Must match existing VPC/subnet configuration

**Testing Strategy**:
```go
// Test file: hypershift-operator/controllers/hostedcluster/internal/platform/gcp/gcpcluster_test.go
func TestReconcileGCPCluster(t *testing.T) {
    tests := []struct {
        name          string
        hostedCluster *hyperv1.HostedCluster
        serviceAttachment *computepb.ServiceAttachment
        expectError   bool
    }{
        {
            name: "successful GCPCluster creation",
            hostedCluster: testutil.MinimalGCPHostedCluster("test-cluster", "test-namespace"),
            serviceAttachment: &computepb.ServiceAttachment{
                Name:     ptr.String("test-psc-producer"),
                SelfLink: ptr.String("projects/test/regions/us-central1/serviceAttachments/test-psc-producer"),
            },
            expectError: false,
        },
        // Additional test cases...
    }
    // Test implementation...
}
```

#### Milestone 3.2: NodePool Controller Implementation
**Deliverable**: Worker nodes deployed in customer projects via CAPG

**Detailed Technical Tasks**:

**1. Implement GCP NodePool Reconciliation** (`hypershift-operator/controllers/nodepool/gcp.go`):
```go
package nodepool

import (
    "context"
    "fmt"

    hyperv1 "github.com/openshift/hypershift/api/hypershift/v1beta1"
    "github.com/openshift/hypershift/support/upsert"
    capgv1 "sigs.k8s.io/cluster-api-provider-gcp/api/v1beta1"
    capiv1 "sigs.k8s.io/cluster-api/api/v1beta1"
    bootstrapv1 "sigs.k8s.io/cluster-api/bootstrap/kubeadm/api/v1beta1"
    "sigs.k8s.io/controller-runtime/pkg/client"
    "sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
)

// reconcileGCPNodePool handles GCP-specific NodePool reconciliation
func (r *NodePoolReconciler) reconcileGCPNodePool(ctx context.Context, nodePool *hyperv1.NodePool, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string) error {
    log := ctrl.LoggerFrom(ctx).WithValues("platform", "gcp", "nodePool", nodePool.Name)
    log.Info("Reconciling GCP NodePool")

    // 1. Create PSC consumer endpoint for this NodePool's customer project
    if err := r.reconcileNodePoolPSCConsumer(ctx, nodePool, hcluster); err != nil {
        return fmt.Errorf("failed to reconcile NodePool PSC consumer: %w", err)
    }

    // 2. Create GCPMachineTemplate
    machineTemplate, err := r.reconcileGCPMachineTemplate(ctx, nodePool, hcluster, controlPlaneNamespace)
    if err != nil {
        return fmt.Errorf("failed to reconcile GCPMachineTemplate: %w", err)
    }

    // 3. Create KubeadmConfigTemplate for worker node bootstrap
    configTemplate, err := r.reconcileKubeadmConfigTemplate(ctx, nodePool, hcluster, controlPlaneNamespace)
    if err != nil {
        return fmt.Errorf("failed to reconcile KubeadmConfigTemplate: %w", err)
    }

    // 4. Create MachineDeployment
    if err := r.reconcileMachineDeployment(ctx, nodePool, hcluster, controlPlaneNamespace, machineTemplate, configTemplate); err != nil {
        return fmt.Errorf("failed to reconcile MachineDeployment: %w", err)
    }

    return nil
}

// reconcileNodePoolPSCConsumer creates PSC consumer endpoint for NodePool's customer project
func (r *NodePoolReconciler) reconcileNodePoolPSCConsumer(ctx context.Context, nodePool *hyperv1.NodePool, hcluster *hyperv1.HostedCluster) error {
    // Only create PSC consumer if NodePool is in different project
    if nodePool.Spec.Platform.GCP.Project == hcluster.Spec.Platform.GCP.Project {
        return nil // Same project, use existing PSC infrastructure
    }

    // Get GCP platform implementation
    gcpPlatform, err := r.getGCPPlatform(ctx, hcluster)
    if err != nil {
        return fmt.Errorf("failed to get GCP platform: %w", err)
    }

    // Get PSC Service Attachment from HostedCluster status
    serviceAttachmentURI := hcluster.Status.Platform.GCP.PrivateServiceConnect.ServiceAttachmentURI
    if serviceAttachmentURI == "" {
        return fmt.Errorf("PSC Service Attachment not ready in HostedCluster status")
    }

    // Create PSC consumer endpoint in NodePool's customer project
    consumerEndpoint, err := gcpPlatform.reconcilePSCConsumerEndpoint(ctx, hcluster, nodePool.Spec.Platform.GCP.Project, serviceAttachmentURI)
    if err != nil {
        return fmt.Errorf("failed to create PSC consumer endpoint for NodePool: %w", err)
    }

    // Update NodePool status with PSC consumer information
    return r.updateNodePoolPSCStatus(ctx, nodePool, consumerEndpoint)
}

// reconcileGCPMachineTemplate creates GCPMachineTemplate for worker nodes
func (r *NodePoolReconciler) reconcileGCPMachineTemplate(ctx context.Context, nodePool *hyperv1.NodePool, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string) (*capgv1.GCPMachineTemplate, error) {
    machineTemplateName := fmt.Sprintf("%s-%s", nodePool.Name, "machine-template")

    machineTemplate := &capgv1.GCPMachineTemplate{
        ObjectMeta: metav1.ObjectMeta{
            Name:      machineTemplateName,
            Namespace: controlPlaneNamespace,
            Labels: map[string]string{
                "cluster.x-k8s.io/cluster-name": hcluster.Name,
                "hypershift.openshift.io/nodepool": nodePool.Name,
            },
        },
        Spec: capgv1.GCPMachineTemplateSpec{
            Template: capgv1.GCPMachineTemplateResource{
                Spec: capgv1.GCPMachineSpec{
                    // Instance configuration
                    InstanceType: nodePool.Spec.Platform.GCP.InstanceType,

                    // Boot disk configuration
                    RootDeviceSize: nodePool.Spec.Platform.GCP.DiskSizeGB,
                    RootDeviceType: nodePool.Spec.Platform.GCP.DiskType,

                    // Network configuration in customer project
                    NetworkInterfaces: []capgv1.NetworkInterface{
                        {
                            Network: fmt.Sprintf("projects/%s/global/networks/%s",
                                nodePool.Spec.Platform.GCP.Project, r.getNodePoolNetworkName(nodePool)),
                            Subnet: fmt.Sprintf("projects/%s/regions/%s/subnetworks/%s",
                                nodePool.Spec.Platform.GCP.Project, nodePool.Spec.Platform.GCP.Zone[:len(nodePool.Spec.Platform.GCP.Zone)-2], nodePool.Spec.Platform.GCP.Subnet),
                        },
                    },

                    // Service account for worker nodes
                    ServiceAccount: &capgv1.ServiceAccount{
                        Email: fmt.Sprintf("hypershift-%s-worker@%s.iam.gserviceaccount.com",
                            hcluster.Name, nodePool.Spec.Platform.GCP.Project),
                        Scopes: []string{
                            "https://www.googleapis.com/auth/cloud-platform",
                        },
                    },

                    // Instance metadata with cluster information
                    AdditionalMetadata: r.buildWorkerNodeMetadata(ctx, nodePool, hcluster),

                    // Network tags for firewall rules
                    AdditionalNetworkTags: []string{
                        fmt.Sprintf("hypershift-%s-worker", hcluster.Name),
                        fmt.Sprintf("nodepool-%s", nodePool.Name),
                    },

                    // Instance labels
                    AdditionalLabels: map[string]string{
                        "hypershift-cluster": hcluster.Name,
                        "hypershift-nodepool": nodePool.Name,
                        "node-role": "worker",
                    },

                    // Preemptible configuration
                    Preemptible: nodePool.Spec.Platform.GCP.Preemptible,

                    // Zone configuration
                    Zone: nodePool.Spec.Platform.GCP.Zone,

                    // SSH key configuration (if needed)
                    PublicIP: ptr.Bool(false), // Workers should not have public IPs
                },
            },
        },
    }

    // Set owner reference
    if err := controllerutil.SetControllerReference(nodePool, machineTemplate, r.Scheme); err != nil {
        return nil, fmt.Errorf("failed to set controller reference: %w", err)
    }

    // Create or update the machine template
    if err := upsert.New().WithContext(ctx).WithClient(r.Client).WithObject(machineTemplate).Upsert(); err != nil {
        return nil, fmt.Errorf("failed to upsert GCPMachineTemplate: %w", err)
    }

    return machineTemplate, nil
}

// buildWorkerNodeMetadata creates metadata for worker node instances
func (r *NodePoolReconciler) buildWorkerNodeMetadata(ctx context.Context, nodePool *hyperv1.NodePool, hcluster *hyperv1.HostedCluster) map[string]string {
    // Get PSC consumer IP for API server connectivity
    apiServerEndpoint := r.getNodePoolAPIServerEndpoint(nodePool, hcluster)

    return map[string]string{
        "hypershift-cluster": hcluster.Name,
        "hypershift-nodepool": nodePool.Name,
        "api-server-endpoint": apiServerEndpoint,
        "cluster-dns": r.getClusterDNS(hcluster),
        "node-role": "worker",
        // Additional metadata for node initialization
        "psc-enabled": "true",
        "cross-project": fmt.Sprintf("%t", nodePool.Spec.Platform.GCP.Project != hcluster.Spec.Platform.GCP.Project),
    }
}

// getNodePoolAPIServerEndpoint determines the API server endpoint for worker nodes
func (r *NodePoolReconciler) getNodePoolAPIServerEndpoint(nodePool *hyperv1.NodePool, hcluster *hyperv1.HostedCluster) string {
    // If NodePool has its own PSC consumer, use that IP
    if nodePool.Status.Platform != nil && nodePool.Status.Platform.GCP != nil &&
        nodePool.Status.Platform.GCP.PSCConsumer != nil &&
        nodePool.Status.Platform.GCP.PSCConsumer.IPAddress != "" {
        return fmt.Sprintf("%s:6443", nodePool.Status.Platform.GCP.PSCConsumer.IPAddress)
    }

    // Otherwise, use HostedCluster's PSC consumer endpoint
    if hcluster.Status.Platform != nil && hcluster.Status.Platform.GCP != nil &&
        hcluster.Status.Platform.GCP.PrivateServiceConnect != nil &&
        len(hcluster.Status.Platform.GCP.PrivateServiceConnect.ConsumerEndpoints) > 0 {
        // Find consumer endpoint for this NodePool's project
        for _, endpoint := range hcluster.Status.Platform.GCP.PrivateServiceConnect.ConsumerEndpoints {
            if endpoint.ProjectID == nodePool.Spec.Platform.GCP.Project {
                return fmt.Sprintf("%s:6443", endpoint.IPAddress)
            }
        }
        // Fallback to first endpoint
        return fmt.Sprintf("%s:6443", hcluster.Status.Platform.GCP.PrivateServiceConnect.ConsumerEndpoints[0].IPAddress)
    }

    // Should not reach here in normal operation
    return "" // Will cause node join failure
}

// reconcileKubeadmConfigTemplate creates bootstrap configuration for worker nodes
func (r *NodePoolReconciler) reconcileKubeadmConfigTemplate(ctx context.Context, nodePool *hyperv1.NodePool, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string) (*bootstrapv1.KubeadmConfigTemplate, error) {
    configTemplateName := fmt.Sprintf("%s-%s", nodePool.Name, "config-template")

    configTemplate := &bootstrapv1.KubeadmConfigTemplate{
        ObjectMeta: metav1.ObjectMeta{
            Name:      configTemplateName,
            Namespace: controlPlaneNamespace,
            Labels: map[string]string{
                "cluster.x-k8s.io/cluster-name": hcluster.Name,
                "hypershift.openshift.io/nodepool": nodePool.Name,
            },
        },
        Spec: bootstrapv1.KubeadmConfigTemplateSpec{
            Template: bootstrapv1.KubeadmConfigTemplateResource{
                Spec: bootstrapv1.KubeadmConfigSpec{
                    JoinConfiguration: &bootstrapv1.JoinConfiguration{
                        NodeRegistration: bootstrapv1.NodeRegistrationOptions{
                            Name: "{{ ds.meta_data.local_hostname }}",
                            KubeletExtraArgs: map[string]string{
                                "cloud-provider": "gce",
                                "cloud-config": "/etc/kubernetes/cloud-config",
                                "provider-id": "gce://{{ ds.meta_data.project_id }}/{{ ds.meta_data.zone }}/{{ ds.meta_data.local_hostname }}",
                            },
                            Taints: nodePool.Spec.Taints,
                        },
                        Discovery: bootstrapv1.Discovery{
                            BootstrapToken: &bootstrapv1.BootstrapTokenDiscovery{
                                APIServerEndpoint: r.getNodePoolAPIServerEndpoint(nodePool, hcluster),
                                Token:             "{{ ds.meta_data.bootstrap_token }}",
                                CACertHashes:      []string{"{{ ds.meta_data.ca_cert_hash }}"},
                            },
                        },
                    },
                    Files: r.buildWorkerNodeFiles(nodePool, hcluster),
                    PreKubeadmCommands:  r.buildPreKubeadmCommands(nodePool, hcluster),
                    PostKubeadmCommands: r.buildPostKubeadmCommands(nodePool, hcluster),
                },
            },
        },
    }

    // Set owner reference
    if err := controllerutil.SetControllerReference(nodePool, configTemplate, r.Scheme); err != nil {
        return nil, fmt.Errorf("failed to set controller reference: %w", err)
    }

    // Create or update the config template
    if err := upsert.New().WithContext(ctx).WithClient(r.Client).WithObject(configTemplate).Upsert(); err != nil {
        return nil, fmt.Errorf("failed to upsert KubeadmConfigTemplate: %w", err)
    }

    return configTemplate, nil
}

// buildWorkerNodeFiles creates configuration files for worker nodes
func (r *NodePoolReconciler) buildWorkerNodeFiles(nodePool *hyperv1.NodePool, hcluster *hyperv1.HostedCluster) []bootstrapv1.File {
    return []bootstrapv1.File{
        {
            Path:    "/etc/kubernetes/cloud-config",
            Content: r.buildGCPCloudConfig(nodePool, hcluster),
            Owner:   "root:root",
            Permissions: "0644",
        },
        {
            Path:    "/etc/systemd/system/kubelet.service.d/20-gcp.conf",
            Content: r.buildKubeletGCPConfig(),
            Owner:   "root:root",
            Permissions: "0644",
        },
    }
}

// buildGCPCloudConfig creates GCP cloud provider configuration
func (r *NodePoolReconciler) buildGCPCloudConfig(nodePool *hyperv1.NodePool, hcluster *hyperv1.HostedCluster) string {
    return fmt.Sprintf(`[global]
project-id = %s
regional-gce-pd-zone = %s
multizone = true
node-tags = hypershift-%s-worker,nodepool-%s
node-instance-prefix = %s-%s
`,
        nodePool.Spec.Platform.GCP.Project,
        nodePool.Spec.Platform.GCP.Zone,
        hcluster.Name,
        nodePool.Name,
        hcluster.Name,
        nodePool.Name,
    )
}

// buildKubeletGCPConfig creates kubelet configuration for GCP
func (r *NodePoolReconciler) buildKubeletGCPConfig() string {
    return `[Service]
Environment="KUBELET_KUBECONFIG_ARGS=--bootstrap-kubeconfig=/etc/kubernetes/bootstrap-kubelet.conf --kubeconfig=/etc/kubernetes/kubelet.conf"
Environment="KUBELET_CONFIG_ARGS=--config=/var/lib/kubelet/config.yaml"
Environment="KUBELET_KUBEADM_ARGS=--container-runtime=containerd --container-runtime-endpoint=unix:///var/run/containerd/containerd.sock"
Environment="KUBELET_EXTRA_ARGS=--cloud-provider=gce --cloud-config=/etc/kubernetes/cloud-config"
ExecStart=/usr/bin/kubelet $KUBELET_KUBECONFIG_ARGS $KUBELET_CONFIG_ARGS $KUBELET_KUBEADM_ARGS $KUBELET_EXTRA_ARGS
`
}

// reconcileMachineDeployment creates MachineDeployment for the NodePool
func (r *NodePoolReconciler) reconcileMachineDeployment(ctx context.Context, nodePool *hyperv1.NodePool, hcluster *hyperv1.HostedCluster, controlPlaneNamespace string, machineTemplate *capgv1.GCPMachineTemplate, configTemplate *bootstrapv1.KubeadmConfigTemplate) error {
    machineDeploymentName := nodePool.Name

    machineDeployment := &capiv1.MachineDeployment{
        ObjectMeta: metav1.ObjectMeta{
            Name:      machineDeploymentName,
            Namespace: controlPlaneNamespace,
            Labels: map[string]string{
                "cluster.x-k8s.io/cluster-name": hcluster.Name,
                "hypershift.openshift.io/nodepool": nodePool.Name,
            },
        },
        Spec: capiv1.MachineDeploymentSpec{
            ClusterName: hcluster.Name,
            Replicas:    nodePool.Spec.Replicas,
            Selector: metav1.LabelSelector{
                MatchLabels: map[string]string{
                    "cluster.x-k8s.io/cluster-name": hcluster.Name,
                    "cluster.x-k8s.io/deployment-name": machineDeploymentName,
                },
            },
            Template: capiv1.MachineTemplateSpec{
                ObjectMeta: capiv1.ObjectMeta{
                    Labels: map[string]string{
                        "cluster.x-k8s.io/cluster-name": hcluster.Name,
                        "cluster.x-k8s.io/deployment-name": machineDeploymentName,
                        "hypershift.openshift.io/nodepool": nodePool.Name,
                    },
                },
                Spec: capiv1.MachineSpec{
                    ClusterName: hcluster.Name,
                    InfrastructureRef: corev1.ObjectReference{
                        APIVersion: "infrastructure.cluster.x-k8s.io/v1beta1",
                        Kind:       "GCPMachineTemplate",
                        Name:       machineTemplate.Name,
                        Namespace:  machineTemplate.Namespace,
                    },
                    Bootstrap: capiv1.Bootstrap{
                        ConfigRef: &corev1.ObjectReference{
                            APIVersion: "bootstrap.cluster.x-k8s.io/v1beta1",
                            Kind:       "KubeadmConfigTemplate",
                            Name:       configTemplate.Name,
                            Namespace:  configTemplate.Namespace,
                        },
                    },
                    Version: ptr.String(hcluster.Spec.Release.Image), // Use cluster version
                },
            },
        },
    }

    // Set owner reference
    if err := controllerutil.SetControllerReference(nodePool, machineDeployment, r.Scheme); err != nil {
        return fmt.Errorf("failed to set controller reference: %w", err)
    }

    // Create or update the machine deployment
    if err := upsert.New().WithContext(ctx).WithClient(r.Client).WithObject(machineDeployment).Upsert(); err != nil {
        return fmt.Errorf("failed to upsert MachineDeployment: %w", err)
    }

    return nil
}
```

**2. Implement NodePool Status Management** (`hypershift-operator/controllers/nodepool/gcp_status.go`):
```go
// updateNodePoolPSCStatus updates NodePool status with PSC consumer information
func (r *NodePoolReconciler) updateNodePoolPSCStatus(ctx context.Context, nodePool *hyperv1.NodePool, consumerEndpoint *computepb.GlobalAddress) error {
    // Update NodePool status with PSC consumer endpoint
    if nodePool.Status.Platform == nil {
        nodePool.Status.Platform = &hyperv1.NodePoolPlatformStatus{}
    }
    if nodePool.Status.Platform.GCP == nil {
        nodePool.Status.Platform.GCP = &hyperv1.GCPNodePoolPlatformStatus{}
    }

    nodePool.Status.Platform.GCP.PSCConsumer = &hyperv1.GCPNodePoolPSCConsumerStatus{
        EndpointName: *consumerEndpoint.Name,
        IPAddress:    *consumerEndpoint.Address,
        Status:       "Ready",
        Project:      nodePool.Spec.Platform.GCP.Project,
    }

    // Add condition for PSC consumer readiness
    meta.SetStatusCondition(&nodePool.Status.Conditions, metav1.Condition{
        Type:    "GCPPSCConsumerReady",
        Status:  metav1.ConditionTrue,
        Reason:  "PSCConsumerCreated",
        Message: fmt.Sprintf("PSC consumer endpoint created with IP %s", *consumerEndpoint.Address),
    })

    return r.Status().Update(ctx, nodePool)
}
```

**Integration Points**:
- **PSC Consumer Dependencies**: NodePool must have PSC consumer endpoint in customer project
- **CAPG Integration**: MachineTemplate must be compatible with CAPG v1beta1
- **Bootstrap Configuration**: Worker nodes must have correct API server endpoint
- **Network Configuration**: Worker nodes must be able to reach PSC consumer endpoint

**Testing Strategy**:
```go
// Test file: hypershift-operator/controllers/nodepool/gcp_test.go
func TestReconcileGCPNodePool(t *testing.T) {
    // Test NodePool reconciliation with cross-project configuration
    // Test PSC consumer endpoint creation
    // Test MachineDeployment creation
    // Test worker node bootstrap configuration
}
```

---

### Phase 4: Production Readiness

#### Milestone 4.1: Environment Validation Controller
**Deliverable**: Proactive monitoring of customer project health

**Detailed Technical Tasks**:

**1. Implement Environment Validation Controller** (`hypershift-operator/controllers/validation/gcp_environment_validator.go`):
```go
package validation

import (
    "context"
    "fmt"
    "time"

    compute "cloud.google.com/go/compute/apiv1"
    iam "cloud.google.com/go/iam/apiv1"
    hyperv1 "github.com/openshift/hypershift/api/hypershift/v1beta1"
    "sigs.k8s.io/controller-runtime/pkg/reconcile"
)

// GCPEnvironmentValidator validates GCP environment health
type GCPEnvironmentValidator struct {
    client.Client
    computeClient *compute.InstancesClient
    iamClient     *iam.IAMClient

    validationInterval time.Duration
}

func NewGCPEnvironmentValidator(client client.Client) *GCPEnvironmentValidator {
    return &GCPEnvironmentValidator{
        Client:             client,
        validationInterval: 5 * time.Minute, // Validate every 5 minutes
    }
}

// Reconcile performs periodic environment validation
func (v *GCPEnvironmentValidator) Reconcile(ctx context.Context, req reconcile.Request) (reconcile.Result, error) {
    log := ctrl.LoggerFrom(ctx).WithValues("validator", "gcp-environment")

    // Get HostedCluster
    hcluster := &hyperv1.HostedCluster{}
    if err := v.Get(ctx, req.NamespacedName, hcluster); err != nil {
        return reconcile.Result{}, client.IgnoreNotFound(err)
    }

    // Only validate GCP clusters
    if hcluster.Spec.Platform.Type != hyperv1.GCPPlatform {
        return reconcile.Result{}, nil
    }

    // Skip validation if cluster is being deleted
    if !hcluster.DeletionTimestamp.IsZero() {
        return reconcile.Result{}, nil
    }

    log.Info("Starting environment validation")

    // Perform validation checks
    validationResults := v.performValidationChecks(ctx, hcluster)

    // Update HostedCluster status with validation results
    if err := v.updateValidationStatus(ctx, hcluster, validationResults); err != nil {
        log.Error(err, "failed to update validation status")
        return reconcile.Result{RequeueAfter: v.validationInterval}, err
    }

    // Requeue for next validation cycle
    return reconcile.Result{RequeueAfter: v.validationInterval}, nil
}

// ValidationResult represents the result of a validation check
type ValidationResult struct {
    CheckName   string
    Passed      bool
    Message     string
    Severity    string // "error", "warning", "info"
    Remediation string
}

// performValidationChecks runs all validation checks
func (v *GCPEnvironmentValidator) performValidationChecks(ctx context.Context, hcluster *hyperv1.HostedCluster) []ValidationResult {
    var results []ValidationResult

    // 1. Validate management project permissions
    results = append(results, v.validateManagementProjectPermissions(ctx, hcluster)...)

    // 2. Validate customer project permissions
    results = append(results, v.validateCustomerProjectPermissions(ctx, hcluster)...)

    // 3. Validate network connectivity
    results = append(results, v.validateNetworkConnectivity(ctx, hcluster)...)

    // 4. Validate PSC infrastructure health
    results = append(results, v.validatePSCInfrastructure(ctx, hcluster)...)

    // 5. Validate quotas and limits
    results = append(results, v.validateQuotasAndLimits(ctx, hcluster)...)

    return results
}

// validateManagementProjectPermissions checks management project IAM permissions
func (v *GCPEnvironmentValidator) validateManagementProjectPermissions(ctx context.Context, hcluster *hyperv1.HostedCluster) []ValidationResult {
    var results []ValidationResult
    project := hcluster.Spec.Platform.GCP.Project

    // Required permissions for hypershift-operator
    requiredPermissions := []string{
        "compute.networks.get",
        "compute.subnetworks.get",
        "compute.subnetworks.create",
        "compute.forwardingRules.create",
        "compute.forwardingRules.delete",
        "compute.backendServices.create",
        "compute.backendServices.delete",
        "compute.healthChecks.create",
        "compute.healthChecks.delete",
        "compute.serviceAttachments.create",
        "compute.serviceAttachments.delete",
        "servicenetworking.services.addPeering",
        "iam.serviceAccounts.actAs",
    }

    // Test each permission
    for _, permission := range requiredPermissions {
        hasPermission, err := v.testPermission(ctx, project, permission)
        if err != nil {
            results = append(results, ValidationResult{
                CheckName:   fmt.Sprintf("management-project-permission-%s", permission),
                Passed:      false,
                Message:     fmt.Sprintf("Failed to test permission %s: %v", permission, err),
                Severity:    "error",
                Remediation: fmt.Sprintf("Ensure service account has permission: %s", permission),
            })
            continue
        }

        results = append(results, ValidationResult{
            CheckName: fmt.Sprintf("management-project-permission-%s", permission),
            Passed:    hasPermission,
            Message: func() string {
                if hasPermission {
                    return fmt.Sprintf("Permission %s is available", permission)
                }
                return fmt.Sprintf("Missing required permission: %s", permission)
            }(),
            Severity: func() string {
                if hasPermission {
                    return "info"
                }
                return "error"
            }(),
            Remediation: fmt.Sprintf("Grant permission %s to service account", permission),
        })
    }

    return results
}

// validateCustomerProjectPermissions checks customer project access
func (v *GCPEnvironmentValidator) validateCustomerProjectPermissions(ctx context.Context, hcluster *hyperv1.HostedCluster) []ValidationResult {
    var results []ValidationResult

    if hcluster.Spec.Platform.GCP.CrossProjectWorkers == nil {
        return results // No cross-project configuration
    }

    // Validate each customer project
    for _, customerProject := range hcluster.Spec.Platform.GCP.CrossProjectWorkers.AllowedProjects {
        // Test cross-project IAM impersonation
        canImpersonate, err := v.testCrossProjectImpersonation(ctx, hcluster, customerProject)
        results = append(results, ValidationResult{
            CheckName: fmt.Sprintf("customer-project-access-%s", customerProject),
            Passed:    err == nil && canImpersonate,
            Message: func() string {
                if err != nil {
                    return fmt.Sprintf("Failed to test cross-project access to %s: %v", customerProject, err)
                }
                if canImpersonate {
                    return fmt.Sprintf("Cross-project access to %s is working", customerProject)
                }
                return fmt.Sprintf("Cannot impersonate service account in project %s", customerProject)
            }(),
            Severity: func() string {
                if err == nil && canImpersonate {
                    return "info"
                }
                return "error"
            }(),
            Remediation: fmt.Sprintf("Configure IAM impersonation for project %s", customerProject),
        })
    }

    return results
}

// validateNetworkConnectivity checks network configuration and connectivity
func (v *GCPEnvironmentValidator) validateNetworkConnectivity(ctx context.Context, hcluster *hyperv1.HostedCluster) []ValidationResult {
    var results []ValidationResult

    // 1. Validate VPC network exists
    networkExists, err := v.validateVPCNetwork(ctx, hcluster)
    results = append(results, ValidationResult{
        CheckName: "vpc-network-exists",
        Passed:    err == nil && networkExists,
        Message: func() string {
            if err != nil {
                return fmt.Sprintf("Failed to validate VPC network: %v", err)
            }
            if networkExists {
                return "VPC network is accessible"
            }
            return "VPC network does not exist or is not accessible"
        }(),
        Severity: func() string {
            if err == nil && networkExists {
                return "info"
            }
            return "error"
        }(),
        Remediation: "Ensure VPC network exists and service account has access",
    })

    // 2. Validate subnet exists
    subnetExists, err := v.validateSubnet(ctx, hcluster)
    results = append(results, ValidationResult{
        CheckName: "subnet-exists",
        Passed:    err == nil && subnetExists,
        Message: func() string {
            if err != nil {
                return fmt.Sprintf("Failed to validate subnet: %v", err)
            }
            if subnetExists {
                return "Subnet is accessible"
            }
            return "Subnet does not exist or is not accessible"
        }(),
        Severity: func() string {
            if err == nil && subnetExists {
                return "info"
            }
            return "error"
        }(),
        Remediation: "Ensure subnet exists in the specified region",
    })

    // 3. Validate firewall rules allow required traffic
    firewallValid, err := v.validateFirewallRules(ctx, hcluster)
    results = append(results, ValidationResult{
        CheckName: "firewall-rules-valid",
        Passed:    err == nil && firewallValid,
        Message: func() string {
            if err != nil {
                return fmt.Sprintf("Failed to validate firewall rules: %v", err)
            }
            if firewallValid {
                return "Firewall rules allow required traffic"
            }
            return "Firewall rules may block required traffic"
        }(),
        Severity: func() string {
            if err == nil && firewallValid {
                return "info"
            }
            return "warning"
        }(),
        Remediation: "Review firewall rules for ports 6443, 443, 22623",
    })

    return results
}

// validatePSCInfrastructure checks PSC infrastructure health
func (v *GCPEnvironmentValidator) validatePSCInfrastructure(ctx context.Context, hcluster *hyperv1.HostedCluster) []ValidationResult {
    var results []ValidationResult

    // 1. Validate PSC Service Attachment exists and is ready
    serviceAttachmentReady, err := v.validatePSCServiceAttachment(ctx, hcluster)
    results = append(results, ValidationResult{
        CheckName: "psc-service-attachment-ready",
        Passed:    err == nil && serviceAttachmentReady,
        Message: func() string {
            if err != nil {
                return fmt.Sprintf("Failed to validate PSC Service Attachment: %v", err)
            }
            if serviceAttachmentReady {
                return "PSC Service Attachment is ready"
            }
            return "PSC Service Attachment is not ready"
        }(),
        Severity: func() string {
            if err == nil && serviceAttachmentReady {
                return "info"
            }
            return "error"
        }(),
        Remediation: "Check PSC Service Attachment status in GCP Console",
    })

    // 2. Validate ILB health
    ilbHealthy, err := v.validateILBHealth(ctx, hcluster)
    results = append(results, ValidationResult{
        CheckName: "ilb-healthy",
        Passed:    err == nil && ilbHealthy,
        Message: func() string {
            if err != nil {
                return fmt.Sprintf("Failed to validate ILB health: %v", err)
            }
            if ilbHealthy {
                return "Internal Load Balancer is healthy"
            }
            return "Internal Load Balancer backends are unhealthy"
        }(),
        Severity: func() string {
            if err == nil && ilbHealthy {
                return "info"
            }
            return "error"
        }(),
        Remediation: "Check ILB backend health in GCP Console",
    })

    return results
}

// updateValidationStatus updates HostedCluster status with validation results
func (v *GCPEnvironmentValidator) updateValidationStatus(ctx context.Context, hcluster *hyperv1.HostedCluster, results []ValidationResult) error {
    // Count validation results
    var passed, failed, warnings int
    var errorMessages, warningMessages []string

    for _, result := range results {
        if result.Passed {
            passed++
        } else {
            failed++
            if result.Severity == "error" {
                errorMessages = append(errorMessages, result.Message)
            } else if result.Severity == "warning" {
                warnings++
                warningMessages = append(warningMessages, result.Message)
            }
        }
    }

    // Update environment validation condition
    conditionStatus := metav1.ConditionTrue
    reason := "EnvironmentValidationPassed"
    message := fmt.Sprintf("Environment validation passed (%d checks)", passed)

    if failed > 0 {
        conditionStatus = metav1.ConditionFalse
        reason = "EnvironmentValidationFailed"
        message = fmt.Sprintf("Environment validation failed (%d errors, %d warnings)", failed, warnings)
        if len(errorMessages) > 0 {
            message += fmt.Sprintf(": %s", strings.Join(errorMessages[:min(3, len(errorMessages))], "; "))
        }
    }

    meta.SetStatusCondition(&hcluster.Status.Conditions, metav1.Condition{
        Type:    "GCPEnvironmentValidationReady",
        Status:  conditionStatus,
        Reason:  reason,
        Message: message,
    })

    // Store detailed validation results in status
    if hcluster.Status.Platform == nil {
        hcluster.Status.Platform = &hyperv1.PlatformStatus{}
    }
    if hcluster.Status.Platform.GCP == nil {
        hcluster.Status.Platform.GCP = &hyperv1.GCPPlatformStatus{}
    }

    hcluster.Status.Platform.GCP.EnvironmentValidation = &hyperv1.GCPEnvironmentValidationStatus{
        LastValidationTime: metav1.Now(),
        TotalChecks:        len(results),
        PassedChecks:       passed,
        FailedChecks:       failed,
        WarningChecks:      warnings,
    }

    return v.Status().Update(ctx, hcluster)
}
```

**2. Implement Validation Helper Functions** (`hypershift-operator/controllers/validation/gcp_validation_helpers.go`):
```go
// testPermission tests if a specific IAM permission is available
func (v *GCPEnvironmentValidator) testPermission(ctx context.Context, project, permission string) (bool, error) {
    // Use IAM testIamPermissions API
    req := &iampb.TestIamPermissionsRequest{
        Resource:    fmt.Sprintf("projects/%s", project),
        Permissions: []string{permission},
    }

    resp, err := v.iamClient.TestIamPermissions(ctx, req)
    if err != nil {
        return false, err
    }

    return len(resp.Permissions) > 0 && resp.Permissions[0] == permission, nil
}

// testCrossProjectImpersonation tests IAM impersonation to customer project
func (v *GCPEnvironmentValidator) testCrossProjectImpersonation(ctx context.Context, hcluster *hyperv1.HostedCluster, customerProject string) (bool, error) {
    // Attempt to create cross-project client
    targetSA := fmt.Sprintf("hypershift-%s-customer@%s.iam.gserviceaccount.com", hcluster.Name, customerProject)

    // Test impersonation by attempting to list compute instances
    tokenSource, err := impersonate.CredentialsTokenSource(ctx, impersonate.CredentialsConfig{
        TargetPrincipal: targetSA,
        Scopes:         []string{"https://www.googleapis.com/auth/compute.readonly"},
    })
    if err != nil {
        return false, err
    }

    // Test with a simple API call
    computeClient, err := compute.NewInstancesRESTClient(ctx, option.WithTokenSource(tokenSource))
    if err != nil {
        return false, err
    }
    defer computeClient.Close()

    // Try to list instances (should succeed even if no instances exist)
    _, err = computeClient.List(ctx, &computepb.ListInstancesRequest{
        Project: customerProject,
        Zone:    hcluster.Spec.Platform.GCP.Region + "-a",
    })

    return err == nil, nil
}
```

**Integration Points**:
- **Controller Manager**: Must be registered in controller manager startup
- **RBAC**: Needs permissions to read HostedClusters and update status
- **GCP APIs**: Requires compute and IAM client initialization
- **Monitoring**: Should expose metrics for validation results

#### Milestone 4.2: Control Plane Integration with Workload Identity
**Deliverable**: Control plane pods accessible via PSC with proper authentication

**Detailed Technical Tasks**:

**1. Configure ILB Backend Integration** (`control-plane-operator/controllers/hostedcontrolplane/gcp/ilb_backend_manager.go`):
```go
package gcp

import (
    "context"
    "fmt"

    compute "cloud.google.com/go/compute/apiv1"
    "cloud.google.com/go/compute/apiv1/computepb"
    hyperv1 "github.com/openshift/hypershift/api/hypershift/v1beta1"
)

// ILBBackendManager manages ILB backend configuration for control plane pods
type ILBBackendManager struct {
    computeClient *compute.BackendServicesClient
    project       string
    region        string
}

// ReconcileILBBackends configures ILB backends to point to GKE nodes running control plane pods
func (m *ILBBackendManager) ReconcileILBBackends(ctx context.Context, hcp *hyperv1.HostedControlPlane) error {
    backendServiceName := fmt.Sprintf("hypershift-%s-api-backend", hcp.Spec.ClusterID)

    // Get current backend service
    backendService, err := m.computeClient.Get(ctx, &computepb.GetBackendServiceRequest{
        Project:        m.project,
        Region:         m.region,
        BackendService: backendServiceName,
    })
    if err != nil {
        return fmt.Errorf("failed to get backend service: %w", err)
    }

    // Get GKE node instance groups
    instanceGroups, err := m.getGKEInstanceGroups(ctx, hcp)
    if err != nil {
        return fmt.Errorf("failed to get GKE instance groups: %w", err)
    }

    // Update backend service with current instance groups
    updatedBackends := make([]*computepb.Backend, 0, len(instanceGroups))
    for _, instanceGroup := range instanceGroups {
        backend := &computepb.Backend{
            Group:          &instanceGroup,
            BalancingMode:  ptr.String("CONNECTION"),
            MaxConnections: ptr.Int32(1000),
            Description:    ptr.String("GKE nodes running control plane pods"),
        }
        updatedBackends = append(updatedBackends, backend)
    }

    // Update the backend service
    backendService.Backends = updatedBackends

    operation, err := m.computeClient.Update(ctx, &computepb.UpdateBackendServiceRequest{
        Project:               m.project,
        Region:                m.region,
        BackendService:        backendServiceName,
        BackendServiceResource: backendService,
    })
    if err != nil {
        return fmt.Errorf("failed to update backend service: %w", err)
    }

    // Wait for operation completion
    return m.waitForRegionalOperation(ctx, operation.GetName())
}

// getGKEInstanceGroups discovers GKE instance groups for the management cluster
func (m *ILBBackendManager) getGKEInstanceGroups(ctx context.Context, hcp *hyperv1.HostedControlPlane) ([]string, error) {
    // Discover GKE cluster instance groups
    // This should be configured based on the actual GKE cluster setup
    gkeClusterName := fmt.Sprintf("hypershift-mgmt-%s", m.region)

    zones := []string{
        fmt.Sprintf("%s-a", m.region),
        fmt.Sprintf("%s-b", m.region),
        fmt.Sprintf("%s-c", m.region),
    }

    var instanceGroups []string
    for _, zone := range zones {
        instanceGroupURL := fmt.Sprintf("projects/%s/zones/%s/instanceGroups/gke-%s-default-pool",
            m.project, zone, gkeClusterName)
        instanceGroups = append(instanceGroups, instanceGroupURL)
    }

    return instanceGroups, nil
}
```

**2. Implement GCP Cloud Controller Manager Deployment** (`control-plane-operator/controllers/hostedcontrolplane/manifests/gcp_cloud_controller.go`):
```go
// gcpCloudControllerManagerDeployment creates the GCP cloud controller manager deployment with Workload Identity
func gcpCloudControllerManagerDeployment(hcp *hyperv1.HostedControlPlane) *appsv1.Deployment {
    return &appsv1.Deployment{
        ObjectMeta: metav1.ObjectMeta{
            Name:      "gcp-cloud-controller-manager",
            Namespace: hcp.Namespace,
            Labels: map[string]string{
                "app": "gcp-cloud-controller-manager",
                "hypershift.openshift.io/control-plane-component": "gcp-cloud-controller-manager",
            },
        },
        Spec: appsv1.DeploymentSpec{
            Replicas: ptr.To(int32(2)), // HA deployment
            Selector: &metav1.LabelSelector{
                MatchLabels: map[string]string{
                    "app": "gcp-cloud-controller-manager",
                },
            },
            Template: corev1.PodTemplateSpec{
                ObjectMeta: metav1.ObjectMeta{
                    Labels: map[string]string{
                        "app": "gcp-cloud-controller-manager",
                        "hypershift.openshift.io/control-plane-component": "gcp-cloud-controller-manager",
                    },
                    Annotations: map[string]string{
                        "target.workload.openshift.io/management": `{"effect": "PreferredDuringScheduling"}`,
                    },
                },
                Spec: corev1.PodSpec{
                    ServiceAccountName: "gcp-cloud-controller-manager",
                    PriorityClassName:  "hypershift-control-plane",
                    Containers: []corev1.Container{
                        {
                            Name:  "gcp-cloud-controller-manager",
                            Image: getGCPCloudControllerImage(hcp),
                            Command: []string{
                                "/usr/local/bin/gcp-cloud-controller-manager",
                            },
                            Args: []string{
                                "--cloud-config=/etc/gcp/cloud-config",
                                "--cluster-name=" + hcp.Spec.ClusterID,
                                "--cluster-cidr=" + hcp.Spec.NetworkSpec.ClusterCIDR,
                                "--service-cluster-ip-range=" + hcp.Spec.NetworkSpec.ServiceCIDR,
                                "--kubeconfig=/etc/kubernetes/kubeconfig/kubeconfig",
                                "--leader-elect=true",
                                "--leader-elect-lease-duration=137s",
                                "--leader-elect-renew-deadline=107s",
                                "--leader-elect-retry-period=26s",
                                "--leader-elect-resource-namespace=" + hcp.Namespace,
                                "--v=2",
                                "--bind-address=0.0.0.0",
                                "--secure-port=10258",
                                "--port=0",
                            },
                            Env: []corev1.EnvVar{
                                {
                                    Name:  "GOOGLE_APPLICATION_CREDENTIALS",
                                    Value: "/var/secrets/gcp/credentials.json", // Workload Identity mounted token
                                },
                                {
                                    Name:  "GCP_PROJECT",
                                    Value: hcp.Spec.Platform.GCP.Project,
                                },
                                {
                                    Name:  "GCP_REGION",
                                    Value: hcp.Spec.Platform.GCP.Region,
                                },
                            },
                            Resources: corev1.ResourceRequirements{
                                Requests: corev1.ResourceList{
                                    corev1.ResourceCPU:    resource.MustParse("50m"),
                                    corev1.ResourceMemory: resource.MustParse("100Mi"),
                                },
                                Limits: corev1.ResourceList{
                                    corev1.ResourceCPU:    resource.MustParse("200m"),
                                    corev1.ResourceMemory: resource.MustParse("200Mi"),
                                },
                            },
                            VolumeMounts: []corev1.VolumeMount{
                                {
                                    Name:      "kubeconfig",
                                    MountPath: "/etc/kubernetes/kubeconfig",
                                    ReadOnly:  true,
                                },
                                {
                                    Name:      "gcp-cloud-config",
                                    MountPath: "/etc/gcp",
                                    ReadOnly:  true,
                                },
                                {
                                    Name:      "gcp-credentials",
                                    MountPath: "/var/secrets/gcp",
                                    ReadOnly:  true,
                                },
                            },
                            LivenessProbe: &corev1.Probe{
                                ProbeHandler: corev1.ProbeHandler{
                                    HTTPGet: &corev1.HTTPGetAction{
                                        Path:   "/healthz",
                                        Port:   intstr.FromInt(10258),
                                        Scheme: corev1.URISchemeHTTPS,
                                    },
                                },
                                InitialDelaySeconds: 30,
                                PeriodSeconds:       30,
                                TimeoutSeconds:      10,
                            },
                        },
                    },
                    Volumes: []corev1.Volume{
                        {
                            Name: "kubeconfig",
                            VolumeSource: corev1.VolumeSource{
                                Secret: &corev1.SecretVolumeSource{
                                    SecretName: "gcp-cloud-controller-manager-kubeconfig",
                                },
                            },
                        },
                        {
                            Name: "gcp-cloud-config",
                            VolumeSource: corev1.VolumeSource{
                                ConfigMap: &corev1.ConfigMapVolumeSource{
                                    LocalObjectReference: corev1.LocalObjectReference{
                                        Name: "gcp-cloud-config",
                                    },
                                },
                            },
                        },
                        {
                            Name: "gcp-credentials",
                            VolumeSource: corev1.VolumeSource{
                                Projected: &corev1.ProjectedVolumeSource{
                                    Sources: []corev1.VolumeProjection{
                                        {
                                            ServiceAccountToken: &corev1.ServiceAccountTokenProjection{
                                                Audience:          "https://gcp.workload.identity",
                                                ExpirationSeconds: ptr.To(int64(3600)),
                                                Path:              "token",
                                            },
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    }
}

// gcpCloudControllerManagerServiceAccount creates the ServiceAccount with Workload Identity
func gcpCloudControllerManagerServiceAccount(hcp *hyperv1.HostedControlPlane) *corev1.ServiceAccount {
    return &corev1.ServiceAccount{
        ObjectMeta: metav1.ObjectMeta{
            Name:      "gcp-cloud-controller-manager",
            Namespace: hcp.Namespace,
            Annotations: map[string]string{
                "iam.gke.io/gcp-service-account": fmt.Sprintf("hypershift-%s-ccm@%s.iam.gserviceaccount.com",
                    hcp.Spec.ClusterID, hcp.Spec.Platform.GCP.Project),
            },
        },
    }
}

// gcpCloudConfig creates the cloud config for GCP cloud controller manager
func gcpCloudConfig(hcp *hyperv1.HostedControlPlane) *corev1.ConfigMap {
    cloudConfig := fmt.Sprintf(`[global]
project-id = %s
regional-gce-pd-zone = %s
multizone = true
token-url = nil
local-zone = %s
`,
        hcp.Spec.Platform.GCP.Project,
        hcp.Spec.Platform.GCP.Region,
        hcp.Spec.Platform.GCP.Region+"-a",
    )

    return &corev1.ConfigMap{
        ObjectMeta: metav1.ObjectMeta{
            Name:      "gcp-cloud-config",
            Namespace: hcp.Namespace,
        },
        Data: map[string]string{
            "cloud-config": cloudConfig,
        },
    }
}
```

**3. Implement GCP CSI Driver Deployment** (`control-plane-operator/controllers/hostedcontrolplane/manifests/gcp_csi_driver.go`):
```go
// gcpCSIControllerDeployment creates the GCP CSI controller deployment
func gcpCSIControllerDeployment(hcp *hyperv1.HostedControlPlane) *appsv1.Deployment {
    return &appsv1.Deployment{
        ObjectMeta: metav1.ObjectMeta{
            Name:      "gcp-csi-controller",
            Namespace: hcp.Namespace,
            Labels: map[string]string{
                "app": "gcp-csi-controller",
                "hypershift.openshift.io/control-plane-component": "gcp-csi-controller",
            },
        },
        Spec: appsv1.DeploymentSpec{
            Replicas: ptr.To(int32(1)),
            Selector: &metav1.LabelSelector{
                MatchLabels: map[string]string{
                    "app": "gcp-csi-controller",
                },
            },
            Template: corev1.PodTemplateSpec{
                ObjectMeta: metav1.ObjectMeta{
                    Labels: map[string]string{
                        "app": "gcp-csi-controller",
                        "hypershift.openshift.io/control-plane-component": "gcp-csi-controller",
                    },
                },
                Spec: corev1.PodSpec{
                    ServiceAccountName: "gcp-csi-controller",
                    PriorityClassName:  "hypershift-control-plane",
                    Containers: []corev1.Container{
                        {
                            Name:  "gcp-csi-driver",
                            Image: getGCPCSIDriverImage(hcp),
                            Args: []string{
                                "--endpoint=unix:///csi/csi.sock",
                                "--logtostderr",
                                "--v=2",
                            },
                            Env: []corev1.EnvVar{
                                {
                                    Name:  "GOOGLE_APPLICATION_CREDENTIALS",
                                    Value: "/var/secrets/gcp/token", // Workload Identity token
                                },
                                {
                                    Name:  "GCP_PROJECT",
                                    Value: hcp.Spec.Platform.GCP.Project,
                                },
                            },
                            Resources: corev1.ResourceRequirements{
                                Requests: corev1.ResourceList{
                                    corev1.ResourceCPU:    resource.MustParse("50m"),
                                    corev1.ResourceMemory: resource.MustParse("100Mi"),
                                },
                                Limits: corev1.ResourceList{
                                    corev1.ResourceCPU:    resource.MustParse("200m"),
                                    corev1.ResourceMemory: resource.MustParse("200Mi"),
                                },
                            },
                            VolumeMounts: []corev1.VolumeMount{
                                {
                                    Name:      "socket-dir",
                                    MountPath: "/csi",
                                },
                                {
                                    Name:      "gcp-credentials",
                                    MountPath: "/var/secrets/gcp",
                                    ReadOnly:  true,
                                },
                            },
                        },
                        {
                            Name:  "csi-provisioner",
                            Image: getCSIProvisionerImage(hcp),
                            Args: []string{
                                "--csi-address=/csi/csi.sock",
                                "--kubeconfig=/etc/kubernetes/kubeconfig/kubeconfig",
                                "--leader-election",
                                "--leader-election-namespace=" + hcp.Namespace,
                                "--v=2",
                            },
                            VolumeMounts: []corev1.VolumeMount{
                                {
                                    Name:      "socket-dir",
                                    MountPath: "/csi",
                                },
                                {
                                    Name:      "kubeconfig",
                                    MountPath: "/etc/kubernetes/kubeconfig",
                                    ReadOnly:  true,
                                },
                            },
                        },
                        {
                            Name:  "csi-attacher",
                            Image: getCSIAttacherImage(hcp),
                            Args: []string{
                                "--csi-address=/csi/csi.sock",
                                "--kubeconfig=/etc/kubernetes/kubeconfig/kubeconfig",
                                "--leader-election",
                                "--leader-election-namespace=" + hcp.Namespace,
                                "--v=2",
                            },
                            VolumeMounts: []corev1.VolumeMount{
                                {
                                    Name:      "socket-dir",
                                    MountPath: "/csi",
                                },
                                {
                                    Name:      "kubeconfig",
                                    MountPath: "/etc/kubernetes/kubeconfig",
                                    ReadOnly:  true,
                                },
                            },
                        },
                    },
                    Volumes: []corev1.Volume{
                        {
                            Name: "socket-dir",
                            VolumeSource: corev1.VolumeSource{
                                EmptyDir: &corev1.EmptyDirVolumeSource{},
                            },
                        },
                        {
                            Name: "kubeconfig",
                            VolumeSource: corev1.VolumeSource{
                                Secret: &corev1.SecretVolumeSource{
                                    SecretName: "gcp-csi-controller-kubeconfig",
                                },
                            },
                        },
                        {
                            Name: "gcp-credentials",
                            VolumeSource: corev1.VolumeSource{
                                Projected: &corev1.ProjectedVolumeSource{
                                    Sources: []corev1.VolumeProjection{
                                        {
                                            ServiceAccountToken: &corev1.ServiceAccountTokenProjection{
                                                Audience:          "https://gcp.workload.identity",
                                                ExpirationSeconds: ptr.To(int64(3600)),
                                                Path:              "token",
                                            },
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    }
}
```

**4. Implement API Server Service Configuration** (`control-plane-operator/controllers/hostedcontrolplane/manifests/api_server_service.go`):
```go
// apiServerService creates the Kubernetes Service for the API server
func apiServerService(hcp *hyperv1.HostedControlPlane) *corev1.Service {
    return &corev1.Service{
        ObjectMeta: metav1.ObjectMeta{
            Name:      "kube-apiserver",
            Namespace: hcp.Namespace,
            Labels: map[string]string{
                "app": "kube-apiserver",
                "hypershift.openshift.io/control-plane-component": "kube-apiserver",
            },
            Annotations: map[string]string{
                "service.beta.kubernetes.io/gcp-load-balancer-type": "Internal",
                "cloud.google.com/backend-config": `{"default": "kube-apiserver-backend-config"}`,
            },
        },
        Spec: corev1.ServiceSpec{
            Type:     corev1.ServiceTypeLoadBalancer,
            Selector: map[string]string{
                "app": "kube-apiserver",
            },
            Ports: []corev1.ServicePort{
                {
                    Name:       "https",
                    Port:       6443,
                    TargetPort: intstr.FromInt(6443),
                    Protocol:   corev1.ProtocolTCP,
                },
                {
                    Name:       "oauth",
                    Port:       443,
                    TargetPort: intstr.FromInt(8443),
                    Protocol:   corev1.ProtocolTCP,
                },
                {
                    Name:       "mcs",
                    Port:       22623,
                    TargetPort: intstr.FromInt(22623),
                    Protocol:   corev1.ProtocolTCP,
                },
            },
            LoadBalancerSourceRanges: []string{
                "10.0.0.0/8",   // Private IP ranges
                "172.16.0.0/12",
                "192.168.0.0/16",
            },
        },
    }
}
```

**Integration Points**:
- **GKE Node Discovery**: ILB backends must target actual GKE nodes
- **Workload Identity Configuration**: All service accounts must be properly configured
- **API Server Connectivity**: Service must be accessible via PSC endpoint
- **Storage Integration**: CSI driver must work with GCP Persistent Disks

**Testing Strategy**:
```bash
# Test API server connectivity via PSC
kubectl --kubeconfig=customer-kubeconfig get nodes

# Test storage provisioning
kubectl apply -f test-pvc.yaml
kubectl get pv

# Verify Workload Identity (no credential files)
kubectl exec -n hypershift-cluster pod/gcp-cloud-controller-manager -- ls /var/secrets/
```

#### Milestone 4.3: CLI and Automation
**Deliverable**: Customer setup automation tools

**Detailed Technical Tasks**:

**1. Create Customer Setup CLI Command** (`cmd/setup/gcp.go`):
```go
package setup

import (
    "context"
    "fmt"
    "os"
    "path/filepath"
    "text/template"

    "github.com/spf13/cobra"
    hyperv1 "github.com/openshift/hypershift/api/hypershift/v1beta1"
)

// NewGCPSetupCommand creates the GCP customer setup command
func NewGCPSetupCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "gcp",
        Short: "Generate GCP customer project setup scripts",
        Long: `Generate scripts and configuration files for setting up customer GCP projects
to work with HyperShift GCP platform using Private Service Connect.

This command creates:
- IAM service accounts and role bindings
- VPC network and subnet configuration
- Firewall rules for cluster communication
- PSC consumer endpoint setup scripts
- Terraform modules for infrastructure automation`,
        RunE: runGCPSetup,
    }

    cmd.Flags().String("cluster-name", "", "Name of the HostedCluster")
    cmd.Flags().String("customer-project", "", "Customer GCP project ID")
    cmd.Flags().String("customer-region", "", "Customer GCP region")
    cmd.Flags().String("customer-network", "default", "Customer VPC network name")
    cmd.Flags().String("customer-subnet", "default", "Customer subnet name")
    cmd.Flags().String("management-project", "", "Management cluster GCP project ID")
    cmd.Flags().String("psc-service-attachment", "", "PSC Service Attachment URI")
    cmd.Flags().String("output-dir", "./gcp-setup", "Output directory for generated files")
    cmd.Flags().Bool("terraform", false, "Generate Terraform modules instead of shell scripts")
    cmd.Flags().Bool("dry-run", false, "Generate files without applying any changes")

    cmd.MarkFlagRequired("cluster-name")
    cmd.MarkFlagRequired("customer-project")
    cmd.MarkFlagRequired("management-project")
    cmd.MarkFlagRequired("psc-service-attachment")

    return cmd
}

type GCPSetupConfig struct {
    ClusterName           string
    CustomerProject       string
    CustomerRegion        string
    CustomerNetwork       string
    CustomerSubnet        string
    ManagementProject     string
    PSCServiceAttachment  string
    OutputDir            string
    GenerateTerraform    bool
    DryRun               bool
}

func runGCPSetup(cmd *cobra.Command, args []string) error {
    config := &GCPSetupConfig{
        ClusterName:          cmd.Flag("cluster-name").Value.String(),
        CustomerProject:      cmd.Flag("customer-project").Value.String(),
        CustomerRegion:       cmd.Flag("customer-region").Value.String(),
        CustomerNetwork:      cmd.Flag("customer-network").Value.String(),
        CustomerSubnet:       cmd.Flag("customer-subnet").Value.String(),
        ManagementProject:    cmd.Flag("management-project").Value.String(),
        PSCServiceAttachment: cmd.Flag("psc-service-attachment").Value.String(),
        OutputDir:           cmd.Flag("output-dir").Value.String(),
        GenerateTerraform:   cmd.Flag("terraform").Value.String() == "true",
        DryRun:              cmd.Flag("dry-run").Value.String() == "true",
    }

    // Validate configuration
    if err := validateGCPSetupConfig(config); err != nil {
        return fmt.Errorf("configuration validation failed: %w", err)
    }

    // Create output directory
    if err := os.MkdirAll(config.OutputDir, 0755); err != nil {
        return fmt.Errorf("failed to create output directory: %w", err)
    }

    // Generate setup files
    if config.GenerateTerraform {
        return generateTerraformModules(config)
    }

    return generateShellScripts(config)
}

// validateGCPSetupConfig validates the setup configuration
func validateGCPSetupConfig(config *GCPSetupConfig) error {
    // Validate GCP project ID format
    if !isValidGCPProjectID(config.CustomerProject) {
        return fmt.Errorf("invalid customer project ID: %s", config.CustomerProject)
    }

    if !isValidGCPProjectID(config.ManagementProject) {
        return fmt.Errorf("invalid management project ID: %s", config.ManagementProject)
    }

    // Validate PSC Service Attachment URI format
    if !isValidPSCServiceAttachmentURI(config.PSCServiceAttachment) {
        return fmt.Errorf("invalid PSC Service Attachment URI: %s", config.PSCServiceAttachment)
    }

    // Set default region if not specified
    if config.CustomerRegion == "" {
        config.CustomerRegion = "us-central1" // Default region
    }

    return nil
}

// generateShellScripts generates shell scripts for customer setup
func generateShellScripts(config *GCPSetupConfig) error {
    scripts := map[string]string{
        "setup-iam.sh":        iamSetupScript,
        "setup-network.sh":    networkSetupScript,
        "setup-psc.sh":        pscSetupScript,
        "cleanup.sh":          cleanupScript,
        "validate-setup.sh":   validationScript,
    }

    for filename, templateContent := range scripts {
        if err := generateScriptFromTemplate(config, filename, templateContent); err != nil {
            return fmt.Errorf("failed to generate %s: %w", filename, err)
        }
    }

    // Generate README with instructions
    if err := generateReadme(config); err != nil {
        return fmt.Errorf("failed to generate README: %w", err)
    }

    fmt.Printf("Setup scripts generated in: %s\n", config.OutputDir)
    fmt.Printf("Run the scripts in this order:\n")
    fmt.Printf("1. chmod +x %s/*.sh\n", config.OutputDir)
    fmt.Printf("2. ./%s/setup-iam.sh\n", config.OutputDir)
    fmt.Printf("3. ./%s/setup-network.sh\n", config.OutputDir)
    fmt.Printf("4. ./%s/setup-psc.sh\n", config.OutputDir)
    fmt.Printf("5. ./%s/validate-setup.sh\n", config.OutputDir)

    return nil
}

// generateScriptFromTemplate generates a script file from a template
func generateScriptFromTemplate(config *GCPSetupConfig, filename, templateContent string) error {
    tmpl, err := template.New(filename).Parse(templateContent)
    if err != nil {
        return fmt.Errorf("failed to parse template: %w", err)
    }

    filepath := filepath.Join(config.OutputDir, filename)
    file, err := os.Create(filepath)
    if err != nil {
        return fmt.Errorf("failed to create file: %w", err)
    }
    defer file.Close()

    if err := tmpl.Execute(file, config); err != nil {
        return fmt.Errorf("failed to execute template: %w", err)
    }

    // Make script executable
    if err := os.Chmod(filepath, 0755); err != nil {
        return fmt.Errorf("failed to make script executable: %w", err)
    }

    return nil
}

// Script templates
const iamSetupScript = `#!/bin/bash
# IAM Setup Script for HyperShift GCP Customer Project
# Generated for cluster: {{.ClusterName}}

set -euo pipefail

CUSTOMER_PROJECT="{{.CustomerProject}}"
MANAGEMENT_PROJECT="{{.ManagementProject}}"
CLUSTER_NAME="{{.ClusterName}}"

echo "Setting up IAM for HyperShift GCP customer project: $CUSTOMER_PROJECT"

# Create service account for worker nodes
gcloud iam service-accounts create "hypershift-$CLUSTER_NAME-worker" \
    --display-name="HyperShift $CLUSTER_NAME Worker Nodes" \
    --description="Service account for HyperShift worker nodes" \
    --project="$CUSTOMER_PROJECT"

# Create service account for customer project operations
gcloud iam service-accounts create "hypershift-$CLUSTER_NAME-customer" \
    --display-name="HyperShift $CLUSTER_NAME Customer Operations" \
    --description="Service account for cross-project operations" \
    --project="$CUSTOMER_PROJECT"

# Grant required roles to worker service account
WORKER_SA="hypershift-$CLUSTER_NAME-worker@$CUSTOMER_PROJECT.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$CUSTOMER_PROJECT" \
    --member="serviceAccount:$WORKER_SA" \
    --role="roles/compute.instanceAdmin"

gcloud projects add-iam-policy-binding "$CUSTOMER_PROJECT" \
    --member="serviceAccount:$WORKER_SA" \
    --role="roles/compute.networkUser"

# Grant required roles to customer operations service account
CUSTOMER_SA="hypershift-$CLUSTER_NAME-customer@$CUSTOMER_PROJECT.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$CUSTOMER_PROJECT" \
    --member="serviceAccount:$CUSTOMER_SA" \
    --role="roles/compute.networkAdmin"

gcloud projects add-iam-policy-binding "$CUSTOMER_PROJECT" \
    --member="serviceAccount:$CUSTOMER_SA" \
    --role="roles/compute.instanceAdmin"

# Allow management project to impersonate customer service account
MANAGEMENT_SA="hypershift-operator@$MANAGEMENT_PROJECT.iam.gserviceaccount.com"
gcloud iam service-accounts add-iam-policy-binding "$CUSTOMER_SA" \
    --member="serviceAccount:$MANAGEMENT_SA" \
    --role="roles/iam.serviceAccountTokenCreator" \
    --project="$CUSTOMER_PROJECT"

echo "IAM setup completed successfully!"
`

const networkSetupScript = `#!/bin/bash
# Network Setup Script for HyperShift GCP Customer Project

set -euo pipefail

CUSTOMER_PROJECT="{{.CustomerProject}}"
CUSTOMER_REGION="{{.CustomerRegion}}"
CUSTOMER_NETWORK="{{.CustomerNetwork}}"
CUSTOMER_SUBNET="{{.CustomerSubnet}}"
CLUSTER_NAME="{{.ClusterName}}"

echo "Setting up network configuration for customer project: $CUSTOMER_PROJECT"

# Create firewall rules for HyperShift traffic
gcloud compute firewall-rules create "hypershift-$CLUSTER_NAME-allow-api" \
    --project="$CUSTOMER_PROJECT" \
    --network="$CUSTOMER_NETWORK" \
    --allow="tcp:6443,tcp:443,tcp:22623" \
    --source-tags="hypershift-$CLUSTER_NAME-worker" \
    --description="Allow HyperShift API and MCS traffic" \
    --direction="INGRESS"

gcloud compute firewall-rules create "hypershift-$CLUSTER_NAME-allow-internal" \
    --project="$CUSTOMER_PROJECT" \
    --network="$CUSTOMER_NETWORK" \
    --allow="tcp:0-65535,udp:0-65535,icmp" \
    --source-ranges="10.0.0.0/8,172.16.0.0/12,192.168.0.0/16" \
    --target-tags="hypershift-$CLUSTER_NAME-worker" \
    --description="Allow internal cluster communication" \
    --direction="INGRESS"

echo "Network setup completed successfully!"
`

const pscSetupScript = `#!/bin/bash
# PSC Setup Script for HyperShift GCP Customer Project

set -euo pipefail

CUSTOMER_PROJECT="{{.CustomerProject}}"
CUSTOMER_REGION="{{.CustomerRegion}}"
CUSTOMER_NETWORK="{{.CustomerNetwork}}"
CLUSTER_NAME="{{.ClusterName}}"
PSC_SERVICE_ATTACHMENT="{{.PSCServiceAttachment}}"

echo "Setting up PSC consumer endpoint for cluster: $CLUSTER_NAME"

# Create PSC consumer endpoint
gcloud compute addresses create "hypershift-$CLUSTER_NAME-consumer" \
    --project="$CUSTOMER_PROJECT" \
    --global \
    --purpose="PRIVATE_SERVICE_CONNECT" \
    --address-type="INTERNAL" \
    --network="projects/$CUSTOMER_PROJECT/global/networks/$CUSTOMER_NETWORK"

# Connect to PSC service attachment
gcloud compute forwarding-rules create "hypershift-$CLUSTER_NAME-consumer-fwd" \
    --project="$CUSTOMER_PROJECT" \
    --region="$CUSTOMER_REGION" \
    --network="projects/$CUSTOMER_PROJECT/global/networks/$CUSTOMER_NETWORK" \
    --address="hypershift-$CLUSTER_NAME-consumer" \
    --target-service-attachment="$PSC_SERVICE_ATTACHMENT"

# Get the assigned IP address
CONSUMER_IP=$(gcloud compute addresses describe "hypershift-$CLUSTER_NAME-consumer" \
    --project="$CUSTOMER_PROJECT" \
    --global \
    --format="value(address)")

echo "PSC consumer endpoint created with IP: $CONSUMER_IP"
echo "Use this IP as the API server endpoint for worker nodes"

# Save IP to file for reference
echo "$CONSUMER_IP" > "$CLUSTER_NAME-api-endpoint.txt"
echo "API endpoint IP saved to: $CLUSTER_NAME-api-endpoint.txt"
`

const validationScript = `#!/bin/bash
# Validation Script for HyperShift GCP Customer Setup

set -euo pipefail

CUSTOMER_PROJECT="{{.CustomerProject}}"
CLUSTER_NAME="{{.ClusterName}}"

echo "Validating HyperShift GCP customer setup..."

# Validate service accounts exist
echo "Checking service accounts..."
gcloud iam service-accounts describe "hypershift-$CLUSTER_NAME-worker@$CUSTOMER_PROJECT.iam.gserviceaccount.com" \
    --project="$CUSTOMER_PROJECT" > /dev/null
echo "✓ Worker service account exists"

gcloud iam service-accounts describe "hypershift-$CLUSTER_NAME-customer@$CUSTOMER_PROJECT.iam.gserviceaccount.com" \
    --project="$CUSTOMER_PROJECT" > /dev/null
echo "✓ Customer operations service account exists"

# Validate firewall rules
echo "Checking firewall rules..."
gcloud compute firewall-rules describe "hypershift-$CLUSTER_NAME-allow-api" \
    --project="$CUSTOMER_PROJECT" > /dev/null
echo "✓ API firewall rule exists"

# Validate PSC consumer endpoint
echo "Checking PSC consumer endpoint..."
gcloud compute addresses describe "hypershift-$CLUSTER_NAME-consumer" \
    --project="$CUSTOMER_PROJECT" \
    --global > /dev/null
echo "✓ PSC consumer endpoint exists"

# Test connectivity (if possible)
if [ -f "$CLUSTER_NAME-api-endpoint.txt" ]; then
    API_IP=$(cat "$CLUSTER_NAME-api-endpoint.txt")
    echo "Testing connectivity to API server at $API_IP..."

    # Try to connect to the API server (basic connectivity test)
    if timeout 10 bash -c "</dev/tcp/$API_IP/6443"; then
        echo "✓ API server is reachable"
    else
        echo "⚠ API server connectivity test failed (this may be expected if cluster is not fully ready)"
    fi
fi

echo "Validation completed!"
`

const cleanupScript = `#!/bin/bash
# Cleanup Script for HyperShift GCP Customer Setup

set -euo pipefail

CUSTOMER_PROJECT="{{.CustomerProject}}"
CUSTOMER_REGION="{{.CustomerRegion}}"
CLUSTER_NAME="{{.ClusterName}}"

echo "Cleaning up HyperShift GCP customer resources..."

# Delete PSC resources
echo "Deleting PSC resources..."
gcloud compute forwarding-rules delete "hypershift-$CLUSTER_NAME-consumer-fwd" \
    --project="$CUSTOMER_PROJECT" \
    --region="$CUSTOMER_REGION" \
    --quiet || true

gcloud compute addresses delete "hypershift-$CLUSTER_NAME-consumer" \
    --project="$CUSTOMER_PROJECT" \
    --global \
    --quiet || true

# Delete firewall rules
echo "Deleting firewall rules..."
gcloud compute firewall-rules delete "hypershift-$CLUSTER_NAME-allow-api" \
    --project="$CUSTOMER_PROJECT" \
    --quiet || true

gcloud compute firewall-rules delete "hypershift-$CLUSTER_NAME-allow-internal" \
    --project="$CUSTOMER_PROJECT" \
    --quiet || true

# Delete service accounts
echo "Deleting service accounts..."
gcloud iam service-accounts delete "hypershift-$CLUSTER_NAME-worker@$CUSTOMER_PROJECT.iam.gserviceaccount.com" \
    --project="$CUSTOMER_PROJECT" \
    --quiet || true

gcloud iam service-accounts delete "hypershift-$CLUSTER_NAME-customer@$CUSTOMER_PROJECT.iam.gserviceaccount.com" \
    --project="$CUSTOMER_PROJECT" \
    --quiet || true

echo "Cleanup completed!"
`
```

**2. Generate Terraform Modules** (`cmd/setup/terraform.go`):
```go
// generateTerraformModules creates Terraform modules for infrastructure automation
func generateTerraformModules(config *GCPSetupConfig) error {
    modules := map[string]string{
        "main.tf":          terraformMainModule,
        "variables.tf":     terraformVariables,
        "outputs.tf":       terraformOutputs,
        "versions.tf":      terraformVersions,
        "iam.tf":           terraformIAMModule,
        "network.tf":       terraformNetworkModule,
        "psc.tf":           terraformPSCModule,
    }

    // Create terraform directory
    terraformDir := filepath.Join(config.OutputDir, "terraform")
    if err := os.MkdirAll(terraformDir, 0755); err != nil {
        return fmt.Errorf("failed to create terraform directory: %w", err)
    }

    for filename, templateContent := range modules {
        if err := generateTerraformFile(config, terraformDir, filename, templateContent); err != nil {
            return fmt.Errorf("failed to generate %s: %w", filename, err)
        }
    }

    // Generate terraform.tfvars file with customer values
    if err := generateTerraformVars(config, terraformDir); err != nil {
        return fmt.Errorf("failed to generate terraform.tfvars: %w", err)
    }

    fmt.Printf("Terraform modules generated in: %s\n", terraformDir)
    fmt.Printf("To apply the configuration:\n")
    fmt.Printf("1. cd %s\n", terraformDir)
    fmt.Printf("2. terraform init\n")
    fmt.Printf("3. terraform plan\n")
    fmt.Printf("4. terraform apply\n")

    return nil
}

const terraformMainModule = `# HyperShift GCP Customer Project Setup
# Generated for cluster: {{.ClusterName}}

terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 4.0"
    }
  }
}

provider "google" {
  project = var.customer_project
  region  = var.customer_region
}

# Import existing resources if they exist
resource "google_compute_network" "customer_network" {
  count                   = var.create_network ? 1 : 0
  name                    = var.customer_network
  auto_create_subnetworks = false
  project                 = var.customer_project
}

resource "google_compute_subnetwork" "customer_subnet" {
  count         = var.create_subnet ? 1 : 0
  name          = var.customer_subnet
  network       = var.customer_network
  ip_cidr_range = var.subnet_cidr
  region        = var.customer_region
  project       = var.customer_project

  depends_on = [google_compute_network.customer_network]
}
`
```

**Integration Points**:
- **CLI Framework**: Integrates with existing HyperShift CLI structure
- **Template System**: Uses Go templates for dynamic script generation
- **Validation**: Includes configuration validation and pre-flight checks
- **Documentation**: Auto-generates README and usage instructions

**Testing Strategy**:
```bash
# Test CLI command generation
hypershift setup gcp --cluster-name=test-cluster --customer-project=customer-123 --management-project=mgmt-123 --psc-service-attachment=projects/mgmt-123/regions/us-central1/serviceAttachments/test-psc

# Test generated scripts
cd gcp-setup
./validate-setup.sh
```

#### Milestone 4.4: Testing and Documentation
**Deliverable**: Complete test coverage and documentation

**Detailed Technical Tasks**:

**1. Complete E2E Test Suite** (`test/e2e/gcp/cluster_lifecycle_test.go`):
```go
package gcp

import (
    "context"
    "fmt"
    "testing"
    "time"

    . "github.com/onsi/ginkgo/v2"
    . "github.com/onsi/gomega"

    hyperv1 "github.com/openshift/hypershift/api/hypershift/v1beta1"
    "github.com/openshift/hypershift/test/e2e/util"
    apierrors "k8s.io/apimachinery/pkg/api/errors"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/utils/ptr"
    "sigs.k8s.io/controller-runtime/pkg/client"
)

var _ = Describe("GCP Cluster Lifecycle E2E", func() {
    var (
        ctx           context.Context
        hostedCluster *hyperv1.HostedCluster
        nodePool      *hyperv1.NodePool
        clusterName   string
        namespace     string
    )

    BeforeEach(func() {
        ctx = context.Background()
        clusterName = fmt.Sprintf("e2e-gcp-%s", util.SimpleNameGenerator.GenerateName(""))
        namespace = "hypershift-e2e-gcp"

        // Ensure namespace exists
        util.EnsureNamespace(k8sClient, namespace)
    })

    AfterEach(func() {
        if hostedCluster != nil {
            // Clean up HostedCluster
            Expect(k8sClient.Delete(ctx, hostedCluster)).To(Succeed())

            // Wait for deletion
            Eventually(func() bool {
                cluster := &hyperv1.HostedCluster{}
                err := k8sClient.Get(ctx, client.ObjectKeyFromObject(hostedCluster), cluster)
                return apierrors.IsNotFound(err)
            }, "15m", "30s").Should(BeTrue())
        }
    })

    Context("Full Cluster Lifecycle", func() {
        It("should create, scale, and delete a HostedCluster successfully", func() {
            By("Creating HostedCluster with GCP platform")
            hostedCluster = &hyperv1.HostedCluster{
                ObjectMeta: metav1.ObjectMeta{
                    Name:      clusterName,
                    Namespace: namespace,
                },
                Spec: hyperv1.HostedClusterSpec{
                    Platform: hyperv1.PlatformSpec{
                        Type: hyperv1.GCPPlatform,
                        GCP: &hyperv1.GCPPlatformSpec{
                            Project: e2eGCPProject,
                            Region:  e2eGCPRegion,
                            Network: &hyperv1.GCPNetworkSpec{
                                Name:   e2eGCPNetwork,
                                Subnet: e2eGCPSubnet,
                            },
                            PrivateServiceConnect: &hyperv1.GCPPSCSpec{
                                Enabled: true,
                                Type:    "dedicated",
                            },
                            CrossProjectWorkers: &hyperv1.GCPCrossProjectConfig{
                                Enabled:         true,
                                AllowedProjects: []string{e2eCustomerProject},
                            },
                        },
                    },
                    Release: hyperv1.Release{
                        Image: e2eReleaseImage,
                    },
                    ClusterID: clusterName,
                    InfraID:   clusterName,
                    DNS: hyperv1.DNSSpec{
                        BaseDomain: e2eBaseDomain,
                    },
                    Services: []hyperv1.ServiceSpec{
                        {
                            Service: hyperv1.APIServer,
                            ServicePublishingStrategy: hyperv1.ServicePublishingStrategy{
                                Type: hyperv1.LoadBalancer,
                            },
                        },
                    },
                    Networking: hyperv1.ClusterNetworking{
                        PodCIDR:     "10.132.0.0/14",
                        ServiceCIDR: "172.31.0.0/16",
                    },
                },
            }

            Expect(k8sClient.Create(ctx, hostedCluster)).To(Succeed())

            By("Waiting for PSC infrastructure to be ready")
            Eventually(func() bool {
                cluster := &hyperv1.HostedCluster{}
                err := k8sClient.Get(ctx, client.ObjectKeyFromObject(hostedCluster), cluster)
                if err != nil {
                    return false
                }

                // Check for PSC ready condition
                for _, condition := range cluster.Status.Conditions {
                    if condition.Type == "GCPPrivateServiceConnectReady" && condition.Status == metav1.ConditionTrue {
                        return true
                    }
                }
                return false
            }, "10m", "30s").Should(BeTrue())

            By("Waiting for cluster to become available")
            Eventually(func() bool {
                cluster := &hyperv1.HostedCluster{}
                err := k8sClient.Get(ctx, client.ObjectKeyFromObject(hostedCluster), cluster)
                if err != nil {
                    return false
                }

                // Check for Available condition
                for _, condition := range cluster.Status.Conditions {
                    if condition.Type == "Available" && condition.Status == metav1.ConditionTrue {
                        return true
                    }
                }
                return false
            }, "20m", "1m").Should(BeTrue())

            By("Creating NodePool in customer project")
            nodePool = &hyperv1.NodePool{
                ObjectMeta: metav1.ObjectMeta{
                    Name:      clusterName + "-workers",
                    Namespace: namespace,
                },
                Spec: hyperv1.NodePoolSpec{
                    ClusterName: clusterName,
                    Replicas:    ptr.To(int32(2)),
                    Platform: hyperv1.NodePoolPlatform{
                        Type: hyperv1.GCPPlatform,
                        GCP: &hyperv1.GCPNodePoolPlatform{
                            Project:      e2eCustomerProject,
                            Zone:         e2eGCPRegion + "-a",
                            InstanceType: "e2-standard-4",
                            DiskSizeGB:   100,
                            DiskType:     "pd-balanced",
                            Subnet:       e2eCustomerSubnet,
                        },
                    },
                    Management: hyperv1.NodePoolManagement{
                        AutoRepair:  true,
                        UpgradeType: hyperv1.UpgradeTypeReplace,
                    },
                },
            }

            Expect(k8sClient.Create(ctx, nodePool)).To(Succeed())

            By("Waiting for worker nodes to become ready")
            Eventually(func() int32 {
                pool := &hyperv1.NodePool{}
                err := k8sClient.Get(ctx, client.ObjectKeyFromObject(nodePool), pool)
                if err != nil {
                    return 0
                }
                return pool.Status.ReadyReplicas
            }, "15m", "30s").Should(Equal(int32(2)))

            By("Testing PSC connectivity from worker nodes")
            Expect(validatePSCConnectivity(ctx, hostedCluster, nodePool)).To(Succeed())

            By("Scaling NodePool up")
            nodePool.Spec.Replicas = ptr.To(int32(3))
            Expect(k8sClient.Update(ctx, nodePool)).To(Succeed())

            Eventually(func() int32 {
                pool := &hyperv1.NodePool{}
                err := k8sClient.Get(ctx, client.ObjectKeyFromObject(nodePool), pool)
                if err != nil {
                    return 0
                }
                return pool.Status.ReadyReplicas
            }, "10m", "30s").Should(Equal(int32(3)))

            By("Scaling NodePool down")
            nodePool.Spec.Replicas = ptr.To(int32(1))
            Expect(k8sClient.Update(ctx, nodePool)).To(Succeed())

            Eventually(func() int32 {
                pool := &hyperv1.NodePool{}
                err := k8sClient.Get(ctx, client.ObjectKeyFromObject(nodePool), pool)
                if err != nil {
                    return 0
                }
                return pool.Status.ReadyReplicas
            }, "10m", "30s").Should(Equal(int32(1)))

            By("Deleting NodePool")
            Expect(k8sClient.Delete(ctx, nodePool)).To(Succeed())

            Eventually(func() bool {
                pool := &hyperv1.NodePool{}
                err := k8sClient.Get(ctx, client.ObjectKeyFromObject(nodePool), pool)
                return apierrors.IsNotFound(err)
            }, "10m", "30s").Should(BeTrue())
        })

        It("should handle cross-project scenarios correctly", func() {
            // Test multiple customer projects
            // Test Shared VPC scenarios
            // Test IAM permission validation
        })

        It("should validate PSC endpoint security", func() {
            // Test firewall rule enforcement
            // Test unauthorized access prevention
            // Test network isolation between clusters
        })
    })
})

// validatePSCConnectivity tests end-to-end connectivity via PSC
func validatePSCConnectivity(ctx context.Context, hc *hyperv1.HostedCluster, np *hyperv1.NodePool) error {
    // Get PSC consumer IP from NodePool status
    if np.Status.Platform == nil || np.Status.Platform.GCP == nil || np.Status.Platform.GCP.PSCConsumer == nil {
        return fmt.Errorf("PSC consumer information not available in NodePool status")
    }

    consumerIP := np.Status.Platform.GCP.PSCConsumer.IPAddress
    if consumerIP == "" {
        return fmt.Errorf("PSC consumer IP not assigned")
    }

    // Test API server accessibility
    // This would involve creating a test pod in the customer project and testing connectivity
    // For now, we'll simulate this test

    log.Printf("Testing PSC connectivity to API server at %s:6443", consumerIP)

    // In a real implementation, this would:
    // 1. Create a test VM in customer project
    // 2. Test curl/telnet to the PSC consumer IP on port 6443
    // 3. Verify proper TLS handshake
    // 4. Clean up test resources

    return nil
}
```

**2. Performance and Scale Testing** (`test/e2e/gcp/scale_test.go`):
```go
// Scale testing with multiple HostedClusters
var _ = Describe("GCP Scale Testing", func() {
    It("should support multiple concurrent HostedClusters", func() {
        const numClusters = 5
        var clusters []*hyperv1.HostedCluster

        By(fmt.Sprintf("Creating %d HostedClusters concurrently", numClusters))
        for i := 0; i < numClusters; i++ {
            cluster := createTestHostedCluster(fmt.Sprintf("scale-test-%d", i))
            clusters = append(clusters, cluster)
            Expect(k8sClient.Create(ctx, cluster)).To(Succeed())
        }

        By("Waiting for all clusters to become available")
        for _, cluster := range clusters {
            Eventually(func() bool {
                return isClusterAvailable(ctx, cluster)
            }, "25m", "1m").Should(BeTrue())
        }

        By("Testing PSC resource limits")
        validatePSCResourceUsage(ctx, clusters)

        By("Cleaning up all clusters")
        for _, cluster := range clusters {
            Expect(k8sClient.Delete(ctx, cluster)).To(Succeed())
        }
    })

    It("should handle PSC endpoint limits gracefully", func() {
        // Test behavior when approaching PSC quota limits
        // Verify proper error handling and status reporting
    })
})
```

**3. Troubleshooting Documentation** (`docs/troubleshooting/gcp-psc.md`):
```markdown
# GCP PSC Troubleshooting Guide

## Common Issues

### PSC Service Attachment Creation Failed

**Symptoms**:
- HostedCluster stuck in "Creating" state
- Error: "failed to create PSC service attachment"

**Diagnosis**:
```bash
# Check service account permissions
gcloud projects get-iam-policy PROJECT_ID

# Verify PSC quota
gcloud compute project-info describe --project=PROJECT_ID
```

**Solutions**:
1. Grant `roles/compute.networkAdmin` to service account
2. Request PSC quota increase
3. Check for naming conflicts

### Worker Nodes Cannot Reach API Server

**Symptoms**:
- Nodes stuck in "NotReady" state
- Kubelet logs show connection timeouts

**Diagnosis**:
```bash
# Check PSC consumer endpoint
gcloud compute addresses describe CONSUMER_ENDPOINT --global --project=CUSTOMER_PROJECT

# Test connectivity from worker node
gcloud compute ssh WORKER_NODE --project=CUSTOMER_PROJECT --command="curl -k https://PSC_IP:6443/healthz"
```

**Solutions**:
1. Verify firewall rules allow traffic on ports 6443, 443, 22623
2. Check PSC consumer endpoint configuration
3. Validate network tags on worker nodes

### Cross-Project Access Denied

**Symptoms**:
- NodePool creation fails with permission errors
- CAPI provider logs show impersonation failures

**Diagnosis**:
```bash
# Test impersonation
gcloud auth activate-service-account --key-file=MANAGEMENT_SA_KEY
gcloud auth print-access-token --impersonate-service-account=CUSTOMER_SA
```

**Solutions**:
1. Configure IAM role bindings for cross-project access
2. Ensure service account exists in customer project
3. Verify Workload Identity configuration
```

**4. Operational Procedures Documentation** (`docs/operations/gcp-operations.md`):
```markdown
# GCP Operations Guide

## Cluster Creation

### Prerequisites
1. Management GKE cluster with Workload Identity enabled
2. Required GCP APIs enabled
3. Service accounts configured with appropriate IAM roles
4. Customer project prepared with setup scripts

### Creation Process
```bash
# 1. Generate customer setup scripts
hypershift setup gcp --cluster-name=CLUSTER_NAME --customer-project=CUSTOMER_PROJECT

# 2. Customer runs setup scripts
cd gcp-setup
./setup-iam.sh
./setup-network.sh
./setup-psc.sh

# 3. Create HostedCluster
kubectl apply -f hosted-cluster.yaml

# 4. Monitor cluster creation
kubectl get hostedcluster CLUSTER_NAME -w

# 5. Create NodePool
kubectl apply -f nodepool.yaml
```

## Monitoring

### Key Metrics
- PSC connection count per Service Attachment
- ILB backend health status
- Cross-project API call success rate
- Worker node join success rate

### Health Checks
```bash
# Check cluster health
kubectl get hostedcluster
kubectl get nodepool

# Check PSC infrastructure
gcloud compute service-attachments list --project=MANAGEMENT_PROJECT
gcloud compute forwarding-rules list --project=MANAGEMENT_PROJECT

# Check worker node health
kubectl --kubeconfig=guest-kubeconfig get nodes
```

## Scaling Operations

### Scaling NodePools
```bash
# Scale up
kubectl patch nodepool NODEPOOL_NAME --type='merge' -p='{"spec":{"replicas":5}}'

# Scale down
kubectl patch nodepool NODEPOOL_NAME --type='merge' -p='{"spec":{"replicas":1}}'
```

### Adding Customer Projects
```bash
# Update HostedCluster spec
kubectl patch hostedcluster CLUSTER_NAME --type='merge' -p='{
  "spec":{
    "platform":{
      "gcp":{
        "crossProjectWorkers":{
          "allowedProjects":["project1","project2","project3"]
        }
      }
    }
  }
}'
```

## Disaster Recovery

### Backup Procedures
1. Export HostedCluster and NodePool manifests
2. Document PSC Service Attachment URIs
3. Backup customer project configurations

### Recovery Procedures
1. Recreate management cluster infrastructure
2. Restore HostedCluster from manifest
3. Reconnect to existing PSC endpoints
4. Validate worker node connectivity
```

**Integration Points**:
- **CI/CD Integration**: E2E tests run in continuous integration pipeline
- **Documentation Site**: Auto-generated docs integrated with documentation website
- **Monitoring Dashboard**: Test results and performance metrics displayed in dashboards
- **Alert Integration**: Test failures trigger alerts for engineering teams

**Test Infrastructure Requirements**:
```yaml
# E2E test environment configuration
gcp:
  managementProject: "hypershift-e2e-mgmt"
  customerProject: "hypershift-e2e-customer"
  region: "us-central1"
  network: "e2e-test-vpc"
  subnet: "e2e-test-subnet"

clusters:
  maxConcurrent: 5
  timeout: "30m"

resources:
  - type: "PSC Service Attachments"
    quota: 10
  - type: "Internal Load Balancers"
    quota: 50
  - type: "Compute Instances"
    quota: 100
```

---

## Implementation Guidelines

### Development Standards
- **Testing Required**: Each milestone requires unit, integration, and acceptance tests
- **Incremental Delivery**: Each milestone should be independently testable
- **Error Handling**: Comprehensive error handling with actionable error messages
- **Documentation**: Code documentation and user-facing guides for each milestone

### Technical Constraints
- **GCP Quotas**: PSC Service Attachment quota limits cluster count per management cluster
- **Cross-Project Permissions**: Customer must maintain required IAM roles
- **Network Requirements**: Customer VPC must allow PSC consumer endpoints
- **CAPG Compatibility**: Must work with supported CAPG versions

### Risk Mitigation
- **Incremental Testing**: Each phase builds on tested components from previous phases
- **Fallback Plans**: Each milestone has clear acceptance criteria for go/no-go decisions
- **Resource Cleanup**: All milestones include cleanup procedures
- **Monitoring**: Status tracking and validation throughout implementation

---

## Success Criteria

### Functional Requirements
- [ ] HostedCluster creation succeeds with GCP platform
- [ ] Worker nodes deploy in customer GCP projects
- [ ] Cross-project PSC connectivity works reliably
- [ ] Customer setup process is documented and automated
- [ ] Resource cleanup works on cluster deletion

### Performance Requirements
- [ ] HostedCluster creation time < 15 minutes
- [ ] Worker node deployment time < 10 minutes
- [ ] PSC connectivity latency < 10ms additional overhead
- [ ] Support for 50+ concurrent HostedClusters per management cluster

### Operational Requirements
- [ ] Clear error messages for common failure scenarios
- [ ] Automated customer environment validation
- [ ] Comprehensive troubleshooting documentation
- [ ] Monitoring and alerting for PSC connectivity

---

## Dependencies and Prerequisites

### External Dependencies
- **CAPG Version**: Compatible with HyperShift's CAPG version requirements
- **GCP APIs**: Compute Engine, IAM, DNS APIs enabled
- **Workload Identity**: GKE cluster with Workload Identity enabled
- **Google Service Accounts**: Pre-created for all 5 controllers with appropriate IAM roles
- **Network Infrastructure**: Customer VPC and subnets pre-configured
- **IAM Permissions**: Management cluster service account has permission to create/bind Google Service Accounts

### Development Environment
- **Test Projects**: Separate GCP projects for development and testing
- **Quota Increases**: Sufficient quotas for PSC and ILB resources during testing
- **Workload Identity Test Setup**: Test GKE clusters with Workload Identity enabled
- **Google Service Account Setup**: Test Google Service Accounts for all controllers

---

## Risk Assessment

### High Risk Items
- **PSC Quota Limitations**: May limit scale testing and production capacity
- **Cross-Project IAM Complexity**: Customer permission management may be complex
- **CAPG Integration Changes**: CAPG API changes could require rework

### Mitigation Strategies
- **Early Quota Validation**: Test quota limits early in development
- **Comprehensive IAM Testing**: Validate all cross-project permission scenarios
- **CAPG Version Pinning**: Pin to specific CAPG version during development

### Contingency Plans
- **Scale Alternative**: Fall back to fewer clusters per management cluster if quota issues
- **Permission Simplification**: Reduce cross-project operations if IAM proves complex
- **CAPG Compatibility**: Implement compatibility layer if CAPG APIs change