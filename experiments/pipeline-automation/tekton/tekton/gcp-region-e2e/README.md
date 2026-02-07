# GCP Region E2E Testing Pipeline

Automated end-to-end testing pipeline for GCP Terraform configurations. This pipeline clones a Git repository, runs Terraform to provision infrastructure, executes E2E tests, and then tears down the infrastructure.

## Overview

This pipeline is designed to:
1. Clone the [hcp-gcp-terraform-example-1](https://github.com/jimdaga/hcp-gcp-terraform-example-1) repository
2. Run Terraform workflow (init, validate, plan, apply)
3. Execute E2E tests against the provisioned infrastructure
4. Clean up by destroying all created resources
5. Run automatically every night via CronJob

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    gcp-region-e2e-pipeline                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. git-clone                                                   │
│     └─> Clone github.com/jimdaga/hcp-gcp-terraform-example-1   │
│                                                                 │
│  2. terraform-init                                              │
│     └─> Initialize Terraform in specified directory            │
│                                                                 │
│  3. terraform-validate                                          │
│     └─> Validate Terraform configuration                       │
│                                                                 │
│  4. terraform-plan                                              │
│     └─> Create execution plan                                  │
│                                                                 │
│  5. terraform-apply                                             │
│     └─> Provision infrastructure in GCP                        │
│                                                                 │
│  6. run-e2e-tests                                               │
│     └─> Execute end-to-end tests (currently mocked)            │
│                                                                 │
│  7. terraform-destroy                                           │
│     └─> Tear down all infrastructure                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

### 1. Install Tekton Hub Tasks

This pipeline requires the `git-clone` task from Tekton Hub:

```bash
# Install git-clone task
tkn hub install task git-clone

# Verify installation
kubectl get task git-clone
```

### 2. Ensure terraform-gcp Task Exists

The pipeline uses the `terraform-gcp` task from the gcp-region-provision setup:

```bash
# Check if terraform-gcp task exists
kubectl get task terraform-gcp

# If not, install it
kubectl apply -f ../gcp-region-provision/k8s/terraform-gcp-task.yaml
```

### 3. GCP Authentication

Ensure GCP authentication is configured (required for Terraform):

```bash
cd ../gcp-region-provision/setup
./setup-local-gcp-auth.sh
./grant-storage-admin.sh
```

Verify the service account and secret exist:

```bash
kubectl get serviceaccount tekton-gcp-deployer
kubectl get secret gcp-credentials
```

## Installation

### Deploy the Pipeline

```bash
# Deploy the E2E pipeline
kubectl apply -f pipeline.yaml

# Verify pipeline created
kubectl get pipeline gcp-region-e2e-pipeline
```

### Deploy the Nightly CronJob (Optional)

```bash
# Deploy CronJob for nightly runs at 2 AM UTC
kubectl apply -f cronjob.yaml

# Verify CronJob created
kubectl get cronjob gcp-region-e2e-nightly

# View CronJob details
kubectl describe cronjob gcp-region-e2e-nightly
```

## Usage

### Method 1: Manual Trigger with Tekton CLI (Recommended)

```bash
# Trigger with default parameters
tkn pipeline start gcp-region-e2e-pipeline \
  --serviceaccount=tekton-gcp-deployer \
  --workspace name=shared-data,volumeClaimTemplateFile=- <<EOF
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
EOF

# Trigger with custom parameters
tkn pipeline start gcp-region-e2e-pipeline \
  --param terraform-dir=environments/prod/region/us-east1 \
  --param git-url=https://github.com/jimdaga/hcp-gcp-terraform-example-1 \
  --param git-revision=main \
  --serviceaccount=tekton-gcp-deployer \
  --workspace name=shared-data,volumeClaimTemplateFile=- <<EOF
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
EOF

# Follow logs in real-time
tkn pipeline start gcp-region-e2e-pipeline \
  --serviceaccount=tekton-gcp-deployer \
  --workspace name=shared-data,volumeClaimTemplateFile=- <<EOF
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
EOF \
  --showlog
```

### Method 2: Manual Trigger with kubectl

```bash
# Create the PipelineRun (NOTE: use 'create', not 'apply' due to generateName)
kubectl create -f pipelinerun.yaml

# Watch the pipeline run
kubectl get pipelineruns -w

# Get the generated name
PIPELINE_RUN=$(kubectl get pipelineruns -l trigger=manual --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')

# Follow logs
tkn pipelinerun logs $PIPELINE_RUN -f
```

**Note**: You must use `kubectl create` (not `kubectl apply`) because the manifest uses `generateName` which creates a unique name for each run.

### Method 3: Trigger from CronJob Manually

```bash
# Manually trigger the CronJob (don't wait for schedule)
kubectl create job --from=cronjob/gcp-region-e2e-nightly manual-trigger-$(date +%s)

# Watch the job
kubectl get jobs -w
```

## Parameters

The pipeline accepts the following parameters:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `terraform-dir` | Directory in the Git repo containing Terraform configs | `environments/int/region/us-central1` |
| `git-url` | Git repository URL to clone | `https://github.com/jimdaga/hcp-gcp-terraform-example-1` |
| `git-revision` | Git branch, tag, or commit SHA to checkout | `main` |

## Monitoring

### View Pipeline Runs

```bash
# List all pipeline runs
kubectl get pipelineruns

# List only nightly runs
kubectl get pipelineruns -l schedule=nightly

# List only manual runs
kubectl get pipelineruns -l trigger=manual

# Get detailed status
kubectl describe pipelinerun <pipelinerun-name>
```

### View Logs

```bash
# Using tkn CLI (recommended)
tkn pipelinerun logs <pipelinerun-name> -f

# View specific task logs
tkn pipelinerun logs <pipelinerun-name> -t git-clone
tkn pipelinerun logs <pipelinerun-name> -t terraform-init
tkn pipelinerun logs <pipelinerun-name> -t terraform-validate
tkn pipelinerun logs <pipelinerun-name> -t terraform-plan
tkn pipelinerun logs <pipelinerun-name> -t terraform-apply
tkn pipelinerun logs <pipelinerun-name> -t run-e2e-tests
tkn pipelinerun logs <pipelinerun-name> -t terraform-destroy

# Using kubectl
kubectl logs -l tekton.dev/pipelineRun=<pipelinerun-name> --all-containers
```

### View CronJob Status

```bash
# View CronJob details
kubectl get cronjob gcp-region-e2e-nightly

# View recent jobs triggered by CronJob
kubectl get jobs -l cronjob-name=gcp-region-e2e-nightly

# View CronJob execution history
kubectl describe cronjob gcp-region-e2e-nightly
```

## Customizing the Schedule

The default schedule is nightly at 2 AM UTC (`0 2 * * *`). To change it:

```bash
# Edit cronjob.yaml and modify the schedule field
# Cron format: minute hour day month weekday

# Examples:
# Every 6 hours:     "0 */6 * * *"
# Twice daily:       "0 2,14 * * *"
# Weekly (Sundays):  "0 2 * * 0"
# Weekdays only:     "0 2 * * 1-5"

# Apply the changes
kubectl apply -f cronjob.yaml
```

## Testing Different Environments

### Test Integration Environment (Default)

```bash
tkn pipeline start gcp-region-e2e-pipeline \
  --param terraform-dir=environments/int/region/us-central1 \
  --serviceaccount=tekton-gcp-deployer \
  --showlog
```

### Test Production Environment

```bash
tkn pipeline start gcp-region-e2e-pipeline \
  --param terraform-dir=environments/prod/region/us-east1 \
  --serviceaccount=tekton-gcp-deployer \
  --showlog
```

### Test Different Git Branch

```bash
tkn pipeline start gcp-region-e2e-pipeline \
  --param git-revision=feature/new-vpc-config \
  --serviceaccount=tekton-gcp-deployer \
  --showlog
```

## Cleanup

### Delete a Specific Pipeline Run

```bash
kubectl delete pipelinerun <pipelinerun-name>
```

### Delete All Pipeline Runs

```bash
kubectl delete pipelineruns -l pipeline=gcp-region-e2e-pipeline
```

### Delete Completed Pipeline Runs

```bash
kubectl get pipelineruns -o json | \
  jq -r '.items[] | select(.status.conditions[0].status == "True") | .metadata.name' | \
  xargs kubectl delete pipelinerun
```

### Suspend the Nightly CronJob

```bash
# Suspend (stop scheduling new runs)
kubectl patch cronjob gcp-region-e2e-nightly -p '{"spec":{"suspend":true}}'

# Resume
kubectl patch cronjob gcp-region-e2e-nightly -p '{"spec":{"suspend":false}}'
```

### Uninstall Everything

```bash
# Delete CronJob
kubectl delete cronjob gcp-region-e2e-nightly

# Delete all pipeline runs
kubectl delete pipelineruns -l pipeline=gcp-region-e2e-pipeline

# Delete pipeline
kubectl delete pipeline gcp-region-e2e-pipeline
```

## Troubleshooting

### Pipeline Fails at git-clone

```bash
# Check git-clone task logs
tkn pipelinerun logs <pipelinerun-name> -t git-clone

# Common issues:
# - Repository doesn't exist or is private
# - Network connectivity issues
# - Invalid git-revision parameter
```

### Pipeline Fails at Terraform Tasks

```bash
# Check specific Terraform task logs
tkn pipelinerun logs <pipelinerun-name> -t terraform-init

# Common issues:
# - Missing GCP credentials (check secret: gcp-credentials)
# - Insufficient permissions (check service account roles)
# - Invalid Terraform configuration in the specified directory
# - terraform-gcp task not installed
```

### Verify GCP Authentication

```bash
# Check if secret exists
kubectl get secret gcp-credentials

# Check if service account exists
kubectl get serviceaccount tekton-gcp-deployer

# Test GCP access from a pod
kubectl run -it --rm gcp-test \
  --image=google/cloud-sdk:slim \
  --serviceaccount=tekton-gcp-deployer \
  --overrides='{"spec":{"containers":[{"name":"gcp-test","image":"google/cloud-sdk:slim","command":["gcloud","auth","list"],"volumeMounts":[{"name":"gcp-creds","mountPath":"/var/secrets/gcp"}],"env":[{"name":"GOOGLE_APPLICATION_CREDENTIALS","value":"/var/secrets/gcp/key.json"}]}],"volumes":[{"name":"gcp-creds","secret":{"secretName":"gcp-credentials"}}]}}' \
  -- gcloud auth list
```

### CronJob Not Triggering

```bash
# Check CronJob status
kubectl get cronjob gcp-region-e2e-nightly

# Check if suspended
kubectl get cronjob gcp-region-e2e-nightly -o jsonpath='{.spec.suspend}'

# Check recent jobs
kubectl get jobs -l cronjob-name=gcp-region-e2e-nightly

# View CronJob events
kubectl describe cronjob gcp-region-e2e-nightly
```

### Infrastructure Not Destroyed

If `terraform-destroy` fails, you may need to manually clean up:

```bash
# List resources created in the test
gcloud compute instances list --project=<YOUR-PROJECT-ID>
gcloud storage buckets list --project=<YOUR-PROJECT-ID>

# Manually delete resources as needed
# Then check the terraform-destroy logs to understand why it failed
```

## Performance Expectations

Typical execution times:
- **git-clone**: 10-30 seconds (depends on repo size)
- **terraform-init**: 30-60 seconds (downloads providers)
- **terraform-validate**: 5-10 seconds
- **terraform-plan**: 10-30 seconds
- **terraform-apply**: 1-5 minutes (depends on resources)
- **run-e2e-tests**: Currently mocked (5-10 seconds)
- **terraform-destroy**: 1-5 minutes (depends on resources)

**Total Duration**: 3-10 minutes (depends on infrastructure complexity)

## Next Steps

### 1. Implement Real E2E Tests

Replace the mock E2E tests with actual tests:

```yaml
- name: run-e2e-tests
  steps:
    - name: run-tests
      image: your-test-image:latest
      script: |
        #!/bin/sh
        # Run your actual E2E test suite
        pytest tests/e2e/
        # or
        go test ./e2e/...
```

### 2. Add Notifications

Integrate with Slack or email for test results:

```bash
# Add a final task to send notifications
- name: notify
  runAfter:
    - terraform-destroy
  taskRef:
    name: send-to-slack
```

### 3. Add Approval Step

Add a manual approval between apply and destroy for debugging:

```yaml
- name: manual-approval
  runAfter:
    - run-e2e-tests
  taskRef:
    name: manual-approval
```

### 4. Parameterize More Options

Add more parameters for flexibility:
- GCP project ID
- Terraform backend configuration
- Test suite to run
- Destroy on failure vs. always destroy

## Files

- [pipeline.yaml](pipeline.yaml) - Main E2E pipeline definition
- [cronjob.yaml](cronjob.yaml) - Nightly scheduled execution
- [pipelinerun.yaml](pipelinerun.yaml) - Manual trigger template
- [README.md](README.md) - This file
