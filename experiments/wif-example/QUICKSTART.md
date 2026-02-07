# WIF Example - Quick Start Guide

Complete guide to set up and deploy the WIF example application from scratch.

## Prerequisites

- GCP project with billing enabled
- `gcloud` CLI installed and authenticated
- `kubectl` configured for your management cluster
- `podman` installed (for building containers)
- HyperShift management cluster running

## Step 0: Environment Configuration

Set up your environment variables for easy reuse:

```bash
# 1. Copy the environment template
cp env.example .env

# 2. Edit .env with your values
vi .env

# Required settings:
#   GCP_PROJECT_ID="your-gcp-project"
#   HYPERSHIFT_INFRA_ID="your-cluster-id"
#   JWKS_FILE="hosted-cluster-setup/jwks.json"

# 3. Source the environment file
source .env

# 4. Verify settings
echo "Project: $GCP_PROJECT_ID"
echo "Cluster: $HYPERSHIFT_INFRA_ID"
echo "JWKS File: $JWKS_FILE"
```

## Step 1: Hosted Cluster Setup

Generate the service account signing key for your hosted cluster and extract the public JWKS.

```bash
cd hosted-cluster-setup

# 1. Generate the private key (PKCS#1 format)
./1-generate-sa-signing-key.sh

# 2. Create the Kubernetes secret manifest
./2-create-secret.sh

# 3. Extract the public JWKS for GCP WIF
./3-extract-jwks.sh

# 4. Apply the secret to your management cluster
kubectl apply -f sa-signing-key-secret.yaml

# 5. Verify the secret was created
kubectl get secret sa-signing-key -n clusters

cd ..
```

**Important:** Update your HostedCluster spec to reference the signing key:
```yaml
spec:
  serviceAccountSigningKey:
    name: sa-signing-key
```

See `hosted-cluster-setup/hosted-cluster-example.yaml` for a complete example.

## Step 2: GCP Infrastructure Setup

Set up the GCP Workload Identity Federation infrastructure.

```bash
cd infra

# Run the setup script (uses environment variables from Step 0)
./setup-wif-example-gcp.sh

# Or with explicit flags:
./setup-wif-example-gcp.sh \
  --project-id $GCP_PROJECT_ID \
  --infra-id $HYPERSHIFT_INFRA_ID \
  --jwks-file ../hosted-cluster-setup/jwks.json

cd ..
```

This creates:
- Workload Identity Pool: `${HYPERSHIFT_INFRA_ID}-wi-pool`
- OIDC Provider: `${HYPERSHIFT_INFRA_ID}-k8s-provider`
- GCP Service Account: `wif-app@${GCP_PROJECT_ID}.iam.gserviceaccount.com`
- IAM role bindings
- `infra/credentials.json` file

**Verify GCP resources:**
```bash
# Check Workload Identity Pool
gcloud iam workload-identity-pools list --location=global

# Check Service Account
gcloud iam service-accounts list --filter="email~wif-app"

# Verify credentials file was created
ls -la infra/credentials.json
```

## Step 3: Application Build and Deployment

Build the container image and deploy the application.

### 3.1: Build Container Image

```bash
cd app

# Option A: Using the build script
export GCP_PROJECT_ID="your-project-id"
./build-and-push.sh

# Option B: Using Makefile
make container GCP_PROJECT_ID=$GCP_PROJECT_ID

cd ..
```

This will:
1. Login to `gcr.io` using gcloud credentials
2. Build the image as `gcr.io/${GCP_PROJECT_ID}/wif-example:latest`
3. Push to Google Container Registry

### 3.2: Create Kubernetes Resources

```bash
# 1. Create the ConfigMap with GCP credentials
kubectl create configmap gcp-wif-credentials \
  --from-file=credentials.json=infra/credentials.json \
  -n clusters-${HYPERSHIFT_INFRA_ID}

# 2. Create the kubeconfig secret for token-minter
# (Use your hosted cluster's admin kubeconfig)
kubectl create secret generic admin-kubeconfig \
  --from-file=kubeconfig=/path/to/hosted-cluster-kubeconfig \
  -n clusters-${HYPERSHIFT_INFRA_ID}

# 3. Ensure pull-secret exists (for token-minter image)
# If not, create it from your pull-secret.json
kubectl create secret generic pull-secret \
  --from-file=.dockerconfigjson=/path/to/pull-secret.json \
  --type=kubernetes.io/dockerconfigjson \
  -n clusters-${HYPERSHIFT_INFRA_ID}
```

### 3.3: Deploy the Application

```bash
# Deploy the application
kubectl apply -f app/deployment.yaml
```

## Step 4: Verify Deployment

Check that everything is running correctly.

```bash
# 1. Check pod status
kubectl get pods -n clusters-${HYPERSHIFT_INFRA_ID} -l app=wif-example

# 2. Check both containers are running
kubectl get pods -n clusters-${HYPERSHIFT_INFRA_ID} -l app=wif-example -o jsonpath='{.items[0].status.containerStatuses[*].name}'

# 3. View application logs
kubectl logs -n clusters-${HYPERSHIFT_INFRA_ID} -l app=wif-example -c wif-app -f

# 4. View token-minter logs
kubectl logs -n clusters-${HYPERSHIFT_INFRA_ID} -l app=wif-example -c token-minter -f

# 5. Describe the pod for detailed status
kubectl describe pod -n clusters-${HYPERSHIFT_INFRA_ID} -l app=wif-example
```

**Expected output in wif-app logs:**
```
Starting WIF Example Application...
Successfully authenticated with GCP using Workload Identity Federation
Listing GCP Compute instances in project: your-project-id
...
```

## Step 5: Troubleshooting

### Common Issues

**Pod not starting:**
```bash
# Check events
kubectl get events -n clusters-${HYPERSHIFT_INFRA_ID} --sort-by='.lastTimestamp'

# Check pod status
kubectl describe pod -n clusters-${HYPERSHIFT_INFRA_ID} -l app=wif-example
```

**Token-minter errors:**
```bash
# Check token-minter logs
kubectl logs -n clusters-${HYPERSHIFT_INFRA_ID} -l app=wif-example -c token-minter

# Common issues:
# - Missing kubeconfig secret
# - Service account doesn't exist in hosted cluster
# - Incorrect namespace
```

**GCP authentication errors:**
```bash
# Check app logs
kubectl logs -n clusters-${HYPERSHIFT_INFRA_ID} -l app=wif-example -c wif-app

# Verify credentials ConfigMap
kubectl get configmap gcp-wif-credentials -n clusters-${HYPERSHIFT_INFRA_ID} -o yaml

# Check GCP IAM bindings
gcloud iam service-accounts get-iam-policy wif-app@${GCP_PROJECT_ID}.iam.gserviceaccount.com
```

**Token exchange fails:**
```bash
# Verify the GCP service account has the serviceAccountTokenCreator role
gcloud projects add-iam-policy-binding ${GCP_PROJECT_ID} \
  --member="serviceAccount:wif-app@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator"
```

## Step 6: Cleanup

Remove all resources when done.

```bash
# 1. Delete Kubernetes resources
kubectl delete -f app/deployment.yaml
kubectl delete configmap gcp-wif-credentials -n clusters-${HYPERSHIFT_INFRA_ID}
kubectl delete secret admin-kubeconfig -n clusters-${HYPERSHIFT_INFRA_ID}

# Note: The service account in the hosted cluster (wif-app-workload-sa) will be
# automatically cleaned up when the deployment is deleted

# 2. Delete GCP Service Account
gcloud iam service-accounts delete wif-app@${GCP_PROJECT_ID}.iam.gserviceaccount.com --quiet

# 3. Delete OIDC Provider
gcloud iam workload-identity-pools providers delete ${HYPERSHIFT_INFRA_ID}-k8s-provider \
  --workload-identity-pool=${HYPERSHIFT_INFRA_ID}-wi-pool \
  --location=global \
  --quiet

# 4. Delete Workload Identity Pool
gcloud iam workload-identity-pools delete ${HYPERSHIFT_INFRA_ID}-wi-pool \
  --location=global \
  --quiet

# 5. Delete generated files
rm -f infra/credentials.json
rm -f hosted-cluster-setup/sa-signing-key.pem
rm -f hosted-cluster-setup/sa-signing-key-secret.yaml
rm -f hosted-cluster-setup/jwks.json
```

## Quick Reference

### Key Files Generated

| File | Location | Purpose |
|------|----------|---------|
| `sa-signing-key.pem` | `hosted-cluster-setup/` | Private key for HostedCluster |
| `sa-signing-key-secret.yaml` | `hosted-cluster-setup/` | Kubernetes secret manifest |
| `jwks.json` | `hosted-cluster-setup/` | Public JWKS for GCP WIF |
| `credentials.json` | `infra/` | GCP WIF credentials for app |

### Key Commands

```bash
# Source environment
source .env

# Generate hosted cluster keys
cd hosted-cluster-setup && ./1-generate-sa-signing-key.sh && ./2-create-secret.sh && ./3-extract-jwks.sh && cd ..

# Setup GCP infrastructure
cd infra && ./setup-wif-example-gcp.sh && cd ..

# Build and push container
cd app && make container GCP_PROJECT_ID=$GCP_PROJECT_ID && cd ..

# Deploy application
kubectl apply -f app/deployment.yaml

# View logs
kubectl logs -n clusters-${HYPERSHIFT_INFRA_ID} -l app=wif-example -c wif-app -f
```

## Next Steps

- Review the detailed documentation in `README.md`
- Customize IAM roles in `infra/setup-wif-example-gcp.sh`
- Modify the application in `app/main.go` for your use case
- See `hosted-cluster-setup/README.md` for key rotation procedures
- See `infra/README.md` for advanced GCP WIF configuration

## Getting Help

- **Hosted Cluster Setup**: See `hosted-cluster-setup/README.md`
- **GCP Infrastructure**: See `infra/README.md`
- **Application Details**: See main `README.md`
- **Architecture Diagram**: See `README.md` for the complete flow
