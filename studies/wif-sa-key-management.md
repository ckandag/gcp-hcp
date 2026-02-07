# Workload Identity Federation: Service Account Key Management Research

## Table of Contents

1. [Overview](#overview)
2. [Requirements](#requirements)
3. [Current Implementation Analysis](#current-implementation-analysis)
4. [Security Concerns](#security-concerns)
5. [Anti-Pattern: Central GCP Service Account](#anti-pattern-central-gcp-service-account)
6. [Platform-Hosted OIDC Endpoint](#platform-hosted-oidc-endpoint)
7. [Bootstrap Approaches](#bootstrap-approaches)
8. [HyperShift HostedCluster Architecture Constraint](#hypershift-hostedcluster-architecture-constraint)
9. [Key Storage and Signing Options](#key-storage-and-signing-options)
10. [Rotation Strategies](#rotation-strategies)
11. [Isolation Mechanisms](#isolation-mechanisms)
12. [Customer Experience](#customer-experience)
13. [Comprehensive Comparison](#comprehensive-comparison)
14. [Decision Criteria](#decision-criteria)
15. [Rejected Alternatives](#rejected-alternatives)
16. [Open Questions](#open-questions)
17. [Related Work](#related-work)
18. [References](#references)

---

## Overview

### Problem Statement

GCP HCP enables customers to run Hypershift-managed hosted clusters on Google Cloud Platform. For workload pods in these hosted clusters to access customer GCP resources, we use **Workload Identity Federation (WIF)** with service account tokens signed by the Kubernetes API server.

**Current Challenge**: The process of managing service account signing keys presents significant security and operational concerns:

1. **Key Sprawl**: Private keys traverse multiple systems (customer → CLS database → Hypershift operator → control-plane)
2. **Multi-Tenant Risk**: Shared components (CLS/CLM, Hypershift operator) have access to customer-specific secrets
3. **No Rotation Strategy**: Manual, customer-driven rotation is operationally impractical
4. **Compliance Risk**: Storing all customer private keys in a central database creates audit concerns

### Scope

This document researches approaches to service account signing key management for Workload Identity Federation. It analyzes multiple options, their trade-offs, and provides decision criteria for team discussion.

**Out of Scope**: User authentication to Kubernetes API (covered in `PROJECTS/OIDC/`).

---

## Requirements

The following requirements drive the design of any solution:

### Security First

**REQ-1: Minimize Private Key Exposure**

Private keys must exist only where absolutely necessary for signing operations. Each additional location where a private key exists increases attack surface.

- Private keys should NOT traverse network boundaries unnecessarily
- Private keys should NOT be stored in databases accessible by shared components
- Private keys should be encrypted at rest where storage is required
- Ephemeral keys preferred over long-lived keys

**REQ-2: Isolation Between Customers**

Each hosted cluster must have a unique signing key. Compromise or exposure of one cluster's key must not affect other clusters.

- Keys must be isolated per cluster (no shared signing keys)
- Access control must prevent one cluster from accessing another's keys
- Isolation must be enforced by infrastructure (not application logic alone)

**REQ-3: No Shared Component Access**

Multi-tenant shared components (CLS/CLM, Hypershift operator, central operators) must NOT have access to customer private keys or signing facilities.

- CLS/CLM: May coordinate keypair lifecycle but must not access private keys
- Hypershift operator: Must not have access to private keys during reconciliation
- Central operators (e.g., cluster-wide External Secrets Operator): Must not have broad access to all customer keys

**Rationale**: Shared components serve all customers. Compromise of a shared component should not expose all customer keys. Defense in depth requires limiting blast radius.

### Operational Excellence

**REQ-4: Enable Automated Rotation**

The platform must be able to rotate signing keys automatically on a schedule without customer action.

- Rotation should be configurable per cluster (frequency)
- Rotation should be zero-downtime (no service interruption)
- Platform-managed rotation reduces operational burden on customers

**REQ-5: Support Customer-Initiated Rotation**

Customers must be able to trigger immediate key rotation (e.g., in response to suspected compromise).

- Manual rotation via CLI or API
- Rotation status visibility
- Clear documentation and workflow

**REQ-6: Backup and Disaster Recovery**

Keys must be backed up securely to support cluster recovery scenarios. Loss of the signing key means loss of workload access to customer GCP resources.

**Backup Requirements**:
- Private keys must be recoverable if control-plane namespace is destroyed
- Keys must survive management cluster failures
- Backup storage must maintain same isolation guarantees as primary storage
- Recovery process must be documented and tested

**Disaster Recovery Scenarios**:
- Control-plane namespace accidentally deleted
- Management cluster failure or corruption
- Region-wide outage requiring cluster migration to different region
- Key corruption or accidental deletion

**Storage Implications**:
- **Plain Kubernetes Secret**: Backed up only via etcd backups (management cluster level)
  - Lost if management cluster destroyed
  - No independent backup mechanism
  - Recovery requires etcd restore
- **Google Secret Manager**: Independent backup storage outside Kubernetes
  - Survives management cluster deletion
  - Multi-region replication available
  - Version history for recovery
- **Cloud KMS**: HSM-backed with automatic replication
  - Highest availability guarantees
  - Built-in version management
  - Cannot be accidentally deleted (soft delete protection)

**Why This Drives GSM/KMS Choice**: Plain Kubernetes Secrets are backed up only via etcd. If management cluster is lost, secrets are lost unless etcd is restored. External secret storage (GSM/KMS) provides independent backup and higher availability.

### Customer Experience

**REQ-7: Balance Setup Complexity**

The customer setup workflow should be as simple as possible while maintaining security.

**Trade-off**: A two-step process (keypair generation, then cluster creation) provides better security (platform generates keys) but adds complexity. Customer tooling (CLI, UI, Terraform) must handle this appropriately.

- CLI can encapsulate multi-step workflows with clear guidance
- UI can provide wizard-style flows
- Terraform modules can compose resources appropriately

**Consideration**: Any workflow implemented in CLI must also be supported by UI and Terraform. Business logic should not be CLI-only.

---

## Current Implementation Analysis

### How It Works Today

Based on `hypershift/cmd/infra/gcp/iam.go`:

1. Customer generates RSA keypair (public and private key) on their local machine
2. Customer creates OIDC provider in their GCP project:
   - Workload Identity Pool with OIDC provider
   - JWKS contains public key for token verification
   - Custom issuer URL based on cluster infrastructure ID
3. Customer provides both private and public keys to CLS during cluster creation
4. CLS stores private key in its database alongside cluster metadata
5. Hypershift operator receives keys when reconciling HostedCluster resource
6. Control-plane components use private key to sign service account tokens
7. Customer's GCP verifies tokens using public key from OIDC provider JWKS

### Code References

**Primary Implementation**: `hypershift/cmd/infra/gcp/iam.go`

- OIDC issuer URL generation
- Workload Identity Pool and Provider creation
- JWKS configuration with public keys
- Service account principal formatting for WIF bindings

**HyperShift Enhancement**: PR #1259 added `ServiceAccountSigningKey` field to HostedCluster spec, enabling custom signing key management.

### Security Boundaries Today

```
Customer
  │ Generates keypair (private key exposed on local machine)
  ▼
CLS/CLM (Shared, Multi-Tenant)
  │ Stores private key in database
  │ All customer keys accessible to CLS
  ▼
Hypershift Operator (Shared, Multi-Tenant)
  │ Receives private key during reconciliation
  │ Has access to all cluster keys on management cluster
  ▼
Control-Plane Namespace (Customer-Specific)
  │ Uses private key to sign service account tokens
  │ Isolated to this cluster's workloads
  ▼
Customer GCP
    Verifies tokens using public key from OIDC provider
```

**Violation of Requirements**:

- REQ-1: Private key travels from customer → network → CLS database → Hypershift operator → control-plane
- REQ-3: CLS and Hypershift operator (shared components) have access to all customer private keys

### Key Lifecycle Today

- **Creation**: Customer-generated, one-time during cluster setup
- **Storage**: CLS database (persistent, all customers), Hypershift operator (transient, in-memory)
- **Usage**: Control-plane kube-apiserver signs tokens
- **Rotation**: Not supported; would require manual customer action and cluster downtime
- **Revocation**: No mechanism; keys are permanent

---

## Security Concerns

### 1. Private Key Sprawl

**Issue**: Private keys exist in multiple locations with different security contexts.

**Locations**:

- Customer's local machine (temporary during setup)
- Network transmission (TLS-protected but still traverses boundary)
- CLS database (persistent storage, shared component)
- Hypershift operator memory (transient, shared component)
- Control-plane namespace (persistent, customer-specific)

**Risk**: Each location represents a potential compromise point. Shared component compromise exposes multiple customer keys.

**Impact**: Violates REQ-1 (minimize exposure) and REQ-3 (no shared component access).

### 2. Multi-Tenant Component Access

**Issue**: CLS and Hypershift operator are shared components serving all customers on the platform.

**Attack Scenarios**:

- SQL injection in CLS exposes all customer private keys from database
- Vulnerability in Hypershift operator allows key extraction from memory
- Insider threat: platform operators with CLS/Hypershift access can extract keys

**Impact**: Violates REQ-3. Single compromise of shared component affects all customers.

**Blast Radius**: High - all customer keys potentially exposed.

### 3. No Rotation Capability

**Issue**: Keys are created once and never rotated.

**Risks**:

- Cryptographic aging: older keys more vulnerable to cryptanalysis
- No recovery mechanism from key compromise
- Non-compliance with security policies requiring periodic rotation (typically 30-90 days)

**Operational Impact**: Manual rotation would require:

1. Customer generates new keypair locally
2. Customer updates OIDC provider JWKS in their GCP project
3. Customer provides new key to CLS
4. CLS updates database
5. Control-plane restart (downtime)

**Impact**: Violates REQ-4 (automated rotation) and REQ-5 (customer-initiated rotation).

### 4. Customer Trust Boundary

**Issue**: Customers must trust the platform with private keys that authenticate to their GCP projects.

**Concern**: Private keys can sign tokens that authenticate as any service account in the hosted cluster, potentially granting access to sensitive customer resources.

**Trust Requirements**:

- Customer trusts platform not to misuse keys
- Customer trusts platform security posture (no breaches)
- Customer trusts platform operators (no malicious insiders)

**Consideration**: This trust model may not meet all customers' security requirements, especially regulated workloads.

### 5. No Auditability or Observability

**Issue**: No visibility into key usage, age, or health.

**Missing Capabilities**:

- Key age metrics
- Rotation history and audit trail
- Alerts for aging keys or rotation failures
- Logs of key access or signing operations

**Impact**: Customers and platform operators cannot assess security posture or detect anomalies.

---

## Anti-Pattern: Central GCP Service Account

### Overview

An alternative approach sometimes proposed by teams is to use a **central GCP service account** that can be impersonated by various platform components and is granted broad access to customer GCP projects.

### Architecture

```
Platform Components (CLS, Hypershift Operator, others)
  │
  │ Impersonate
  ▼
Central Platform GCP Service Account
  │
  │ Granted IAM permissions in ALL customer projects
  ▼
Customer GCP Projects (Project A, B, C, ...)
  └── Resources (Cloud Storage, KMS, Secret Manager, etc.)
```

**How It Works**:

- Platform creates one GCP service account in platform project
- Each customer grants IAM permissions to this SA in their project
- Platform components impersonate this SA to access customer resources
- Single credential provides access to all customer projects

### Why This Is a Security Risk

**Violation of REQ-3**: Central SA is accessible by all shared components, creating a single point of failure.

**Broad Privilege Scope**:

- One compromised platform component gains access to ALL customer projects
- Privilege escalation: any component that can impersonate the SA gains broad access
- No granular isolation between customers or clusters

**Blast Radius**:

- Compromise of central SA credentials = compromise of all customer projects
- Insider threat: anyone with impersonation rights can access any customer
- Credential leakage: single credential exposure affects all customers

**Auditability Challenges**:

- Hard to attribute actions to specific component or cluster
- Audit logs show actions by central SA, not originating component
- Difficult to implement least-privilege per-component access

**Operational Risks**:

- Credential rotation affects all customers simultaneously
- Revocation of access is all-or-nothing
- Dependency on single SA creates reliability risk

### Comparison to Per-Cluster Isolation

| Aspect | Central GCP SA (Anti-Pattern) | Per-Cluster Isolation |
|--------|-------------------------------|----------------------|
| **Blast radius** | All customers | Single cluster |
| **Privilege scope** | Broad (all projects) | Narrow (one cluster) |
| **Compromise impact** | Platform-wide | Isolated |
| **Auditability** | Poor (central identity) | Good (per-cluster identity) |
| **Least privilege** | Difficult | Enforceable |
| **Shared component access** | Yes (violates REQ-3) | No (meets REQ-3) |

### Recommendation

**Avoid central GCP service account impersonation patterns**. Use per-cluster isolation with Workload Identity Federation and namespace-scoped service accounts instead.

---

## Platform-Hosted OIDC Endpoint

### Overview

The platform hosts an OIDC discovery endpoint for each hosted cluster, serving JWKS with public keys for token verification. This eliminates the need for customers to create OIDC providers in their GCP projects and removes all key exchange between platform and customer.

**Key Decision**: This is the chosen approach for GCP HCP, replacing the customer-hosted OIDC provider pattern.

### Architecture

```
Platform Infrastructure:
├── OIDC Endpoint Service (HTTPS, HA)
│   ├── Route: /{cluster-id}/.well-known/openid-configuration
│   ├── Route: /{cluster-id}/.well-known/jwks.json
│   └── Serves: Public keys for token verification
│
├── JWKS Management Service
│   ├── Updates JWKS when keys rotate
│   └── Manages grace periods (multiple keys)
│
└── Per-Cluster Key Storage (GSM or KMS)
    └── Private keys isolated per cluster

Customer GCP Project:
└── Workload Identity Pool
    └── OIDC Provider: trusts platform issuer URL
        Issuer: https://oidc.gcp-hcp.com/{cluster-id}
```

### How It Works

**Cluster Setup:**

1. **Platform generates keypair** (during cluster creation)
   - Private key stored in GSM or KMS (per-cluster, isolated)
   - Public key published to JWKS endpoint

2. **Customer configures Workload Identity Pool**
   - Creates WIF Pool in their GCP project
   - Adds OIDC provider pointing to: `https://oidc.gcp-hcp.com/{cluster-id}`
   - GCP fetches JWKS from platform endpoint for verification
   - No public key handling by customer
   - No bootstrap SA permissions needed

3. **Control-plane signs tokens**
   - kube-apiserver signs service account tokens with private key (from GSM/KMS)
   - Tokens include issuer: `https://oidc.gcp-hcp.com/{cluster-id}`

4. **Customer GCP verifies tokens**
   - Customer workloads present tokens to GCP APIs
   - GCP fetches JWKS from platform OIDC endpoint
   - GCP verifies token signature using public key from JWKS
   - Access granted based on WIF bindings

**Key Rotation:**

1. **Platform generates new keypair**
   - New private key stored in GSM/KMS
   - New public key added to JWKS endpoint (alongside existing key)

2. **Grace period** (1-2 hours)
   - JWKS contains both old and new public keys
   - Control-plane switches to signing with new key
   - Existing tokens (signed with old key) remain valid

3. **Cleanup**
   - Platform removes old public key from JWKS
   - Platform archives old private key (for audit/recovery)

**Zero customer involvement** - rotation is fully automated, no bootstrap SA required.

### Infrastructure Requirements

**OIDC Endpoint Service:**
- **HTTPS Server**: TLS-terminated, publicly accessible
- **DNS**: `oidc.gcp-hcp.com` with wildcard or per-cluster subdomains
- **High Availability**: Multi-region deployment, load balanced
- **Certificate Management**: Valid TLS certificates (Let's Encrypt, GCP Certificate Manager)
- **CDN/Caching**: Optional - JWKS can be cached (low change frequency)

**OIDC Discovery Document** (`/.well-known/openid-configuration`):
```json
{
  "issuer": "https://oidc.gcp-hcp.com/{cluster-id}",
  "jwks_uri": "https://oidc.gcp-hcp.com/{cluster-id}/.well-known/jwks.json",
  "response_types_supported": ["id_token"],
  "subject_types_supported": ["public"],
  "id_token_signing_alg_values_supported": ["RS256"]
}
```

**JWKS Endpoint** (`/.well-known/jwks.json`):
```json
{
  "keys": [
    {
      "kty": "RSA",
      "use": "sig",
      "kid": "key-2024-12-17-v1",
      "n": "...",
      "e": "AQAB"
    }
  ]
}
```
*Note: Multiple keys present during grace period after rotation.*

**Implementation Options:**

**Option A: Cloud Run Service**
- Custom Go/Python service serving OIDC endpoints
- Reads public keys from GSM/KMS on-demand or cached
- Auto-scaling, serverless

**Option B: Cloud Storage + Cloud CDN**
- Static JWKS files in Cloud Storage buckets (per cluster)
- Cloud CDN for global distribution and caching
- Cloud Function for dynamic discovery document generation
- Lower operational complexity

**Option C: Existing API Infrastructure**
- Extend existing platform API with OIDC endpoints
- Leverage existing HA, DNS, certificate infrastructure

### Advantages

**vs. Customer-Hosted OIDC Provider:**

| Aspect | Customer-Hosted OIDC | Platform-Hosted OIDC |
|--------|----------------------|---------------------|
| **Customer setup** | Complex (create provider, configure JWKS) | ✅ Simple (point to issuer URL) |
| **Public key exchange** | Required (platform → customer) | ✅ Not required (auto-fetched) |
| **Rotation coordination** | Bootstrap SA needed | ✅ Zero customer involvement |
| **Customer trust boundary** | Customer owns OIDC provider | Platform endpoint trusted |
| **Platform infrastructure** | None (customer hosts) | OIDC service required |
| **Automation** | Requires bootstrap SA | ✅ Fully automated |

**Security Benefits:**
- ✅ **No key exchange**: Public keys never transmitted to customer
- ✅ **Zero customer IAM**: No bootstrap SA permissions required
- ✅ **Full platform control**: Rotation purely platform-managed
- ✅ **Consistent enforcement**: Platform controls verification keys

**Operational Benefits:**
- ✅ **Simpler customer workflow**: Single configuration step (WIF trust)
- ✅ **Automated rotation**: No customer coordination needed
- ✅ **Centralized management**: Platform controls entire OIDC infrastructure
- ✅ **Easier debugging**: Platform owns entire token lifecycle

**Trade-offs:**
- ⚠️ **Infrastructure dependency**: Platform must run production OIDC service
- ⚠️ **Trust model**: Customer must trust platform's OIDC endpoint (acceptable for managed service)
- ⚠️ **Operational burden**: Platform responsible for HA, DNS, certificates
- ⚠️ **New attack surface**: Publicly accessible OIDC endpoints (mitigated by standard security practices)

### Security Posture

**Attack Surface:**
- Public HTTPS endpoints (OIDC discovery, JWKS)
- DNS infrastructure (domain ownership critical)
- TLS certificates

**Mitigations:**
- HTTPS only (TLS 1.3, strong ciphers)
- Rate limiting on OIDC endpoints
- DDoS protection (Cloud Armor, CDN)
- DNS security (DNSSEC, domain lock)
- Certificate rotation and monitoring
- Audit logging (access to JWKS endpoints)

**Isolation:**
- JWKS per cluster (separate URLs: `/{cluster-id}/...`)
- No shared keys or endpoints between clusters
- Public keys only (private keys never exposed via OIDC endpoint)

### Deployment Architecture

```
Platform GCP Project (per region):
├── Cloud Run Service: oidc-endpoint-service
│   ├── Serves: OIDC discovery + JWKS endpoints
│   ├── Reads: Public keys from GSM/KMS
│   └── Scaling: Auto (based on request load)
│
├── Cloud Load Balancer: oidc.gcp-hcp.com
│   ├── Backend: oidc-endpoint-service (Cloud Run)
│   ├── TLS: Managed certificate
│   └── CDN: Optional caching
│
├── Cloud Armor: DDoS protection
│   └── Rate limiting per source IP
│
└── Cloud DNS: oidc.gcp-hcp.com
    └── A record → Load Balancer IP
```

### Monitoring and SLOs

**Metrics:**
- OIDC endpoint availability (uptime %)
- JWKS fetch latency (p50, p95, p99)
- Request rate per cluster
- Error rate (4xx, 5xx)
- Certificate expiration

**SLO:**
- 99.9% availability for OIDC endpoints
- p95 latency < 200ms for JWKS fetches

### Integration with Key Storage Options

Platform-hosted OIDC is **compatible with all key storage options**:

**ESO + GSM:**
- Private key stored in GSM (per-cluster secret)
- Platform reads public key from GSM to update JWKS
- Control-plane uses ESO-synced K8s Secret for signing

**KMS + External Signer:**
- Private key in KMS (never extracted)
- Platform calls KMS API to fetch public key for JWKS
- Control-plane sidecar calls KMS for signing

**Recommended:** ESO + GSM provides best balance of security, DR, and HyperShift compatibility.

---

## Bootstrap Approaches

### Overview

With platform-hosted OIDC endpoints, the bootstrap process is dramatically simplified. The customer never handles public or private keys - they only configure their Workload Identity Pool to trust the platform's issuer URL.

**Chosen Approach**: Platform-generated keypairs with platform-hosted OIDC.

---

### Platform-Generated Keypairs with Platform-Hosted OIDC

**Workflow:**

1. **Customer initiates cluster creation**
   ```bash
   gcphcp cluster create \
     --cluster-name=prod-cluster \
     --region=us-central1 \
     --customer-project-id=my-gcp-project
   ```

2. **Platform generates keypair** (atomic operation during cluster creation)
   - CLS creates control-plane namespace: `clusters-{uuid}`
   - CLS launches Kubernetes Job in namespace
   - Job generates RSA keypair (or creates KMS key)
   - Job stores private key in GSM/KMS with namespace IAM bindings
   - Job publishes public key to platform OIDC JWKS endpoint
   - **Issuer URL returned to customer**: `https://oidc.gcp-hcp.com/{cluster-id}`

3. **Customer configures Workload Identity Pool** (one-time setup)
   ```bash
   gcloud iam workload-identity-pools providers create-oidc prod-cluster-oidc \
     --location=global \
     --workload-identity-pool=my-wif-pool \
     --issuer-uri=https://oidc.gcp-hcp.com/{cluster-id} \
     --allowed-audiences=gcp
   ```
   - Customer does NOT need public key (GCP fetches from platform JWKS endpoint)
   - Customer does NOT create bootstrap SA (no rotation permissions needed)

4. **Cluster becomes operational**
   - Control-plane signs tokens using private key from GSM/KMS
   - Tokens include issuer: `https://oidc.gcp-hcp.com/{cluster-id}`
   - Customer GCP verifies tokens by fetching JWKS from platform endpoint

**Advantages:**
- ✅ **Zero key exposure**: Customer never handles keys (public or private)
- ✅ **Single-step workflow**: Customer only configures WIF trust
- ✅ **No key exchange**: Public key served via OIDC endpoint (auto-fetched by GCP)
- ✅ **No bootstrap SA**: No customer IAM permissions needed for rotation
- ✅ **Fully automated**: Platform controls entire lifecycle
- ✅ **No orphaned resources**: Keypair created atomically with cluster

**Comparison to Alternatives:**

| Aspect | Customer-Provided Key | Platform-Gen + Customer OIDC | Platform-Gen + Platform OIDC (CHOSEN) |
|--------|----------------------|------------------------------|--------------------------------------|
| **Customer handles private key** | ❌ Yes (bootstrap) | ✅ Never | ✅ Never |
| **Customer handles public key** | ❌ Yes (OIDC setup) | ❌ Yes (OIDC setup) | ✅ Never (auto-fetched) |
| **Customer workflow steps** | 2 (generate + create) | 2 (get key + create) | **1 (create + configure WIF)** |
| **Bootstrap SA required** | ✅ Yes | ✅ Yes | ✅ **No** |
| **Key exchange** | Network (customer → CLS) | API (platform → customer) | ✅ **None** (OIDC endpoint) |
| **Rotation customer involvement** | Bootstrap SA needed | Bootstrap SA needed | ✅ **Zero** |
| **REQ-1 compliance** | ⚠️ Partial (bootstrap) | ✅ Full | ✅ Full |
| **REQ-3 compliance** | ❌ Fails (CLS sees key) | ✅ Full | ✅ Full |

**CLS Database Schema** (metadata only):

```
keypairs table:
- id (UUID, primary key)
- cluster_id (foreign key, unique)
- region (string)
- storage_type (enum: gsm, kms)
- storage_location (string: GSM secret name or KMS key name)
- oidc_issuer_url (string: platform OIDC endpoint)
- created_at (timestamp)
- last_rotated_at (timestamp, nullable)
```

**No secrets stored in database** - only references to GSM/KMS resources and OIDC endpoint URLs.

---

## HyperShift HostedCluster Architecture Constraint

### Critical Design Constraint

**HyperShift HostedCluster spec requires** a reference to a Kubernetes Secret containing the service account signing key. This architectural constraint significantly impacts the viable options for key storage.

### HostedCluster Resource Structure

```
Management Cluster:
├── Namespace: clusters (or HostedCluster namespace)
│   └── HostedCluster CR: prod-cluster
│       └── spec.serviceAccountSigningKey:
│           name: "prod-cluster-sa-key"  (reference to K8s Secret)
│
└── Namespace: clusters-prod-cluster (control-plane namespace)
    ├── Secret: prod-cluster-sa-key (REQUIRED - referenced by HostedCluster)
    │   └── Contains: private key for signing
    │
    └── Pods: kube-apiserver, etc.
        └── Mount Secret from control-plane namespace
```

**Key Points**:
1. HostedCluster resource lives in a separate namespace (often `clusters` or similar)
2. HostedCluster spec.serviceAccountSigningKey must reference a Kubernetes Secret
3. The Secret must exist in the HostedCluster namespace OR control-plane namespace
4. HostedCluster namespace typically has NO pods running (only resources)
5. Control-plane namespace has all the running pods (kube-apiserver, etc.)

### Impact on Storage Options

This constraint means:

**ESO (External Secrets Operator)**:
- ✅ **Viable**: ExternalSecret syncs from GSM → K8s Secret in target namespace
- ✅ Can create Secret in HostedCluster namespace or control-plane namespace
- ✅ HostedCluster references the synced Secret
- ✅ Standard K8s Secret pattern that HyperShift expects

**CSI Driver**:
- ❌ **Problematic**: CSI driver mounts secrets into pods via volumes
- ❌ HostedCluster namespace has no pods (cannot use CSI mount)
- ⚠️ Could potentially work if Secret created in control-plane namespace and referenced from HostedCluster
- ⚠️ Adds complexity: CSI mount in control-plane, but HostedCluster needs reference
- **Conclusion**: CSI doesn't align well with HyperShift's Secret reference pattern

**KMS External Signer**:
- ❌ **Potentially Incompatible**: Requires `--service-account-signing-endpoint` flag
- ❌ HyperShift spec expects Secret reference, not external endpoint configuration
- ❓ **Unknown**: Does HyperShift support configuring external signer endpoint?
- ❓ If not supported, would require HyperShift API changes
- **Conclusion**: Feasibility depends on HyperShift capability (research needed)

### Recommended Approach Given Constraint

**External Secrets Operator (ESO) emerges as the most compatible option** because:
1. Creates standard K8s Secret that HyperShift expects
2. Secret can be created in appropriate namespace (HostedCluster or control-plane)
3. No pod volume mounts required (Secret is just data)
4. ESO handles syncing from GSM with strong WIF-based isolation
5. Aligns with HyperShift's existing architecture assumptions

---

## Key Storage and Signing Options

After bootstrap (either approach), the cluster's signing key must be stored and used for token signing. The options below are evaluated against the HyperShift HostedCluster constraint and backup/DR requirements.

### Option 0: Plain Kubernetes Secret Only (Baseline)

**Architecture**:

```
Control-Plane Namespace (per cluster)
└── Pod: kube-apiserver
    └── Mounts K8s Secret: sa-signing-key (created during cluster setup)
        Uses standard flag: --service-account-signing-key-file=/path/to/secret
```

**How It Works**:
- Private key provided during cluster creation (customer-provided or platform-generated)
- Stored directly as Kubernetes Secret in control-plane namespace
- No external storage (GSM/KMS)
- kube-apiserver mounts Secret as file (standard pattern)

**Advantages**:
- ✅ Simplest approach (no additional dependencies)
- ✅ Zero operational complexity (standard K8s pattern)
- ✅ No external service dependencies (GSM/KMS)
- ✅ No cost beyond cluster resources
- ✅ Fully compatible with HyperShift (standard Secret reference)
- ✅ Strong isolation (namespace-scoped Secrets)

**Disadvantages**:
- ❌ **No independent backup** (only via etcd backups)
- ❌ **Backup coupled to management cluster lifecycle** (lost if cluster destroyed)
- ❌ **No version history** (Secret updates overwrite previous versions)
- ❌ **Recovery requires etcd restore** (complex, may not be granular per-cluster)
- ❌ **No cross-region availability** (Secret tied to single cluster)
- ⚠️ Rotation requires manual Secret updates and kube-apiserver restarts
- ⚠️ Private key stored in etcd (encrypted at rest, but extractable)

**Disaster Recovery Limitations**:
- If management cluster is destroyed, signing keys are lost unless:
  - Full etcd backup exists and is restorable
  - Keys were backed up externally by other means
- Cannot migrate cluster to different management cluster without key
- No recovery from accidental Secret deletion (unless etcd backup exists)

**Operational Complexity**: Lowest

**Security Posture**: Good for isolation, but poor for disaster recovery (violates REQ-6)

**When to Use**:
- Early prototyping or development environments where DR is not critical
- First implementation phase (MVP) before adding GSM/KMS
- Environments where etcd backup/restore is well-established and tested

**Limitations for Production**:
- Does not meet REQ-6 (disaster recovery) without robust etcd backup strategy
- Rotation automation more complex (no external secret versioning)
- Cannot easily recover individual cluster keys without full etcd restore

---

### Option 1: Google Secret Manager with External Secrets Operator

**Architecture**:

```
Control-Plane Namespace (per cluster)
├── Kubernetes ServiceAccount: kube-apiserver
│   └── Workload Identity binding: access to cluster-specific GSM secrets only
│
├── SecretStore (namespaced External Secrets resource)
│   └── References: serviceAccountName: kube-apiserver
│       (ESO uses this SA's WIF identity for GSM access)
│
├── ExternalSecret (namespaced)
│   └── References: SecretStore
│       Fetches from GSM: cluster-{id}-sa-signing-key-current
│       Syncs to K8s Secret: sa-signing-key
│
└── Pod: kube-apiserver
    └── Mounts K8s Secret: sa-signing-key
        Uses standard flag: --service-account-signing-key-file=/path/to/secret
```

**How It Works**:

- Private key stored in Google Secret Manager (platform region project)
- External Secrets Operator (ESO) deployed on management cluster
- Each control-plane namespace has namespaced SecretStore resource
- SecretStore references namespace's Kubernetes ServiceAccount (e.g., `kube-apiserver`)
- ESO controller uses pod's ServiceAccount via Workload Identity to access GSM
- ESO syncs GSM secret → Kubernetes Secret in control-plane namespace
- kube-apiserver mounts Kubernetes Secret as file (standard pattern)
- No changes to kube-apiserver configuration (uses standard signing key file flag)

**Isolation Mechanism**:

- Each namespace has unique Kubernetes ServiceAccount
- Each SA has unique Workload Identity principal (includes namespace in subject)
- GSM secret has IAM binding granting access only to specific namespace SA
- GCP IAM enforces isolation: namespace A's SA cannot access namespace B's GSM secret

**Key Rotation**:

- Update GSM secret version with new private key
- ESO polls GSM (configurable interval, e.g., 1 minute)
- ESO syncs new version to Kubernetes Secret
- kube-apiserver pods restart to pick up new key
- During restart, grace period with old key still in OIDC JWKS ensures zero downtime

**Advantages**:

- ✅ Zero changes to kube-apiserver pod spec (standard K8s secret mount)
- ✅ Strong isolation via Workload Identity + namespace-scoped SAs
- ✅ Private key encrypted at rest in GSM
- ✅ Familiar Kubernetes Secret pattern
- ✅ ESO is widely adopted, well-maintained
- ✅ No JSON service account keys required (native WIF support)

**Disadvantages**:

- ⚠️ Private key stored in Kubernetes Secret (etcd, though encrypted at rest)
- ⚠️ Dependency on External Secrets Operator
- ⚠️ ESO sync lag (delay between GSM update and K8s secret sync)
- ⚠️ Private key exists in GSM (encrypted, but extractable)

**Operational Complexity**: Low - standard ESO deployment, familiar K8s patterns

**Security Posture**: Good - encrypted storage, strong isolation, but private key exists and is extractable

---

### Option 2: Google Secret Manager with CSI Driver

**Architecture**:

```
Control-Plane Namespace (per cluster)
├── Kubernetes ServiceAccount: kube-apiserver
│   └── Workload Identity binding: access to cluster-specific GSM secrets only
│
├── SecretProviderClass (namespaced)
│   └── Specifies: GSM secret to mount, path in pod
│
└── Pod: kube-apiserver
    ├── Volume: CSI driver volume
    │   └── Configured via SecretProviderClass
    │       CSI driver uses pod's SA (kube-apiserver) to access GSM
    │       Mounts GSM secret as file directly into pod
    │
    └── Container: kube-apiserver
        Uses standard flag: --service-account-signing-key-file=/mnt/secrets/sa.key
```

**How It Works**:

- Private key stored in Google Secret Manager (platform region project)
- Google Secret Manager CSI Driver deployed on management cluster nodes
- Each control-plane namespace has SecretProviderClass resource
- kube-apiserver pod spec includes CSI volume mount
- CSI driver uses pod's ServiceAccount via Workload Identity to fetch GSM secret
- Secret mounted as file directly into pod (ephemeral, not stored in etcd)
- kube-apiserver uses mounted file (standard signing key file flag)

**Isolation Mechanism**:

- Same as ESO approach: namespace-scoped SA with WIF binding to GSM secret
- GCP IAM enforces per-namespace access control

**Key Rotation**:

- Update GSM secret version with new private key
- CSI driver polls GSM (configurable interval)
- CSI driver updates mounted file in running pod
- kube-apiserver must detect file change and reload (or restart)

**Advantages**:

- ✅ Private key NOT stored in Kubernetes Secret/etcd (ephemeral mount)
- ✅ Native GCP integration (first-party CSI driver)
- ✅ Strong isolation via Workload Identity + namespace-scoped SAs
- ✅ Private key encrypted at rest in GSM
- ✅ Simpler dependency (no third-party operator like ESO)

**Disadvantages**:

- ⚠️ Requires changes to kube-apiserver pod spec (CSI volume mount)
- ⚠️ HyperShift must support CSI volume configuration in control-plane pods
- ⚠️ Private key exists in GSM (encrypted, but extractable)
- ⚠️ File reload mechanism: kube-apiserver may need restart on rotation

**Operational Complexity**: Low-Medium - requires pod spec changes, HyperShift validation needed

**Security Posture**: Good - slightly better than ESO (not in etcd), but private key still exists in GSM

---

### Option 3: Cloud KMS with External Signer Sidecar

**Architecture**:

```
Control-Plane Namespace (per cluster)
├── Kubernetes ServiceAccount: kms-jwt-signer
│   └── Workload Identity binding: access to cluster-specific KMS key only
│
└── Pod: kube-apiserver
    ├── Container: kms-jwt-signer (sidecar)
    │   ├── Uses Management Cluster ServiceAccount: kms-jwt-signer
    │   │   (gets token from Management Cluster kube-apiserver, no circular dependency)
    │   ├── Authenticates to platform KMS via Workload Identity
    │   ├── Implements gRPC ExternalJWTSigner interface
    │   └── Exposes Unix domain socket: /var/run/kms-signer.sock
    │
    └── Container: kube-apiserver
        Uses external signer flag: --service-account-signing-endpoint=unix:///var/run/kms-signer.sock
        (Instead of --service-account-signing-key-file)
```

**How It Works**:

- Private key NEVER extracted from Cloud KMS (HSM-backed)
- KMS key created in platform region project during keypair generation
- Sidecar container (kms-jwt-signer) runs alongside kube-apiserver
- Sidecar uses its Management Cluster ServiceAccount to get token from MC kube-apiserver (standard file-based signing, no circular dependency)
- Sidecar authenticates to platform KMS using that token via Workload Identity
- Sidecar implements Kubernetes External JWT Signer gRPC interface
- kube-apiserver calls sidecar via Unix domain socket to sign tokens
- Sidecar calls Cloud KMS asymmetric signing API
- KMS returns signature (private key never leaves KMS HSM)
- Sidecar returns signed JWT to kube-apiserver

**No Circular Dependency** (Key Insight):

- kms-jwt-signer runs in Management Cluster namespace (e.g., `clusters-{id}`)
- kms-jwt-signer has Management Cluster ServiceAccount
- Management Cluster kube-apiserver signs tokens for Management Cluster SAs (standard setup)
- kms-jwt-signer uses this MC token to authenticate to KMS via WIF
- Customer workload tokens (in hosted cluster) are signed by KMS, not MC kube-apiserver

**Why Platform KMS, Not Customer KMS?**

An alternative approach would be to place the KMS key in the **customer's GCP project** instead of the platform region project. However, this creates an **unsolvable circular dependency**:

```
Problem with Customer-Side KMS:

1. kms-jwt-signer sidecar needs to call customer KMS to sign tokens
2. To call customer KMS, sidecar must authenticate via Workload Identity
3. WIF requires a service account token to authenticate
4. Sidecar has Management Cluster SA, gets token from MC kube-apiserver ✓
5. BUT: Customer must grant this SA access to their KMS key
6. Customer IAM binding requires knowing the SA principal identity
7. SA principal includes namespace: ns/clusters-{id}/sa/kms-jwt-signer
8. Namespace doesn't exist until cluster is created
9. Cluster can't be created without KMS key access
10. ❌ Chicken-and-egg: can't create cluster without access, can't grant access without cluster

Bootstrap Challenge:
- Customer would need to grant KMS access BEFORE cluster exists
- But cluster ID/namespace is generated during creation
- Pre-creating namespace defeats isolation benefits
- Requires customer to trust platform with broad KMS access patterns
```

**Platform KMS Solution**:

By placing KMS keys in the **platform region project**:
- ✅ Platform controls IAM bindings (no customer coordination needed)
- ✅ Namespace can be created first, then IAM binding configured atomically
- ✅ No bootstrap chicken-and-egg problem
- ✅ Easier cluster migration between management clusters (same region project)
- ⚠️ Trade-off: Customer doesn't own the KMS key (similar trust model to platform-managed GSM)

**Customer Control**:
- Customer still controls OIDC provider (public key verification)
- Customer can audit signing operations via their OIDC access logs
- Customer grants bootstrap SA permission to update OIDC JWKS
- If customer distrusts platform, they can use customer-provided bootstrap keys instead

**Conclusion**: Platform KMS is the only viable KMS option due to bootstrap constraints. Customer KMS creates circular dependency that cannot be resolved without pre-coordination or broad platform access grants.

**Isolation Mechanism**:

- Each control-plane namespace has unique kms-jwt-signer SA
- Each SA has unique Workload Identity principal (includes namespace)
- KMS key has IAM binding granting access only to specific namespace SA
- GCP IAM enforces isolation: namespace A's SA cannot call namespace B's KMS key

**Key Rotation**:

- Cloud KMS automatic key rotation (configurable, default 90 days)
- New KMS key version created automatically
- Platform component fetches new public key from KMS
- Platform component updates customer OIDC JWKS with new public key
- Zero kube-apiserver changes (KMS handles version management)

**Advantages**:

- ✅ **Private key NEVER leaves KMS HSM** (maximum security)
- ✅ Strong isolation via Workload Identity + namespace-scoped SAs
- ✅ KMS automatic key rotation (90-day default, configurable)
- ✅ Private key never extractable (even by platform operators)
- ✅ Cloud KMS audit logs for all signing operations
- ✅ Meets highest security standards (HSM-backed crypto)
- ✅ No circular dependency (uses MC ServiceAccount tokens)

**Disadvantages**:

- ❌ Requires changes to kube-apiserver configuration (external signer endpoint)
- ❌ Requires sidecar container in control-plane pod
- ❌ HyperShift must support external signing endpoint configuration
- ⚠️ Latency: external KMS call per token signature (~50-100ms)
- ⚠️ Cost: KMS signing operations (~$0.03 per 10k operations)
- ⚠️ Dependency on Cloud KMS availability

**Performance Considerations**:

- Token signing is infrequent (kubelet caches tokens, refreshes at 80% TTL)
- Estimated signing rate: 10-100 signatures/minute per cluster
- Latency acceptable for token signing (not on critical path for app requests)

**Cost Considerations**:

- Estimated 100k signatures/month/cluster
- Cost: ~$0.30/cluster/month (negligible)

**Operational Complexity**: High - custom sidecar, gRPC implementation, HyperShift validation required

**Security Posture**: Best - private key never leaves HSM, not extractable by anyone

---

### Comparison: Key Storage and Signing Options

| Aspect | Plain K8s Secret | ESO + GSM | CSI Driver + GSM | KMS + External Signer |
|--------|-----------------|-----------|------------------|----------------------|
| **HyperShift compatibility** | ✅ **Fully compatible** | ✅ **Fully compatible** (syncs to K8s Secret) | ⚠️ **Problematic** (CSI mount doesn't align) | ❌ **Unknown/Incompatible** (may need API changes) |
| **kube-apiserver changes** | ✅ None | ✅ None (standard secret mount) | ⚠️ CSI volume mount | ❌ External signer endpoint + sidecar |
| **Backup/DR** | ❌ **etcd only** (REQ-6 issue) | ✅ Independent (GSM) | ✅ Independent (GSM) | ✅ Independent (KMS HSM) |
| **Key recovery** | ❌ Requires etcd restore | ✅ Per-cluster granular | ✅ Per-cluster granular | ✅ Per-cluster granular |
| **Multi-region DR** | ❌ Single cluster only | ✅ GSM multi-region | ✅ GSM multi-region | ✅ KMS multi-region |
| **Version history** | ❌ None (overwrites) | ✅ GSM versions | ✅ GSM versions | ✅ KMS versions |
| **Private key extractable** | ⚠️ Yes (etcd) | ⚠️ Yes (GSM or etcd) | ⚠️ Yes (GSM) | ✅ No (never leaves KMS HSM) |
| **Private key location** | K8s Secret (etcd) | GSM + K8s Secret (etcd) | GSM + pod mount (ephemeral) | KMS HSM only |
| **Isolation strength** | ✅ Strong (namespace-scoped) | ✅ Strong (WIF + namespace SA) | ✅ Strong (WIF + namespace SA) | ✅ Strong (WIF + namespace SA) |
| **Rotation handling** | Manual Secret update | ESO polls GSM, syncs to K8s | CSI polls GSM, updates mount | KMS automatic, update OIDC JWKS |
| **Dependencies** | None | External Secrets Operator | Secret Manager CSI Driver | Custom sidecar (kms-jwt-signer) |
| **Operational complexity** | ✅ Lowest | Low | Medium | High |
| **HyperShift validation** | ✅ Standard pattern | ✅ Works as-is | ⚠️ Complex workaround needed | ❌ Requires HyperShift API support |
| **Security posture** | Fair | Good | Good | Best (HSM-backed) |
| **Cost** | $0 | GSM storage (~$0.12/month) | GSM storage (~$0.12/month) | KMS operations (~$0.30/month) |
| **Latency** | None | None (in-memory key) | None (mounted file) | ~50-100ms per signature |
| **REQ-1 compliance** | ⚠️ Partial (key in etcd) | ⚠️ Partial (key stored) | ⚠️ Partial (key stored) | ✅ Full (key in HSM only) |
| **REQ-3 compliance** | ✅ Yes (namespace isolation) | ✅ Yes (namespace isolation) | ✅ Yes (namespace isolation) | ✅ Yes (namespace isolation) |
| **REQ-6 compliance** | ❌ **Fails** (no independent backup) | ✅ Full | ✅ Full | ✅ Full |
| **Deployment readiness** | ✅ **Ready now** (simplest) | ✅ **Ready now** | ⚠️ **Needs investigation** | ❌ **Blocked on HyperShift support** |

**Key Insight**: Plain Kubernetes Secret is the simplest option but **fails REQ-6 (disaster recovery)**. This is the primary driver for adopting GSM or KMS - not just security, but operational resilience.

**Critical Note**: HyperShift HostedCluster spec requires a Kubernetes Secret reference for the signing key. This architectural constraint makes **ESO + GSM** the most viable option that balances DR requirements with HyperShift compatibility.

---

## Rotation Strategies

Regardless of storage/signing option, key rotation strategies are critical for security and compliance.

### Zero-Downtime Rotation with Platform-Hosted OIDC

**Key Principle**: OIDC JWKS supports multiple public keys simultaneously. During rotation, both old and new keys are trusted for a grace period.

**Simplified Rotation Flow** (with platform-hosted OIDC):

```
Before Rotation:
  Private Key: Key-A (current) in GSM/KMS
  Platform OIDC JWKS: [Key-A public]
  Tokens: Signed with Key-A, verified with Key-A from platform endpoint

Rotation Triggered (Day 30):
  Step 1: Platform generates Key-B (new keypair)
  Step 2: Platform stores Key-B in GSM/KMS (new secret version or KMS key version)
  Step 3: Platform updates JWKS endpoint: [Key-A public, Key-B public]  ← Both trusted
  Step 4: Platform updates control-plane to sign with Key-B:
    - ESO: Syncs new K8s secret, restarts kube-apiserver
    - KMS: Sidecar uses new KMS key version automatically

Grace Period (1-2 hours):
  Private Keys: Key-A (previous), Key-B (current)
  Platform OIDC JWKS: [Key-A public, Key-B public]
  New tokens: Signed with Key-B, verified with Key-B (from platform JWKS)
  Existing tokens: Signed with Key-A, verified with Key-A (from platform JWKS)
  Customer GCP: Fetches both keys from platform JWKS, accepts both

After Grace Period:
  Step 5: Platform removes Key-A public from JWKS endpoint
  Platform OIDC JWKS: [Key-B public]
  Tokens: All new tokens signed with Key-B, verified with Key-B
  Key-A: Archived in GSM/KMS (for audit/recovery)
```

**Zero Customer Involvement:**
- ✅ No customer IAM permissions required
- ✅ No customer OIDC provider updates
- ✅ No bootstrap SA
- ✅ No customer API calls
- ✅ Fully automated platform operation

**Compared to Customer-Hosted OIDC:**

| Rotation Step | With Bootstrap SA (old) | With Platform OIDC (NEW) |
|---------------|------------------------|--------------------------|
| Generate new key | Platform | Platform |
| Store new key | Platform (GSM/KMS) | Platform (GSM/KMS) |
| Update OIDC JWKS | **Customer** (via bootstrap SA) | ✅ **Platform** (direct JWKS update) |
| Update control-plane | Platform | Platform |
| Grace period | Platform waits | Platform waits |
| Remove old key | **Customer** (via bootstrap SA) | ✅ **Platform** (direct JWKS update) |

### Platform-Managed Automated Rotation

**Concept**: Platform automatically rotates keys on a schedule without customer action or coordination.

**Components**:

- Rotation controller (Kubernetes controller or CronJob) per cluster or per management cluster
- Configurable rotation frequency per cluster (default: 30-90 days)
- No customer coordination or approval needed

**Rotation Logic**:

1. Check if rotation due (based on last rotation date + frequency)
2. Generate new keypair (or trigger KMS rotation)
3. Store new private key (GSM secret version or KMS key version)
4. Fetch new public key
5. Update platform OIDC JWKS endpoint (append new key)
6. Update control-plane to use new key (restart kube-apiserver if needed)
7. Wait grace period (1-2 hours)
8. Remove old public key from platform OIDC JWKS
9. Archive old private key (mark as rotated in GSM/KMS)
10. Update metrics and audit logs

**Benefits**:

- ✅ Meets REQ-4 (automated rotation)
- ✅ Zero customer operational burden
- ✅ No customer IAM permissions required
- ✅ Ensures compliance with rotation policies
- ✅ Consistent rotation across all clusters

**Failure Handling**:

- Retry logic for each step
- Rollback capability (revert to old key if new key fails)
- Alerting on rotation failures
- Continue using current key if rotation fails (no outage)

### Customer-Initiated Manual Rotation

**Concept**: Customer can trigger immediate rotation via CLI or API (e.g., after suspected key compromise).

**Workflow**:

```bash
gcphcp cluster keys rotate prod-cluster --now
```

**Behind the scenes**:
- Customer calls CLS API
- CLS triggers rotation job (same process as automated rotation)
- Customer sees status: "Rotation in progress, estimated 10 minutes"
- Rotation completes without customer action

**Benefits**:

- ✅ Meets REQ-5 (customer-initiated rotation)
- ✅ Rapid response to security incidents
- ✅ Customer control and visibility
- ✅ No customer involvement in actual rotation (just triggers it)

**Challenges**:

- Must bypass normal rotation schedule guards (e.g., "rotated less than 7 days ago")
- Must handle concurrent rotation requests gracefully
- Customer expectations: rotation is not instant (takes several minutes)

---

## Isolation Mechanisms

All proposed options rely on **per-namespace Kubernetes ServiceAccounts** with **Workload Identity Federation** for GCP access. This section explains the isolation enforcement.

### Namespace-Scoped Service Accounts

**Architecture**:

- Each hosted cluster's control-plane runs in a dedicated namespace on the management cluster
- Namespace name is deterministic based on cluster ID: `clusters-{id}`
- Each namespace has dedicated Kubernetes ServiceAccounts (e.g., `kube-apiserver`, `kms-jwt-signer`)
- ServiceAccounts are namespace-scoped (cannot be used across namespaces)

**Example**:

```
Management Cluster:
├── Namespace: clusters-abc123
│   ├── ServiceAccount: kube-apiserver
│   └── ServiceAccount: kms-jwt-signer (if using KMS option)
│
├── Namespace: clusters-def456
│   ├── ServiceAccount: kube-apiserver
│   └── ServiceAccount: kms-jwt-signer (if using KMS option)
│
└── Namespace: clusters-ghi789
    ├── ServiceAccount: kube-apiserver
    └── ServiceAccount: kms-jwt-signer (if using KMS option)
```

### Workload Identity Federation Principals

**Workload Identity Principal Format**:

```
principal://iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global/workloadIdentityPools/{PROJECT_ID}.svc.id.goog/subject/ns/{NAMESPACE}/sa/{SA_NAME}
```

**Key Property**: Namespace is part of the principal identity.

**Example Principals**:

```
Cluster ABC123 kube-apiserver SA:
principal://iam.googleapis.com/projects/123456789/locations/global/workloadIdentityPools/platform-region-us-central1.svc.id.goog/subject/ns/clusters-abc123/sa/kube-apiserver

Cluster DEF456 kube-apiserver SA:
principal://iam.googleapis.com/projects/123456789/locations/global/workloadIdentityPools/platform-region-us-central1.svc.id.goog/subject/ns/clusters-def456/sa/kube-apiserver
```

**Different namespaces = different principals = isolated identities**.

### GCP IAM Bindings (Isolation Enforcement)

**Per-Resource IAM Binding**:

Each GSM secret or KMS key has an IAM binding granting access to exactly one namespace's ServiceAccount.

**Example (GSM secret for cluster ABC123)**:

```
GSM Secret: cluster-abc123-sa-signing-key-current
IAM Binding:
  Role: roles/secretmanager.secretAccessor
  Member: principal://iam.googleapis.com/projects/123456789/locations/global/workloadIdentityPools/platform-region-us-central1.svc.id.goog/subject/ns/clusters-abc123/sa/kube-apiserver
```

**Enforcement**:

- Cluster ABC123's `kube-apiserver` SA can access this secret
- Cluster DEF456's `kube-apiserver` SA **cannot** access this secret (different principal, no IAM binding)
- GCP IAM service enforces this at API layer

**Example (KMS key for cluster ABC123)**:

```
KMS Key: cluster-abc123-sa-signing-key
IAM Binding:
  Role: roles/cloudkms.signerVerifier
  Member: principal://iam.googleapis.com/projects/123456789/locations/global/workloadIdentityPools/platform-region-us-central1.svc.id.goog/subject/ns/clusters-abc123/sa/kms-jwt-signer
```

**Enforcement**: Same as GSM - only cluster ABC123's sidecar can call this KMS key.

### Isolation Validation

**Test Scenario**: Attempt cross-namespace access

```
From pod in namespace clusters-abc123 using SA kube-apiserver:
  Attempt to access GSM secret: cluster-def456-sa-signing-key-current
  Result: HTTP 403 Forbidden (Permission Denied)
  Reason: No IAM binding for clusters-abc123 SA on def456 secret

From pod in namespace clusters-def456 using SA kube-apiserver:
  Attempt to access KMS key: cluster-abc123-sa-signing-key
  Result: HTTP 403 Forbidden (Permission Denied)
  Reason: No IAM binding for clusters-def456 SA on abc123 KMS key
```

**Isolation Strength**: Infrastructure-enforced (GCP IAM), not application-logic dependent.

### Compliance with Requirements

- ✅ REQ-2: Each cluster has unique key, isolated by namespace + WIF principal
- ✅ REQ-3: Shared components (CLS, Hypershift operator) do not have access (different namespaces/SAs)

---

## Customer Experience

### Cluster Creation Workflow (Platform-Hosted OIDC)

**Step 1: Create Cluster**

```bash
gcphcp cluster create \
  --cluster-name=prod-cluster \
  --region=us-central1 \
  --customer-project-id=my-gcp-project
```

**Behind the Scenes:**
- Platform generates keypair (atomic with cluster creation)
- Platform stores private key in GSM/KMS (per-cluster)
- Platform publishes public key to OIDC JWKS endpoint
- Platform provisions control-plane infrastructure

**CLI Output:**
```
Cluster creation initiated.

Cluster ID: prod-cluster-abc123
Region: us-central1
OIDC Issuer URL: https://oidc.gcp-hcp.com/prod-cluster-abc123

Next step:
Configure Workload Identity Federation in your GCP project to trust this issuer:

  gcloud iam workload-identity-pools providers create-oidc prod-cluster-oidc \
    --location=global \
    --workload-identity-pool=YOUR_WIF_POOL \
    --issuer-uri=https://oidc.gcp-hcp.com/prod-cluster-abc123 \
    --allowed-audiences=gcp

Estimated time to ready: 10-15 minutes
Monitor: gcphcp cluster status prod-cluster-abc123
```

**Step 2: Configure Workload Identity Federation**

Customer creates WIF provider in their GCP project:

```bash
# Create Workload Identity Pool (if not exists)
gcloud iam workload-identity-pools create my-wif-pool \
  --location=global \
  --display-name="GCP HCP Clusters"

# Create OIDC Provider pointing to platform issuer
gcloud iam workload-identity-pools providers create-oidc prod-cluster-oidc \
  --location=global \
  --workload-identity-pool=my-wif-pool \
  --issuer-uri=https://oidc.gcp-hcp.com/prod-cluster-abc123 \
  --allowed-audiences=gcp
```

**That's it.** No public key handling, no bootstrap SA, no IAM permissions for rotation.

**Step 3: Grant IAM Bindings (Standard WIF)**

Customer grants workload access to GCP resources (standard WIF pattern):

```bash
gcloud projects add-iam-policy-binding my-gcp-project \
  --member="principal://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/my-wif-pool/subject/system:serviceaccount:default:my-app-sa" \
  --role="roles/storage.objectViewer"
```

### Key Rotation Visibility

**View Current Key Status:**

```bash
gcphcp cluster keys status prod-cluster-abc123

Output:
Cluster: prod-cluster-abc123
Current Key ID: key-2024-12-17-v1
Last Rotation: 2024-12-17 10:00:00 UTC (0 days ago)
Next Scheduled Rotation: 2025-01-16 10:00:00 UTC (in 30 days)
Rotation Frequency: 30 days
Rotation History:
  - 2024-12-17: Initial key (bootstrap)

OIDC Issuer: https://oidc.gcp-hcp.com/prod-cluster-abc123
Public Keys in JWKS: 1 key (key-2024-12-17-v1)
```

**Trigger Manual Rotation:**

```bash
gcphcp cluster keys rotate prod-cluster-abc123 --now

Output:
Rotation initiated for cluster prod-cluster-abc123.
This is a zero-downtime operation. Estimated duration: 10 minutes.

Status: In Progress
  [✓] New key generated
  [✓] New key stored in GSM
  [✓] JWKS updated with new key (grace period: 2 hours)
  [→] Updating control-plane to use new key
  [ ] Grace period wait
  [ ] Old key removed from JWKS

Monitor: gcphcp cluster keys rotation-status prod-cluster-abc123
```

**Customer never needs to touch their WIF configuration during rotation.**

**Configure Rotation Frequency:**

```bash
gcphcp cluster keys set-frequency prod-cluster-abc123 --days=90

Output:
Rotation frequency updated to 90 days.
Next rotation scheduled for: 2025-03-17 10:00:00 UTC
```

### Comparison: Customer Workflow

| Workflow Step | Customer-Hosted OIDC (old) | Platform-Hosted OIDC (NEW) |
|---------------|----------------------------|---------------------------|
| **Setup: Get public key** | Required (from platform API) | ✅ Not required (OIDC endpoint) |
| **Setup: Create OIDC provider** | Create with public key in JWKS | ✅ Simple - trust issuer URL |
| **Setup: Bootstrap SA** | Create SA, grant IAM permissions | ✅ Not required |
| **Setup: Complexity** | 3-4 steps (key, OIDC, SA) | ✅ **1 step** (trust issuer URL) |
| **Rotation: Customer action** | None (bootstrap SA handles it) | ✅ **None** (platform handles it) |
| **Rotation: Customer IAM** | Bootstrap SA needs permissions | ✅ **No customer IAM** |
| **Rotation: Visibility** | CLI/API status checks | CLI/API status checks |

**Simplification achieved:** Customer workflow reduced from 3-4 steps to 1 step (just configure WIF trust).

---

## Comprehensive Comparison

**Note**: All "Platform-Generated" options below assume **platform-hosted OIDC** (the chosen approach), which eliminates bootstrap SA complexity and provides zero customer involvement in rotation.

### Security Comparison (with Platform-Hosted OIDC)

| Aspect | Current | Plain K8s Secret | Platform OIDC + ESO + GSM (CHOSEN) | Platform OIDC + KMS |
|--------|---------|-----------------|-------------------------------------|---------------------|
| **Private key exposure** | ❌ Customer, network, CLS DB, Hypershift Op | ✅ Control-plane only (etcd) | ✅ Never leaves platform | ✅ Never leaves KMS HSM |
| **Public key exchange** | ❌ Customer receives key | N/A | ✅ **None** (OIDC endpoint) | ✅ **None** (OIDC endpoint) |
| **Shared component access** | ❌ CLS, Hypershift Op have access | ✅ None (namespace-scoped) | ✅ CLS never accesses (only metadata) | ✅ CLS never accesses (only metadata) |
| **Private key storage** | ❌ CLS database (all customers) | ⚠️ etcd only (no external backup) | ✅ GSM (per-cluster, isolated) | ✅ KMS HSM (per-cluster, isolated) |
| **Key extractable** | ❌ Yes (CLS database) | ⚠️ Yes (etcd backup) | ⚠️ Yes (GSM, authorized SA) | ✅ No (never leaves HSM) |
| **Isolation** | ❌ None (shared storage) | ✅ Strong (namespace-scoped) | ✅ Strong (WIF + namespace SA) | ✅ Strong (WIF + namespace SA) |
| **Backup/DR** | ❌ No backup | ❌ **etcd only** (REQ-6 fail) | ✅ Independent (GSM) | ✅ Independent (KMS HSM) |
| **Rotation** | ❌ Not supported | ⚠️ Manual only | ✅ **Fully automated** (zero customer involvement) | ✅ **Fully automated** (zero customer involvement) |
| **Customer IAM for rotation** | N/A | N/A | ✅ **Not required** | ✅ **Not required** |
| **Auditability** | ❌ Minimal | ⚠️ K8s audit logs only | ✅ GSM + rotation logs + OIDC logs | ✅ Cloud KMS audit logs + OIDC logs |
| **REQ-1 compliance** | ❌ Fails | ⚠️ Partial (key in etcd) | ✅ Full | ✅ Full |
| **REQ-2 compliance** | ❌ No isolation | ✅ Full | ✅ Full | ✅ Full |
| **REQ-3 compliance** | ❌ Shared components have access | ✅ Full | ✅ Full | ✅ Full |
| **REQ-6 compliance** | ❌ No backup | ❌ **Fails** (etcd coupling) | ✅ Full | ✅ Full |

### Operational Comparison (with Platform-Hosted OIDC)

| Aspect | Plain K8s Secret | Platform OIDC + ESO + GSM (CHOSEN) | Platform OIDC + KMS |
|--------|-----------------|-------------------------------------|---------------------|
| **Customer workflow** | Manual keypair, create cluster | ✅ **Single step** (create cluster) | ✅ **Single step** (create cluster) |
| **Customer setup complexity** | Medium (handle keys) | ✅ **Minimal** (trust issuer URL) | ✅ **Minimal** (trust issuer URL) |
| **Platform infrastructure** | None (just K8s) | ESO + OIDC endpoint service | KMS sidecar + OIDC endpoint service |
| **Platform components** | None | ESO + OIDC service | KMS sidecar + OIDC service |
| **HyperShift changes** | None | None (standard secret) | ❌ External signer endpoint + sidecar |
| **kube-apiserver changes** | ✅ None | ✅ None | ❌ External endpoint flag + sidecar container |
| **Rotation customer action** | Manual update | ✅ **Zero** (fully automated) | ✅ **Zero** (fully automated) |
| **Rotation platform complexity** | N/A (manual) | Low (update GSM + JWKS, restart) | Low (KMS auto-rotation + JWKS update) |
| **Failure modes** | Secret deletion, etcd issues | ESO sync failures, GSM unavailable, OIDC endpoint down | KMS unavailable, sidecar failures, OIDC endpoint down |
| **Key backup strategy** | ❌ etcd backup only (coupled) | ✅ Independent (GSM versioning) | ✅ Independent (KMS versioning) |
| **Cluster migration** | ❌ Requires key export/import | ✅ Easy (same GSM + OIDC in region) | ✅ Easy (same KMS + OIDC in region) |
| **Operational burden** | ✅ Lowest (but limited DR) | ✅ Low (fully automated) | Medium-High (sidecar + OIDC management) |
| **REQ-4 compliance** | ❌ Manual only | ✅ **Fully automated** | ✅ **Fully automated** |
| **REQ-5 compliance** | ⚠️ Manual Secret update | ✅ Manual rotation trigger supported | ✅ Manual rotation trigger supported |
| **REQ-6 compliance** | ❌ **Fails** (no independent backup) | ✅ Full | ✅ Full |

### Cost Comparison (with Platform-Hosted OIDC)

| Aspect | Plain K8s Secret | Platform OIDC + ESO + GSM (CHOSEN) | Platform OIDC + KMS |
|--------|-----------------|-------------------------------------|---------------------|
| **Storage cost** | $0 (etcd included) | GSM: ~$0.06/secret/month = $0.06 | KMS key: $1/month (includes rotation) |
| **Operation cost** | $0 | GSM access: ~free (infrequent) | KMS signing: ~$0.03/10k ops, ~100k/month = $0.30 |
| **OIDC endpoint cost** | $0 | Shared platform cost (Cloud Run/LB/CDN) | Shared platform cost (Cloud Run/LB/CDN) |
| **Total per cluster** | **$0** | **~$0.06/month** (+ shared OIDC) | **~$1.30/month** (+ shared OIDC) |
| **Cost at scale (1000 clusters)** | $0 | $60/month (+ OIDC infrastructure ~$100-200/month) | $1,300/month (+ OIDC infrastructure ~$100-200/month) |

**Note**: OIDC endpoint infrastructure (Cloud Run, Load Balancer, CDN, DNS) is shared across all clusters, adding ~$100-200/month platform-wide cost. Per-cluster costs remain negligible compared to cluster operating costs. Plain K8s Secret has zero incremental cost but lacks DR capabilities and platform-hosted OIDC benefits.

---

## Decision Criteria

### HyperShift Constraint Impact on Decisions

**Before evaluating other criteria, note the critical HyperShift architectural constraint**: HostedCluster spec requires a Kubernetes Secret reference for the signing key.

**Practical Impact**:
- **ESO + GSM**: ✅ Fully compatible with current HyperShift, ready for deployment
- **CSI + GSM**: ⚠️ Requires workarounds or unclear if viable with Secret reference requirement
- **KMS + External Signer**: ❌ Requires HyperShift API changes to support external endpoints (unknown feasibility)

**Reality**: Unless HyperShift API is extended to support external signing endpoints or alternative secret sourcing patterns, **ESO + GSM is the only viable storage/signing option** that works with current HyperShift architecture without modifications.

The decision criteria below assume either:
- (a) Acceptance of the HyperShift constraint, making ESO the practical choice, OR
- (b) Willingness to invest in HyperShift API modifications to support CSI or KMS approaches

---

### Bootstrap Approach Decisions

### Choose Customer-Provided Bootstrap When

- Customer has existing key generation workflows (e.g., HSM-generated keys)
- Customer requires offline/air-gapped setup (cannot call CLS API initially)
- Customer security policy requires customer-owned key generation
- Legacy compatibility: integration with existing provisioning systems
- Single-step customer workflow is critical (UX priority over security)

**Accept Trade-off**: Private key exposure during bootstrap, CLS sees key temporarily

---

### Choose Platform-Generated Bootstrap When

- Security is highest priority (REQ-1, REQ-3 strict compliance)
- Automated provisioning (CI/CD, GitOps) where two-step workflow is acceptable
- Customers lack secure local key generation capabilities
- Minimize customer mistakes (key leakage, insecure storage)
- Platform manages full lifecycle (generation through rotation)

**Accept Trade-off**: Two-step customer workflow, orphaned keypair garbage collection

---

### Storage/Signing Option Decisions

### Choose Plain K8s Secret When

- Early development, prototyping, or non-production environments
- Disaster recovery handled through comprehensive etcd backup/restore strategy
- Cost minimization is critical (zero incremental cost)
- Operational simplicity prioritized over DR capabilities
- First phase/MVP implementation before adding external storage

**Accept Trade-off**: No independent backup (violates REQ-6), manual rotation only, etcd coupling

**Warning**: Not recommended for production without robust etcd DR strategy.

---

### Choose ESO + GSM When

- **Production environments requiring disaster recovery** (meets REQ-6)
- Minimal changes to HyperShift/kube-apiserver required
- Familiar Kubernetes Secret pattern preferred
- ESO already deployed and managed on platform
- Private key extractability acceptable (encrypted at rest in GSM)

**Accept Trade-off**: Private key stored in K8s Secret (etcd), ESO dependency

---

### Choose CSI Driver + GSM When

- Avoid storing private keys in Kubernetes etcd
- Native GCP integration preferred (no third-party operators)
- Pod spec changes acceptable (HyperShift supports CSI volumes)
- Private key extractability acceptable (from GSM)

**Accept Trade-off**: Pod spec modifications, CSI driver dependency

---

### Choose KMS + External Signer When

- Maximum security required (REQ-1 strictest interpretation)
- HSM-backed cryptography mandated by compliance
- Private key must never be extractable by anyone (including platform operators)
- Automatic key rotation by KMS desired
- Cost and complexity acceptable for security benefit
- HyperShift supports external signer configuration

**Accept Trade-off**: Highest operational complexity, sidecar management, latency, HyperShift validation required, higher cost

---

## Rejected Alternatives

This section documents alternative approaches that were considered and rejected during the design process, along with the rationale for rejection.

### 1. Customer-Side Secret Storage (GSM or KMS)

**Concept**: Store signing keys (GSM secrets) or KMS signing keys in customer's GCP project instead of platform region project.

**Why Rejected**: Creates unsolvable circular dependency during bootstrap.

**The Circular Dependency Problem**:

```
For Customer-Side GSM:
1. Control-plane kube-apiserver needs to read private key from customer GSM
2. ESO (or pod SA) must authenticate to customer GSM via Workload Identity
3. WIF authentication requires Management Cluster ServiceAccount token
4. Customer must grant GSM access to platform SA principal: ns/clusters-{id}/sa/kube-apiserver
5. But cluster ID and namespace don't exist until cluster is created
6. Cluster can't be created without access to signing key in customer GSM
7. ❌ Chicken-and-egg: can't grant access before cluster exists, can't create cluster without access

For Customer-Side KMS:
(Same problem - detailed in KMS section above)
1. kms-jwt-signer needs to call customer KMS to sign tokens
2. Must authenticate via WIF using Management Cluster SA
3. Customer must grant KMS access before cluster exists
4. But SA principal includes namespace that doesn't exist yet
5. ❌ Same circular dependency
```

**Workaround Considered**: Pre-create namespace and communicate to customer for IAM setup.

**Why Pre-Creation Doesn't Work**:
- Defeats namespace isolation principle (namespaces exist before clusters)
- Creates orphaned namespaces if customer never completes cluster creation
- Complex coordination: customer must setup IAM for specific namespace, then reference it during cluster creation
- Error-prone: namespace name mismatch breaks everything

**Platform Storage Solution**:

By placing keys in **platform region project**:
- ✅ Platform controls IAM bindings (configured atomically during cluster creation)
- ✅ Namespace created first, then IAM binding granted in single operation
- ✅ No customer coordination required for bootstrap access
- ✅ Easier cluster migration between management clusters (same storage)
- ⚠️ Trade-off: Customer doesn't own the key storage (similar trust model to current approach)

**Customer Control Mechanisms**:
- Customer still controls OIDC provider (verification layer)
- Customer can request platform-generated keys OR provide their own (bootstrap approach choice)
- Customer grants bootstrap SA permission to update OIDC (explicit consent)
- Customer can audit all operations via their OIDC access logs

**Conclusion**: Platform-side storage (GSM or KMS in region project) is the only viable option that avoids circular dependencies while maintaining strong isolation.

---

### 2. Shared/Central KMS Signing Service

**Concept**: Deploy one KMS signing service per management cluster (not per hosted cluster). All control-planes connect to shared service via network (not UDS).

**Architecture**:
```
Management Cluster:
├── KMS Signing Service (shared, platform-wide)
│   └── Has access to ALL cluster KMS keys in region
│   └── Exposed as network service (gRPC over TCP)
│
└── Control-Plane Namespaces
    └── kube-apiservers connect to shared service over network
```

**Advantages**:
- Single service to manage/monitor
- One authentication point (shared service SA to platform KMS)
- Potentially simpler deployment

**Why Rejected**:
- ❌ **Violates REQ-3**: Shared component has access to all customer signing capabilities
- ❌ **High blast radius**: Compromise of signing service = all clusters affected
- ❌ **Network calls**: Adds latency compared to sidecar UDS (external signing already has latency, no need to add more)
- ❌ **Isolation weakness**: Application-level routing (service must validate cluster ID in request) vs infrastructure-enforced (GCP IAM)
- ❌ **Single point of failure**: Shared service outage impacts all clusters

**Comparison**: Per-cluster sidecar has better isolation, lower blast radius, infrastructure-enforced access control.

---

### 3. Static Service Account JSON Keys for Authentication

**Concept**: Use GCP service account JSON keys (traditional credentials) instead of Workload Identity Federation for component authentication to GSM/KMS.

**How It Would Work**:
- Create GCP SA per cluster: `cluster-{id}-key-access@{project}`
- Generate JSON key for that SA
- Store JSON key as Kubernetes Secret
- Components use JSON key to authenticate to GSM/KMS

**Why Rejected**:
- ❌ **Reintroduces key management problem**: Now managing GCP SA JSON keys instead of signing keys
- ❌ **Violates REQ-1**: JSON keys are long-lived credentials that must be stored
- ❌ **No automatic rotation**: JSON keys require manual rotation
- ❌ **Security regression**: Workload Identity is more secure than static JSON keys
- ❌ **Defeats purpose**: Trying to eliminate key management by introducing more keys

**Conclusion**: Workload Identity Federation is the correct authentication mechanism; static JSON keys are anti-pattern.

---

### 4. Per-Namespace ESO Controllers

**Concept**: Deploy External Secrets Operator controller per control-plane namespace instead of cluster-wide ESO.

**Why Considered**: Avoid shared ESO controller having broad permissions.

**Why Rejected**:
- ❌ **Massive operational overhead**: ESO controller per hosted cluster (hundreds to thousands)
- ❌ **Resource waste**: Each controller consumes memory/CPU
- ❌ **Unnecessary**: ESO controller with WIF-based SecretStore already provides strong isolation
  - ESO controller doesn't need broad permissions
  - Each SecretStore uses its namespace's SA
  - ESO controller just reconciles resources, actual GSM access is per-SA
- ✅ **Cluster-wide ESO is secure**: Controller is not the security boundary; WIF IAM bindings are

**Conclusion**: Cluster-wide ESO with namespace-scoped SecretStores provides sufficient isolation without operational complexity.

---

### 5. Bootstrap Key for kms-jwt-signer Authentication

**Concept**: Use two separate signing mechanisms simultaneously:
- Local keypair for signing kms-jwt-signer's own tokens (bootstrap)
- KMS for signing all other service account tokens

**How It Would Work**:
- kube-apiserver configured with both `--service-account-signing-key-file` and `--service-account-signing-endpoint`
- Use file-based signing for specific service accounts (kms-jwt-signer)
- Use KMS external signer for all other service accounts
- kms-jwt-signer gets token signed by local key, uses it to authenticate to KMS

**Why Rejected**:
- ❌ **Kubernetes doesn't support dual signing modes**: Cannot configure SA-specific or namespace-specific signing methods
- ❌ **Flags are mutually exclusive**: `--service-account-signing-endpoint` XOR `--service-account-signing-key-file`, not both
- ❌ **Would require Kubernetes core changes**: Not feasible for this project

**Alternative That Works**: kms-jwt-signer uses Management Cluster ServiceAccount (different namespace, different kube-apiserver) - no circular dependency.

---

### 6. Direct kube-apiserver KMS Integration

**Concept**: Modify kube-apiserver directly to call Cloud KMS API without separate sidecar.

**Why Rejected**:
- ❌ **Not how Kubernetes extensibility works**: External signer pattern exists for a reason
- ❌ **Would require forking kube-apiserver**: Unsustainable maintenance burden
- ❌ **Violates Kubernetes architecture**: Signing should be pluggable, not hardcoded to specific KMS provider
- ❌ **HyperShift complexity**: Would need to maintain forked kube-apiserver images
- ✅ **Standard pattern exists**: `--service-account-signing-endpoint` is the correct Kubernetes-native approach

**Conclusion**: Use Kubernetes external signer gRPC interface as designed, not custom kube-apiserver modifications.

---

### 7. Customer-Hosted OIDC Provider (with Bootstrap SA)

**Concept**: Customer creates and hosts OIDC provider in their GCP project. Platform manages public keys via bootstrap SA with customer IAM permissions.

**How It Would Work**:
- Customer creates Workload Identity Pool and OIDC provider in their project
- Platform provides public key to customer during cluster setup
- Customer configures OIDC provider JWKS with platform's public key
- Customer creates bootstrap SA and grants it permissions to update OIDC provider
- Platform uses bootstrap SA to update JWKS during key rotation

**Advantages**:
- ✅ Customer owns OIDC infrastructure (customer control)
- ✅ No platform OIDC endpoint infrastructure required
- ✅ Standard GCP WIF pattern (customer-hosted OIDC provider)
- ✅ Customer can audit all OIDC updates in their Cloud Audit Logs

**Why Rejected**:
- ❌ **Complex customer setup**: Customer must handle public keys, create OIDC provider, create bootstrap SA
- ❌ **Bootstrap SA coordination**: Customer must grant IAM permissions for rotation
- ❌ **Public key exchange**: Platform must transmit public key to customer
- ❌ **3-4 step workflow**: More steps than platform-hosted OIDC (1 step)
- ❌ **Customer IAM dependency**: Rotation requires customer IAM permissions

**Replaced By**: Platform-hosted OIDC endpoint (chosen approach) eliminates all bootstrap SA complexity and provides zero-step customer rotation.

---

### 8. Customer Manually Updates OIDC JWKS During Rotation

**Concept**: Instead of bootstrap SA with automated OIDC updates, customer manually updates JWKS when platform notifies them.

**How It Would Work**:
- Platform generates new keypair and notifies customer (email, API event)
- Customer manually fetches new public key from platform API
- Customer manually updates OIDC provider JWKS in their GCP project
- Customer notifies platform that update is complete
- Platform completes rotation

**Why Rejected**:
- ❌ **Violates REQ-4**: Cannot automate rotation if manual customer action required
- ❌ **Operational burden**: Every rotation requires customer action (30-day rotation = 12 customer actions/year/cluster)
- ❌ **Delays**: Customer may be slow to respond, leaving old keys in use longer
- ❌ **Error-prone**: Manual steps increase chance of misconfiguration
- ❌ **Scales poorly**: Hundreds of clusters = hundreds of manual rotation requests

**Conclusion**: Automated rotation requires platform capability to update customer OIDC, hence bootstrap SA approach.

---

### 9. Self-Contained Rotation Without Customer OIDC Access

**Concept**: Rotate keys entirely within platform systems without ever updating customer OIDC provider.

**Why It's Impossible**:
- ❌ Customer OIDC provider JWKS must contain current public key for token verification
- ❌ Customer's GCP IAM verifies tokens by fetching JWKS from customer's OIDC provider
- ❌ Platform has no way to inject public keys into customer's GCP verification path without updating customer OIDC
- ❌ Cannot work around this: it's fundamental to how OIDC/WIF works

**Conclusion**: Customer OIDC provider must be updated during rotation. No alternative exists within GCP Workload Identity Federation architecture.

---

## Summary of Rejected Alternatives

| Alternative | Primary Reason for Rejection |
|-------------|------------------------------|
| Customer-side storage (GSM/KMS) | Circular dependency during bootstrap (chicken-and-egg) |
| Shared/central KMS signing service | Violates REQ-3 (shared component access), high blast radius |
| Static SA JSON keys for authentication | Reintroduces key management problem, defeats purpose |
| Per-namespace ESO controllers | Unnecessary overhead, cluster-wide ESO already secure |
| Bootstrap key for kms-jwt-signer (dual signing) | Kubernetes doesn't support dual signing modes |
| Direct kube-apiserver KMS integration (forked) | Violates Kubernetes architecture, unsustainable maintenance |
| Platform-hosted OIDC endpoint | Customer trust concerns, operational complexity (deferred) |
| Manual customer OIDC updates during rotation | Violates REQ-4 (automated rotation), poor scalability |
| Rotation without customer OIDC access | Architecturally impossible with GCP WIF |

All rejected alternatives either violate stated requirements, create operational complexity disproportionate to benefits, or are architecturally infeasible.

---

## Open Questions

### 1. HyperShift External Signer Support

**Question**: Does HyperShift HostedCluster API support configuring `--service-account-signing-endpoint` for kube-apiserver?

**Investigation Needed**:

- Review HyperShift HostedCluster API spec for kube-apiserver flag configuration
- Test injecting sidecar containers into control-plane pods
- Validate Unix domain socket volume sharing between containers
- Prototype KMS external signer integration

**Impact**: Critical for KMS option feasibility.

---

### 2. Default Rotation Frequency

**Question**: What should the default key rotation frequency be?

**Options**:

- 30 days: High security, more operations, more API calls
- 60 days: Balanced
- 90 days: Industry standard (Azure Workload Identity recommendation)

**Considerations**:

- Customer compliance requirements vary
- More frequent rotation = better security, more complexity
- Configurable per-cluster is essential

**Recommendation**: Start with 30-day default, allow customer configuration.

---

### 3. Bootstrap SA Permissions Scope

**Question**: What is the minimum IAM role required for bootstrap SA to update OIDC provider?

**Options**:

- `roles/iam.workloadIdentityPoolAdmin`: Broad pool-level permissions
- Custom role with only `iam.workloadIdentityPoolProviders.update`: Narrowest scope

**Security Concern**: Granting platform SA admin-level permissions in customer project

**Investigation Needed**:

- Test custom role with minimal permissions
- Validate OIDC JWKS update works with narrow permissions
- Document customer setup for custom role creation

---

### 4. Orphaned Keypair Garbage Collection

**Question**: What is the appropriate TTL for unused keypairs before automatic deletion?

**Options**:

- 7 days: Quick cleanup, may be too aggressive for slow customer workflows
- 14 days: More buffer
- 30 days: Safe buffer, but slower cleanup

**Considerations**:

- Customer may request keypair, then delay cluster creation (waiting for approvals, etc.)
- Deleting too soon frustrates customers
- Keeping too long accumulates orphaned resources
- Customer should be able to explicitly delete unused keypairs

**Recommendation**: 14-day TTL with explicit customer deletion option.

---

### 5. Rotation Failure Handling

**Question**: What should happen when automated rotation fails repeatedly?

**Scenarios**:

- Customer OIDC provider unreachable (network, permissions)
- GSM/KMS unavailable (platform issues)
- kube-apiserver fails to restart (control-plane issues)

**Options**:

- Continue using current key, retry indefinitely (safe, but key ages)
- Disable automated rotation after N failures, require manual intervention
- Alert customer and platform operations

**Investigation Needed**:

- Define SLA for manual intervention
- Design customer notification system (email, webhooks)
- Escalation matrix for persistent failures

---

### 6. Cross-Region Key Access

**Question**: Should keys be accessible from multiple regions for disaster recovery?

**Consideration**:

- If management cluster in us-central1 fails, can cluster be recovered in us-east1?
- GSM supports multi-region replication
- KMS supports multi-region key rings

**Investigation Needed**:

- Define disaster recovery requirements
- Test cross-region cluster migration with key access
- Consider cost of multi-region replication

---

### 7. CLI/UI/Terraform Logic Parity

**Question**: How do we ensure CLI, UI, and Terraform provide equivalent workflows?

**Challenge**:

- CLI can be interactive (multi-step wizard)
- UI can guide users through steps
- Terraform is declarative (must compose resources correctly)

**Approach**:

- Business logic in CLS API backend (not in clients)
- CLI/UI/Terraform are thin clients calling CLS API
- Terraform module composes CLS API resources (keypair + cluster)

---

## Related Work

### OpenShift Cloud Credential Operator

**Reference**: [rotate-oidc-key.md](https://github.com/openshift/cloud-credential-operator/blob/master/docs/rotate-oidc-key.md)

**Key Findings**:

- Documented OIDC service account signing key rotation process
- Grace period approach: upload combined JWKS (old + new keys), wait, then remove old key
- Warning: "Remaining steps may cause downtime for the cluster"
- Manual process using `ccoctl` utility

**Lessons**:

- Grace period with multiple keys is standard practice for zero-downtime
- Manual rotation is error-prone, automation is critical
- Downtime acceptable for standalone clusters, not for hosted clusters (different SLA)

---

### Azure Workload Identity Key Rotation

**Reference**: [service-account-key-rotation.html](https://azure.github.io/azure-workload-identity/docs/topics/self-managed-clusters/service-account-key-rotation.html)

**Key Findings**:

- Recommends rotation every 3 months (90 days)
- JWKS supports multiple keys during rotation
- Grace period should exceed maximum token TTL
- Uses `azwi` CLI for JWKS generation

**Lessons**:

- 90-day rotation is industry standard
- Automation reduces operational burden
- JWKS multi-key support is well-understood pattern

---

### HyperShift PR #1259: Custom Service Account Signing Key

**Reference**: [hypershift/pull/1259](https://github.com/openshift/hypershift/pull/1259)

**Key Findings**:

- Adds `ServiceAccountSigningKey` field to HostedCluster spec
- Allows customers to provide custom signing key (vs. default S3-based OIDC discovery)
- Skips S3 OIDC document upload if custom key provided

**Lessons**:

- HyperShift already supports custom signing key references
- API design: optional field with local object reference
- Flexibility for different OIDC hosting approaches (S3, customer-managed, platform-managed)

**Impact on Design**: Can reference GSM secrets or KMS keys via HostedCluster spec extensions.

---

### GKE Built-in Service Account Key Rotation

**Reference**: [GKE Service Accounts](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/service-accounts)

**Key Findings**:

- GKE rotates service account signing keys automatically
- Public keys published via OIDC discovery endpoint
- No customer action required for rotation
- Fully managed by Google Cloud Platform

**Lessons**:

- Fully automated rotation is achievable
- Cloud provider can host OIDC endpoint (we could consider hosting on platform)
- Zero customer visibility needed if done correctly

**Consideration**: GKE controls OIDC endpoint, we use customer OIDC provider (different model).

---

### Kubernetes External JWT Signer (v1.34+)

**Reference**: [Managing Service Accounts](https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/)

**Key Findings**:

- Beta feature in Kubernetes v1.34+: external JWT signer via gRPC
- Flag: `--service-account-signing-endpoint` (mutually exclusive with `--service-account-signing-key-file`)
- Use case: Integration with KMS, HSM, or external key management systems
- gRPC interface: `FetchKeys()` for public keys, `Sign()` for token signing

**Lessons**:

- Kubernetes provides standard pattern for external signing
- Enables KMS/HSM integration without key extraction
- Requires gRPC server implementation (not trivial)

**Impact on Design**: Enables KMS option, but requires custom sidecar implementation.

---

## References

### Google Cloud Documentation

- [Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation)
- [Configuring Workload Identity Federation with OIDC](https://cloud.google.com/iam/docs/workload-identity-federation-with-oidc)
- [Cloud KMS Asymmetric Signing](https://cloud.google.com/kms/docs/samples/kms-sign-asymmetric)
- [Secret Manager](https://cloud.google.com/secret-manager/docs)
- [Google Secret Manager CSI Driver](https://github.com/GoogleCloudPlatform/secrets-store-csi-driver-provider-gcp)

### External Secrets Operator

- [External Secrets Operator Documentation](https://external-secrets.io/)
- [Google Secret Manager Provider - Workload Identity](https://external-secrets.io/latest/provider/google-secrets-manager/)

### Kubernetes Documentation

- [Managing Service Accounts](https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/)
- [Service Account Token Volume Projection](https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/#service-account-token-volume-projection)
- [Using a KMS provider for data encryption](https://kubernetes.io/docs/tasks/administer-cluster/kms-provider/)

### OpenShift/HyperShift

- [HyperShift PR #1259](https://github.com/openshift/hypershift/pull/1259) - Custom service account signing key
- [cloud-credential-operator OIDC key rotation](https://github.com/openshift/cloud-credential-operator/blob/master/docs/rotate-oidc-key.md)

### Azure Workload Identity

- [Service Account Key Rotation](https://azure.github.io/azure-workload-identity/docs/topics/self-managed-clusters/service-account-key-rotation.html)
- [Azure Workload Identity with HyperShift](https://hypershift.pages.dev/how-to/azure/azure-workload-identity-setup/)

### Standards

- [RFC 7517: JSON Web Key (JWK)](https://datatracker.ietf.org/doc/html/rfc7517)
- [RFC 7519: JSON Web Token (JWT)](https://datatracker.ietf.org/doc/html/rfc7519)
- [OpenID Connect Discovery](https://openid.net/specs/openid-connect-discovery-1_0.html)

### Code References

- `hypershift/cmd/infra/gcp/iam.go` - Current WIF/OIDC implementation
- `hypershift/api/v1beta1/hostedcluster_types.go` - HostedCluster API
- `WIF.md` - Workload Identity Federation setup reference

---

**End of Research Document**

*This document provides a comprehensive analysis of service account signing key management options for GCP HCP. It is intended as a basis for team discussion and decision-making. No single option is prescribed; each has trade-offs that must be evaluated against project requirements and constraints.*
