# Testing Guide - GCP Region Provisioning Pipeline

This guide walks through testing the complete GCP region provisioning pipeline, from triggering via webhook to verifying the GCS bucket creation in Google Cloud.

## Prerequisites

Before testing, ensure you've completed the setup:

```bash
# 1. GCP authentication
cd setup
./setup-local-gcp-auth.sh
./grant-storage-admin.sh

# 2. Verify secret created
kubectl get secret gcp-credentials -n default

# 3. Deploy all Tekton resources
cd ..
kubectl apply -f pvc.yaml
kubectl apply -f sa.yaml
kubectl apply -f k8s/serviceaccount.yaml
kubectl apply -f k8s/terraform-gcp-task.yaml
kubectl apply -f pipeline.yaml
kubectl apply -f triggerbinding.yaml
kubectl apply -f triggertemplate.yaml
kubectl apply -f eventlistener.yaml

# 4. Verify EventListener is running
kubectl get pods | grep el-gcp-region

# 5. Port forward to access webhook
kubectl port-forward svc/el-gcp-region-provisioning-listener 8080:8080
```

## Test Methods

### Method 1: Using gcpctl CLI (Recommended)

```bash
cd <path-to-gcpctl>

# Build the CLI
go build -o gcpctl

# Trigger pipeline
./gcpctl region add -e integration -r us-central1 -s test

# Expected output:
# ✓ Pipeline triggered successfully!
#
# Event ID: 8694fbab-3b46-4143-bc7d-f28de10089f3
# Pipeline: gcp-region-provisioning-pipeline
#
# Monitor progress:
#   ./gcpctl region status 8694fbab-3b46-4143-bc7d-f28de10089f3
#   kubectl get pipelineruns -w

# Check status (wait 30-60 seconds for pipeline to start)
./gcpctl region status 8694fbab-3b46-4143-bc7d-f28de10089f3
```

### Method 2: Using curl

```bash
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d '{
    "environment": "integration",
    "region": "us-central1",
    "sector": "test"
  }'

# Expected response:
# {"eventListener":"gcp-region-provisioning-listener","namespace":"default","eventListenerUID":"...","eventID":"..."}
```

## Monitoring Pipeline Execution

### 1. List All Pipeline Runs

```bash
kubectl get pipelineruns

# Example output:
# NAME                              SUCCEEDED   REASON      STARTTIME   COMPLETIONTIME
# gcp-region-provision-8694fbab     Unknown     Running     2m
```

### 2. Watch Pipeline Progress

```bash
# Watch all pipeline runs
kubectl get pipelineruns -w

# Get detailed status of specific run
kubectl get pipelinerun gcp-region-provision-8694fbab -o yaml
```

### 3. Check Individual Task Status

The pipeline has 8 tasks:
1. `validate-inputs`
2. `create-directory-structure`
3. `generate-terraform-config`
4. `terraform-init`
5. `terraform-validate`
6. `terraform-plan`
7. `terraform-apply`
8. `commit-to-git`

```bash
# List all task runs for a pipeline
kubectl get taskruns -l tekton.dev/pipelineRun=gcp-region-provision-8694fbab

# Example output:
# NAME                                          SUCCEEDED   REASON      STARTTIME   COMPLETIONTIME
# gcp-region-provision-8694fbab-validate-inputs              True        Succeeded   3m          3m
# gcp-region-provision-8694fbab-create-directory-structure   True        Succeeded   3m          2m
# gcp-region-provision-8694fbab-generate-terraform-config    True        Succeeded   2m          2m
# gcp-region-provision-8694fbab-terraform-init               True        Succeeded   2m          1m
# gcp-region-provision-8694fbab-terraform-validate           True        Succeeded   1m          1m
# gcp-region-provision-8694fbab-terraform-plan               True        Succeeded   1m          30s
# gcp-region-provision-8694fbab-terraform-apply              Unknown     Running     30s
# gcp-region-provision-8694fbab-commit-to-git                False       Pending
```

### 4. View Logs for Specific Tasks

#### validate-inputs
```bash
kubectl logs -l tekton.dev/pipelineRun=gcp-region-provision-8694fbab \
  -l tekton.dev/pipelineTask=validate-inputs \
  -c step-validate

# Expected output:
# === Validating Input Parameters ===
# ✓ Environment: integration
# ✓ Region: us-central1
# ✓ Sector: test (4 chars)
# === All validations passed ===
```

#### create-directory-structure
```bash
kubectl logs -l tekton.dev/pipelineRun=gcp-region-provision-8694fbab \
  -l tekton.dev/pipelineTask=create-directory-structure \
  -c step-create-dirs

# Expected output:
# === Creating Directory Structure ===
# Creating directory: config/region/integration/test/us-central1
# ✓ Directory structure created successfully
```

#### generate-terraform-config
```bash
kubectl logs -l tekton.dev/pipelineRun=gcp-region-provision-8694fbab \
  -l tekton.dev/pipelineTask=generate-terraform-config \
  -c step-create-terraform-files

# Expected output:
# === Generating Terraform Configuration ===
# Creating directory: config/region/integration/test/us-central1
# ✓ Terraform files created:
# [shows main.tf and variables.tf]
```

#### terraform-init
```bash
kubectl logs -l tekton.dev/pipelineRun=gcp-region-provision-8694fbab \
  -l tekton.dev/pipelineTask=terraform-init \
  -c step-terraform

# Expected output:
# Initializing the backend...
# Initializing provider plugins...
# - Finding hashicorp/google versions matching "~> 5.0"...
# - Finding hashicorp/random versions matching "~> 3.5"...
# - Installing hashicorp/google v5.x.x...
# - Installing hashicorp/random v3.x.x...
# Terraform has been successfully initialized!
```

#### terraform-validate
```bash
kubectl logs -l tekton.dev/pipelineRun=gcp-region-provision-8694fbab \
  -l tekton.dev/pipelineTask=terraform-validate \
  -c step-terraform

# Expected output:
# Success! The configuration is valid.
```

#### terraform-plan
```bash
kubectl logs -l tekton.dev/pipelineRun=gcp-region-provision-8694fbab \
  -l tekton.dev/pipelineTask=terraform-plan \
  -c step-terraform

# Expected output:
# Terraform will perform the following actions:
#   # google_storage_bucket.test_bucket will be created
#   + resource "google_storage_bucket" "test_bucket" {
#       + name          = "tekton-test-integration-test-abc123de"
#       + location      = "us-central1"
#       ...
#   }
# Plan: 2 to add, 0 to change, 0 to destroy.
```

#### terraform-apply
```bash
kubectl logs -l tekton.dev/pipelineRun=gcp-region-provision-8694fbab \
  -l tekton.dev/pipelineTask=terraform-apply \
  -c step-terraform

# Expected output:
# google_storage_bucket.test_bucket: Creating...
# google_storage_bucket.test_bucket: Creation complete after 2s [id=tekton-test-integration-test-abc123de]
# Apply complete! Resources: 2 added, 0 changed, 0 destroyed.
# Outputs:
# bucket_name = "tekton-test-integration-test-abc123de"
# bucket_url = "gs://tekton-test-integration-test-abc123de"
```

#### commit-to-git
```bash
kubectl logs -l tekton.dev/pipelineRun=gcp-region-provision-8694fbab \
  -l tekton.dev/pipelineTask=commit-to-git \
  -c step-mock-git-commit

# Expected output:
# === Committing to Git (MOCK) ===
# Configuring git...
# ✓ Git user configured
# Staging changes...
# ✓ Changes staged
# Creating commit...
# ✓ Commit created [abc123def]
# Pushing to remote...
# ✓ Changes pushed to remote repository
# === Region Provisioning Complete ===
```

### 5. Get Complete Pipeline Logs

```bash
# Get logs from all tasks in pipeline
kubectl logs -l tekton.dev/pipelineRun=gcp-region-provision-8694fbab --all-containers

# Or use tkn CLI (if installed)
tkn pipelinerun logs gcp-region-provision-8694fbab -f
```

## Verifying Results

### 1. Check Pipeline Completion Status

```bash
# Using gcpctl
./gcpctl region status 8694fbab-3b46-4143-bc7d-f28de10089f3

# Using kubectl
kubectl get pipelinerun gcp-region-provision-8694fbab -o jsonpath='{.status.conditions[0].reason}'

# Expected: "Succeeded"
```

### 2. Verify GCS Bucket in Google Cloud

```bash
# List all buckets created by Tekton
gcloud storage buckets list --project=<YOUR-PROJECT-ID> | grep tekton-test

# Expected output:
# gs://tekton-test-integration-test-abc123de

# Get bucket details
gcloud storage buckets describe gs://tekton-test-integration-test-abc123de

# Expected output shows:
# - location: US-CENTRAL1
# - labels:
#     created_by: tekton
#     environment: integration
#     region: us-central1
#     sector: test
# - lifecycle rules: delete after 30 days
```

### 3. Verify in GCP Console

Visit: https://console.cloud.google.com/storage/browser?project=<YOUR-PROJECT-ID>

Look for bucket matching pattern: `tekton-test-{environment}-{sector}-{random}`

### 4. Check Workspace Contents

```bash
# Create a debug pod to inspect workspace
kubectl run -it --rm debug \
  --image=busybox \
  --overrides='{"spec":{"volumes":[{"name":"workspace","persistentVolumeClaim":{"claimName":"tekton-workspace-pvc"}}],"containers":[{"name":"debug","image":"busybox","command":["sh"],"volumeMounts":[{"name":"workspace","mountPath":"/workspace"}]}]}}' \
  -- sh

# Inside the pod:
ls -la /workspace/config/region/integration/test/us-central1/
# Should show: main.tf, variables.tf, .terraform/, terraform.tfstate, tfplan

cat /workspace/config/region/integration/test/us-central1/main.tf
# Should show the generated Terraform configuration

exit
```

## Testing Different Scenarios

### Test 1: Valid Environments

```bash
# Production
./gcpctl region add -e production -r us-east1 -s main

# Staging
./gcpctl region add -e staging -r europe-west1 -s canary

# Integration
./gcpctl region add -e integration -r asia-northeast1 -s test
```

### Test 2: Invalid Environment (Should Fail)

```bash
./gcpctl region add -e development -r us-central1 -s test

# Check logs - validate-inputs task should fail
kubectl logs -l tekton.dev/pipelineTask=validate-inputs -c step-validate

# Expected error:
# ✗ Invalid environment: development
#   Allowed values: production, staging, integration
```

### Test 3: Long Sector Name (Should Fail)

```bash
./gcpctl region add -e integration -r us-central1 -s this-is-a-very-long-sector-name-that-exceeds-forty-characters

# Check logs - validate-inputs task should fail
kubectl logs -l tekton.dev/pipelineTask=validate-inputs -c step-validate

# Expected error:
# ✗ Sector exceeds 40 characters: this-is-a-very-long-sector-name-that-exceeds-forty-characters (68 chars)
```

### Test 4: Different GCP Regions

```bash
# US regions
./gcpctl region add -e integration -r us-central1 -s test
./gcpctl region add -e integration -r us-east1 -s test
./gcpctl region add -e integration -r us-west1 -s test

# Europe regions
./gcpctl region add -e integration -r europe-west1 -s test
./gcpctl region add -e integration -r europe-north1 -s test

# Asia regions
./gcpctl region add -e integration -r asia-northeast1 -s test
./gcpctl region add -e integration -r asia-southeast1 -s test
```

## Cleanup

### Clean Up Test Buckets

```bash
# List all test buckets
gcloud storage buckets list --project=<YOUR-PROJECT-ID> | grep tekton-test

# Delete specific bucket
gcloud storage rm -r gs://tekton-test-integration-test-abc123de

# Delete all test buckets (USE WITH CAUTION)
gcloud storage buckets list --project=<YOUR-PROJECT-ID> --format="value(name)" | \
  grep tekton-test | \
  xargs -I {} gcloud storage rm -r gs://{}
```

### Clean Up Pipeline Runs

```bash
# Delete all pipeline runs
kubectl delete pipelineruns --all

# Delete specific pipeline run
kubectl delete pipelinerun gcp-region-provision-8694fbab

# Clean up completed runs older than 1 hour
kubectl get pipelineruns -o json | \
  jq -r '.items[] | select(.status.completionTime != null) | select((.status.completionTime | fromdateiso8601) < (now - 3600)) | .metadata.name' | \
  xargs kubectl delete pipelinerun
```

### Clean Up Workspace

```bash
# Delete and recreate PVC (removes all Terraform state)
kubectl delete pvc tekton-workspace-pvc
kubectl apply -f pvc.yaml
```

## Troubleshooting

### Pipeline Stuck in "Running" State

```bash
# Check which task is stuck
kubectl get taskruns -l tekton.dev/pipelineRun=gcp-region-provision-8694fbab

# View logs of stuck task
kubectl logs -l tekton.dev/pipelineTask=<task-name> --all-containers
```

### Terraform Authentication Errors

```bash
# Verify GCP credentials secret exists
kubectl get secret gcp-credentials -n default

# Check if credentials are valid
kubectl get secret gcp-credentials -o jsonpath='{.data.key\.json}' | base64 -d | jq .

# Verify service account has storage.admin role
gcloud projects get-iam-policy <YOUR-PROJECT-ID> \
  --flatten="bindings[].members" \
  --filter="bindings.members:tekton-deployer-local"
```

### Terraform Init Fails

```bash
# Check logs
kubectl logs -l tekton.dev/pipelineTask=terraform-init -c step-terraform

# Common issues:
# - Network connectivity (provider downloads)
# - Invalid Terraform syntax in generated main.tf
# - Missing GOOGLE_APPLICATION_CREDENTIALS env var
```

### Bucket Creation Fails

```bash
# Check terraform-apply logs
kubectl logs -l tekton.dev/pipelineTask=terraform-apply -c step-terraform

# Common issues:
# - Insufficient permissions (missing storage.admin role)
# - Bucket name already exists globally
# - Invalid region name
# - Project quota exceeded
```

### EventListener Not Accessible

```bash
# Check EventListener pod
kubectl get pods | grep el-gcp-region
kubectl logs -l eventlistener=gcp-region-provisioning-listener

# Verify service exists
kubectl get svc el-gcp-region-provisioning-listener

# Re-establish port forward
kubectl port-forward svc/el-gcp-region-provisioning-listener 8080:8080
```

## Success Criteria

A successful test should show:

1. ✅ Pipeline run completes with `SUCCEEDED` status
2. ✅ All 8 tasks complete successfully
3. ✅ GCS bucket created in Google Cloud with correct:
   - Name pattern: `tekton-test-{environment}-{sector}-{random}`
   - Location: Specified region
   - Labels: environment, sector, region, created_by
   - Lifecycle rule: 30-day auto-delete
4. ✅ Terraform state files created in workspace
5. ✅ gcpctl status command shows completion

## Performance Benchmarks

Expected task durations:
- `validate-inputs`: 5-10 seconds
- `create-directory-structure`: 5-10 seconds
- `generate-terraform-config`: 5-10 seconds
- `terraform-init`: 30-60 seconds (downloads providers)
- `terraform-validate`: 5-10 seconds
- `terraform-plan`: 10-20 seconds
- `terraform-apply`: 20-40 seconds (creates bucket in GCP)
- `commit-to-git`: 5-10 seconds

**Total pipeline duration**: 2-3 minutes

## Next Steps

After successful testing:

1. Set up remote Terraform backend (GCS bucket for state)
2. Add approval step between terraform-plan and terraform-apply
3. Implement actual Git commit/push (replace mock)
4. Add more GCP resources (VPC, subnets, firewall rules, etc.)
5. Set up notifications (Slack, email)
6. Implement drift detection pipeline
