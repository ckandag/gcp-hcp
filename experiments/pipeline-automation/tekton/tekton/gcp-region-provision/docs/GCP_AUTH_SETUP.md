# GCP Authentication Setup for Tekton

This guide covers two methods for authenticating Tekton pipelines to Google Cloud Platform.

## Method 1: Workload Identity (Recommended for Production)

Workload Identity allows Kubernetes service accounts to impersonate GCP service accounts without managing credential files.

### Prerequisites

- GKE cluster with Workload Identity enabled
- `gcloud` CLI configured
- Appropriate IAM permissions to create service accounts

### Step 1: Enable Workload Identity on Your GKE Cluster

If your cluster doesn't have Workload Identity enabled:

```bash
# For existing cluster
gcloud container clusters update CLUSTER_NAME \
    --workload-pool=PROJECT_ID.svc.id.goog \
    --region=REGION

# For new cluster
gcloud container clusters create CLUSTER_NAME \
    --workload-pool=PROJECT_ID.svc.id.goog \
    --region=REGION
```

### Step 2: Create GCP Service Account

```bash
# Set variables
export PROJECT_ID="your-project-id"
export GSA_NAME="tekton-deployer"
export GSA_EMAIL="${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Create the service account
gcloud iam service-accounts create ${GSA_NAME} \
    --display-name="Tekton Pipeline Deployer" \
    --description="Service account for Tekton to manage GCP resources" \
    --project=${PROJECT_ID}

# Grant necessary IAM roles
# For compute VM management:
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${GSA_EMAIL}" \
    --role="roles/compute.admin"

# For viewing project resources:
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${GSA_EMAIL}" \
    --role="roles/viewer"

# Optional: For managing GCS buckets (if using Terraform backend):
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${GSA_EMAIL}" \
    --role="roles/storage.admin"
```

### Step 3: Create Kubernetes Service Account

Create a Kubernetes service account that will be bound to the GCP service account:

```bash
# Set variables
export KSA_NAME="tekton-gcp-deployer"
export NAMESPACE="default"

# Create the Kubernetes service account
kubectl create serviceaccount ${KSA_NAME} -n ${NAMESPACE}
```

### Step 4: Bind Kubernetes SA to GCP SA

```bash
# Allow the Kubernetes service account to impersonate the GCP service account
gcloud iam service-accounts add-iam-policy-binding ${GSA_EMAIL} \
    --role=roles/iam.workloadIdentityUser \
    --member="serviceAccount:${PROJECT_ID}.svc.id.goog[${NAMESPACE}/${KSA_NAME}]"

# Annotate the Kubernetes service account
kubectl annotate serviceaccount ${KSA_NAME} \
    -n ${NAMESPACE} \
    iam.gke.io/gcp-service-account=${GSA_EMAIL}
```

### Step 5: Update Pipeline to Use the Service Account

In your PipelineRun or Pipeline, reference the service account:

```yaml
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  name: gcp-region-provision-run
spec:
  serviceAccountName: tekton-gcp-deployer  # <-- Use this SA
  pipelineRef:
    name: gcp-region-provisioning-pipeline
  # ... rest of spec
```

### Step 6: Verify Authentication

Test that the authentication works:

```bash
# Create a test pod using the service account
kubectl run -it --rm gcloud-test \
    --image=google/cloud-sdk:slim \
    --serviceaccount=tekton-gcp-deployer \
    --namespace=default \
    -- gcloud auth list

# You should see the GCP service account listed
```

---

## Method 2: JSON Key File (Development/Testing Only)

This method uses a service account key file stored as a Kubernetes Secret. **Not recommended for production** due to security concerns.

### Step 1: Create GCP Service Account and Key

```bash
# Set variables
export PROJECT_ID="your-project-id"
export GSA_NAME="tekton-deployer-dev"
export GSA_EMAIL="${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
export KEY_FILE="./tekton-sa-key.json"

# Create service account
gcloud iam service-accounts create ${GSA_NAME} \
    --display-name="Tekton Deployer (Dev)" \
    --project=${PROJECT_ID}

# Grant IAM roles
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${GSA_EMAIL}" \
    --role="roles/compute.admin"

# Create and download key
gcloud iam service-accounts keys create ${KEY_FILE} \
    --iam-account=${GSA_EMAIL} \
    --project=${PROJECT_ID}

echo "⚠️  Key file created: ${KEY_FILE}"
echo "⚠️  Keep this file secure and never commit to git!"
```

### Step 2: Create Kubernetes Secret

```bash
# Create secret from the key file
kubectl create secret generic gcp-credentials \
    --from-file=key.json=${KEY_FILE} \
    --namespace=default

# Verify the secret
kubectl get secret gcp-credentials -n default
```

### Step 3: Mount Secret in Pipeline Tasks

Add the secret as a volume in your task:

```yaml
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: terraform-apply
spec:
  steps:
    - name: terraform-apply
      image: hashicorp/terraform:latest
      env:
        - name: GOOGLE_APPLICATION_CREDENTIALS
          value: /var/secrets/gcp/key.json
      volumeMounts:
        - name: gcp-credentials
          mountPath: /var/secrets/gcp
          readOnly: true
      script: |
        #!/bin/sh
        gcloud auth activate-service-account --key-file=$GOOGLE_APPLICATION_CREDENTIALS
        terraform apply -auto-approve
  volumes:
    - name: gcp-credentials
      secret:
        secretName: gcp-credentials
```

### Security Considerations

❌ **Cons of JSON Key Method:**
- Keys don't expire automatically
- Requires manual rotation
- Risk of exposure if secret is compromised
- Keys stored in cluster (attack surface)

⚠️ **If you must use this method:**
- Rotate keys regularly (every 90 days)
- Use least-privilege IAM roles
- Enable audit logging
- Never commit keys to git
- Delete unused keys immediately

---

## Recommended IAM Roles for Common Use Cases

### For Compute VM Management
```bash
# Minimum required
roles/compute.admin           # Full control over Compute Engine resources
roles/iam.serviceAccountUser  # Required to attach service accounts to VMs

# Optional
roles/compute.networkAdmin    # If managing VPCs/networks
roles/compute.securityAdmin   # If managing firewalls/security policies
```

### For Terraform State Backend (GCS)
```bash
roles/storage.objectAdmin     # Read/write to GCS bucket
```

### For Multi-Project Deployments
```bash
# Grant at folder or organization level
roles/resourcemanager.projectCreator
roles/billing.user
```

---

## Troubleshooting

### "Permission denied" errors

```bash
# Check if Workload Identity is enabled
gcloud container clusters describe CLUSTER_NAME \
    --region=REGION \
    --format="value(workloadIdentityConfig.workloadPool)"

# Check service account binding
gcloud iam service-accounts get-iam-policy ${GSA_EMAIL}

# Check annotation on Kubernetes SA
kubectl get serviceaccount ${KSA_NAME} -n ${NAMESPACE} -o yaml
```

### "Could not authenticate" errors

```bash
# Test from within a pod
kubectl run -it --rm debug \
    --image=google/cloud-sdk:slim \
    --serviceaccount=${KSA_NAME} \
    -- gcloud auth list

# Check for the GCP service account email in the output
```

### Verify IAM permissions

```bash
# Test permissions
gcloud projects get-iam-policy ${PROJECT_ID} \
    --flatten="bindings[].members" \
    --format="table(bindings.role)" \
    --filter="bindings.members:${GSA_EMAIL}"
```

---

## Quick Start Scripts

See the `setup/` directory for automated setup scripts:
- `setup-workload-identity.sh` - Automates Workload Identity setup
- `setup-json-key.sh` - Automates JSON key setup (dev only)
