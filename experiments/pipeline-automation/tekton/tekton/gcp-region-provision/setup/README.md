# GCP Authentication Setup for Tekton

This directory contains scripts to set up authentication for Tekton pipelines to access Google Cloud Platform resources.

## Quick Start

### Option 1: Local Clusters (Kind/Minikube) - Recommended for Development

For local Kubernetes clusters, use JSON key authentication:

```bash
# Run the automated setup script
./setup-local-gcp-auth.sh

# Grant storage permissions
./grant-storage-admin.sh
```

This will:
1. Create a GCP service account: `tekton-deployer-local@<YOUR-PROJECT-ID>.iam.gserviceaccount.com`
2. Generate and download a JSON key file
3. Create a Kubernetes secret with the credentials
4. Create a Kubernetes ServiceAccount
5. Grant necessary IAM roles (compute.admin, iam.serviceAccountUser, viewer)
6. Verify the setup

### Option 2: GKE Clusters - Recommended for Production

For GKE clusters, use Workload Identity:

```bash
# Run the automated setup script
./setup-workload-identity.sh

# Or with custom values
PROJECT_ID=<YOUR-PROJECT-ID> \
  GSA_NAME=tekton-deployer \
  KSA_NAME=tekton-gcp-deployer \
  CLUSTER_NAME=my-cluster \
  REGION=us-central1 \
  ./setup-workload-identity.sh

# Grant storage permissions
./grant-storage-admin.sh
```

This will:
1. Verify Workload Identity is enabled on your GKE cluster
2. Create a GCP service account with necessary IAM roles
3. Create a Kubernetes service account
4. Bind them together using Workload Identity
5. Verify the setup

## What Gets Created

### GCP Resources (Local Auth)
- **Service Account**: `tekton-deployer-local@<YOUR-PROJECT-ID>.iam.gserviceaccount.com`
- **JSON Key File**: `gcp-key.json` (stored locally, added to .gitignore)
- **IAM Roles**:
  - `roles/compute.admin` - Full control over Compute Engine resources
  - `roles/iam.serviceAccountUser` - Attach service accounts to VMs
  - `roles/viewer` - Read project resources
  - `roles/storage.admin` - Create and manage GCS buckets

### GCP Resources (Workload Identity)
- **Service Account**: `tekton-deployer@<YOUR-PROJECT-ID>.iam.gserviceaccount.com`
- **IAM Roles**: Same as local auth
- **Workload Identity Binding**: Links GCP SA to Kubernetes SA

### Kubernetes Resources
- **Secret**: `gcp-credentials` (local auth only - contains JSON key)
- **ServiceAccount**: `tekton-gcp-deployer` (in `default` namespace)
- **Role**: Basic permissions to read ConfigMaps, Secrets, and PVCs
- **RoleBinding**: Binds the role to the service account

## Verification

After setup, verify authentication works:

### Local Auth (JSON Key)
```bash
# Test from a pod
kubectl run -it --rm gcloud-test \
  --image=google/cloud-sdk:slim \
  --serviceaccount=tekton-gcp-deployer \
  --namespace=default \
  --overrides='{"spec":{"containers":[{"name":"gcloud-test","image":"google/cloud-sdk:slim","command":["gcloud","auth","list"],"volumeMounts":[{"name":"gcp-creds","mountPath":"/var/secrets/gcp"}],"env":[{"name":"GOOGLE_APPLICATION_CREDENTIALS","value":"/var/secrets/gcp/key.json"}]}],"volumes":[{"name":"gcp-creds","secret":{"secretName":"gcp-credentials"}}]}}' \
  -- gcloud auth list

# Expected output should show:
#   tekton-deployer-local@<YOUR-PROJECT-ID>.iam.gserviceaccount.com
```

### Workload Identity (GKE)
```bash
# Test from a pod
kubectl run -it --rm gcloud-test \
  --image=google/cloud-sdk:slim \
  --serviceaccount=tekton-gcp-deployer \
  --namespace=default \
  -- gcloud auth list

# Expected output should show:
#   tekton-deployer@<YOUR-PROJECT-ID>.iam.gserviceaccount.com
```

## Using in Pipelines

The TriggerTemplate has already been updated to use this service account:

```yaml
apiVersion: tekton.dev/v1beta1
kind: PipelineRun
spec:
  serviceAccountName: tekton-gcp-deployer  # <-- This line
  pipelineRef:
    name: gcp-region-provisioning-pipeline
```

All tasks in the pipeline will now run with GCP credentials automatically!

## Troubleshooting

### "Permission denied" when running pipeline (Local Auth)

**Check 1: Secret exists?**
```bash
kubectl get secret gcp-credentials -n default
```

**Check 2: Secret has key.json?**
```bash
kubectl get secret gcp-credentials -n default -o jsonpath='{.data.key\.json}' | base64 -d | jq .
```

**Check 3: Service account has storage.admin role?**
```bash
gcloud projects get-iam-policy <YOUR-PROJECT-ID> \
  --flatten="bindings[].members" \
  --filter="bindings.members:tekton-deployer-local"
```

Should show `roles/storage.admin`.

### "Permission denied" when running pipeline (Workload Identity)

**Check 1: Workload Identity enabled?**
```bash
gcloud container clusters describe CLUSTER_NAME \
  --region=REGION \
  --format="value(workloadIdentityConfig.workloadPool)"
```

**Check 2: Service account annotation**
```bash
kubectl get serviceaccount tekton-gcp-deployer -n default -o yaml | grep iam.gke.io
```

**Check 3: IAM policy binding**
```bash
gcloud iam service-accounts get-iam-policy \
  tekton-deployer@<YOUR-PROJECT-ID>.iam.gserviceaccount.com
```

### "Could not find service account"

Make sure you've run the setup script:
```bash
kubectl get serviceaccount -n default | grep tekton
```

Should show `tekton-gcp-deployer`.

### Still having issues?

See the comprehensive troubleshooting section in:
```bash
cat ../docs/GCP_AUTH_SETUP.md
```

## Environment Variables

The setup script supports these environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `PROJECT_ID` | GCP project ID | Current gcloud project |
| `GSA_NAME` | GCP service account name | `tekton-deployer` |
| `KSA_NAME` | Kubernetes service account name | `tekton-gcp-deployer` |
| `NAMESPACE` | Kubernetes namespace | `default` |
| `CLUSTER_NAME` | GKE cluster name | Auto-detected from kubectl context |
| `REGION` | GKE cluster region | `us-central1` |

## Security Best Practices

✅ **DO:**
- Use Workload Identity for production
- Follow principle of least privilege
- Regularly audit IAM permissions
- Use separate service accounts per environment
- Enable Cloud Audit Logs

❌ **DON'T:**
- Use JSON key files in production
- Grant overly broad IAM roles
- Commit credentials to git
- Share service accounts across teams

## Next Steps

After setting up authentication:

1. **Test the pipeline:**
   ```bash
   # Trigger a test run
   gcpctl region add -e integration -r us-central1 -s test

   # Check the logs to verify GCP access
   kubectl logs -f <pipeline-run-pod>
   ```

2. **Set up Terraform backend:**
   - Create GCS bucket for Terraform state
   - Update `pipeline.yaml` with bucket name

3. **Configure additional IAM roles** as needed for your use case

## Files in This Directory

- `setup-local-gcp-auth.sh` - Automated local GCP auth setup (JSON key)
- `setup-workload-identity.sh` - Automated Workload Identity setup (GKE)
- `grant-storage-admin.sh` - Grant storage.admin role to service account
- `WHICH_SETUP.md` - Guide to choosing the right auth method
- `README.md` - This file
- `../docs/GCP_AUTH_SETUP.md` - Comprehensive authentication guide
- `../k8s/serviceaccount.yaml` - Kubernetes ServiceAccount manifest

## Support

For questions or issues:
1. Check the troubleshooting section in `/docs/GCP_AUTH_SETUP.md`
2. Review [Google's Workload Identity documentation](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity)
3. Review [Tekton authentication documentation](https://tekton.dev/docs/pipelines/auth/)
