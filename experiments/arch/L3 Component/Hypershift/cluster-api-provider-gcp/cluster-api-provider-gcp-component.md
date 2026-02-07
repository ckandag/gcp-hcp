# Cluster API Provider GCP Component Architecture (L3)

## Component Information
- **Component**: Cluster API Provider GCP (CAPG)
- **Level**: L3 Component Architecture
- **Repository**: `sigs.k8s.io/cluster-api-provider-gcp`
- **Integration Point**: HyperShift CAPI Provider Deployment
- **Status**: 🔄 **EXISTING COMPONENT - REQUIRES CONFIGURATION**
- **Version**: 1.0

## Implementation Status
- **Core CAPG Controllers**: ✅ **EXISTS** - No changes required to core CAPG functionality
- **GCPCluster Controller**: ✅ **EXISTS** - No changes required
- **GCPMachine Controller**: ✅ **EXISTS** - No changes required
- **PSC Consumer Support**: ❓ **UNCLEAR** - May need enhancement for cross-project PSC consumers
- **HyperShift Integration**: 🔄 **REQUIRES CONFIGURATION** - Deployment and RBAC configuration needed
- **Cross-Project Operations**: ✅ **EXISTS** - CAPG already supports cross-project deployment

## Required Changes
- **HyperShift CAPI Deployment**: ❌ **NEW** - New deployment configuration in control plane namespace
- **PSC Consumer Logic**: ❓ **ASSESSMENT NEEDED** - Verify CAPG supports PSC consumer endpoints
- **Workload Identity Configuration**: 🔄 **CONFIGURATION** - Service account annotations required
- **NodePool Integration**: 🔄 **ENHANCEMENT** - HyperShift NodePool controller integration

## Component Overview

The Cluster API Provider GCP component manages the lifecycle of GCP infrastructure resources for worker nodes, including cross-project deployment, PSC consumer endpoints, and machine instance management within the HyperShift architecture.

## Component Responsibilities

### Primary Functions
1. **Worker Node Lifecycle**: Manages GCE instances for worker nodes across customer projects
2. **PSC Consumer Management**: Creates and manages PSC consumer endpoints in customer projects
3. **Cross-Project Operations**: Orchestrates resources across management and customer GCP projects
4. **Machine Template Management**: Handles GCPMachineTemplate resources for worker node specifications
5. **Bootstrap Coordination**: Manages worker node bootstrap configuration and cluster joining

### Secondary Functions
- Network configuration for worker nodes
- Disk management and persistent volume setup
- Instance metadata configuration
- SSH key management for worker nodes
- Firewall rule coordination for cluster communication

## Detailed Architecture

### Controller Structure
```go
// Main cluster controller
type GCPClusterReconciler struct {
    client.Client
    Scheme    *runtime.Scheme
    gcpClient GCPClientInterface
}

// Machine controller for individual worker nodes
type GCPMachineReconciler struct {
    client.Client
    Scheme    *runtime.Scheme
    gcpClient GCPClientInterface
}

// Machine template controller
type GCPMachineTemplateReconciler struct {
    client.Client
    Scheme *runtime.Scheme
}
```

### Resource Definitions

#### GCPCluster Resource
```go
type GCPCluster struct {
    metav1.TypeMeta   `json:",inline"`
    metav1.ObjectMeta `json:"metadata,omitempty"`

    Spec   GCPClusterSpec   `json:"spec,omitempty"`
    Status GCPClusterStatus `json:"status,omitempty"`
}

type GCPClusterSpec struct {
    // GCP project where worker nodes will be deployed
    Project string `json:"project"`

    // GCP region for the cluster
    Region string `json:"region"`

    // Network configuration
    Network NetworkSpec `json:"network"`

    // Control plane endpoint (from PSC)
    ControlPlaneEndpoint *APIEndpoint `json:"controlPlaneEndpoint,omitempty"`

    // Private Service Connect configuration
    PrivateServiceConnect *PSCConfig `json:"privateServiceConnect,omitempty"`

    // Additional cluster-level configuration
    AdditionalLabels map[string]string `json:"additionalLabels,omitempty"`
}

type PSCConfig struct {
    // Enable PSC for this cluster
    Enabled bool `json:"enabled"`

    // URI of the PSC service attachment from management project
    ServiceAttachmentURI string `json:"serviceAttachmentURI"`

    // Consumer endpoint configuration
    ConsumerEndpoint *PSCConsumerEndpointConfig `json:"consumerEndpoint,omitempty"`
}
```

#### GCPMachine Resource
```go
type GCPMachine struct {
    metav1.TypeMeta   `json:",inline"`
    metav1.ObjectMeta `json:"metadata,omitempty"`

    Spec   GCPMachineSpec   `json:"spec,omitempty"`
    Status GCPMachineStatus `json:"status,omitempty"`
}

type GCPMachineSpec struct {
    // GCP instance configuration
    InstanceType string `json:"instanceType"`
    Zone         string `json:"zone"`

    // Disk configuration
    RootDeviceSize int64  `json:"rootDeviceSize,omitempty"`
    RootDeviceType string `json:"rootDeviceType,omitempty"`

    // Network configuration
    Subnet             string   `json:"subnet"`
    InternalIP         string   `json:"internalIP,omitempty"`
    PublicIP           *bool    `json:"publicIP,omitempty"`
    AdditionalNetworks []string `json:"additionalNetworks,omitempty"`

    // Service account configuration
    ServiceAccount ServiceAccount `json:"serviceAccount,omitempty"`

    // Bootstrap configuration
    ProviderID string `json:"providerID,omitempty"`
}
```

### GCPCluster Controller Logic

#### Cluster Reconciliation Flow
```go
func (r *GCPClusterReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
    log := ctrl.LoggerFrom(ctx)

    // 1. Fetch GCPCluster resource
    gcpCluster := &infrav1.GCPCluster{}
    if err := r.Get(ctx, req.NamespacedName, gcpCluster); err != nil {
        return ctrl.Result{}, client.IgnoreNotFound(err)
    }

    // 2. Get the associated CAPI Cluster
    cluster, err := util.GetOwnerCluster(ctx, r.Client, gcpCluster.ObjectMeta)
    if err != nil {
        return ctrl.Result{}, err
    }
    if cluster == nil {
        log.Info("Cluster Controller has not yet set OwnerRef")
        return ctrl.Result{}, nil
    }

    // 3. Handle deletion
    if !gcpCluster.DeletionTimestamp.IsZero() {
        return r.reconcileDelete(ctx, gcpCluster, cluster)
    }

    // 4. Handle normal reconciliation
    return r.reconcileNormal(ctx, gcpCluster, cluster)
}

func (r *GCPClusterReconciler) reconcileNormal(ctx context.Context,
    gcpCluster *infrav1.GCPCluster, cluster *clusterv1.Cluster) (ctrl.Result, error) {

    log := ctrl.LoggerFrom(ctx).WithValues("cluster", cluster.Name)

    // 1. Ensure finalizer is set
    if !controllerutil.ContainsFinalizer(gcpCluster, infrav1.ClusterFinalizer) {
        controllerutil.AddFinalizer(gcpCluster, infrav1.ClusterFinalizer)
        return ctrl.Result{}, r.Update(ctx, gcpCluster)
    }

    // 2. Create PSC consumer endpoint if PSC is enabled
    if gcpCluster.Spec.PrivateServiceConnect != nil && gcpCluster.Spec.PrivateServiceConnect.Enabled {
        if err := r.reconcilePSCConsumerEndpoint(ctx, gcpCluster); err != nil {
            return ctrl.Result{}, fmt.Errorf("failed to reconcile PSC consumer: %w", err)
        }
    }

    // 3. Reconcile network resources
    if err := r.reconcileNetworkResources(ctx, gcpCluster); err != nil {
        return ctrl.Result{}, fmt.Errorf("failed to reconcile network: %w", err)
    }

    // 4. Update cluster status
    if err := r.updateClusterStatus(ctx, gcpCluster); err != nil {
        return ctrl.Result{}, fmt.Errorf("failed to update status: %w", err)
    }

    // 5. Mark cluster as ready
    gcpCluster.Status.Ready = true
    conditions.MarkTrue(gcpCluster, infrav1.NetworkInfrastructureReadyCondition)

    return ctrl.Result{}, r.Status().Update(ctx, gcpCluster)
}
```

#### PSC Consumer Endpoint Management
```go
func (r *GCPClusterReconciler) reconcilePSCConsumerEndpoint(ctx context.Context,
    gcpCluster *infrav1.GCPCluster) error {

    log := ctrl.LoggerFrom(ctx)
    pscConfig := gcpCluster.Spec.PrivateServiceConnect

    // Create consumer endpoint name
    consumerEndpointName := fmt.Sprintf("hypershift-%s-consumer", gcpCluster.Name)

    // Check if consumer endpoint already exists
    existing, err := r.gcpClient.GetGlobalAddress(ctx, gcpCluster.Spec.Project, consumerEndpointName)
    if err == nil {
        // Update status with existing endpoint
        gcpCluster.Status.Network.PSCConsumerEndpoint = &infrav1.PSCConsumerEndpointStatus{
            Name:      existing.Name,
            IPAddress: existing.Address,
            Status:    "Ready",
        }
        return nil
    }

    // Create new consumer endpoint
    globalAddress := &compute.GlobalAddress{
        Name:        consumerEndpointName,
        Description: fmt.Sprintf("PSC consumer endpoint for HyperShift cluster %s", gcpCluster.Name),
        Purpose:     "PRIVATE_SERVICE_CONNECT",
        PscTarget:   pscConfig.ServiceAttachmentURI,
        Network:     fmt.Sprintf("projects/%s/global/networks/%s",
                       gcpCluster.Spec.Project, gcpCluster.Spec.Network.Name),
    }

    operation, err := r.gcpClient.CreateGlobalAddress(ctx, gcpCluster.Spec.Project, globalAddress)
    if err != nil {
        return fmt.Errorf("failed to create PSC consumer endpoint: %w", err)
    }

    // Wait for operation to complete
    if err := r.waitForGlobalOperation(ctx, gcpCluster.Spec.Project, operation.Name); err != nil {
        return fmt.Errorf("failed waiting for PSC consumer creation: %w", err)
    }

    // Get the created endpoint
    created, err := r.gcpClient.GetGlobalAddress(ctx, gcpCluster.Spec.Project, consumerEndpointName)
    if err != nil {
        return fmt.Errorf("failed to get created PSC consumer: %w", err)
    }

    // Update cluster status
    gcpCluster.Status.Network.PSCConsumerEndpoint = &infrav1.PSCConsumerEndpointStatus{
        Name:      created.Name,
        IPAddress: created.Address,
        Status:    "Ready",
    }

    log.Info("PSC consumer endpoint created",
        "name", created.Name,
        "ip", created.Address)

    return nil
}
```

### GCPMachine Controller Logic

#### Machine Reconciliation Flow
```go
func (r *GCPMachineReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
    log := ctrl.LoggerFrom(ctx)

    // 1. Fetch GCPMachine resource
    gcpMachine := &infrav1.GCPMachine{}
    if err := r.Get(ctx, req.NamespacedName, gcpMachine); err != nil {
        return ctrl.Result{}, client.IgnoreNotFound(err)
    }

    // 2. Get the associated CAPI Machine
    machine, err := util.GetOwnerMachine(ctx, r.Client, gcpMachine.ObjectMeta)
    if err != nil {
        return ctrl.Result{}, err
    }
    if machine == nil {
        log.Info("Machine Controller has not yet set OwnerRef")
        return ctrl.Result{}, nil
    }

    // 3. Get the associated Cluster
    cluster, err := util.GetClusterFromMetadata(ctx, r.Client, machine.ObjectMeta)
    if err != nil {
        return ctrl.Result{}, err
    }

    // 4. Handle deletion
    if !gcpMachine.DeletionTimestamp.IsZero() {
        return r.reconcileDelete(ctx, gcpMachine, machine, cluster)
    }

    // 5. Handle normal reconciliation
    return r.reconcileNormal(ctx, gcpMachine, machine, cluster)
}

func (r *GCPMachineReconciler) reconcileNormal(ctx context.Context,
    gcpMachine *infrav1.GCPMachine, machine *clusterv1.Machine,
    cluster *clusterv1.Cluster) (ctrl.Result, error) {

    log := ctrl.LoggerFrom(ctx).WithValues("machine", machine.Name)

    // 1. Ensure finalizer is set
    if !controllerutil.ContainsFinalizer(gcpMachine, infrav1.MachineFinalizer) {
        controllerutil.AddFinalizer(gcpMachine, infrav1.MachineFinalizer)
        return ctrl.Result{}, r.Update(ctx, gcpMachine)
    }

    // 2. Create or get the GCE instance
    instance, err := r.reconcileGCEInstance(ctx, gcpMachine, machine, cluster)
    if err != nil {
        return ctrl.Result{}, fmt.Errorf("failed to reconcile GCE instance: %w", err)
    }

    // 3. Update machine status
    if err := r.updateMachineStatus(ctx, gcpMachine, instance); err != nil {
        return ctrl.Result{}, fmt.Errorf("failed to update machine status: %w", err)
    }

    // 4. Update machine addresses
    if err := r.updateMachineAddresses(ctx, gcpMachine, instance); err != nil {
        return ctrl.Result{}, fmt.Errorf("failed to update machine addresses: %w", err)
    }

    return ctrl.Result{}, nil
}
```

#### GCE Instance Management
```go
func (r *GCPMachineReconciler) reconcileGCEInstance(ctx context.Context,
    gcpMachine *infrav1.GCPMachine, machine *clusterv1.Machine,
    cluster *clusterv1.Cluster) (*compute.Instance, error) {

    instanceName := gcpMachine.Name

    // Check if instance already exists
    existing, err := r.gcpClient.GetInstance(ctx, gcpMachine.Spec.Project, gcpMachine.Spec.Zone, instanceName)
    if err == nil {
        return existing, nil // Instance already exists
    }

    // Get bootstrap data from machine
    bootstrapData, err := r.getBootstrapData(ctx, machine)
    if err != nil {
        return nil, fmt.Errorf("failed to get bootstrap data: %w", err)
    }

    // Get PSC consumer endpoint IP from cluster
    gcpCluster := &infrav1.GCPCluster{}
    if err := r.Get(ctx, types.NamespacedName{
        Namespace: cluster.Namespace,
        Name:      cluster.Spec.InfrastructureRef.Name,
    }, gcpCluster); err != nil {
        return nil, fmt.Errorf("failed to get GCPCluster: %w", err)
    }

    var apiServerEndpoint string
    if gcpCluster.Status.Network.PSCConsumerEndpoint != nil {
        apiServerEndpoint = fmt.Sprintf("%s:6443", gcpCluster.Status.Network.PSCConsumerEndpoint.IPAddress)
    } else {
        return nil, fmt.Errorf("PSC consumer endpoint not ready")
    }

    // Create instance configuration
    instance := &compute.Instance{
        Name:         instanceName,
        Description:  fmt.Sprintf("Worker node for HyperShift cluster %s", cluster.Name),
        MachineType:  fmt.Sprintf("zones/%s/machineTypes/%s", gcpMachine.Spec.Zone, gcpMachine.Spec.InstanceType),
        Zone:         gcpMachine.Spec.Zone,

        // Boot disk configuration
        Disks: []*compute.AttachedDisk{
            {
                Boot:       true,
                AutoDelete: true,
                InitializeParams: &compute.AttachedDiskInitializeParams{
                    SourceImage: r.getWorkerNodeImage(ctx),
                    DiskType:    fmt.Sprintf("zones/%s/diskTypes/%s", gcpMachine.Spec.Zone, gcpMachine.Spec.RootDeviceType),
                    DiskSizeGb:  gcpMachine.Spec.RootDeviceSize,
                },
            },
        },

        // Network configuration
        NetworkInterfaces: []*compute.NetworkInterface{
            {
                Network:    fmt.Sprintf("projects/%s/global/networks/%s", gcpMachine.Spec.Project, gcpCluster.Spec.Network.Name),
                Subnetwork: fmt.Sprintf("projects/%s/regions/%s/subnetworks/%s", gcpMachine.Spec.Project, gcpCluster.Spec.Region, gcpMachine.Spec.Subnet),
                // No external IP for worker nodes
            },
        },

        // Service account configuration (Workload Identity)
        ServiceAccounts: []*compute.ServiceAccount{
            {
                Email: gcpMachine.Spec.ServiceAccount.Email,
                Scopes: []string{
                    "https://www.googleapis.com/auth/compute",
                    "https://www.googleapis.com/auth/devstorage.read_only",
                    "https://www.googleapis.com/auth/logging.write",
                    "https://www.googleapis.com/auth/monitoring.write",
                },
            },
        },

        // Metadata for bootstrap and configuration
        Metadata: &compute.Metadata{
            Items: []*compute.MetadataItems{
                {
                    Key:   "user-data",
                    Value: &bootstrapData,
                },
                {
                    Key:   "api-server-endpoint",
                    Value: &apiServerEndpoint,
                },
                {
                    Key:   "cluster-name",
                    Value: &cluster.Name,
                },
            },
        },

        // Labels for identification and management
        Labels: map[string]string{
            "hypershift-cluster": cluster.Name,
            "cluster-api-machine": machine.Name,
            "node-role": "worker",
        },

        // Tags for firewall rules
        Tags: &compute.Tags{
            Items: []string{
                fmt.Sprintf("hypershift-%s-worker", cluster.Name),
                "hypershift-worker-node",
            },
        },
    }

    // Create the instance
    operation, err := r.gcpClient.CreateInstance(ctx, gcpMachine.Spec.Project, gcpMachine.Spec.Zone, instance)
    if err != nil {
        return nil, fmt.Errorf("failed to create GCE instance: %w", err)
    }

    // Wait for instance creation
    if err := r.waitForZoneOperation(ctx, gcpMachine.Spec.Project, gcpMachine.Spec.Zone, operation.Name); err != nil {
        return nil, fmt.Errorf("failed waiting for instance creation: %w", err)
    }

    // Get the created instance
    created, err := r.gcpClient.GetInstance(ctx, gcpMachine.Spec.Project, gcpMachine.Spec.Zone, instanceName)
    if err != nil {
        return nil, fmt.Errorf("failed to get created instance: %w", err)
    }

    log.Info("GCE instance created",
        "instance", created.Name,
        "status", created.Status)

    return created, nil
}
```

### Bootstrap Configuration

#### Worker Node Bootstrap Data
```go
func (r *GCPMachineReconciler) getBootstrapData(ctx context.Context, machine *clusterv1.Machine) (string, error) {
    if machine.Spec.Bootstrap.DataSecretName == nil {
        return "", fmt.Errorf("bootstrap data secret name is not set")
    }

    secret := &corev1.Secret{}
    if err := r.Get(ctx, types.NamespacedName{
        Namespace: machine.Namespace,
        Name:      *machine.Spec.Bootstrap.DataSecretName,
    }, secret); err != nil {
        return "", fmt.Errorf("failed to get bootstrap secret: %w", err)
    }

    data, exists := secret.Data["value"]
    if !exists {
        return "", fmt.Errorf("bootstrap data not found in secret")
    }

    return string(data), nil
}

// Custom bootstrap configuration for PSC connectivity
func (r *GCPMachineReconciler) enhanceBootstrapForPSC(bootstrapData, apiServerEndpoint string) string {
    // Enhance the bootstrap script to use PSC endpoint
    pscBootstrapScript := fmt.Sprintf(`
# Configure API server endpoint for PSC
API_SERVER_ENDPOINT="%s"

# Update kubeadm configuration to use PSC endpoint
sed -i "s/server: .*/server: https://${API_SERVER_ENDPOINT}/" /etc/kubernetes/bootstrap-kubelet.conf

# Ensure proper DNS resolution for PSC endpoint
echo "# PSC endpoint configuration" >> /etc/hosts
echo "%s hypershift-api-server" >> /etc/hosts

%s
`, apiServerEndpoint, strings.Split(apiServerEndpoint, ":")[0], bootstrapData)

    return pscBootstrapScript
}
```

### Cross-Project Security

#### Service Account Management
```go
func (r *GCPMachineReconciler) reconcileServiceAccount(ctx context.Context,
    gcpMachine *infrav1.GCPMachine, cluster *clusterv1.Cluster) error {

    // Use Workload Identity-enabled service account
    serviceAccountEmail := fmt.Sprintf("hypershift-%s-worker@%s.iam.gserviceaccount.com",
        cluster.Name, gcpMachine.Spec.Project)

    // Validate service account exists and has required permissions
    if err := r.validateServiceAccount(ctx, gcpMachine.Spec.Project, serviceAccountEmail); err != nil {
        return fmt.Errorf("service account validation failed: %w", err)
    }

    gcpMachine.Spec.ServiceAccount.Email = serviceAccountEmail
    return nil
}

func (r *GCPMachineReconciler) validateServiceAccount(ctx context.Context,
    project, email string) error {

    // Check if service account exists
    sa, err := r.gcpClient.GetServiceAccount(ctx, project, email)
    if err != nil {
        return fmt.Errorf("service account %s not found in project %s: %w", email, project, err)
    }

    // Validate required IAM roles
    requiredRoles := []string{
        "roles/compute.viewer",
        "roles/storage.objectViewer",
        "roles/logging.logWriter",
        "roles/monitoring.metricWriter",
    }

    for _, role := range requiredRoles {
        if !r.hasIAMRole(ctx, project, sa.Email, role) {
            return fmt.Errorf("service account %s missing required role %s", email, role)
        }
    }

    return nil
}
```

## Integration with HyperShift

### Deployment Configuration
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-api-provider-gcp
  namespace: clusters-example
spec:
  replicas: 1
  selector:
    matchLabels:
      app: cluster-api-provider-gcp
  template:
    metadata:
      labels:
        app: cluster-api-provider-gcp
    spec:
      serviceAccountName: cluster-api-provider-gcp
      containers:
      - name: manager
        image: gcr.io/k8s-staging-cluster-api-gcp/cluster-api-gcp-controller:latest
        args:
        - --namespace=clusters-example
        - --v=2
        env:
        - name: GCP_PROJECT
          value: "customer-project-123"
        - name: GCP_REGION
          value: "us-central1"
        - name: PSC_ENABLED
          value: "true"
        resources:
          limits:
            cpu: 500m
            memory: 512Mi
          requests:
            cpu: 100m
            memory: 128Mi
```

### NodePool Integration
```go
// NodePool controller creates GCPMachineTemplate and MachineDeployment
func (r *NodePoolReconciler) reconcileGCPNodePool(ctx context.Context,
    nodePool *hyperv1.NodePool, hcluster *hyperv1.HostedCluster) error {

    // 1. Create GCPMachineTemplate
    machineTemplate := &infrav1.GCPMachineTemplate{
        ObjectMeta: metav1.ObjectMeta{
            Name:      nodePool.Name,
            Namespace: nodePool.Namespace,
        },
        Spec: infrav1.GCPMachineTemplateSpec{
            Template: infrav1.GCPMachineTemplateResource{
                Spec: infrav1.GCPMachineSpec{
                    Project:        nodePool.Spec.Platform.GCP.Project,
                    Zone:           nodePool.Spec.Platform.GCP.Zone,
                    InstanceType:   nodePool.Spec.Platform.GCP.InstanceType,
                    RootDeviceSize: int64(nodePool.Spec.Platform.GCP.DiskSizeGB),
                    RootDeviceType: nodePool.Spec.Platform.GCP.DiskType,
                    Subnet:         nodePool.Spec.Platform.GCP.Subnet,
                },
            },
        },
    }

    if err := r.createOrUpdate(ctx, machineTemplate); err != nil {
        return fmt.Errorf("failed to reconcile GCPMachineTemplate: %w", err)
    }

    // 2. Create MachineDeployment
    machineDeployment := &clusterv1.MachineDeployment{
        ObjectMeta: metav1.ObjectMeta{
            Name:      nodePool.Name,
            Namespace: nodePool.Namespace,
        },
        Spec: clusterv1.MachineDeploymentSpec{
            ClusterName: hcluster.Name,
            Replicas:    nodePool.Spec.Replicas,
            Template: clusterv1.MachineTemplateSpec{
                Spec: clusterv1.MachineSpec{
                    ClusterName: hcluster.Name,
                    InfrastructureRef: corev1.ObjectReference{
                        APIVersion: infrav1.GroupVersion.String(),
                        Kind:       "GCPMachineTemplate",
                        Name:       machineTemplate.Name,
                        Namespace:  machineTemplate.Namespace,
                    },
                    Bootstrap: clusterv1.Bootstrap{
                        ConfigRef: &corev1.ObjectReference{
                            APIVersion: "bootstrap.cluster.x-k8s.io/v1beta1",
                            Kind:       "KubeadmConfigTemplate",
                            Name:       nodePool.Name,
                            Namespace:  nodePool.Namespace,
                        },
                    },
                },
            },
        },
    }

    return r.createOrUpdate(ctx, machineDeployment)
}
```

## Testing Strategy

### Component Testing
```go
func TestGCPClusterController_ReconcilePSCConsumer(t *testing.T) {
    tests := []struct {
        name         string
        gcpCluster   *infrav1.GCPCluster
        mockSetup    func(*MockGCPClient)
        expectError  bool
        expectResult string
    }{
        {
            name: "successful PSC consumer creation",
            gcpCluster: &infrav1.GCPCluster{
                ObjectMeta: metav1.ObjectMeta{Name: "test-cluster"},
                Spec: infrav1.GCPClusterSpec{
                    Project: "test-project",
                    PrivateServiceConnect: &infrav1.PSCConfig{
                        Enabled:              true,
                        ServiceAttachmentURI: "projects/mgmt/regions/us-central1/serviceAttachments/test-psc",
                    },
                },
            },
            mockSetup: func(mockClient *MockGCPClient) {
                mockClient.EXPECT().GetGlobalAddress(gomock.Any(), "test-project", "hypershift-test-cluster-consumer").
                    Return(nil, &googleapi.Error{Code: 404})
                mockClient.EXPECT().CreateGlobalAddress(gomock.Any(), "test-project", gomock.Any()).
                    Return(&compute.Operation{Name: "op-123"}, nil)
                mockClient.EXPECT().WaitForGlobalOperation(gomock.Any(), "test-project", "op-123").
                    Return(nil)
                mockClient.EXPECT().GetGlobalAddress(gomock.Any(), "test-project", "hypershift-test-cluster-consumer").
                    Return(&compute.GlobalAddress{
                        Name:    "hypershift-test-cluster-consumer",
                        Address: "10.0.0.100",
                    }, nil)
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

### Network Isolation
- Worker nodes have no public IP addresses
- All communication via Private Service Connect
- Firewall rules restrict access to necessary ports only
- Network segmentation between different clusters

### Identity and Access
- Workload Identity for all GCP API access
- Cross-project service account impersonation
- Least privilege IAM permissions
- No long-lived service account keys

This component is essential for managing the worker node infrastructure in customer GCP projects while maintaining secure connectivity to the control plane via PSC.