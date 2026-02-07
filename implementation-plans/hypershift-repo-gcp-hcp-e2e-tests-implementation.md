# GCP E2E Tests Configuration in the HyperShift Repository

## Overview

Configure end-to-end tests for the GCP platform in the HyperShift repository. These tests validate the **HyperShift GCP platform code** that enables managed OpenShift services on GCP.

> **Scope Note**: These tests validate the HyperShift operator's GCP platform implementation (WIF, PSC, CAPG integration, etc.). This is testing the code that powers the managed service, but NOT the managed service pipelines or gcp.redhat.com infrastructure itself. See [enhancement PR #1916](https://github.com/openshift/enhancements/pull/1916) for the full scope.

### Goals

- Prioritize generic conformance tests before GCP-specific functionality
- Follow an incremental approach to build up test coverage
- Keep provisioning scripts simple and generic to minimize flakiness

### Key Repositories

- **openshift/hypershift** - HyperShift operator and E2E test framework
- **openshift/release** - CI configuration, step registry, and cluster profiles

### E2E Test Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              PROW CI JOB EXECUTION                                  │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  PRE: Provision Infrastructure                                                      │
│─────────────────────────────────────────────────────────────────────────────────────│
│                                                                                     │
│  1. Acquire Boskos Lease (quota slot)                                               │
│                 │                                                                   │
│                 ▼                                                                   │
│  2. Mount GCP Credentials (CI SA that can create projects)                          │
│                 │                                                                   │
│                 ▼                                                                   │
│  3. Create Dynamic Projects (under CI folder)                                       │
│     `gcloud projects create ${INFRA_ID}-mgmt --folder=${CI_FOLDER_ID}`              │
│     `gcloud projects create ${INFRA_ID}-customer --folder=${CI_FOLDER_ID}`          │
│                 │                                                                   │
│                 ▼                                                                   │
│  ┌────────────────────────────────────┐    ┌────────────────────────────────────┐   │
│  │  MANAGEMENT PROJECT (dynamic)      │    │   CUSTOMER PROJECT (dynamic)       │   │
│  ├────────────────────────────────────┤    ├────────────────────────────────────┤   │
│  │                                    │    │                                    │   │
│  │  4. Create GKE Autopilot Cluster   │    │  6. Create IAM (WIF)               │   │
│  │     - VPC + PSC subnet             │    │     `hypershift create iam gcp`    │   │
│  │     - Cloud Router + NAT           │    │     - WIF Pool + OIDC Provider     │   │
│  │     - Autopilot (managed nodes)    │    │     - GSAs for controllers         │   │
│  │              │                     │    │              │                     │   │
│  │              ▼                     │    │              ▼                     │   │
│  │  5. Install HyperShift Operator    │───▶│  7. Create Network Infra           │   │
│  │     `hypershift install`           │    │     `hypershift create infra gcp`  │   │
│  │     --platform-type GCP            │    │     - VPC, Subnet, Router, NAT     │   │
│  │                                    │    │     - Firewall rules               │   │
│  └────────────────────────────────────┘    └────────────────────────────────────┘   │
│                                                              │                      │
└──────────────────────────────────────────────────────────────┼──────────────────────┘
                                                               │
                                                               ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  TEST: Execute E2E Tests                                                            │
│─────────────────────────────────────────────────────────────────────────────────────│
│                                                                                     │
│  8. Run E2E Test Suite (each test manages its own cluster lifecycle)                │
│                                                                                     │
│     TestCreateCluster_GCP:                                                          │
│       a. Create Hosted Cluster (`hypershift create cluster gcp`)                    │
│       b. Wait for cluster ready, run validations                                    │
│       c. Delete cluster (`hypershift destroy cluster gcp`)                          │
│       d. Verify deletion complete (HC CR gone, no resources remain)                 │
│                                                                                     │
│     TestNodePool_GCP, TestPSC_GCP, etc. follow same pattern                         │
│                                                              │                      │
└──────────────────────────────────────────────────────────────┼──────────────────────┘
                                                               │
                                                               ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  POST: Cleanup (safety net if tests fail or crash)                                  │
│─────────────────────────────────────────────────────────────────────────────────────│
│                                                                                     │
│  9. Gather Artifacts (logs, manifests, events)                                      │
│                 │                                                                   │
│                 ▼                                                                   │
│  10. Delete any remaining Hosted Clusters                                           │
│      `hypershift destroy cluster gcp --name=${CLUSTER_NAME}`                        │
│                 │                                                                   │
│                 ▼                                                                   │
│  11. Delete Management Cluster                                                      │
│      `gcloud container clusters delete ${CLUSTER_NAME} --quiet`                     │
│                 │                                                                   │
│                 ▼                                                                   │
│  12. Delete Dynamic Projects (all remaining resources deleted with projects)        │
│      `gcloud projects delete ${INFRA_ID}-customer --quiet`                          │
│      `gcloud projects delete ${INFRA_ID}-mgmt --quiet`                              │
│                 │                                                                   │
│                 ▼                                                                   │
│  13. Release Boskos Lease                                                           │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

**Benefits of Dynamic Projects**:
- Complete isolation between test runs (no resource leaks)
- Bounded cleanup scope (resources confined to per-test projects)
- Parallel tests don't interfere with each other
- Mirrors production flow (customers get their own projects)

---

## Epic: GCP E2E Tests Configuration

**Summary**: Configure end-to-end tests for GCP hosted clusters in the HyperShift repository

**Acceptance Criteria**:
- [ ] GCP cluster creation and deletion can be tested automatically
- [ ] CI jobs run on PR changes affecting GCP code paths
- [ ] Test artifacts are collected and accessible for debugging
- [ ] Documentation exists for test infrastructure and debugging

---

## Implementation Stories

### Story 1: Finalize CI Infrastructure Decisions

**Summary**: Resolve open questions blocking CI infrastructure implementation

**Description**:
Before implementing the CI infrastructure, we need team decisions on several architectural choices. This story captures the remaining investigation items that require discussion.

**Resolved Investigation Items**:
- [x] How to request GCP credentials for CI → Self-service via Vault. See [Adding a New Secret to CI](https://docs.ci.openshift.org/docs/how-tos/adding-a-new-secret-to-ci/).
- [x] Hosted cluster credential strategy → Two-project architecture. See Appendix G.
- [x] Investigate `hypershift infra gcp` credential requirements → Uses ADC, creates WIF in customer project. See Appendix G.
- [x] Required GCP IAM roles and permissions → See Appendix G for complete IAM roles table.
- [x] Quota requirements for running E2E tests → Standard quotas sufficient. GCP-HCP team will set appropriate limits during project setup.
- [x] GCP Project Creation → Dynamic projects per-test. CI infrastructure (folder, project, SA) via Terraform in `gcp-hcp-infra`. See Story 2 and Appendix G.
- [x] CI Authentication Method → **Service Account with static credentials**. Matches existing OpenShift CI patterns for AWS/Azure.
- [x] Cluster Profile → **Dedicated `hypershift-gcp` profile** with own quota slice. GCP tests won't use resources from AWS-based hypershift-ci cluster.

**Reference**:
- [Cluster Profile Documentation](https://docs.ci.openshift.org/docs/how-tos/adding-a-cluster-profile/)
- [Adding a New Secret to CI](https://docs.ci.openshift.org/docs/how-tos/adding-a-new-secret-to-ci/) - Self-service Vault portal
- Appendix D: Quota Slices and Cluster Profiles
- Appendix G: GCP Dynamic Project Architecture

**Acceptance Criteria**:
- [x] All investigation items resolved

---

### Story 2: CI Infrastructure Setup (Dynamic Projects)

**Summary**: Create CI folder, service account with project creator permissions, and store credentials in Vault

**Description**:
Set up the GCP infrastructure for dynamic project creation. Each E2E test run will create its own management and customer projects under a dedicated CI folder, ensuring complete isolation between tests.

**Tasks**:
1. **Create CI Folder** (manual, following GCP HCP Commons pattern):
   - [ ] Create folder `gcp-hcp-ci` under the GCP HCP folder (`405445313657`) via GCP Console or gcloud
   - [ ] Note the folder ID for use in Terraform
   - [ ] This folder will contain all dynamically-created test projects

2. **Create Terraform module for CI infrastructure** (in `gcp-hcp-infra` repo):
   - [ ] Create `terraform/modules/ci/` following the commons module pattern
   - [ ] Accept `ci_folder_id` as input variable (same pattern as `commons_folder_id`)
   - [ ] Use `terraform-google-modules/project-factory/google` to create CI project
   - [ ] Create CI service account with direct folder-level permissions (not impersonation)
   - [ ] Output SA key for Vault storage

   > **Note**: GCP doesn't have per-folder project limits. Concurrency control is via Boskos quota slices (e.g., 50 slots = max ~100 concurrent projects).

3. **CI Service Account** (created by Terraform module):
   - [ ] Service account `hypershift-ci@<ci-project>.iam.gserviceaccount.com`
   - [ ] **Direct permissions on CI folder only** (for complete isolation from managed service):
     - `roles/resourcemanager.projectCreator` on CI folder
     - `roles/resourcemanager.projectDeleter` on CI folder
     - `roles/billing.user` via billing group membership
   - [ ] Generate service account key (JSON)
   - [ ] **Note**: Does NOT impersonate `project-creator` - ensures CI cannot affect managed service projects

4. **Store Credentials in Vault**:
   - [ ] Create secret collection in Vault
   - [ ] Log in to Vault with OIDC
   - [ ] Create secret with required `secretsync` metadata:
     ```
     secretsync/target-namespace: "test-credentials"
     secretsync/target-name: "hypershift-ci-jobs-gcpcreds"
     credentials.json: <SA key JSON>
     ci-folder-id: <folder-id>
     billing-account-id: <billing-account-id>
     ```
   - [ ] Verify secret syncs to build clusters (~30 minutes)

**Reference**:
- [Adding a New Secret to CI](https://docs.ci.openshift.org/docs/how-tos/adding-a-new-secret-to-ci/)
- Existing `project-creator` SA: `gcp-hcp-infra/terraform/modules/commons/service-accounts.tf`
- Appendix G: GCP Dynamic Project Architecture

**Acceptance Criteria**:
- [ ] CI folder created under GCP HCP organization
- [ ] CI project created to host CI service account
- [ ] CI service account can create/delete projects in CI folder
- [ ] Secret `hypershift-ci-jobs-gcpcreds` available in `test-credentials` namespace

---

### Story 3: Create Cluster Profile

**Summary**: Register the `hypershift-gcp` cluster profile in CI infrastructure with private access controls

**Description**:
Create and configure the cluster profile that CI jobs will use. The profile must be registered in ci-tools, configured in openshift/release with Boskos quota slices, and marked as private to prevent unauthorized usage.

**Prerequisites**: Story 2 (credentials available in Vault)

**Tasks**:

1. **Register profile in ci-tools** (PR to `openshift/ci-tools`):
   - [ ] Add `ClusterProfileHypershiftGCP` constant to `pkg/api/types.go`
   - [ ] Add to `ClusterProfiles()` list of valid profiles
   - [ ] Map profile to cluster type in `ClusterProfile::ClusterType()`
   - [ ] Map profile to lease type in `ClusterProfile::LeaseType()` → `hypershift-gcp-quota-slice`

2. **Configure Boskos quota slice** (PR to `openshift/release`):
   - [ ] Add quota slice in `core-services/prow/02_config/_boskos.yaml`:
     ```yaml
     - type: hypershift-gcp-quota-slice
       state: free
       min-count: 10  # Start conservative, increase based on usage
       max-count: 10
     ```

3. **Configure ci-secret-bootstrap** (PR to `openshift/release`):
   - [ ] Add configuration linking Vault secret to cluster profile
   - [ ] Ensure `hypershift-ci-jobs-gcpcreds` is accessible to the profile

4. **Configure as private profile** (PR to `openshift/release`):
   - [ ] Add to `ci-operator/step-registry/cluster-profiles/cluster-profiles-config.yaml`:
     ```yaml
     - profile: hypershift-gcp
       owners:
         - org: openshift
           repos:
             - hypershift
     ```

> **Security Note**: The private profile configuration ensures only `openshift/hypershift` can use these GCP credentials. Without this, any repository could reference `cluster_profile: hypershift-gcp` and use the SA with project creation permissions.

**Reference**:
- [Adding a Cluster Profile](https://docs.ci.openshift.org/docs/how-tos/adding-a-cluster-profile/)
- [Private Cluster Profiles](https://docs.ci.openshift.org/docs/how-tos/adding-a-cluster-profile/#private-cluster-profiles)

**Acceptance Criteria**:
- [ ] Cluster profile `hypershift-gcp` registered in ci-tools
- [ ] Quota slice `hypershift-gcp-quota-slice` configured in Boskos
- [ ] Cluster profile configured as private (restricted to `openshift/hypershift`)
- [ ] CI jobs can reference `cluster_profile: hypershift-gcp`

---

### Story 4: GKE Provision/Deprovision Steps

**Summary**: Create step registry entries for GKE management cluster lifecycle

**Description**:
Create the step registry entries in `openshift/release` for provisioning and deprovisioning the GKE management cluster, following the AKS pattern.

**Prerequisites**: Story 2 (credentials available in Vault)

**Reference**: AKS management cluster provisioning pattern:
```
ci-operator/step-registry/aks/              # openshift/release
├── OWNERS
├── provision/
│   ├── aks-provision-ref.yaml              # Step definition with credentials mount
│   └── aks-provision-commands.sh           # Provision script
└── deprovision/
    ├── aks-deprovision-ref.yaml
    └── aks-deprovision-commands.sh
```

**Deliverables**:

1. **Step Registry Structure** (`ci-operator/step-registry/hypershift-gcp/`):
   ```
   ci-operator/step-registry/hypershift-gcp/
   ├── OWNERS
   ├── provision/
   │   ├── gke-provision-ref.yaml
   │   └── gke-provision-commands.sh
   └── deprovision/
       ├── gke-deprovision-ref.yaml
       └── gke-deprovision-commands.sh
   ```

2. **Provision Step** (`gke-provision-ref.yaml`, `gke-provision-commands.sh`)
3. **Deprovision Step** (`gke-deprovision-ref.yaml`, `gke-deprovision-commands.sh`)

**Management Cluster Provisioning Approach**:

Follow the AKS pattern: provision a GKE-based management cluster per-test using simple `gcloud` commands (not Terraform). This keeps scripts simple and generic, reducing flakiness.

**Step Registry Reference** (`gke-provision-ref.yaml`) - following AKS pattern:
```yaml
ref:
  as: gke-provision
  from_image:
    namespace: ocp
    name: "4.16"
    tag: upi-installer
  commands: gke-provision-commands.sh
  resources:
    requests:
      cpu: 100m
      memory: 100Mi
  timeout: 30m0s
  grace_period: 10m0s
  env:
  - name: GKE_REGION
    default: "us-central1"
    documentation: GCP region for the GKE cluster.
  credentials:
    - mount_path: /etc/hypershift-ci-jobs-gcpcreds
      name: hypershift-ci-jobs-gcpcreds
      namespace: test-credentials
  documentation: |-
    This step provisions a GKE cluster for use as a HyperShift management cluster.
    Follows pattern from ci-operator/step-registry/aks/provision/.
```

**Provision Step** (`gke-provision-commands.sh`):
```bash
#!/usr/bin/env bash
set -euo pipefail

# Load GCP credentials from mounted secret
GCP_CREDS_FILE="/etc/hypershift-ci-jobs-gcpcreds/credentials.json"
CI_FOLDER_ID="$(<"/etc/hypershift-ci-jobs-gcpcreds/ci-folder-id")"
BILLING_ACCOUNT_ID="$(<"/etc/hypershift-ci-jobs-gcpcreds/billing-account-id")"
GCP_REGION="${GKE_REGION:-${LEASED_RESOURCE:-us-central1}}"

# Authenticate with GCP
gcloud auth activate-service-account --key-file="${GCP_CREDS_FILE}"

gcloud --version
set -x

# Generate unique resource name prefix (following AKS pattern)
RESOURCE_NAME_PREFIX="${NAMESPACE}-${UNIQUE_HASH}"
CLUSTER_NAME="${RESOURCE_NAME_PREFIX}-gke"
INFRA_ID="${RESOURCE_NAME_PREFIX}"
PSC_SUBNET="${INFRA_ID}-psc"

# Dynamic project IDs (created per-test)
MGMT_PROJECT_ID="${INFRA_ID}-mgmt"
CUSTOMER_PROJECT_ID="${INFRA_ID}-cust"

# ============================================================================
# Step 1: Create Dynamic Projects (under CI folder)
# ============================================================================
echo "Creating management project: ${MGMT_PROJECT_ID}"
gcloud projects create "${MGMT_PROJECT_ID}" \
    --folder="${CI_FOLDER_ID}" \
    --quiet

echo "Creating customer project: ${CUSTOMER_PROJECT_ID}"
gcloud projects create "${CUSTOMER_PROJECT_ID}" \
    --folder="${CI_FOLDER_ID}" \
    --quiet

# Link projects to billing account
echo "Linking projects to billing account"
gcloud billing projects link "${MGMT_PROJECT_ID}" \
    --billing-account="${BILLING_ACCOUNT_ID}"
gcloud billing projects link "${CUSTOMER_PROJECT_ID}" \
    --billing-account="${BILLING_ACCOUNT_ID}"

# Enable required APIs in management project
echo "Enabling APIs in management project"
gcloud services enable container.googleapis.com compute.googleapis.com \
    --project="${MGMT_PROJECT_ID}"

# Enable required APIs in customer project
echo "Enabling APIs in customer project"
gcloud services enable compute.googleapis.com dns.googleapis.com iam.googleapis.com \
    iamcredentials.googleapis.com cloudresourcemanager.googleapis.com \
    --project="${CUSTOMER_PROJECT_ID}"

# Wait for API enablement to propagate
echo "Waiting for API enablement to propagate..."
sleep 30

gcloud config set project "${MGMT_PROJECT_ID}"

# ============================================================================
# Step 2: Create VPC and networking in management project
# ============================================================================
echo "Creating VPC in management project"
gcloud compute networks create "${INFRA_ID}-vpc" \
    --project="${MGMT_PROJECT_ID}" \
    --subnet-mode=auto \
    --quiet

echo "Creating Cloud Router and NAT"
gcloud compute routers create "${INFRA_ID}-router" \
    --project="${MGMT_PROJECT_ID}" \
    --region="${GCP_REGION}" \
    --network="${INFRA_ID}-vpc" \
    --quiet

gcloud compute routers nats create "${INFRA_ID}-nat" \
    --project="${MGMT_PROJECT_ID}" \
    --region="${GCP_REGION}" \
    --router="${INFRA_ID}-router" \
    --nat-all-subnet-ip-ranges \
    --auto-allocate-nat-external-ips \
    --quiet

# ============================================================================
# Step 3: Add PSC Subnet to VPC (for Service Attachments)
# ============================================================================
echo "Creating PSC subnet: ${PSC_SUBNET}"
gcloud compute networks subnets create "${PSC_SUBNET}" \
    --project="${MGMT_PROJECT_ID}" \
    --region="${GCP_REGION}" \
    --network="${INFRA_ID}-vpc" \
    --range="10.3.0.0/24" \
    --purpose=PRIVATE_SERVICE_CONNECT \
    --quiet

# ============================================================================
# Step 4: Create GKE Autopilot Cluster
# ============================================================================
echo "Creating GKE Autopilot cluster: ${CLUSTER_NAME}"
gcloud container clusters create-auto "${CLUSTER_NAME}" \
    --project="${MGMT_PROJECT_ID}" \
    --region="${GCP_REGION}" \
    --network="${INFRA_ID}-vpc" \
    --release-channel=stable \
    --quiet

echo "Waiting for GKE cluster to be ready"
gcloud container clusters describe "${CLUSTER_NAME}" \
    --project="${MGMT_PROJECT_ID}" \
    --region="${GCP_REGION}" \
    --format="value(status)" | grep -q "RUNNING"

echo "Getting kubeconfig"
export KUBECONFIG="${SHARED_DIR}/kubeconfig"
gcloud container clusters get-credentials "${CLUSTER_NAME}" \
    --project="${MGMT_PROJECT_ID}" \
    --region="${GCP_REGION}"

# Save cluster info for deprovision step
echo "${CLUSTER_NAME}" > "${SHARED_DIR}/cluster-name"
echo "${MGMT_PROJECT_ID}" > "${SHARED_DIR}/mgmt-project-id"
echo "${CUSTOMER_PROJECT_ID}" > "${SHARED_DIR}/customer-project-id"
echo "${GCP_REGION}" > "${SHARED_DIR}/gcp-region"
echo "${INFRA_ID}" > "${SHARED_DIR}/infra-id"
echo "${PSC_SUBNET}" > "${SHARED_DIR}/psc-subnet"

# Verify cluster access
oc get nodes
oc version

# ============================================================================
# Step 5: Install HyperShift operator
# ============================================================================
echo "Installing HyperShift operator"
hypershift install \
    --platform-type GCP \
    --private-platform GCP \
    --external-dns-provider google \
    --external-dns-domain-filter dummy \
    --tech-preview-no-upgrade

# Wait for operator to be ready
kubectl wait --for=condition=Available deployment/operator -n hypershift --timeout=300s

# ============================================================================
# Step 6: Create IAM resources (WIF) in customer project
# ============================================================================
echo "Creating IAM resources in customer project"
hypershift create iam gcp \
    --infra-id="${INFRA_ID}" \
    --project-id="${CUSTOMER_PROJECT_ID}" \
    --output-file="${SHARED_DIR}/iam-output.json"

# ============================================================================
# Step 7: Create network infrastructure in customer project
# ============================================================================
echo "Creating network infrastructure in customer project"
hypershift create infra gcp \
    --infra-id="${INFRA_ID}" \
    --project-id="${CUSTOMER_PROJECT_ID}" \
    --region="${GCP_REGION}" \
    --output-file="${SHARED_DIR}/infra-output.json"

# Parse outputs and save for E2E step
cat > "${SHARED_DIR}/e2e-env.sh" << EOF
export MGMT_PROJECT_ID="${MGMT_PROJECT_ID}"
export CUSTOMER_PROJECT_ID="${CUSTOMER_PROJECT_ID}"
export GCP_REGION="${GCP_REGION}"
export GCP_PROJECT_NUMBER=$(jq -r '.projectNumber' "${SHARED_DIR}/iam-output.json")
export GCP_WIF_POOL_ID=$(jq -r '.workloadIdentityPool.poolId' "${SHARED_DIR}/iam-output.json")
export GCP_WIF_PROVIDER_ID=$(jq -r '.workloadIdentityPool.providerId' "${SHARED_DIR}/iam-output.json")
export GCP_NODEPOOL_SA=$(jq -r '.serviceAccounts["nodepool-mgmt"]' "${SHARED_DIR}/iam-output.json")
export GCP_CTRLPLANE_SA=$(jq -r '.serviceAccounts["ctrlplane-op"]' "${SHARED_DIR}/iam-output.json")
export GCP_NETWORK=$(jq -r '.network' "${SHARED_DIR}/infra-output.json")
export GCP_SUBNET=$(jq -r '.subnet' "${SHARED_DIR}/infra-output.json")
export PSC_SUBNET="${PSC_SUBNET}"
export INFRA_ID="${INFRA_ID}"
EOF

echo "GKE management cluster provisioned successfully"
```

**Deprovision Step** (`gke-deprovision-commands.sh`):
```bash
#!/usr/bin/env bash
set -euo pipefail

# Load GCP credentials
GCP_CREDS_FILE="/etc/hypershift-ci-jobs-gcpcreds/credentials.json"
gcloud auth activate-service-account --key-file="${GCP_CREDS_FILE}"

# Load cluster info from provision step
MGMT_PROJECT_ID="$(<"${SHARED_DIR}/mgmt-project-id")"
CUSTOMER_PROJECT_ID="$(<"${SHARED_DIR}/customer-project-id")"
CLUSTER_NAME="$(<"${SHARED_DIR}/cluster-name")"
GCP_REGION="$(<"${SHARED_DIR}/gcp-region")"
INFRA_ID="$(<"${SHARED_DIR}/infra-id")"

set -x

# ============================================================================
# IMPORTANT: Some resources can block or survive project deletion.
# We must explicitly delete these resources before deleting the projects.
# Resources that can block deletion: VPC with active connections, GKE clusters
# Resources that may survive: Billing data, audit logs (retained by policy)
# ============================================================================

# ----------------------------------------------------------------------------
# Step 1: Delete GKE cluster (blocks project deletion if running)
# ----------------------------------------------------------------------------
echo "Deleting GKE management cluster: ${CLUSTER_NAME}"
gcloud container clusters delete "${CLUSTER_NAME}" \
    --project="${MGMT_PROJECT_ID}" \
    --region="${GCP_REGION}" \
    --quiet || true

# Wait for GKE deletion to propagate
echo "Waiting for GKE cluster deletion to complete..."
for i in {1..30}; do
    if ! gcloud container clusters describe "${CLUSTER_NAME}" \
        --project="${MGMT_PROJECT_ID}" \
        --region="${GCP_REGION}" 2>/dev/null; then
        echo "GKE cluster deleted successfully"
        break
    fi
    echo "Waiting for GKE cluster deletion... (attempt $i/30)"
    sleep 10
done

# ----------------------------------------------------------------------------
# Step 2: Delete VPC resources (can block project deletion)
# VPC deletion order: firewall rules → routes → subnets → routers → VPC
# ----------------------------------------------------------------------------
echo "Cleaning up VPC resources in management project..."

# Delete firewall rules
echo "Deleting firewall rules..."
for fw in $(gcloud compute firewall-rules list --project="${MGMT_PROJECT_ID}" \
    --format="value(name)" 2>/dev/null); do
    echo "Deleting firewall rule: ${fw}"
    gcloud compute firewall-rules delete "${fw}" \
        --project="${MGMT_PROJECT_ID}" --quiet || true
done

# Delete Cloud NAT
echo "Deleting Cloud NAT..."
gcloud compute routers nats delete "${INFRA_ID}-nat" \
    --router="${INFRA_ID}-router" \
    --region="${GCP_REGION}" \
    --project="${MGMT_PROJECT_ID}" \
    --quiet || true

# Delete Cloud Router
echo "Deleting Cloud Router..."
gcloud compute routers delete "${INFRA_ID}-router" \
    --region="${GCP_REGION}" \
    --project="${MGMT_PROJECT_ID}" \
    --quiet || true

# Delete subnets (including PSC subnet)
echo "Deleting subnets..."
for subnet in $(gcloud compute networks subnets list --project="${MGMT_PROJECT_ID}" \
    --filter="network~${INFRA_ID}-vpc" --format="value(name,region)" 2>/dev/null); do
    subnet_name=$(echo "$subnet" | cut -f1)
    subnet_region=$(echo "$subnet" | cut -f2)
    echo "Deleting subnet: ${subnet_name}"
    gcloud compute networks subnets delete "${subnet_name}" \
        --region="${subnet_region}" \
        --project="${MGMT_PROJECT_ID}" \
        --quiet || true
done

# Delete VPC network
echo "Deleting VPC network..."
gcloud compute networks delete "${INFRA_ID}-vpc" \
    --project="${MGMT_PROJECT_ID}" \
    --quiet || true

# ----------------------------------------------------------------------------
# Step 3: Clean up customer project resources
# ----------------------------------------------------------------------------
echo "Cleaning up customer project resources..."

# Delete VPC resources created by hypershift create infra gcp
for fw in $(gcloud compute firewall-rules list --project="${CUSTOMER_PROJECT_ID}" \
    --format="value(name)" 2>/dev/null); do
    gcloud compute firewall-rules delete "${fw}" \
        --project="${CUSTOMER_PROJECT_ID}" --quiet || true
done

for router in $(gcloud compute routers list --project="${CUSTOMER_PROJECT_ID}" \
    --format="value(name,region)" 2>/dev/null); do
    router_name=$(echo "$router" | cut -f1)
    router_region=$(echo "$router" | cut -f2)
    # Delete NATs first
    for nat in $(gcloud compute routers nats list --router="${router_name}" \
        --region="${router_region}" --project="${CUSTOMER_PROJECT_ID}" \
        --format="value(name)" 2>/dev/null); do
        gcloud compute routers nats delete "${nat}" \
            --router="${router_name}" --region="${router_region}" \
            --project="${CUSTOMER_PROJECT_ID}" --quiet || true
    done
    gcloud compute routers delete "${router_name}" \
        --region="${router_region}" \
        --project="${CUSTOMER_PROJECT_ID}" --quiet || true
done

for subnet in $(gcloud compute networks subnets list --project="${CUSTOMER_PROJECT_ID}" \
    --format="value(name,region)" 2>/dev/null); do
    subnet_name=$(echo "$subnet" | cut -f1)
    subnet_region=$(echo "$subnet" | cut -f2)
    gcloud compute networks subnets delete "${subnet_name}" \
        --region="${subnet_region}" \
        --project="${CUSTOMER_PROJECT_ID}" --quiet || true
done

for vpc in $(gcloud compute networks list --project="${CUSTOMER_PROJECT_ID}" \
    --format="value(name)" 2>/dev/null); do
    gcloud compute networks delete "${vpc}" \
        --project="${CUSTOMER_PROJECT_ID}" --quiet || true
done

# ----------------------------------------------------------------------------
# Step 4: Delete projects (now safe after explicit resource cleanup)
# ----------------------------------------------------------------------------
echo "Deleting customer project: ${CUSTOMER_PROJECT_ID}"
gcloud projects delete "${CUSTOMER_PROJECT_ID}" --quiet || true

echo "Deleting management project: ${MGMT_PROJECT_ID}"
gcloud projects delete "${MGMT_PROJECT_ID}" --quiet || true

echo "Cleanup complete"
```

**WIF Infrastructure Created by `hypershift infra gcp`**:

| Resource | Naming Convention | Purpose |
| -------- | ----------------- | ------- |
| WIF Pool | `{infraID}-wi-pool` | Workload Identity Pool for the cluster |
| OIDC Provider | `{infraID}-k8s-provider` | Links K8s OIDC issuer to GCP IAM |
| GSA: nodepool-mgmt | `{infraID}-nodepool-mgmt@{project}.iam.gserviceaccount.com` | CAPG controller (compute.instanceAdmin, networkAdmin) |
| GSA: ctrlplane-op | `{infraID}-ctrlplane-op@{project}.iam.gserviceaccount.com` | Control Plane Operator (dns.admin, networkAdmin) |

The `hypershift infra gcp` command outputs a JSON file (`CreateIAMOutput`) containing all WIF configuration. See `openshift/hypershift/cmd/infra/gcp/create_iam.go` for implementation details and `cmd/infra/gcp/iam-bindings.json` for service account role definitions.

**Why not Terraform?**:
- Simple `gcloud` commands are sufficient for MC provisioning
- Avoids Terraform state management complexity
- Reduces dependencies in CI environment
- Aligns with existing patterns in Hypershift CI

**Acceptance Criteria**:
- [ ] `gke-provision-ref.yaml` passes CI validation
- [ ] `gke-provision-commands.sh` passes shellcheck
- [ ] `gke-deprovision-ref.yaml` passes CI validation
- [ ] `gke-deprovision-commands.sh` passes shellcheck
- [ ] Steps can be rehearsed with `pj-rehearse`

---

### Story 5: E2E Workflow and CI Configuration

**Summary**: Create workflow definition and CI operator configuration for GCP E2E tests

**Description**:
Create the workflow that orchestrates the E2E test execution and configure the CI operator to run GCP tests on the HyperShift repository.

**Prerequisites**: Story 4 (provision/deprovision steps available)

**Deliverables**:

1. **Step Registry Structure** (additional steps):
   ```
   ci-operator/step-registry/hypershift-gcp/
   ├── e2e/
   │   ├── hypershift-gcp-e2e-ref.yaml
   │   └── hypershift-gcp-e2e-commands.sh
   └── gather/
       ├── hypershift-gcp-gather-ref.yaml
       └── hypershift-gcp-gather-commands.sh
   ```

2. **Workflow Definition** (`hypershift-gcp-e2e-workflow.yaml`):
   ```yaml
   workflow:
     as: hypershift-gcp-e2e
     steps:
       pre:
         - chain: hypershift-gcp-provision
       test:
         - ref: hypershift-gcp-e2e
       post:
         - ref: hypershift-gcp-gather
         - ref: hypershift-gcp-deprovision
   ```

3. **CI Operator Config** (`ci-operator/config/openshift/hypershift/openshift-hypershift-main.yaml`):
   - [ ] Add GCP E2E test job configuration
   - [ ] Configure `run_if_changed` patterns for GCP code paths
   - [ ] Set resource limits (recommend: 4Gi memory, 8 CPU based on ARO HCP)

4. **E2E Tools Image** (optional):
   - [ ] Build image with `gcloud` CLI, `kubectl`, and test tooling
   - [ ] Similar to ARO HCP's `aro-hcp-e2e-tools` image

**Cost Estimation and Controls**:

| Resource | Per-Test Cost (Est.) | Notes |
| -------- | -------------------- | ----- |
| GKE Autopilot Management Cluster | <cost-estimate> | Billed per pod resource usage, ~10-15 min runtime |
| Hosted Cluster nodes | <cost-estimate> | Depends on test scenario |
| Cloud DNS zones | <cost-estimate> | Usually 1-2 zones per test |
| Network egress | Minimal | Intra-region traffic |
| **Estimated per-test cost** | **<cost-estimate>** | Autopilot trades cost for operational simplicity |

**Cost Controls**:
> Note: Concurrency control is via Boskos quota slices. GCP has a dedicated `hypershift-gcp-quota-slice` (Option A chosen). GCP doesn't support per-folder project limits.

- [ ] Auto-delete test artifacts from GCS after 30 days
- [ ] Set monthly budget alert at <budget-threshold>
- [ ] Monitor for orphaned projects (projects older than 4 hours in CI folder)

**Acceptance Criteria**:
- [ ] Workflow definition passes CI validation
- [ ] E2E and gather steps pass validation
- [ ] CI operator config generates valid Prow job
- [ ] Job can be triggered via `/test e2e-gcp` on PRs

---

### Story 6: Add GCP Platform Support to E2E Test Framework

**Summary**: Add GCP platform flags and options to E2E test framework

**Description**:
Add GCP-specific command-line flags to `test/e2e/e2e_test.go` and platform options to `test/e2e/util/options.go` following the pattern used by AWS, Azure, and other platforms.

> **Current State (as of Dec 2025)**: GCP is NOT yet integrated into the E2E test framework. The `cmd/cluster/gcp/create.go` file exists with `RawCreateOptions`, but there are no GCP flags in `e2e_test.go` and no `GCPPlatform` in the `DefaultClusterOptions` switch statement.

**Files to Modify**:

1. **`test/e2e/util/options.go`** - Add import:
   ```go
   import (
       // ... existing imports
       hypershiftgcp "github.com/openshift/hypershift/cmd/cluster/gcp"
   )
   ```

2. **`test/e2e/util/options.go`** - Add to `ConfigurableClusterOptions` struct (around line 178):
   ```go
   // GCP options (matching cmd/cluster/gcp/create.go RawCreateOptions)
   GCPProject                       string
   GCPRegion                        string
   GCPNetwork                       string
   GCPPrivateServiceConnectSubnet   string
   GCPWorkloadIdentityProjectNumber string
   GCPWorkloadIdentityPoolID        string
   GCPWorkloadIdentityProviderID    string
   GCPNodePoolServiceAccount        string
   GCPControlPlaneServiceAccount    string
   ```

3. **`test/e2e/util/options.go`** - Add `DefaultGCPOptions()` function (after `DefaultPowerVSOptions`):
   ```go
   func (o *Options) DefaultGCPOptions() hypershiftgcp.RawCreateOptions {
       return hypershiftgcp.RawCreateOptions{
           Project:                       o.ConfigurableClusterOptions.GCPProject,
           Region:                        o.ConfigurableClusterOptions.GCPRegion,
           Network:                       o.ConfigurableClusterOptions.GCPNetwork,
           PrivateServiceConnectSubnet:   o.ConfigurableClusterOptions.GCPPrivateServiceConnectSubnet,
           WorkloadIdentityProjectNumber: o.ConfigurableClusterOptions.GCPWorkloadIdentityProjectNumber,
           WorkloadIdentityPoolID:        o.ConfigurableClusterOptions.GCPWorkloadIdentityPoolID,
           WorkloadIdentityProviderID:    o.ConfigurableClusterOptions.GCPWorkloadIdentityProviderID,
           NodePoolServiceAccount:        o.ConfigurableClusterOptions.GCPNodePoolServiceAccount,
           ControlPlaneServiceAccount:    o.ConfigurableClusterOptions.GCPControlPlaneServiceAccount,
       }
   }
   ```

4. **`test/e2e/util/hypershift_framework.go`** - Add to `PlatformAgnosticOptions` struct (around line 49):
   ```go
   type PlatformAgnosticOptions struct {
       core.RawCreateOptions

       NonePlatform      none.RawCreateOptions
       AWSPlatform       aws.RawCreateOptions
       KubevirtPlatform  kubevirt.RawCreateOptions
       AzurePlatform     azure.RawCreateOptions
       PowerVSPlatform   powervs.RawCreateOptions
       OpenStackPlatform openstack.RawCreateOptions
       GCPPlatform       hypershiftgcp.RawCreateOptions  // ADD THIS

       ExtOIDCConfig *ExtOIDCConfig
   }
   ```

5. **`test/e2e/util/options.go`** - Update `DefaultClusterOptions()` (around line 204-217):
   ```go
   createOption := PlatformAgnosticOptions{
       // ... existing fields
       GCPPlatform: o.DefaultGCPOptions(),  // ADD THIS
   }

   switch o.Platform {
   case hyperv1.AWSPlatform, hyperv1.AzurePlatform, hyperv1.NonePlatform, hyperv1.KubevirtPlatform, hyperv1.OpenStackPlatform:
       createOption.Arch = hyperv1.ArchitectureAMD64
   case hyperv1.GCPPlatform:  // ADD THIS CASE
       createOption.Arch = hyperv1.ArchitectureAMD64
   case hyperv1.PowerVSPlatform:
       createOption.Arch = hyperv1.ArchitecturePPC64LE
   }
   ```

6. **`test/e2e/e2e_test.go`** - Add GCP flags (after PowerVS flags, around line 160):
   ```go
   // GCP specific flags
   flag.StringVar(&globalOpts.ConfigurableClusterOptions.GCPProject, "e2e.gcp-project", "", "GCP project ID for testing")
   flag.StringVar(&globalOpts.ConfigurableClusterOptions.GCPRegion, "e2e.gcp-region", "us-central1", "GCP region for clusters")
   flag.StringVar(&globalOpts.ConfigurableClusterOptions.GCPNetwork, "e2e.gcp-network", "", "VPC network name")
   flag.StringVar(&globalOpts.ConfigurableClusterOptions.GCPPrivateServiceConnectSubnet, "e2e.gcp-psc-subnet", "", "Subnet for Private Service Connect endpoints")
   flag.StringVar(&globalOpts.ConfigurableClusterOptions.GCPWorkloadIdentityProjectNumber, "e2e.gcp-wif-project-number", "", "Numeric GCP project ID for WIF")
   flag.StringVar(&globalOpts.ConfigurableClusterOptions.GCPWorkloadIdentityPoolID, "e2e.gcp-wif-pool-id", "", "Workload Identity Pool ID")
   flag.StringVar(&globalOpts.ConfigurableClusterOptions.GCPWorkloadIdentityProviderID, "e2e.gcp-wif-provider-id", "", "Workload Identity Provider ID")
   flag.StringVar(&globalOpts.ConfigurableClusterOptions.GCPNodePoolServiceAccount, "e2e.gcp-nodepool-sa", "", "Service Account for NodePool CAPG controllers")
   flag.StringVar(&globalOpts.ConfigurableClusterOptions.GCPControlPlaneServiceAccount, "e2e.gcp-controlplane-sa", "", "Service Account for Control Plane Operator")
   ```

**Reference**: The GCP `RawCreateOptions` struct is defined in `cmd/cluster/gcp/create.go:31-58`

**Acceptance Criteria**:
- [ ] GCP flags are recognized by test binary (`go test -v ./test/e2e/... -args -help | grep gcp`)
- [ ] Flags match all fields in `cmd/cluster/gcp/create.go` `RawCreateOptions`
- [ ] `DefaultGCPOptions()` returns valid `hypershiftgcp.RawCreateOptions`
- [ ] Platform switch includes `hyperv1.GCPPlatform` case
- [ ] Tests compile with `go build -tags e2e ./test/e2e/...`

---

### Story 7: Implement GCP Cluster Lifecycle Tests and Utilities

**Summary**: Create tests for GCP cluster creation, validation, and deletion along with required utilities

**Description**:
Implement the core E2E tests for GCP cluster lifecycle following patterns from existing platform tests. GCP-specific utility functions (in `test/e2e/util/gcp.go`) should be created as needed during test implementation.

**Important**: GCP is currently TechPreview. Tests may need to handle the `TECH_PREVIEW_NO_UPGRADE` environment variable similar to existing validation tests in `test/e2e/create_cluster_test.go:1669`. See Appendix F for details.

**New File: `test/e2e/util/gcp.go`**:
```go
package util

// GCP-specific utilities following pattern from aws.go
// - GetGCPClient() - Create GCP API client
// - ValidatePSCEndpoint() - Validate Private Service Connect
// - ValidateDNSZone() - Validate Cloud DNS configuration
// - CleanupGCPResources() - Resource cleanup helpers
```

**Test Scenarios (Phase 1 - Generic Conformance Tests)**:

> **Strategy Note**: Prioritize running generic, conformance-style Hypershift E2E tests first. These tests are not cloud-specific and validate core Hypershift operator functionality on GCP infrastructure. This approach reduces complexity and establishes a stable baseline before adding GCP-specific tests.

| Test | Description | File |
| ---- | ----------- | ---- |
| `TestCreateCluster` | Generic cluster creation using existing conformance test with GCP platform | `test/e2e/create_cluster_test.go` |
| `TestNodePoolCreation` | Generic NodePool lifecycle tests | `test/e2e/nodepool_test.go` |
| `TestClusterConformance` | Standard Kubernetes conformance on GCP-hosted cluster | `test/e2e/conformance_test.go` |

**Test Scenarios (Phase 2 - GCP-Specific Functionality)**:

| Test | Description | File |
| ---- | ----------- | ---- |
| `TestCreateCluster_GCP` | Full cluster creation with GCP infrastructure provisioning, validation, and deletion | `test/e2e/gcp_cluster_test.go` |
| `TestPrivateServiceConnect_GCP` | Validate PSC endpoint, service attachment, and connectivity | `test/e2e/gcp_psc_test.go` |
| `TestDNSResolution_GCP` | Validate Cloud DNS zone creation, record management, and resolution | `test/e2e/gcp_dns_test.go` |
| `TestCAPGIntegration_GCP` | Validate CAPG (Cluster API Provider GCP) machine provisioning | `test/e2e/gcp_capg_test.go` |
| `TestWorkloadIdentityFederation_GCP` | Validate WIF configuration and OIDC integration | `test/e2e/gcp_wif_test.go` |

**Test Scenarios (Phase 3 - Advanced Features)**:

| Test | Description |
| ---- | ----------- |
| `TestNodePool_GCP` | NodePool creation, scaling, and deletion |
| `TestNodePoolAutoScaling_GCP` | NodePool autoscaling with Karpenter |
| `TestUpgradeControlPlane_GCP` | Control plane upgrade scenarios |
| `TestPrivateCluster_GCP` | Private endpoint access configuration |

**Acceptance Criteria**:
- [ ] `TestCreateCluster_GCP` passes end-to-end
- [ ] Tests handle TechPreview feature gate appropriately
- [ ] Cleanup runs even on test failure (defer patterns)
- [ ] Artifacts collected to `${ARTIFACT_DIR}`

---

### Story 8: Integrate GCP Tests into CI Pipeline

**Summary**: Full CI integration with pre-submit and periodic jobs

**Description**:
Once basic tests and CI infrastructure are in place, integrate GCP tests into the regular CI pipeline in `openshift/release`.

**CI Operator Configuration** (`ci-operator/config/openshift/hypershift/openshift-hypershift-main.yaml`):

> **Safe Introduction Strategy**: New tests should be introduced with `always_run: false` and optionally `skip_report: true`. This allows:
> - Manual triggering via `/test e2e-gcp` command on PRs
> - Failed jobs don't block PR merging during stabilization
> - Rehearsible jobs can be used for initial testing in sandbox environment before merging

```yaml
tests:
  - as: e2e-gcp
    # Safe introduction flags
    always_run: false     # Only run when explicitly triggered with /test
    optional: true        # Don't block PR on failure
    skip_report: true     # Don't report results to PR (remove once stable)
    run_if_changed: "^(api/hypershift/v1beta1/gcp.*|hypershift-operator/controllers/.*/gcp.*|control-plane-operator/controllers/.*/gcp.*|cmd/cluster/gcp/.*|cmd/nodepool/gcp/.*)"
    steps:
      cluster_profile: hypershift-gcp  # Dedicated GCP profile with own quota slice
      workflow: hypershift-gcp-e2e
      env:
        GCP_REGION: us-central1
        TECH_PREVIEW_NO_UPGRADE: "true"
```

**Progression to Blocking**:
1. **Initial**: `always_run: false`, `skip_report: true` - Manual trigger only
2. **Stabilizing**: `always_run: false`, `skip_report: false` - Manual trigger, results visible
3. **Informational**: `always_run: true`, `optional: true` - Runs on GCP changes, non-blocking
4. **Blocking**: `always_run: true`, `optional: false` - Required for merge

**Rehearsible Jobs**:
Before merging new test configurations, use `pj-rehearse` to test in a sandbox:
```bash
# Rehearse the new job configuration
/pj-rehearse pull-ci-openshift-hypershift-main-e2e-gcp
```

**Periodic Job** (for nightly/scheduled runs):
```yaml
- as: e2e-gcp-periodic
  cron: "0 4 * * *"  # Daily at 4 AM UTC
  steps:
    cluster_profile: hypershift-gcp  # Dedicated GCP profile with own quota slice
    workflow: hypershift-gcp-e2e
```

**Tasks**:
- [ ] Add pre-submit job configuration with safe introduction flags
- [ ] Rehearse job configuration before merging
- [ ] Add periodic job for nightly testing
- [ ] Configure test result reporting to TestGrid
- [ ] Set up Sippy dashboard for flake detection
- [ ] Progressively enable: remove `skip_report`, then set `always_run: true`
- [ ] Add to relevant blocking job set once stable (after 1+ week of green runs)

**Acceptance Criteria**:
- [ ] Job can be manually triggered via `/test e2e-gcp`
- [ ] Rehearsal passes in sandbox environment
- [ ] Test results visible in Prow/TestGrid (after removing skip_report)
- [ ] Periodic jobs run successfully for 1 week before promoting to blocking

---

### Story 9: Create GCP Test Artifacts Documentation

**Summary**: Document GCP test artifacts directory structure and debugging guide

**Description**:
Create documentation for GCP E2E test artifacts following the pattern of Azure documentation.

**Documentation Structure**:
```
docs/content/reference/test-information-debugging/GCP/
├── test-artifacts-directory-structure.md
├── debugging-guide.md
└── ci-infrastructure.md
```

**Content to Include**:

1. **test-artifacts-directory-structure.md**:
   - Directory layout of test artifacts
   - Key files: cluster manifests, controller logs, events
   - GCP-specific artifacts: PSC status, DNS records, WIF configuration

2. **debugging-guide.md**:
   - Common failure scenarios and resolution
   - PSC connectivity troubleshooting
   - DNS propagation issues
   - WIF/OIDC authentication failures
   - CAPG machine provisioning failures

3. **ci-infrastructure.md**:
   - Overview of CI setup
   - How to run tests locally
   - How to add new test scenarios
   - Cost management and resource cleanup

**Acceptance Criteria**:
- [ ] Documentation covers all major artifact types
- [ ] Debugging workflows are actionable with specific commands
- [ ] GCP-specific considerations are documented
- [ ] Local development workflow documented

---

### Story 10: Configure Budget Alerts and Cost Monitoring

**Summary**: Set up cost monitoring and alerting for CI infrastructure

**Description**:
Configure budget alerts and monitoring to control CI spending and detect cost anomalies. Budget alerts will be scoped at the **CI folder level** to capture all dynamic project costs.

**Prerequisites**: Story 2 (CI folder and billing account configured)

**Investigation Items**:
- [ ] Define appropriate budget threshold (<budget-threshold> as starting point)
- [ ] Identify notification channels (email, Slack, PagerDuty, etc.)
- [ ] Evaluate orphaned project detection strategy
- [ ] Decide on implementation method (Terraform, gcloud, or Console)

**Tasks**:
- [ ] Configure folder-level budget alert with agreed thresholds
- [ ] Set up notification channels for the team
- [ ] Implement orphaned project monitoring (projects older than 4 hours)
- [ ] Document cost monitoring procedures

**Reference**:
- [GCP Budget API](https://cloud.google.com/billing/docs/how-to/budgets)
- [Terraform google_billing_budget](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/billing_budget)

**Acceptance Criteria**:
- [ ] Folder-level budget alerts configured and triggering correctly
- [ ] Team receives notifications for cost anomalies
- [ ] Orphaned project detection operational

---

### Story 11: Investigate CI Service Account Key Rotation Strategy

**Summary**: Investigate options for rotating the CI service account key used for GCP E2E tests

**Description**:
The CI infrastructure (Story 2) uses a static service account key stored in Vault for authenticating to GCP. Static keys are a security risk if not rotated periodically. This spike investigates rotation options and recommends an approach.

**Prerequisites**: Story 2 (CI infrastructure operational)

**Current State**:
- CI service account: `hypershift-ci@<ci-project>.iam.gserviceaccount.com`
- Key stored in Vault at `hypershift-ci-jobs-gcpcreds`
- Key synced to `test-credentials` namespace on build clusters
- No rotation policy in place

**Investigation Items**:
- [ ] Review OpenShift CI patterns for credential rotation (AWS, Azure)
- [ ] Evaluate Google Cloud's service account key rotation best practices
- [ ] Assess operational overhead of manual vs automated rotation

**Options to Evaluate**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| Manual rotation | Periodic manual key rotation with documented runbook | Simple to implement | Operational burden, human error risk |
| Tekton Pipeline | Scheduled Tekton task rotates key and updates Vault | Leverages existing infrastructure, familiar tooling | Requires Vault API access from Tekton |
| Cloud Functions | Scheduled Cloud Function rotates key and updates Vault | Fully automated, native GCP | Requires Cloud Function setup and Vault API access |

**Reference**:
- [GCP Service Account Key Best Practices](https://cloud.google.com/iam/docs/best-practices-for-managing-service-account-keys)
- Story 2: CI Infrastructure Setup
- GCP-326/GCP-327: Production Secret Storage Strategy

**Acceptance Criteria**:
- [ ] Rotation options documented with pros/cons
- [ ] Recommended approach selected
- [ ] Implementation story created if needed
- [ ] Rotation frequency defined

---

## Appendix

### A. ARO HCP CI Patterns Reference

ARO HCP uses multiple cluster profiles for different environments:
- `<product>-dev` - Development testing
- `<product>-int` - Integration testing
- `<product>-stg` - Staging
- `<product>-prod` - Production validation

Their workflow structure:
```yaml
workflow:
  as: aro-hcp-e2e
  steps:
    test:
      - ref: aro-hcp-tests-run-aro-hcp-tests
    post:
      - ref: aro-hcp-provision-aro-hcp-gather-extra
      - chain: aro-hcp-provision-teardown-cluster
```

### B. OpenShift CI Key Concepts

- **Steps**: Individual test actions (YAML + shell script)
- **Chains**: Ordered sequences of steps
- **Workflows**: Complete test flows with `pre`, `test`, `post` phases
- **Cluster Profiles**: Credential and configuration bundles
- **Leases**: Cloud quota management

### C. Boskos Leasing System

Boskos is a resource management server that apportions leases of resources to clients and manages the lifecycle of the resources. It is a critical component of Prow CI for managing cloud quotas.

**How it works**:
1. A client (test job) requests a lease on an available resource
2. Boskos grants the lease if available, or queues the request (FIFO)
3. The client emits heartbeats while the lease is under active use
4. The client relinquishes the lease once testing is complete
5. If heartbeats stop, Boskos forcibly reclaims the resource

**Credential Management**:
Credentials are NOT provided by Boskos directly. Instead, they are mounted from dedicated secrets via the step registry `credentials` configuration. For HyperShift Azure tests, this is `hypershift-ci-jobs-azurecreds`. For GCP, we need an equivalent `hypershift-ci-jobs-gcpcreds`.

**Example credential mount** (from `aks-provision-ref.yaml`):
```yaml
credentials:
  - mount_path: /etc/hypershift-ci-jobs-azurecreds
    name: hypershift-ci-jobs-azurecreds
    namespace: test-credentials
```

**Environment Variables** (provided by ci-operator):
```bash
# Boskos lease information
LEASED_RESOURCE=us-central1  # Region/location from lease
NAMESPACE=ci-op-xxxxx        # Job namespace
UNIQUE_HASH=abc123           # Unique identifier for this run
SHARED_DIR=/tmp/shared       # Directory for passing data between steps
CLUSTER_PROFILE_DIR=/var/run/secrets/ci.openshift.io/cluster-profile
```

### D. Quota Slices and Cluster Profiles

**What is a Quota Slice?**

A quota slice is a Boskos resource unit that controls concurrency for CI jobs. It acts as a semaphore - each job acquires one slice before running, and releases it when done. If all slices are in use, new jobs wait in queue.

**Current HyperShift Quota Slice Allocation** (from `openshift/release`):

| Quota Slice | Slots | Used By |
|-------------|-------|---------|
| `hypershift-quota-slice` | **50** | AWS, AKS/Azure, IBMCloud, OpenStack, KubeVirt (shared) |
| `hypershift-hive-quota-slice` | **10** | Hive-related tests |
| `hypershift-powervs-quota-slice` | **3** | PowerVS periodic tests |
| `hypershift-powervs-cb-quota-slice` | **5** | PowerVS CB tests |

**Quota Slice vs Cloud Credentials**:

These are separate concerns:
- **Quota Slice**: Controls *how many* jobs run concurrently (CI cluster resources)
- **Credentials**: Controls *where* jobs run (which cloud account)

The `cluster_profile: hypershift` maps to `hypershift-quota-slice` (50 slots). Cloud credentials are mounted separately via the step registry `credentials` field:

```yaml
# From aks-provision-ref.yaml - credentials mounted separately from cluster profile
credentials:
  - mount_path: /etc/hypershift-ci-jobs-azurecreds
    name: hypershift-ci-jobs-azurecreds
    namespace: test-credentials
```

**Why Share a Quota Pool?**

The shared pool (50 slots for AWS/Azure/etc.) prioritizes efficiency over isolation:
- If no Azure tests are running, AWS tests can use all 50 slots
- No slots sit idle because "that's the Azure pool"
- Simpler to manage one pool

The trade-off is no guaranteed capacity per platform - a flood of AWS tests could delay Azure tests.

**Decision for GCP**: **Option A chosen** - Create dedicated `hypershift-gcp` profile with own quota slice.

**Rationale**: GCP tests run on GKE management clusters (not the AWS-based hypershift-ci cluster), so having a separate profile avoids artificially limiting AWS cluster capacity. GCP tests are independent of AWS infrastructure.

**Options Considered**:

| Option | Approach | Pros | Cons | Decision |
|--------|----------|------|------|----------|
| A. New `hypershift-gcp` profile | Full new cluster profile | Clean isolation, dedicated quota | More CI team coordination | **CHOSEN** |
| B. Use `hypershift` + mount creds | Reuse `hypershift` profile, mount GCP creds separately | Follows AKS pattern, simpler | Shares 50 slots with AWS/Azure | |

**Option A (chosen)**:
- Dedicated `hypershift-gcp-quota-slice` with controlled number of slots
- GCP tests won't compete with AWS/Azure for quota
- Requires CI team coordination to set up new profile and Boskos config

**Option B (not chosen)**:
- Would have matched the existing AKS pattern (`hypershift` profile + `hypershift-ci-jobs-azurecreds`)
- Would share 50 slots with AWS/Azure, potentially limiting AWS capacity

### E. Flakiness Mitigation

Eventual consistency issues are common causes of flakiness in infrastructure tests. Keep provision scripts simple and generic to minimize errors.

**Common Flakiness Sources**:

1. **DNS Propagation**: Cloud DNS zones may not be immediately available after creation
   ```bash
   # Add retry logic for DNS operations
   for i in {1..30}; do
       if nslookup api.${CLUSTER_NAME}.${BASE_DOMAIN}; then
           break
       fi
       echo "Waiting for DNS propagation... (attempt $i/30)"
       sleep 10
   done
   ```

2. **API Availability**: GKE/GCP APIs may return success before resources are fully ready
   ```bash
   # Wait for cluster to be truly ready, not just created
   gcloud container clusters get-credentials "${CLUSTER_NAME}" ... || sleep 30
   kubectl wait --for=condition=Ready nodes --all --timeout=300s
   ```

3. **IAM Propagation**: Service account permissions may take time to propagate
   - Add delays after IAM bindings
   - Use exponential backoff for permission-dependent operations

4. **Private Service Connect (PSC)**: Service attachments and endpoints have eventual consistency

**Best Practices**:
- Use `--quiet` flag to suppress interactive prompts
- Set appropriate logging levels (debug for troubleshooting, but avoid exposing tokens)
- Implement idempotent cleanup in deprovision steps
- Use `set -euo pipefail` but with proper error handling
- Add explicit waits rather than relying on command success

**Logging Guidelines**:
```bash
# Good: Debug logging without sensitive data
echo "Creating cluster ${CLUSTER_NAME} in ${GCP_REGION}..."

# Bad: Exposing credentials
echo "Using credentials: ${GOOGLE_APPLICATION_CREDENTIALS}"  # DON'T DO THIS
```

**CI-Specific Requirements**:
- **Shellcheck**: All shell scripts in step registry are validated with shellcheck (fails on errors)
- **Timeout/Grace Period**: Default step timeout is 2h, grace period 15s. GKE provision uses 30m timeout, 10m grace period for cleanup.
- **pj-rehearse**: New/changed steps automatically trigger rehearsal tests before merge
- **Debugging Access**: Jobs run in `ci-op-<hash>` namespaces

**Environment Variables** (provided by ci-operator):
```bash
${LEASED_RESOURCE}      # Resource name from Boskos lease (e.g., region)
${SHARED_DIR}           # Directory for passing data between steps
${ARTIFACT_DIR}         # Directory for test artifacts (uploaded after job)
${CLUSTER_PROFILE_DIR}  # Mounted cluster profile credentials
${NAMESPACE}            # Job namespace (ci-op-xxxxx)
${UNIQUE_HASH}          # Unique identifier for this run
```

### F. Feature Gate Handling

GCP platform is TechPreview. Existing code checks:
```go
// From test/e2e/create_cluster_test.go:1669
if hostedCluster.Spec.Platform.Type == hyperv1.GCPPlatform && os.Getenv("TECH_PREVIEW_NO_UPGRADE") != "true" {
    t.Logf("Skipping GCP validation outside TechPreviewNoUpgrade: %s", v.name)
    continue
}
```

E2E tests should set `TECH_PREVIEW_NO_UPGRADE=true` in CI environment.

### G. GCP Dynamic Project Architecture

GCP E2E tests use a **dynamic two-project architecture** where projects are created per-test under a dedicated CI folder:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           GCP HCP Organization                               │
├─────────────────────────────────────────────────────────────────────────────┤
│   GCP HCP Folder (405445313657)                                             │
│   │                                                                         │
│   ├── GCP HCP Commons (954373422469)     ← Managed service infrastructure   │
│   ├── GCP HCP Integration (1059025110045) ← Integration environment         │
│   ├── GCP HCP Development (...)           ← Development environment         │
│   │                                                                         │
│   └── GCP HCP CI (new) ← CI folder for E2E tests (isolated from above)      │
│       │                                                                     │
│       ├── gcp-hcp-ci (CI Project - permanent, hosts the CI SA)              │
│       │   └── hypershift-ci@<ci-project>.iam.gserviceaccount.com            │
│       │       (has projectCreator/projectDeleter ONLY on CI folder)         │
│       │                                                                     │
│       └── (Dynamic test projects - created/deleted per E2E run)             │
│           ├── ${INFRA_ID}-mgmt (Management Project)                         │
│           │   ├── GKE Autopilot Management Cluster                          │
│           │   ├── HyperShift Operator                                       │
│           │   └── OIDC Issuer                                               │
│           └── ${INFRA_ID}-cust (Customer Project)                           │
│               ├── WIF Pool (trusts MC OIDC)                                 │
│               ├── Service Accounts (GSAs)                                   │
│               ├── Hosted Cluster VMs                                        │
│               └── VPCs, DNS, PSC                                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Isolation**: The CI SA has permissions ONLY on the CI folder. It cannot create, modify, or delete projects in sibling folders (Commons, Integration, Development). This ensures complete isolation between CI tests and managed service infrastructure.

**Benefits of Dynamic Projects**:
- **Complete isolation**: Each test run has its own projects - no resource conflicts
- **Bounded cleanup**: Explicit resource deletion followed by project deletion ensures complete cleanup
- **Mirrors production**: Customers get their own projects in real deployments
- **No cross-test interference**: Resources from one test cannot affect another test

> **Important**: Project deletion does NOT automatically clean up all resources. Some resources (VPC, GKE clusters) can **block** project deletion and must be deleted explicitly first. See the deprovision script in Story 4 for the required cleanup order.

**Credential Approach**:

The Vault secret contains:

| File in Secret | Purpose |
|----------------|---------|
| `credentials.json` | GCP service account key with project creation permissions |
| `ci-folder-id` | GCP folder ID where dynamic projects are created |
| `billing-account-id` | Billing account to link to new projects |

**Required IAM Permissions for CI Service Account**:

| Resource | Required Roles | Purpose |
|----------|----------------|---------|
| CI Folder | `roles/resourcemanager.projectCreator` | Create projects under CI folder |
| CI Folder | `roles/resourcemanager.projectDeleter` | Delete projects during cleanup |
| Billing Account | `roles/billing.user` | Link billing to new projects |
| Created Projects | Owner (auto-granted) | Full admin on projects it creates |

**Note**: The CI SA automatically gets Owner permissions on projects it creates. This gives it all required permissions for GKE, compute, IAM, and DNS operations within those projects.

**Networking Approach**:

- **Management cluster (GKE Autopilot)**: Custom VPC created per-test in management project
  - VPC with auto-mode subnets
  - Cloud Router + NAT (for private node egress)
  - PSC subnet (10.3.0.0/24, purpose=PRIVATE_SERVICE_CONNECT)
  - GKE Autopilot cluster (fully managed nodes, automatic scaling)
- **Hosted cluster workers**: Dedicated VPC per-test via `hypershift create infra gcp` in customer project

GKE Autopilot provides production-equivalent security settings by default (shielded nodes, hardened runtime, etc.) without manual configuration.

**CI Flow** (see E2E Test Flow Diagram):

1. **Create dynamic projects** → `${INFRA_ID}-mgmt` and `${INFRA_ID}-cust` under CI folder
2. **Create VPC and networking** → VPC, Cloud Router, NAT, PSC subnet in management project
3. **Provision GKE Autopilot** → Management cluster with production-equivalent settings
4. **Install HyperShift operator** → Deploys operator with OIDC issuer
5. **Run `hypershift create iam gcp --project-id=<customer-project>`** → Creates WIF pool, OIDC provider, GSAs
6. **Run `hypershift create infra gcp --project-id=<customer-project>`** → Creates VPC, subnet, router, NAT, firewall
7. **Run `hypershift create cluster gcp --project=<customer-project>`** → Creates hosted cluster using infra output
8. **Run E2E tests** → Validate hosted cluster functionality
9. **Cleanup** → Explicit resource deletion (GKE, VPC) followed by project deletion

**Why Two Projects?**

This mirrors real-world deployments where:
- The service provider runs the management infrastructure
- Customer workloads run in customer-owned GCP projects
- WIF allows cross-project authentication without sharing service account keys

---

## Decisions Made

| Decision | Resolution |
| -------- | ---------- |
| Management Cluster Strategy | Provision per-test following AKS pattern |
| Management Cluster Type | GKE Autopilot (fully managed nodes, automatic scaling, no node pool management) |
| Region Selection | us-central1 for initial CI |
| Provisioning Method | Simple gcloud commands (not Terraform) |
| Test Priority | Generic conformance first, then GCP-specific |
| WIF Setup | Per-cluster using `hypershift infra gcp` CLI. See `openshift/hypershift/cmd/infra/gcp/` |
| Credential Architecture | Two-project architecture with single SA having cross-project access (following ARO HCP pattern). See Appendix G. |
| Networking Approach | Custom VPC per-test (with Cloud Router/NAT + PSC subnet) for GKE MC. Dedicated VPC for HC workers via `hypershift create infra gcp`. See Appendix G. |
| Cost Controls | Concurrency via Boskos quota slices (GCP lacks per-folder project limits). Budget alert at <budget-threshold>. Dynamic project deletion ensures cleanup. |
| CI Rollout Strategy | Start with `always_run: false`, `skip_report: true`. Promotion to blocking TBD (likely after internal preview). |
| GCP Project Source | **HCM org account**. Dynamic projects created per-test under GCP HCP org CI folder. |
| Project Lifecycle | Dynamic projects per-test under CI folder. Projects deleted on cleanup. See Appendix G. |
| CI Authentication | **Service Account with static credentials** stored in Vault. Matches existing OpenShift CI patterns for AWS/Azure (HyperShift team owns the cloud accounts). |
| CI Isolation | Direct folder permissions on CI folder only. CI SA cannot affect managed service projects in sibling folders. |
| CI Folder Location | Under GCP HCP folder. New `gcp-hcp-ci` folder for test isolation. |
| Cluster Profile | **Dedicated `hypershift-gcp` profile** with own quota slice. GCP tests won't use resources from the AWS-based hypershift-ci cluster, so having a separate profile avoids artificially limiting AWS cluster capacity. See Appendix D. |

