# HyperShift GKE Installation Script

A comprehensive automation script for deploying OpenShift hosted control planes (HyperShift) on Google Kubernetes Engine (GKE) Standard clusters with complete worker node provisioning and networking configuration.

## Quick Start

```bash
# 1. Configure environment
cp example.env my-cluster.env
# Edit my-cluster.env with your values

# 2. Run installation
source my-cluster.env
python3 hypershift_installer.py
```

## Prerequisites

- **Google Cloud SDK**: Installed and authenticated (`gcloud auth login`)
- **System Tools**: `kubectl`, `helm`, `git`, `ssh-keygen`, `openssl` in PATH
- **GCP Project**: With sufficient quotas for compute instances and load balancers
- **Red Hat Pull Secret**: Downloaded from cloud.redhat.com
- **Python 3.8+**: With pip and virtualenv

## Environment Configuration

Create your environment file by copying the example:

```bash
cp example.env my-cluster.env
```

Required environment variables:
```bash
export PROJECT_ID="your-gcp-project-id"
export GKE_CLUSTER_NAME="hypershift-management"
export HOSTED_CLUSTER_NAME="my-hosted-cluster"
export HOSTED_CLUSTER_DOMAIN="example.com"
export PULL_SECRET_PATH="./pull-secret.txt"
```

Optional configuration:
```bash
export REGION="us-central1"                    # Default: us-central1
export ZONE="us-central1-a"                    # Default: {region}-a
export WORKER_NODE_NAME="hypershift-worker-1"  # Default: hypershift-worker-1
export WORKER_MACHINE_TYPE="e2-standard-8"     # Default: e2-standard-4
export WORKER_DISK_SIZE="100GB"                # Default: 50GB

# Red Hat CoreOS Configuration
export RHCOS_IMAGE_NAME="redhat-coreos-osd-418-x86-64-202508060022"   # Default: redhat-coreos-osd-418-x86-64-202508060022
export RHCOS_IMAGE_PROJECT="redhat-marketplace-dev"                # Default: redhat-marketplace-dev
```

## Red Hat CoreOS (RHCOS) Configuration

The installer uses Red Hat CoreOS by default for worker nodes, providing optimal OpenShift compatibility and security. RHCOS images are configurable for different environments and versions.

### Default Configuration

By default, the installer uses the following RHCOS configuration:

```bash
export RHCOS_IMAGE_NAME="redhat-coreos-osd-418-x86-64-202508060022"
export RHCOS_IMAGE_PROJECT="redhat-marketplace-dev"
```

### Configuration Examples

#### **Using a Different RHCOS Version**
```bash
# For a newer RHCOS release (if available)
export RHCOS_IMAGE_NAME="redhat-coreos-osd-418-x86-64-202509150030"
export RHCOS_IMAGE_PROJECT="redhat-marketplace-dev"
```

#### **Using Organization's Shared Image Project**
```bash
# For centralized image management
export RHCOS_IMAGE_NAME="redhat-coreos-osd-418-x86-64-202508060022"
export RHCOS_IMAGE_PROJECT="my-org-shared-images"
```

#### **Using Custom RHCOS Images**
```bash
# For custom-built RHCOS with organization patches
export RHCOS_IMAGE_NAME="custom-rhcos-osd-418-x86-64-20250826-v1"
export RHCOS_IMAGE_PROJECT="my-dev-project"
```

#### **Development vs Production**
```bash
# Development environment
export RHCOS_IMAGE_PROJECT="dev-images-project"

# Production environment
export RHCOS_IMAGE_PROJECT="prod-images-project"
```

### Finding Available RHCOS Images

To discover available RHCOS images in different projects:

```bash
# Search Red Hat's marketplace project
gcloud compute images list --project=redhat-marketplace-dev --filter="name~'.*coreos.*'"

# Search your organization's project
gcloud compute images list --project=my-org-images --filter="name~'.*coreos.*'"

# Search current project
gcloud compute images list --filter="name~'.*coreos.*'"
```

### Benefits of RHCOS

- **Native CRI-O**: Pre-configured OpenShift-compatible container runtime
- **Ignition Support**: Automated machine configuration during boot
- **SELinux**: Hardened security policies optimized for OpenShift
- **OSTree**: Atomic updates and rollback capabilities
- **OpenShift Integration**: Guaranteed compatibility with OpenShift components

### Image Verification

To verify RHCOS image details:

```bash
# Describe image properties
gcloud compute images describe $RHCOS_IMAGE_NAME --project=$RHCOS_IMAGE_PROJECT

# Check image family and creation date
gcloud compute images list --project=$RHCOS_IMAGE_PROJECT --filter="name=$RHCOS_IMAGE_NAME" --format="table(name,family,creationTimestamp)"
```

## Usage

### Standard Installation
```bash
source my-cluster.env
python3 hypershift_installer.py
```

### Resume Installation
If interrupted, resume from the last completed step:
```bash
python3 hypershift_installer.py --continue
```

### Dry Run Mode
See what would be executed without making changes:
```bash
python3 hypershift_installer.py --dry-run
```

### Skip Pod Security Webhook
For testing or custom environments:
```bash
python3 hypershift_installer.py --skip-webhook
```

### List Installation Steps
```bash
python3 hypershift_installer.py --list-steps
```

### Cleanup All Resources
```bash
python3 hypershift_installer.py --cleanup
```

## Installation Steps Overview

1. **Environment Setup** - Configure gcloud project and authentication
2. **Create GKE Cluster** - Multi-zone Standard GKE cluster for management
3. **Install Prometheus Operator** - CRDs for monitoring (operator only)
4. **Install cert-manager** - Certificate management for HyperShift TLS
5. **Build HyperShift** - Clone, build, and install HyperShift operator
6. **Deploy Webhook** (Optional) - Automatic GKE Autopilot constraint fixes
7. **Create Secrets** - Namespace, pull secrets, SSH keys
8. **Deploy HostedCluster** - OpenShift control plane deployment
9. **Wait for Control Plane** - Monitor deployment with automatic fixes
10. **Fix Service CA** - Populate CA certificates for networking
11. **Fix OVN Networking** - Deploy networking components and certificates
12. **Extract Access** - Get hosted cluster kubeconfig
13. **Create Worker Node** - Provision Red Hat CoreOS GCE instance
14. **Generate Certificates** - Node certificates for kubelet authentication
15. **Configure Kubelet** - Kubelet service and configuration
16. **Setup Networking** - Complete OpenVSwitch and CNI configuration
17. **Verify Installation** - Test deployment and workload scheduling

## Expected Results

After successful installation:

- **Management Cluster**: GKE Standard cluster running HyperShift operator
- **Hosted Cluster**: OpenShift control plane (API server, controllers, etcd)
- **Worker Node**: Red Hat CoreOS (RHCOS) instance with ignition-based bootstrap
- **Networking**: OVN-Kubernetes with OpenVSwitch infrastructure
- **Test Workload**: Running hello-openshift pod demonstrating functionality

Access your hosted cluster:
```bash
export KUBECONFIG=/tmp/kubeconfig-hosted
kubectl get nodes
kubectl get pods --all-namespaces
```

---

# Detailed Technical Documentation

## Architecture Overview

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   GKE Standard  │    │  Hosted Cluster  │    │  Worker Nodes   │
│  (Management)   │    │  Control Plane   │    │ (GCE Instance)  │
│                 │    │                  │    │                 │
│ ┌─────────────┐ │    │ ┌──────────────┐ │    │ ┌─────────────┐ │
│ │ HyperShift  │ │    │ │ API Server   │ │    │ │ kubelet     │ │
│ │ Operator    │ │────┤ │ Controller   │ │────┤ │ CNI (OVN)   │ │
│ │             │ │    │ │ Manager      │ │    │ │ OpenVSwitch │ │
│ └─────────────┘ │    │ │ etcd         │ │    │ └─────────────┘ │
└─────────────────┘    │ └──────────────┘ │    └─────────────────┘
                       └──────────────────┘
```

## Step-by-Step Technical Analysis

### Step 1: Environment Setup
**Purpose**: Configure gcloud project and validate authentication

**What it does**:
- Sets the active GCP project for all subsequent operations
- Validates gcloud authentication status
- Configures kubectl context for management cluster
- Sets up environment variables for consistent tool usage

**Manual equivalent**:
```bash
gcloud config set project $PROJECT_ID
gcloud config get-value project
gcloud auth list --filter=status:ACTIVE
export KUBECONFIG=/tmp/kubeconfig-gke
```

**Why needed**: Ensures all subsequent GCP API calls target the correct project and authentication is valid. Prevents costly mistakes of deploying to wrong projects.

**Failure points**:
- Invalid project ID
- Expired authentication tokens
- Insufficient project permissions

---

### Step 2: Create GKE Cluster
**Purpose**: Create a multi-zone GKE Standard cluster to host the HyperShift operator

**What it does**:
- Creates a 3-zone GKE Standard cluster with autoscaling enabled
- Configures cluster with e2-standard-4 nodes (4 vCPU, 16GB RAM)
- Enables auto-repair and auto-upgrade for maintenance
- Retrieves cluster credentials and configures kubectl access

**Manual equivalent**:
```bash
gcloud container clusters create $GKE_CLUSTER_NAME \
  --zone=$ZONE \
  --node-locations=$ZONE,${REGION}-b,${REGION}-c \
  --num-nodes=1 \
  --machine-type=e2-standard-4 \
  --enable-autoscaling \
  --min-nodes=1 \
  --max-nodes=10 \
  --enable-autorepair \
  --enable-autoupgrade

gcloud container clusters get-credentials $GKE_CLUSTER_NAME --zone=$ZONE
kubectl cluster-info
```

**Why multi-zone**: HyperShift control plane components have anti-affinity rules requiring distribution across multiple zones for high availability. Single-zone clusters will fail to schedule API server replicas.

**Why Standard over Autopilot**:
- Greater control over node configuration
- Support for privileged containers needed by HyperShift
- Ability to customize networking and storage

**Resource requirements**:
- Minimum 3 zones in region
- e2-standard-4 provides sufficient CPU/memory for control plane workloads
- Autoscaling handles traffic spikes automatically

---

### Step 3: Install Prometheus Operator
**Purpose**: Deploy CustomResourceDefinitions needed by HyperShift for monitoring

**What it does**:
- Adds prometheus-community Helm repository
- Installs only the operator components (no full monitoring stack)
- Creates ServiceMonitor and PrometheusRule CRDs
- Provides foundations for metrics collection without resource overhead

**Manual equivalent**:
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus-operator prometheus-community/kube-prometheus-stack \
  --set prometheus.enabled=false \
  --set alertmanager.enabled=false \
  --set grafana.enabled=false \
  --set kubeStateMetrics.enabled=false \
  --set nodeExporter.enabled=false
```

**Why needed**: HyperShift components create ServiceMonitor resources for metrics collection. Without the CRDs, these resources fail to create, causing control plane deployment failures.

**Why operator-only**: Installing the full monitoring stack consumes significant resources. HyperShift only needs the CRDs for resource definitions.

**CRDs installed**:
- `servicemonitors.monitoring.coreos.com`
- `prometheusrules.monitoring.coreos.com`
- `podmonitors.monitoring.coreos.com`

---

### Step 4: Install cert-manager
**Purpose**: Provide certificate management for HyperShift TLS requirements

**What it does**:
- Deploys cert-manager with admission webhooks and CRDs
- Waits for all cert-manager pods to be ready (webhook functionality crucial)
- Validates webhook responsiveness before proceeding
- Enables automatic certificate generation and rotation

**Manual equivalent**:
```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml
kubectl wait --for=condition=ready pod -l app=cert-manager -n cert-manager --timeout=300s
```

**Why needed**: HyperShift generates numerous certificates for secure communication:
- API server serving certificates
- Client certificates for component authentication
- Webhook serving certificates
- etcd peer and client certificates

**Why wait for ready**: cert-manager webhooks must be functional before HyperShift deployment. Failed webhooks prevent certificate resource creation.

**Critical dependencies**:
- Admission webhooks validate Certificate resources
- Issuers must be ready for certificate signing
- CRDs must be established before HyperShift creates certificate requests

---

### Step 5: Build and Install HyperShift
**Purpose**: Deploy the HyperShift operator in development mode

**What it does**:
1. **Build Phase**:
   - Clones HyperShift repository from upstream
   - Builds hypershift binary from source using Go toolchain
   - Installs binary to system PATH for CLI access

2. **Installation Phase**:
   - Installs operator in development mode (no image registry required)
   - Creates hypershift namespace and RBAC
   - Deploys operator with development configuration

3. **Fixes Phase**:
   - Ensures operator deployment has correct replica count
   - Creates missing serving certificates for webhook functionality
   - Restarts operator pod to pick up certificates

**Manual equivalent**:
```bash
# Clone and build
git clone https://github.com/openshift/hypershift.git
cd hypershift
make build
sudo install -m 0755 bin/hypershift /usr/local/bin/hypershift

# Install operator
hypershift install --development

# Fix operator deployment
kubectl scale deployment operator -n hypershift --replicas=1

# Create serving certificate
openssl req -x509 -newkey rsa:2048 -keyout /tmp/tls.key -out /tmp/tls.crt \
  -days 365 -nodes -subj "/CN=hypershift-operator"
kubectl create secret tls manager-serving-cert -n hypershift \
  --cert=/tmp/tls.crt --key=/tmp/tls.key

# Restart operator
kubectl delete pod -l name=operator -n hypershift
kubectl wait --for=condition=ready pod -l name=operator -n hypershift --timeout=300s
```

**Why development mode**:
- Avoids complex image registry setup
- Enables debugging and development features
- Uses local development images rather than production registry

**Why build from source**:
- Ensures latest compatibility with GKE
- Allows custom patches if needed
- Provides development CLI tools

**Common issues**:
- Operator deployment scaling to 0 replicas
- Missing serving certificates causing webhook failures
- ImagePullBackOff for development images

---

### Step 6: Deploy Pod Security Webhook (Optional)
**Purpose**: Automatically fix GKE Autopilot constraint violations in HyperShift pods

This step deploys a sophisticated mutating admission webhook that automatically resolves compatibility issues between HyperShift and GKE Autopilot's strict security policies.

**What it does**:
1. **Image Building**:
   - Enables Google Container Registry API
   - Authenticates Podman with GCR using OAuth tokens
   - Builds multi-architecture webhook image for linux/amd64
   - Pushes image to project's container registry

2. **Certificate Generation**:
   - Creates private key for webhook TLS
   - Generates Certificate Signing Request with proper SANs
   - Submits CSR to Kubernetes certificate API
   - Approves CSR and extracts signed certificate

3. **Webhook Deployment**:
   - Creates namespace and RBAC for webhook
   - Deploys webhook server with security contexts
   - Creates service for webhook communication
   - Configures MutatingWebhookConfiguration for automatic fixes

**What it fixes automatically**:
- **Pod security contexts**: `runAsNonRoot: true`, `runAsUser: 1001`
- **Container security contexts**: Drop all capabilities, no privilege escalation
- **EmptyDir volume replacements**: Converts PersistentVolume claims to EmptyDir for etcd
- **Resource requirements**: Ensures CPU/memory requests meet GKE Autopilot minimums
- **Security profiles**: Adds seccomp profiles for enhanced security

**Manual equivalent**:
```bash
# Enable GCR and authenticate
gcloud services enable containerregistry.googleapis.com --project=$PROJECT_ID
/opt/podman/bin/podman login -u oauth2accesstoken \
  -p "$(gcloud auth print-access-token)" gcr.io

# Build and push webhook image
cd ../webhook
/opt/podman/bin/podman build --platform linux/amd64 \
  -t gcr.io/$PROJECT_ID/hypershift-gke-autopilot-webhook:latest .
/opt/podman/bin/podman push gcr.io/$PROJECT_ID/hypershift-gke-autopilot-webhook:latest

# Generate TLS certificates and deploy webhook
# (See detailed certificate generation process in script)
```

**Why needed**: GKE Autopilot enforces strict security policies that conflict with default HyperShift pod specifications. The webhook automatically resolves these conflicts without manual intervention.

**Critical fixes**:
- **etcd StatefulSet**: Replaces volumeClaimTemplates with EmptyDir volumes
- **cluster-api deployment**: Adds pod and container security contexts
- **control-plane-operator**: Ensures all security requirements are met

---

### Step 7: Create Namespace and Secrets
**Purpose**: Set up hosted cluster namespace and required secrets for deployment

**What it does**:
1. **Namespace Creation**: Creates `clusters` namespace for hosted cluster resources
2. **Pull Secret**: Uploads Red Hat pull secret for OpenShift image access
3. **SSH Key Generation**: Creates RSA keypair for worker node SSH access

**Manual equivalent**:
```bash
# Create namespace
kubectl create namespace clusters

# Create pull secret from Red Hat credential
kubectl create secret generic pull-secret \
  --from-file=.dockerconfigjson=$PULL_SECRET_PATH \
  --type=kubernetes.io/dockerconfigjson -n clusters

# Generate and upload SSH key
ssh-keygen -t rsa -b 4096 -f ./ssh-key -N ""
kubectl create secret generic ssh-key \
  --from-file=id_rsa.pub=./ssh-key.pub -n clusters
```

**Why needed**:
- **Pull secret**: Required for pulling OpenShift release images from quay.io
- **SSH key**: Enables troubleshooting and maintenance access to worker nodes
- **Namespace**: Isolates hosted cluster resources from management cluster

---

### Step 8: Deploy HostedCluster
**Purpose**: Create the hosted OpenShift control plane specification

**What it does**:
- Renders HostedCluster manifest from configuration template
- Specifies OpenShift release version and platform configuration
- Defines networking configuration (pod and service CIDRs)
- References pull secret and SSH key for cluster bootstrap

**Manual equivalent**:
```bash
cat > hosted-cluster.yaml << EOF
apiVersion: hypershift.openshift.io/v1beta1
kind: HostedCluster
metadata:
  name: $HOSTED_CLUSTER_NAME
  namespace: clusters
spec:
  release:
    image: quay.io/openshift-release-dev/ocp-release:4.14.0
  dns:
    baseDomain: $HOSTED_CLUSTER_DOMAIN
  platform:
    type: None
  pullSecret:
    name: pull-secret
  sshKey:
    name: ssh-key
  networking:
    clusterNetwork:
    - cidr: 10.132.0.0/14
    serviceNetwork:
    - cidr: 172.31.0.0/16
  infraID: $INFRAID
EOF

kubectl apply -f hosted-cluster.yaml
```

**Why Platform: None**: Uses platform-agnostic mode allowing manual worker node management rather than cloud provider integration.

**Network configuration**:
- **Cluster network (10.132.0.0/14)**: Pod IP addresses (1,048,576 IPs)
- **Service network (172.31.0.0/16)**: Service ClusterIPs (65,536 IPs)

---

### Step 9: Wait for Control Plane
**Purpose**: Monitor control plane deployment and handle Pod Security violations

**What it does**:
1. **Status Monitoring**: Checks HostedCluster availability condition every 30 seconds
2. **Progress Updates**: Shows detailed status every 2 minutes with current deployment phase
3. **Pod Security Fix**: Automatically detects and fixes Pod Security violations after 2 minutes
4. **Failure Handling**: Shows pod status and events for troubleshooting

**Manual monitoring equivalent**:
```bash
# Check overall HostedCluster status
kubectl get hostedcluster $HOSTED_CLUSTER_NAME -n clusters -o yaml

# Monitor availability condition
watch 'kubectl get hostedcluster $HOSTED_CLUSTER_NAME -n clusters \
  -o jsonpath="{.status.conditions[?(@.type==\"Available\")].status}"'

# Monitor control plane pods
watch 'kubectl get pods -n clusters-$HOSTED_CLUSTER_NAME'

# Check for Pod Security violations
kubectl get events -n clusters-$HOSTED_CLUSTER_NAME \
  --field-selector type=Warning | grep 'violates PodSecurity'
```

**Why long timeout (30 minutes)**: Control plane includes complex bootstrap process with etcd cluster formation, API server certificate generation, and controller manager/scheduler dependencies.

---

### Step 10: Fix Service CA ConfigMap
**Purpose**: Populate service CA certificate for CNI network operator

**What it does**:
1. **ConfigMap Creation**: Creates or updates `openshift-service-ca.crt` configmap
2. **CA Extraction**: Gets root CA certificate from GKE cluster kubeconfig
3. **Certificate Population**: Populates both `ca-bundle.crt` and `service-ca.crt` keys
4. **Network Operator Restart**: Forces cluster-network-operator to reload certificates

**Manual equivalent**:
```bash
# Extract root CA from management cluster kubeconfig
kubectl config view --raw \
  -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d > /tmp/ca.crt

# Create/update service CA configmap in hosted cluster namespace
kubectl create configmap openshift-service-ca.crt \
  -n clusters-$HOSTED_CLUSTER_NAME \
  --from-file=ca-bundle.crt=/tmp/ca.crt \
  --from-file=service-ca.crt=/tmp/ca.crt \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart cluster-network-operator to pick up CA changes
kubectl delete pod -n clusters-$HOSTED_CLUSTER_NAME \
  -l name=cluster-network-operator
```

**Why needed**: OVN-Kubernetes network operator requires service CA certificates to validate API server connections. Empty configmaps cause certificate validation failures.

---

### Step 11: Fix OVN Networking
**Purpose**: Deploy OVN-Kubernetes networking components and missing certificates

**What it does**:
1. **Manifest Wait**: Waits up to 5 minutes for network operator to render OVN deployment manifests
2. **Certificate Creation**: Creates missing `ovn-control-plane-metrics-cert` and `ovn-node-metrics-cert` secrets
3. **Component Monitoring**: Waits for OVN control plane pods (3/3 ready) and node pods (7/8 or 8/8 ready)

**Manual equivalent**:
```bash
# Wait for OVN deployment
kubectl get deployment ovnkube-control-plane -n clusters-$HOSTED_CLUSTER_NAME

# Create missing metrics certificates using existing ovn-cert secret
export KUBECONFIG=/tmp/kubeconfig-hosted
TLS_CRT=$(kubectl get secret ovn-cert -n openshift-ovn-kubernetes \
  -o jsonpath='{.data.tls\.crt}')
TLS_KEY=$(kubectl get secret ovn-cert -n openshift-ovn-kubernetes \
  -o jsonpath='{.data.tls\.key}')

# Create control plane and node metrics certificates
# (See script for detailed certificate creation)

# Monitor OVN pods
watch 'kubectl get pods -n openshift-ovn-kubernetes'
```

**Why certificates are missing**: OVN components expect metrics endpoint certificates that sometimes fail to generate during initial deployment.

**OVN component architecture**:
- **ovnkube-control-plane**: 3 replicas for HA, runs OVN northbound/southbound databases
- **ovnkube-node**: DaemonSet (1 pod per worker), runs OVN controller and CNI server

---

### Step 12: Extract Hosted Cluster Access
**Purpose**: Get kubeconfig for the hosted OpenShift cluster

**What it does**:
- Extracts admin kubeconfig secret from management cluster
- Decodes base64-encoded kubeconfig data
- Saves kubeconfig to local file for hosted cluster access
- Tests connectivity to validate kubeconfig functionality

**Manual equivalent**:
```bash
# Extract kubeconfig from management cluster
kubectl get secret admin-kubeconfig \
  -n clusters-$HOSTED_CLUSTER_NAME \
  -o jsonpath='{.data.kubeconfig}' | base64 -d > /tmp/kubeconfig-hosted

# Test access to hosted cluster
export KUBECONFIG=/tmp/kubeconfig-hosted
kubectl cluster-info
kubectl get nodes
```

**Why needed**: Provides administrative access to the hosted OpenShift cluster for worker node registration and workload deployment.

---

### Step 13: Create Worker Node
**Purpose**: Provision Red Hat CoreOS (RHCOS) instance with ignition-based bootstrap

**What it does**:
1. **Extract Authentication Token**: Gets Bearer token from NodePool-generated TokenSecret
2. **Get Ignition Server Endpoint**: Retrieves ignition server IP from management cluster
3. **Create Ignition User-Data**: Generates RHCOS configuration pointing to ignition server
4. **Instance Creation**: Creates GCE instance with RHCOS and ignition bootstrap configuration

**Manual equivalent**:
```bash
# Extract token from NodePool TokenSecret
TOKEN_SECRET=$(kubectl get secrets -n clusters-$HOSTED_CLUSTER_NAME --no-headers | grep "token-.*-workers-" | awk '{print $1}')
TOKEN=$(kubectl get secret $TOKEN_SECRET -n clusters-$HOSTED_CLUSTER_NAME -o jsonpath='{.data.token}')

# Get ignition server IP
IGNITION_IP=$(kubectl get nodes -o jsonpath="{.items[0].status.addresses[?(@.type==\"ExternalIP\")].address}")

# Create GCE instance with RHCOS and ignition user-data
gcloud compute instances create $WORKER_NODE_NAME \
  --zone=$ZONE \
  --machine-type=$WORKER_MACHINE_TYPE \
  --image=$RHCOS_IMAGE_NAME \
  --image-project=$RHCOS_IMAGE_PROJECT \
  --boot-disk-size=$WORKER_DISK_SIZE \
  --boot-disk-type=pd-standard \
  --subnet=default \
  --tags=hypershift-worker \
  --metadata-from-file=user-data=ignition-config.json
```

**Ignition configuration automatically provides**:
- Complete kubelet configuration and certificates (355KB+ payload)
- CRI-O container runtime (pre-configured with RHCOS)
- OpenVSwitch and CNI networking setup
- All required systemd services and dependencies
- Security contexts and SELinux policies

**Why Red Hat CoreOS**: Purpose-built for OpenShift with native CRI-O, ignition support, and guaranteed compatibility with OpenShift components.

---

### Step 14: Generate Worker Certificates
**Purpose**: Create node certificates for kubelet authentication with hosted cluster

**What it does**:
1. **Bootstrap RBAC**: Creates cluster role bindings for node certificate approval
2. **Key Generation**: Creates RSA private key for worker node identity
3. **CSR Creation**: Generates Certificate Signing Request with node name and organization
4. **Kubernetes CSR**: Submits CSR to hosted cluster certificate API
5. **Certificate Approval**: Approves CSR and extracts signed certificate

**Manual equivalent**:
```bash
export KUBECONFIG=/tmp/kubeconfig-hosted

# Create bootstrap RBAC for automatic certificate approval
kubectl create clusterrolebinding kubelet-bootstrap \
  --clusterrole=system:node-bootstrapper \
  --group=system:bootstrappers

# Generate worker node private key
openssl genrsa -out worker-node.key 2048

# Create Certificate Signing Request
openssl req -new -key worker-node.key -out worker-node.csr \
  -subj "/CN=system:node:$WORKER_NODE_NAME/O=system:nodes"

# Submit CSR to Kubernetes and approve
CSR_B64=$(cat worker-node.csr | base64 | tr -d '\n')
kubectl apply -f - <<EOF
apiVersion: certificates.k8s.io/v1
kind: CertificateSigningRequest
metadata:
  name: worker-node-$WORKER_NODE_NAME
spec:
  request: $CSR_B64
  signerName: kubernetes.io/kube-apiserver-client-kubelet
  usages:
  - client auth
EOF

kubectl certificate approve worker-node-$WORKER_NODE_NAME

# Extract signed certificate
kubectl get csr worker-node-$WORKER_NODE_NAME \
  -o jsonpath='{.status.certificate}' | base64 -d > worker-node.crt
```

**Certificate details**:
- **CN**: `system:node:$WORKER_NODE_NAME` - identifies the specific node
- **O**: `system:nodes` - grants node-level permissions

---

### Step 15: Configure Kubelet
**Purpose**: Set up kubelet service and configuration for hosted cluster registration

**What it does**:
1. **Environment Discovery**: Gets worker node IP and API server endpoint
2. **Certificate Extraction**: Retrieves CA certificate from hosted cluster kubeconfig
3. **Configuration Rendering**: Creates kubelet config and kubeconfig from templates
4. **File Upload**: Transfers configuration files to worker node
5. **Service Configuration**: Sets up kubelet systemd service and starts it

**Manual equivalent**:
```bash
# Get worker node internal IP
WORKER_IP=$(gcloud compute instances describe $WORKER_NODE_NAME \
  --zone=$ZONE --format='get(networkInterfaces[0].networkIP)')

# Get API server endpoint from hosted cluster
export KUBECONFIG=/tmp/kubeconfig-hosted
API_SERVER=$(kubectl cluster-info | grep 'Kubernetes control plane' | \
  grep -E 'https://[^:]+' -o)

# Extract CA certificate
CA_CERT=$(kubectl config view --raw \
  -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')

# Create worker kubeconfig and kubelet configuration
# (See script for detailed configuration file creation)

# Upload configuration files and start kubelet
gcloud compute scp worker-kubeconfig.yaml kubelet-config.yaml kubelet.service \
  $WORKER_NODE_NAME:/tmp/ --zone=$ZONE

gcloud compute ssh $WORKER_NODE_NAME --zone=$ZONE --command="
sudo mkdir -p /etc/kubernetes
sudo cp /tmp/worker-kubeconfig.yaml /etc/kubernetes/kubeconfig
sudo cp /tmp/kubelet-config.yaml /etc/kubernetes/kubelet-config.yaml
sudo cp /tmp/kubelet.service /etc/systemd/system/kubelet.service
sudo systemctl daemon-reload
sudo systemctl enable --now kubelet
"
```

**Kubelet configuration details**:
- **Container runtime**: CRI-O via Unix socket
- **Cluster DNS**: Points to hosted cluster CoreDNS (172.31.0.10)
- **Authentication**: Webhook mode for dynamic authentication

---

### Step 16: Setup Worker Networking
**Purpose**: Install and configure complete networking stack (OpenVSwitch + CNI)

This is the most complex step, combining OpenVSwitch installation and CNI configuration into a single atomic operation.

**What it does**:
1. **OpenVSwitch Installation**:
   - Installs CentOS NFV repository for OpenVSwitch 3.3 on RHCOS
   - Creates openvswitch user and sets proper permissions
   - Initializes OVS database with proper schema
   - Starts ovsdb-server and ovs-vswitchd daemons

2. **CNI Infrastructure Setup**:
   - Creates all required CNI directories
   - Waits up to 5 minutes for ovnkube-node to deploy CNI binary
   - Copies CNI binary to standard locations (/opt/cni/bin)
   - Waits for CNI configuration file from OVN controller
   - Places configuration in both standard and multus locations

3. **Service Integration**:
   - Restarts kubelet to detect CNI changes
   - Cycles ovnkube-node pod for fresh initialization
   - Verifies OpenVSwitch and CNI functionality

**Comprehensive setup script (uploaded to worker)**:
```bash
#!/bin/bash
set -euo pipefail

echo "=== HyperShift Worker Node Networking Setup ==="

# Install OpenVSwitch infrastructure
dnf install -y centos-release-nfv-openvswitch
dnf makecache && dnf install -y openvswitch3.3

# Create directories and setup OVS user
mkdir -p /etc/cni/net.d /opt/cni/bin /var/run/multus/cni/net.d
mkdir -p /var/run/openvswitch /etc/openvswitch
id openvswitch || useradd -r -d /var/lib/openvswitch -s /sbin/nologin openvswitch
chown -R openvswitch:openvswitch /var/run/openvswitch /etc/openvswitch

# Initialize OVS database
if [ ! -f /etc/openvswitch/conf.db ]; then
    ovsdb-tool create /etc/openvswitch/conf.db /usr/share/openvswitch/vswitch.ovsschema
    chown openvswitch:openvswitch /etc/openvswitch/conf.db
fi

# Start OpenVSwitch services
pkill -f ovsdb-server || true
sleep 2
sudo -u openvswitch ovsdb-server --remote=punix:/var/run/openvswitch/db.sock \
    --pidfile=/var/run/openvswitch/ovsdb-server.pid \
    --detach /etc/openvswitch/conf.db

ovs-vsctl --no-wait init

pkill -f ovs-vswitchd || true
sleep 2
sudo -u openvswitch ovs-vswitchd --pidfile=/var/run/openvswitch/ovs-vswitchd.pid --detach

# Wait for CNI binary and configuration deployment (up to 5 minutes each)
max_wait=300
wait_time=0
while [ $wait_time -lt $max_wait ]; do
    if [ -f /var/lib/cni/bin/ovn-k8s-cni-overlay ]; then
        cp /var/lib/cni/bin/ovn-k8s-cni-overlay /opt/cni/bin/
        chmod +x /opt/cni/bin/ovn-k8s-cni-overlay
        break
    fi
    sleep 10
    wait_time=$((wait_time + 10))
done

wait_time=0
while [ $wait_time -lt $max_wait ]; do
    if [ -f /etc/cni/net.d/10-ovn-kubernetes.conf ]; then
        cp /etc/cni/net.d/10-ovn-kubernetes.conf /var/run/multus/cni/net.d/
        break
    fi
    sleep 10
    wait_time=$((wait_time + 10))
done

# Restart kubelet and verify setup
systemctl restart kubelet

echo "✅ Worker node networking setup completed!"
ovs-vsctl show
/opt/cni/bin/ovn-k8s-cni-overlay --help >/dev/null 2>&1 && echo "CNI binary functional"
```

**Why this step is atomic**: All networking setup happens in a single script execution, reducing chance of partial failures and ensuring consistent state.

**Critical timing dependencies**:
1. OpenVSwitch must start first (CNI requires OVS socket)
2. ovnkube-node must be running to deploy CNI binary
3. Configuration needed in both `/etc/cni/net.d` and `/var/run/multus/cni/net.d`

**Why dual CNI configuration locations**:
- **`/etc/cni/net.d/`**: Standard CNI plugin location for kubelet
- **`/var/run/multus/cni/net.d/`**: Required by ovnkube-controller readiness probe

---

### Step 17: Verify Installation
**Purpose**: Validate complete installation and test workload deployment

**What it does**:
1. **Credential Refresh**: Regenerates kubeconfigs with fresh tokens to avoid expiration
2. **Node Registration**: Waits up to 10 minutes for worker node to join and become Ready
3. **Network Verification**: Checks OVN component health and container readiness
4. **Workload Testing**: Deploys test application and validates pod scheduling
5. **Connectivity Testing**: Ensures pods can be scheduled and network connectivity works

**Manual equivalent**:
```bash
# Regenerate fresh kubeconfigs
gcloud container clusters get-credentials $GKE_CLUSTER_NAME --zone=$ZONE
kubectl get secret admin-kubeconfig -n clusters-$HOSTED_CLUSTER_NAME \
  -o jsonpath='{.data.kubeconfig}' | base64 -d > /tmp/kubeconfig-hosted

# Check worker node registration and status
export KUBECONFIG=/tmp/kubeconfig-hosted
kubectl get nodes
kubectl wait --for=condition=Ready node/$WORKER_NODE_NAME --timeout=600s

# Verify OVN networking components
kubectl get pods -n openshift-ovn-kubernetes -l app=ovnkube-control-plane
kubectl get pods -n openshift-ovn-kubernetes -l app=ovnkube-node

# Deploy test workload
kubectl create deployment hello-openshift \
  --image=openshift/hello-openshift:latest
kubectl wait --for=condition=ready pod -l app=hello-openshift --timeout=300s

# Check pod scheduling and connectivity
kubectl get pods -l app=hello-openshift -o wide
kubectl exec deployment/hello-openshift -- curl localhost:8080
```

**Success criteria**:
- Worker node shows as "Ready"
- OVN control plane: 3 pods running with 3/3 containers ready
- OVN node pod: 7/8 or 8/8 containers ready
- Test workload: Pod scheduled, running, and responsive
- Pod networking: Pod has IP in cluster network range (10.132.x.x)

---

## Troubleshooting Guide

### Common Issues and Solutions

**1. Control Plane Pods Failing with Pod Security Violations**
```bash
# Check for violations
kubectl get events -n clusters-$HOSTED_CLUSTER_NAME --field-selector type=Warning | grep 'violates PodSecurity'

# Manual fix if webhook not working
kubectl patch deployment cluster-api -n clusters-$HOSTED_CLUSTER_NAME --patch='
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
'
```

**2. OVN Networking Components Not Starting**
```bash
# Check service CA configmap
kubectl get configmap openshift-service-ca.crt -n clusters-$HOSTED_CLUSTER_NAME -o yaml

# Check for missing metrics certificates
kubectl get secrets -n openshift-ovn-kubernetes | grep metrics-cert

# Restart network operator
kubectl delete pod -n clusters-$HOSTED_CLUSTER_NAME -l name=cluster-network-operator
```

**3. Worker Node Not Joining Cluster**
```bash
# Check kubelet logs
gcloud compute ssh $WORKER_NODE_NAME --zone=$ZONE \
  --command="sudo journalctl -u kubelet --no-pager -l | tail -20"

# Check node certificates
openssl x509 -in worker-node.crt -text -noout

# Verify kubeconfig
export KUBECONFIG=/tmp/kubeconfig-hosted
kubectl cluster-info
```

**4. CNI Socket Not Created**
```bash
# Check OpenVSwitch status
gcloud compute ssh $WORKER_NODE_NAME --zone=$ZONE \
  --command="sudo ovs-vsctl show"

# Check CNI binary and configuration
gcloud compute ssh $WORKER_NODE_NAME --zone=$ZONE --command="
sudo ls -la /opt/cni/bin/ovn-k8s-cni-overlay
sudo ls -la /etc/cni/net.d/10-ovn-kubernetes.conf
sudo ls -la /var/run/multus/cni/net.d/10-ovn-kubernetes.conf
"

# Check ovnkube-node pod
kubectl get pods -n openshift-ovn-kubernetes -l app=ovnkube-node -o wide
```

---

## Critical Issues and Real-World Fixes

Based on extensive troubleshooting of actual deployments, these are the most common critical issues that require manual intervention:

### 🔥 **Issue 1: OVN Control Plane Pods Stuck in Init:0/1**

**Symptoms**:
- OVN control plane pods stuck in `Init:0/1` for hours
- Error: `MountVolume.SetUp failed for volume "ovn-control-plane-metrics-cert" : secret "ovn-control-plane-metrics-cert" not found`

**Root Cause**: The `ovn-control-plane-metrics-cert` secret exists in the hosted cluster but is missing from the management cluster namespace where OVN control plane pods run.

**Solution**:
```bash
# 1. Extract certificate data from hosted cluster
export KUBECONFIG=/tmp/kubeconfig-hosted
TLS_CRT=$(kubectl get secret ovn-cert -n openshift-ovn-kubernetes -o jsonpath='{.data.tls\.crt}')
TLS_KEY=$(kubectl get secret ovn-cert -n openshift-ovn-kubernetes -o jsonpath='{.data.tls\.key}')

# 2. Create missing certificate in management cluster
export KUBECONFIG=/tmp/kubeconfig-gke
cat > ovn-control-plane-metrics-cert.yaml << EOF
apiVersion: v1
kind: Secret
metadata:
  name: ovn-control-plane-metrics-cert
  namespace: clusters-$HOSTED_CLUSTER_NAME
  annotations:
    auth.openshift.io/certificate-hostnames: ovn-control-plane-metrics
type: kubernetes.io/tls
data:
  tls.crt: $TLS_CRT
  tls.key: $TLS_KEY
EOF

kubectl apply -f ovn-control-plane-metrics-cert.yaml

# 3. Force restart of stuck pods
kubectl delete pod -n clusters-$HOSTED_CLUSTER_NAME -l app=ovnkube-control-plane

# 4. Verify all 3 control plane pods are Running (3/3)
watch 'kubectl get pods -n clusters-$HOSTED_CLUSTER_NAME -l app=ovnkube-control-plane'
```

### 🔥 **Issue 2: Pending Certificate Signing Requests (CSRs)**

**Symptoms**:
- Worker node not joining cluster
- ovnkube-controller failing with certificate errors: `failed to start the node certificate manager: certificate was not signed`
- Multiple pending CSRs accumulating

**Root Cause**: Platform "None" doesn't create Machine resources, so machine-approver cannot automatically approve CSRs.

**Diagnosis**:
```bash
export KUBECONFIG=/tmp/kubeconfig-hosted
kubectl get csr | grep Pending
```

**Solution**:
```bash
# Manual CSR approval (immediate fix)
export KUBECONFIG=/tmp/kubeconfig-hosted
kubectl get csr --no-headers | grep Pending | awk '{print $1}' | xargs -I {} oc adm certificate approve {}

# Monitor for new CSRs (worker may generate multiple rounds)
watch 'kubectl get csr | grep Pending'

# Approve new CSRs as they appear
kubectl get csr --no-headers | grep Pending | awk '{print $1}' | xargs -I {} oc adm certificate approve {}
```

**Long-term Solution (Future Enhancement)**:
```bash
# Create Machine resources for automatic approval (template in templates/manual-machine.yaml)
# This bridges platform "None" with automatic CSR approval
```

### 🔥 **Issue 3: Worker Node NotReady - CNI Configuration Missing**

**Symptoms**:
- Worker node status: `NotReady`
- Error: `container runtime network not ready: NetworkReady=false reason:NetworkPluginNotReady message:Network plugin returns error: No CNI configuration file in /etc/kubernetes/cni/net.d/`
- ovnkube-node pod showing 7/8 or 8/8 ready but worker still NotReady

**Root Cause**: ovnkube-controller container may be in an inconsistent state after certificate fixes, preventing CNI configuration creation.

**Diagnosis**:
```bash
export KUBECONFIG=/tmp/kubeconfig-hosted

# Check node status and conditions
kubectl get nodes
kubectl describe node $WORKER_NODE_NAME | grep -A 20 "Conditions:"

# Check if CNI config exists in pod
kubectl exec ovnkube-node-xxx -n openshift-ovn-kubernetes -c ovnkube-controller -- test -f /etc/cni/net.d/10-ovn-kubernetes.conf && echo "EXISTS" || echo "MISSING"
```

**Solution**:
```bash
export KUBECONFIG=/tmp/kubeconfig-hosted

# 1. Restart ovnkube-node pod for fresh initialization
kubectl delete pod -n openshift-ovn-kubernetes -l app=ovnkube-node

# 2. Approve any new CSRs that are generated during restart
sleep 30
kubectl get csr --no-headers | grep Pending | awk '{print $1}' | xargs -I {} oc adm certificate approve {}

# 3. Wait for pod to be fully ready (8/8)
kubectl wait --for=condition=ready pod -l app=ovnkube-node -n openshift-ovn-kubernetes --timeout=300s

# 4. Verify worker node becomes Ready
kubectl wait --for=condition=Ready node/$WORKER_NODE_NAME --timeout=600s

# 5. Test pod scheduling
kubectl run test-pod --image=nginx --rm -i --restart=Never -- echo "Networking test successful"
```

### 🔥 **Issue 4: Multus Circular Dependency Causing Worker NotReady**

**Symptoms**:
- Worker node joins cluster but remains `NotReady` for extended periods
- multus pod in `openshift-multus` namespace shows `CrashLoopBackOff`
- ovnkube-controller container in ovnkube-node pod fails readiness probe
- Error: `container runtime network not ready: NetworkReady=false reason:NetworkPluginNotReady message:Network plugin returns error: No CNI configuration file in /etc/kubernetes/cni/net.d/`

**Root Cause**: **Systematic circular dependency** in HyperShift platform=None deployments:
- `multus` waits for readiness indicator: `/run/multus/cni/net.d/10-ovn-kubernetes.conf`
- `ovnkube-controller` creates this file, but can't start until multus is working
- `kubelet` expects CNI config in `/etc/kubernetes/cni/net.d/10-ovn-kubernetes.conf`

**Diagnosis**:
```bash
export KUBECONFIG=/tmp/kubeconfig-hosted

# Check multus pod status
kubectl get pods -n openshift-multus

# Check ovnkube-node pod containers
kubectl get pods -n openshift-ovn-kubernetes -o wide

# Check node conditions
kubectl describe node $WORKER_NODE_NAME | grep -A 10 "Conditions:"
```

**Solution (Fixed in worker-setup.sh)**:
The issue is now **automatically prevented** by enhanced worker bootstrap that creates CNI directories and configuration files during ignition bootstrap. However, for existing deployments, manual fix:

```bash
# 1. Create missing directories and CNI configuration
kubectl apply -f - << 'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: fix-multus-cycle
spec:
  hostNetwork: true
  nodeName: ${WORKER_NODE_NAME}
  containers:
  - name: fix
    image: busybox
    command:
    - sh
    - -c
    - |
      mkdir -p /host/var/run/multus/cni/net.d /host/etc/kubernetes/cni/net.d
      cat > /host/var/run/multus/cni/net.d/10-ovn-kubernetes.conf << 'EOFCNI'
      {
        "cniVersion": "0.3.1",
        "name": "ovn-kubernetes",
        "type": "ovn-k8s-cni-overlay",
        "ipam": {}, "dns": {},
        "logLevel": "5",
        "logfile": "/var/log/ovn-kubernetes/ovn-k8s-cni-overlay.log",
        "logfile-maxsize": 100, "logfile-maxbackups": 5, "logfile-maxage": 5
      }
EOFCNI
      cp /host/var/run/multus/cni/net.d/10-ovn-kubernetes.conf /host/etc/kubernetes/cni/net.d/
      chown root:root /host/var/run/multus/cni/net.d/10-ovn-kubernetes.conf
      chown root:root /host/etc/kubernetes/cni/net.d/10-ovn-kubernetes.conf
      chmod 644 /host/var/run/multus/cni/net.d/10-ovn-kubernetes.conf
      chmod 644 /host/etc/kubernetes/cni/net.d/10-ovn-kubernetes.conf
      sleep 30
    volumeMounts:
    - name: host
      mountPath: /host
    securityContext:
      privileged: true
  volumes:
  - name: host
    hostPath:
      path: /
  restartPolicy: Never
EOF

# 2. Restart failing pods to pick up new configuration
kubectl delete pod -n openshift-multus -l app=multus
kubectl delete pod -n openshift-ovn-kubernetes -l app=ovnkube-node

# 3. Wait for pods to become ready
kubectl wait --for=condition=ready pod -l app=multus -n openshift-multus --timeout=300s
kubectl wait --for=condition=ready pod -l app=ovnkube-node -n openshift-ovn-kubernetes --timeout=300s

# 4. Verify worker node becomes Ready
kubectl wait --for=condition=Ready node/$WORKER_NODE_NAME --timeout=600s
```

**Prevention**: This issue is now **automatically prevented** in new deployments by the enhanced `worker-setup.sh` script that pre-creates all required directories and CNI configuration files during worker bootstrap.

### 🔥 **Issue 5: Complete Recovery Sequence**

When multiple issues occur together, follow this complete recovery sequence:

```bash
# 1. Fix OVN control plane certificates (if pods stuck in Init:0/1)
source my-cluster.env
python3 test_ignition_worker.py --fix-ovn-only

# 2. Check and approve pending CSRs
export KUBECONFIG=/tmp/kubeconfig-hosted
kubectl get csr | grep Pending
kubectl get csr --no-headers | grep Pending | awk '{print $1}' | xargs -I {} oc adm certificate approve {}

# 3. Restart OVN node pod if worker still NotReady
kubectl delete pod -n openshift-ovn-kubernetes -l app=ovnkube-node

# 4. Approve any new CSRs after restart
sleep 30
kubectl get csr --no-headers | grep Pending | awk '{print $1}' | xargs -I {} oc adm certificate approve {}

# 5. Verify complete system health
kubectl get nodes
kubectl get pods -n openshift-ovn-kubernetes
kubectl run test-pod --image=nginx --rm -i --restart=Never -- echo "System operational"
```

### 📊 **Success Criteria After Fixes**

After applying these fixes, you should see:

- **Management Cluster**:
  ```bash
  export KUBECONFIG=/tmp/kubeconfig-gke
  kubectl get pods -n clusters-$HOSTED_CLUSTER_NAME -l app=ovnkube-control-plane
  # Expected: 3 pods, all showing 3/3 Running
  ```

- **Hosted Cluster**:
  ```bash
  export KUBECONFIG=/tmp/kubeconfig-hosted
  kubectl get pods -n openshift-ovn-kubernetes
  # Expected: ovnkube-node pod showing 8/8 Running

  kubectl get nodes
  # Expected: Worker node status "Ready"
  ```

- **Workload Scheduling**:
  ```bash
  kubectl run test-pod --image=nginx --rm -i --restart=Never -- echo "Success"
  # Expected: Pod schedules and runs successfully
  ```

### Log Locations

**Management Cluster**: `kubectl logs -n hypershift -l name=operator`
**Hosted Cluster**: `kubectl logs -n clusters-$HOSTED_CLUSTER_NAME -l app=kube-apiserver`
**Worker Node**: `gcloud compute ssh $WORKER_NODE_NAME --zone=$ZONE --command="sudo journalctl -u kubelet"`
**OVN Networking**: `kubectl logs -n openshift-ovn-kubernetes -l app=ovnkube-node`

### Recovery and Cleanup

**Resume Installation**:
```bash
# Check completed steps
cat .hypershift_install_state_my-hosted-cluster.json | jq '.completed_steps'

# Continue from last step
python3 hypershift_installer.py --continue
```

**Complete Cleanup**:
```bash
# Clean up all resources
python3 hypershift_installer.py --cleanup

# Manual cleanup if needed
gcloud compute instances delete $WORKER_NODE_NAME --zone=$ZONE --quiet
gcloud container clusters delete $GKE_CLUSTER_NAME --zone=$ZONE --quiet
```

This comprehensive documentation provides both high-level usage instructions and deep technical details for every aspect of the HyperShift GKE installation process, enabling effective operation, troubleshooting, and customization.