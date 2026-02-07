# Control Plane Operator Component Architecture (L3)

## Component Information
- **Component**: Control Plane Operator with GCP Support
- **Level**: L3 Component Architecture
- **Repository**: `github.com/openshift/hypershift`
- **Location**: `control-plane-operator/controllers/hostedcontrolplane/`
- **Status**: 🔄 **EXISTING COMPONENT - REQUIRES EXTENSION**
- **Version**: 1.0

## Implementation Status
- **Core Control Plane Operator**: ✅ **EXISTS** - No changes required to core reconciliation logic
- **HostedControlPlane Controller**: ✅ **EXISTS** - Requires adding GCP platform handling in existing controller
- **GCP Cloud Controller Manager**: ❌ **NEW** - New deployment and configuration logic required
- **GCP CSI Driver Integration**: ❌ **NEW** - New CSI controller deployment and storage class management
- **GCP KMS Provider**: ❌ **NEW** - New KMS integration for encryption at rest
- **PSC Network Configuration**: ❌ **NEW** - New network policy and connectivity configuration
- **Workload Identity Setup**: ❌ **NEW** - New service account annotations and authentication setup

## Required Changes
- **GCP Platform Support**: ❌ **NEW** - Add GCP platform case in reconcileGCPComponents method
- **Cloud Provider Integration**: ❌ **NEW** - Deploy and configure GCP cloud controller manager
- **Storage Integration**: ❌ **NEW** - Deploy GCP CSI driver and configure storage classes
- **Security Integration**: 🔄 **ENHANCEMENT** - Add Workload Identity service account configurations
- **Network Configuration**: ❌ **NEW** - Configure network policies for PSC connectivity

## Component Overview

The Control Plane Operator manages the lifecycle of OpenShift control plane components within dedicated namespaces, including GCP-specific integrations like cloud controller manager, CSI drivers, and PSC connectivity configuration.

## Component Responsibilities

### Primary Functions
1. **HostedControlPlane Reconciliation**: Manages OpenShift control plane component deployment
2. **GCP Cloud Integration**: Deploys and configures GCP-specific controllers
3. **Storage Management**: Configures GCP CSI drivers for persistent volume support
4. **Network Integration**: Ensures control plane connectivity via PSC infrastructure
5. **Component Lifecycle**: Manages etcd, API server, controller managers, and scheduler

### Secondary Functions
- Certificate management and rotation
- ConfigMap and Secret propagation
- Health monitoring and status reporting
- Component version management and upgrades
- Resource optimization and scaling

## Detailed Architecture

### Controller Structure
```go
// Main HostedControlPlane controller
type HostedControlPlaneReconciler struct {
    client.Client
    Scheme              *runtime.Scheme
    ManagementDNS       hyperv1.DNSSpec
    DefaultIngressDomain string
    ImageProvider       ImageProvider
    ReleaseProvider     ReleaseProvider
}

// GCP-specific control plane configuration
type GCPControlPlaneConfig struct {
    CloudControllerManager *GCPCloudControllerConfig
    CSIDriver             *GCPCSIDriverConfig
    KMSProvider           *GCPKMSConfig
    NetworkConfig         *GCPNetworkConfig
}
```

### HostedControlPlane Resource Structure
```go
type HostedControlPlane struct {
    metav1.TypeMeta   `json:",inline"`
    metav1.ObjectMeta `json:"metadata,omitempty"`

    Spec   HostedControlPlaneSpec   `json:"spec,omitempty"`
    Status HostedControlPlaneStatus `json:"status,omitempty"`
}

type HostedControlPlaneSpec struct {
    // Platform-specific configuration
    Platform PlatformSpec `json:"platform"`

    // Control plane component configuration
    Etcd                EtcdSpec                `json:"etcd"`
    KubeAPIServer       KubeAPIServerSpec       `json:"kubeAPIServer"`
    KubeControllerManager KubeControllerManagerSpec `json:"kubeControllerManager"`
    KubeScheduler       KubeSchedulerSpec       `json:"kubeScheduler"`

    // GCP-specific configurations
    CloudControllerManager *CloudControllerManagerSpec `json:"cloudControllerManager,omitempty"`
    Storage               *StorageSpec                 `json:"storage,omitempty"`
    NetworkingConfig      *NetworkingConfigSpec        `json:"networkingConfig,omitempty"`
}
```

### Control Plane Reconciliation Logic

#### Main Reconciliation Flow
```go
func (r *HostedControlPlaneReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
    log := ctrl.LoggerFrom(ctx)

    // 1. Fetch HostedControlPlane resource
    hcp := &hyperv1.HostedControlPlane{}
    if err := r.Get(ctx, req.NamespacedName, hcp); err != nil {
        return ctrl.Result{}, client.IgnoreNotFound(err)
    }

    // 2. Get the associated HostedCluster
    hcluster := &hyperv1.HostedCluster{}
    if err := r.Get(ctx, types.NamespacedName{
        Name:      hcp.Spec.ClusterID,
        Namespace: hcp.Namespace,
    }, hcluster); err != nil {
        return ctrl.Result{}, fmt.Errorf("failed to get HostedCluster: %w", err)
    }

    // 3. Handle deletion
    if !hcp.DeletionTimestamp.IsZero() {
        return r.reconcileDelete(ctx, hcp, hcluster)
    }

    // 4. Handle normal reconciliation
    return r.reconcileNormal(ctx, hcp, hcluster)
}

func (r *HostedControlPlaneReconciler) reconcileNormal(ctx context.Context,
    hcp *hyperv1.HostedControlPlane, hcluster *hyperv1.HostedCluster) (ctrl.Result, error) {

    log := ctrl.LoggerFrom(ctx).WithValues("controlplane", hcp.Name)

    // 1. Ensure finalizer
    if !controllerutil.ContainsFinalizer(hcp, hyperv1.HostedControlPlaneFinalizer) {
        controllerutil.AddFinalizer(hcp, hyperv1.HostedControlPlaneFinalizer)
        return ctrl.Result{}, r.Update(ctx, hcp)
    }

    // 2. Reconcile core control plane components
    if err := r.reconcileCoreComponents(ctx, hcp, hcluster); err != nil {
        return ctrl.Result{}, fmt.Errorf("failed to reconcile core components: %w", err)
    }

    // 3. Reconcile platform-specific components
    if hcluster.Spec.Platform.Type == hyperv1.GCPPlatform {
        if err := r.reconcileGCPComponents(ctx, hcp, hcluster); err != nil {
            return ctrl.Result{}, fmt.Errorf("failed to reconcile GCP components: %w", err)
        }
    }

    // 4. Update status
    if err := r.updateControlPlaneStatus(ctx, hcp); err != nil {
        return ctrl.Result{}, fmt.Errorf("failed to update status: %w", err)
    }

    return ctrl.Result{}, nil
}
```

#### GCP-Specific Component Reconciliation
```go
func (r *HostedControlPlaneReconciler) reconcileGCPComponents(ctx context.Context,
    hcp *hyperv1.HostedControlPlane, hcluster *hyperv1.HostedCluster) error {

    // 1. Reconcile GCP Cloud Controller Manager
    if err := r.reconcileGCPCloudControllerManager(ctx, hcp, hcluster); err != nil {
        return fmt.Errorf("failed to reconcile GCP cloud controller manager: %w", err)
    }

    // 2. Reconcile GCP CSI Driver
    if err := r.reconcileGCPCSIDriver(ctx, hcp, hcluster); err != nil {
        return fmt.Errorf("failed to reconcile GCP CSI driver: %w", err)
    }

    // 3. Reconcile KMS provider if configured
    if hcluster.Spec.Platform.GCP.KMS != nil && hcluster.Spec.Platform.GCP.KMS.Enabled {
        if err := r.reconcileGCPKMSProvider(ctx, hcp, hcluster); err != nil {
            return fmt.Errorf("failed to reconcile GCP KMS provider: %w", err)
        }
    }

    // 4. Configure PSC-specific networking
    if err := r.configureGCPNetworking(ctx, hcp, hcluster); err != nil {
        return fmt.Errorf("failed to configure GCP networking: %w", err)
    }

    return nil
}
```

### GCP Cloud Controller Manager

#### Deployment Configuration
```go
func (r *HostedControlPlaneReconciler) reconcileGCPCloudControllerManager(ctx context.Context,
    hcp *hyperv1.HostedControlPlane, hcluster *hyperv1.HostedCluster) error {

    // Get GCP cloud controller manager image
    image, err := r.ImageProvider.GetImage(ctx, "gcp-cloud-controller-manager", hcp.Spec.ReleaseImage)
    if err != nil {
        return fmt.Errorf("failed to get GCP CCM image: %w", err)
    }

    deployment := &appsv1.Deployment{
        ObjectMeta: metav1.ObjectMeta{
            Name:      "gcp-cloud-controller-manager",
            Namespace: hcp.Namespace,
        },
        Spec: appsv1.DeploymentSpec{
            Replicas: ptr.To(int32(1)),
            Selector: &metav1.LabelSelector{
                MatchLabels: map[string]string{
                    "app": "gcp-cloud-controller-manager",
                },
            },
            Template: corev1.PodTemplateSpec{
                ObjectMeta: metav1.ObjectMeta{
                    Labels: map[string]string{
                        "app": "gcp-cloud-controller-manager",
                    },
                },
                Spec: corev1.PodSpec{
                    ServiceAccountName: "gcp-cloud-controller-manager",
                    SecurityContext: &corev1.PodSecurityContext{
                        RunAsNonRoot: ptr.To(true),
                        RunAsUser:    ptr.To(int64(1001)),
                    },
                    Containers: []corev1.Container{
                        {
                            Name:  "gcp-cloud-controller-manager",
                            Image: image,
                            Command: []string{
                                "/usr/local/bin/gcp-cloud-controller-manager",
                            },
                            Args: []string{
                                "--cloud-config=/etc/gcp/cloud-config",
                                "--cluster-name=" + hcp.Spec.ClusterID,
                                "--kubeconfig=/etc/kubernetes/kubeconfig/kubeconfig",
                                "--bind-address=0.0.0.0",
                                "--secure-port=10258",
                                "--port=0",
                                "--leader-elect=true",
                                "--leader-elect-lease-duration=137s",
                                "--leader-elect-renew-deadline=107s",
                                "--leader-elect-retry-period=26s",
                                "--concurrent-service-syncs=1",
                                "--v=2",
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
                            SecurityContext: &corev1.SecurityContext{
                                AllowPrivilegeEscalation: ptr.To(false),
                                Capabilities: &corev1.Capabilities{
                                    Drop: []corev1.Capability{"ALL"},
                                },
                                ReadOnlyRootFilesystem: ptr.To(true),
                            },
                        },
                    },
                    Volumes: []corev1.Volume{
                        {
                            Name: "kubeconfig",
                            VolumeSource: corev1.VolumeSource{
                                Secret: &corev1.SecretVolumeSource{
                                    SecretName: "service-network-admin-kubeconfig",
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
                    },
                },
            },
        },
    }

    if err := controllerutil.SetControllerReference(hcp, deployment, r.Scheme); err != nil {
        return fmt.Errorf("failed to set controller reference: %w", err)
    }

    return r.createOrUpdate(ctx, deployment)
}
```

#### Cloud Configuration
```go
func (r *HostedControlPlaneReconciler) reconcileGCPCloudConfig(ctx context.Context,
    hcp *hyperv1.HostedControlPlane, hcluster *hyperv1.HostedCluster) error {

    cloudConfig := fmt.Sprintf(`[global]
project-id = %s
regional = true
region = %s
cluster-name = %s

[loadbalancer]
# Use internal load balancers only
load-balancer-type = "internal"

[node-tags]
# Tags for firewall rules
node-tags = hypershift-%s-worker

[metadata]
# Use workload identity
use-metadata-server = true
`, hcluster.Spec.Platform.GCP.Project,
        hcluster.Spec.Platform.GCP.Region,
        hcp.Spec.ClusterID,
        hcluster.Name)

    configMap := &corev1.ConfigMap{
        ObjectMeta: metav1.ObjectMeta{
            Name:      "gcp-cloud-config",
            Namespace: hcp.Namespace,
        },
        Data: map[string]string{
            "cloud-config": cloudConfig,
        },
    }

    if err := controllerutil.SetControllerReference(hcp, configMap, r.Scheme); err != nil {
        return fmt.Errorf("failed to set controller reference: %w", err)
    }

    return r.createOrUpdate(ctx, configMap)
}
```

### GCP CSI Driver

#### CSI Controller Deployment
```go
func (r *HostedControlPlaneReconciler) reconcileGCPCSIDriver(ctx context.Context,
    hcp *hyperv1.HostedControlPlane, hcluster *hyperv1.HostedCluster) error {

    // Get CSI driver image
    csiImage, err := r.ImageProvider.GetImage(ctx, "gcp-pd-csi-driver", hcp.Spec.ReleaseImage)
    if err != nil {
        return fmt.Errorf("failed to get GCP CSI driver image: %w", err)
    }

    deployment := &appsv1.Deployment{
        ObjectMeta: metav1.ObjectMeta{
            Name:      "gcp-pd-csi-controller",
            Namespace: hcp.Namespace,
        },
        Spec: appsv1.DeploymentSpec{
            Replicas: ptr.To(int32(1)),
            Selector: &metav1.LabelSelector{
                MatchLabels: map[string]string{
                    "app": "gcp-pd-csi-controller",
                },
            },
            Template: corev1.PodTemplateSpec{
                ObjectMeta: metav1.ObjectMeta{
                    Labels: map[string]string{
                        "app": "gcp-pd-csi-controller",
                    },
                },
                Spec: corev1.PodSpec{
                    ServiceAccountName: "gcp-csi-driver",
                    SecurityContext: &corev1.PodSecurityContext{
                        RunAsNonRoot: ptr.To(true),
                        RunAsUser:    ptr.To(int64(1001)),
                    },
                    Containers: []corev1.Container{
                        {
                            Name:  "gcp-pd-driver",
                            Image: csiImage,
                            Args: []string{
                                "--endpoint=unix:///csi/csi.sock",
                                "--v=5",
                                "--run-controller-service=true",
                                "--run-node-service=false",
                                "--kubeconfig=/etc/kubernetes/kubeconfig/kubeconfig",
                            },
                            Env: []corev1.EnvVar{
                                {
                                    Name:  "GOOGLE_APPLICATION_CREDENTIALS",
                                    Value: "/var/secrets/google/key.json",
                                },
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
                                {
                                    Name:      "gcp-credentials",
                                    MountPath: "/var/secrets/google",
                                    ReadOnly:  true,
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
                        {
                            Name:  "csi-provisioner",
                            Image: "k8s.gcr.io/sig-storage/csi-provisioner:v3.0.0",
                            Args: []string{
                                "--csi-address=/csi/csi.sock",
                                "--kubeconfig=/etc/kubernetes/kubeconfig/kubeconfig",
                                "--feature-gates=Topology=true",
                                "--v=5",
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
                            Image: "k8s.gcr.io/sig-storage/csi-attacher:v3.4.0",
                            Args: []string{
                                "--csi-address=/csi/csi.sock",
                                "--kubeconfig=/etc/kubernetes/kubeconfig/kubeconfig",
                                "--v=5",
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
                                    SecretName: "service-network-admin-kubeconfig",
                                },
                            },
                        },
                        {
                            Name: "gcp-credentials",
                            VolumeSource: corev1.VolumeSource{
                                Secret: &corev1.SecretVolumeSource{
                                    SecretName: "gcp-csi-credentials",
                                },
                            },
                        },
                    },
                },
            },
        },
    }

    if err := controllerutil.SetControllerReference(hcp, deployment, r.Scheme); err != nil {
        return fmt.Errorf("failed to set controller reference: %w", err)
    }

    return r.createOrUpdate(ctx, deployment)
}
```

#### Storage Class Configuration
```go
func (r *HostedControlPlaneReconciler) reconcileGCPStorageClasses(ctx context.Context,
    hcp *hyperv1.HostedControlPlane, hcluster *hyperv1.HostedCluster) error {

    // Default storage class for GCP
    storageClass := &storagev1.StorageClass{
        ObjectMeta: metav1.ObjectMeta{
            Name: "gcp-pd-csi",
            Annotations: map[string]string{
                "storageclass.kubernetes.io/is-default-class": "true",
            },
        },
        Provisioner:          "pd.csi.storage.gke.io",
        VolumeBindingMode:    ptr.To(storagev1.VolumeBindingWaitForFirstConsumer),
        AllowVolumeExpansion: ptr.To(true),
        Parameters: map[string]string{
            "type":             "pd-balanced",
            "replication-type": "none",
        },
    }

    if err := controllerutil.SetControllerReference(hcp, storageClass, r.Scheme); err != nil {
        return fmt.Errorf("failed to set controller reference: %w", err)
    }

    return r.createOrUpdate(ctx, storageClass)
}
```

### KMS Integration

#### KMS Provider Configuration
```go
func (r *HostedControlPlaneReconciler) reconcileGCPKMSProvider(ctx context.Context,
    hcp *hyperv1.HostedControlPlane, hcluster *hyperv1.HostedCluster) error {

    if hcluster.Spec.Platform.GCP.KMS == nil || !hcluster.Spec.Platform.GCP.KMS.Enabled {
        return nil
    }

    kmsConfig := fmt.Sprintf(`apiVersion: apiserver.k8s.io/v1
kind: EncryptionConfiguration
resources:
- resources:
  - secrets
  providers:
  - kms:
      name: gcp-kms
      endpoint: unix:///var/run/kmsplugin/socket.sock
      cachesize: 100
      timeout: 3s
  - identity: {}
`)

    configMap := &corev1.ConfigMap{
        ObjectMeta: metav1.ObjectMeta{
            Name:      "kms-config",
            Namespace: hcp.Namespace,
        },
        Data: map[string]string{
            "encryption-config.yaml": kmsConfig,
        },
    }

    if err := controllerutil.SetControllerReference(hcp, configMap, r.Scheme); err != nil {
        return fmt.Errorf("failed to set controller reference: %w", err)
    }

    return r.createOrUpdate(ctx, configMap)
}
```

### PSC Network Configuration

#### Network Policy Configuration
```go
func (r *HostedControlPlaneReconciler) configureGCPNetworking(ctx context.Context,
    hcp *hyperv1.HostedControlPlane, hcluster *hyperv1.HostedCluster) error {

    // Configure network policies for PSC connectivity
    networkPolicy := &networkingv1.NetworkPolicy{
        ObjectMeta: metav1.ObjectMeta{
            Name:      "allow-psc-traffic",
            Namespace: hcp.Namespace,
        },
        Spec: networkingv1.NetworkPolicySpec{
            PodSelector: metav1.LabelSelector{
                MatchLabels: map[string]string{
                    "app": "kube-apiserver",
                },
            },
            Ingress: []networkingv1.NetworkPolicyIngressRule{
                {
                    Ports: []networkingv1.NetworkPolicyPort{
                        {
                            Protocol: ptr.To(corev1.ProtocolTCP),
                            Port:     ptr.To(intstr.FromInt(6443)),
                        },
                    },
                    From: []networkingv1.NetworkPolicyPeer{
                        {
                            // Allow traffic from PSC consumer IPs
                            IPBlock: &networkingv1.IPBlock{
                                CIDR: "10.0.0.0/8", // Adjust based on customer VPC ranges
                            },
                        },
                    },
                },
            },
            PolicyTypes: []networkingv1.PolicyType{
                networkingv1.PolicyTypeIngress,
            },
        },
    }

    if err := controllerutil.SetControllerReference(hcp, networkPolicy, r.Scheme); err != nil {
        return fmt.Errorf("failed to set controller reference: %w", err)
    }

    return r.createOrUpdate(ctx, networkPolicy)
}
```

### Service Account Management

#### Workload Identity Configuration
```go
func (r *HostedControlPlaneReconciler) reconcileGCPServiceAccounts(ctx context.Context,
    hcp *hyperv1.HostedControlPlane, hcluster *hyperv1.HostedCluster) error {

    // Service accounts with Workload Identity annotations
    serviceAccounts := []struct {
        name        string
        gcpSAEmail  string
    }{
        {
            name:       "gcp-cloud-controller-manager",
            gcpSAEmail: fmt.Sprintf("gcp-cloud-controller-manager@%s.iam.gserviceaccount.com", hcluster.Spec.Platform.GCP.Project),
        },
        {
            name:       "gcp-csi-driver",
            gcpSAEmail: fmt.Sprintf("gcp-csi-driver@%s.iam.gserviceaccount.com", hcluster.Spec.Platform.GCP.Project),
        },
    }

    for _, sa := range serviceAccounts {
        serviceAccount := &corev1.ServiceAccount{
            ObjectMeta: metav1.ObjectMeta{
                Name:      sa.name,
                Namespace: hcp.Namespace,
                Annotations: map[string]string{
                    "iam.gke.io/gcp-service-account": sa.gcpSAEmail,
                },
            },
        }

        if err := controllerutil.SetControllerReference(hcp, serviceAccount, r.Scheme); err != nil {
            return fmt.Errorf("failed to set controller reference: %w", err)
        }

        if err := r.createOrUpdate(ctx, serviceAccount); err != nil {
            return fmt.Errorf("failed to create/update service account %s: %w", sa.name, err)
        }
    }

    return nil
}
```

## Status Management

### Control Plane Status Updates
```go
func (r *HostedControlPlaneReconciler) updateControlPlaneStatus(ctx context.Context,
    hcp *hyperv1.HostedControlPlane) error {

    // Check component health
    components := []string{
        "etcd",
        "kube-apiserver",
        "kube-controller-manager",
        "kube-scheduler",
        "gcp-cloud-controller-manager",
        "gcp-pd-csi-controller",
    }

    allReady := true
    var unreadyComponents []string

    for _, component := range components {
        ready, err := r.isComponentReady(ctx, hcp.Namespace, component)
        if err != nil {
            return fmt.Errorf("failed to check component %s: %w", component, err)
        }
        if !ready {
            allReady = false
            unreadyComponents = append(unreadyComponents, component)
        }
    }

    // Update status conditions
    if allReady {
        meta.SetStatusCondition(&hcp.Status.Conditions, metav1.Condition{
            Type:    "Available",
            Status:  metav1.ConditionTrue,
            Reason:  "AllComponentsReady",
            Message: "All control plane components are ready",
        })
    } else {
        meta.SetStatusCondition(&hcp.Status.Conditions, metav1.Condition{
            Type:    "Available",
            Status:  metav1.ConditionFalse,
            Reason:  "ComponentsNotReady",
            Message: fmt.Sprintf("Components not ready: %v", unreadyComponents),
        })
    }

    return r.Status().Update(ctx, hcp)
}

func (r *HostedControlPlaneReconciler) isComponentReady(ctx context.Context,
    namespace, component string) (bool, error) {

    deployment := &appsv1.Deployment{}
    if err := r.Get(ctx, types.NamespacedName{
        Name:      component,
        Namespace: namespace,
    }, deployment); err != nil {
        return false, err
    }

    return deployment.Status.ReadyReplicas == *deployment.Spec.Replicas, nil
}
```

## Testing Strategy

### Component Testing
```go
func TestControlPlaneOperator_ReconcileGCPComponents(t *testing.T) {
    tests := []struct {
        name        string
        hcp         *hyperv1.HostedControlPlane
        hcluster    *hyperv1.HostedCluster
        expectError bool
        validate    func(t *testing.T, client client.Client)
    }{
        {
            name:     "successful GCP component creation",
            hcp:      testutil.HostedControlPlane("test-hcp", "test-ns"),
            hcluster: testutil.GCPHostedCluster("test-cluster", "test-ns"),
            expectError: false,
            validate: func(t *testing.T, client client.Client) {
                // Verify GCP cloud controller manager deployment
                deployment := &appsv1.Deployment{}
                err := client.Get(context.Background(), types.NamespacedName{
                    Name:      "gcp-cloud-controller-manager",
                    Namespace: "test-ns",
                }, deployment)
                assert.NoError(t, err)

                // Verify CSI driver deployment
                csiDeployment := &appsv1.Deployment{}
                err = client.Get(context.Background(), types.NamespacedName{
                    Name:      "gcp-pd-csi-controller",
                    Namespace: "test-ns",
                }, csiDeployment)
                assert.NoError(t, err)
            },
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

### Component Security
- All containers run with security contexts (non-root, read-only filesystem)
- Workload Identity for GCP authentication
- Network policies restrict traffic to necessary ports
- Secret management for sensitive configuration

### Access Control
- RBAC permissions scoped to control plane namespace
- Service accounts with minimal required permissions
- TLS encryption for all component communication
- Audit logging for all administrative operations

This component is responsible for managing the OpenShift control plane components with GCP-specific integrations, ensuring proper cloud provider integration while maintaining security and operational excellence.