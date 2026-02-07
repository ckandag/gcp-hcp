# WIF Infrastructure Setup

This directory contains scripts and templates for setting up GCP Workload Identity Federation (WIF) infrastructure.

## Overview

The infrastructure setup creates:
- **Workload Identity Pool**: Trusts tokens from your hosted cluster's OIDC issuer
- **OIDC Provider**: Validates tokens using the provided JWKS
- **GCP Service Account**: Has permissions to access GCP resources
- **IAM Bindings**: Allows WIF to impersonate the service account
- **Credentials File**: JSON configuration for the application to use

## Files

- `setup-wif-example-gcp.sh`: Main setup script
- `credentials.json.template`: Template for the generated credentials file
- `credentials.json`: Generated credentials (created by setup script, gitignored)

## Prerequisites

1. **GCP Project**: You need a GCP project with billing enabled
2. **gcloud CLI**: Installed and authenticated
3. **JWKS File**: Public JWKS from your hosted cluster's service account signing key
4. **Permissions**: You need the following IAM roles in your GCP project:
   - `roles/iam.workloadIdentityPoolAdmin`
   - `roles/iam.serviceAccountAdmin`
   - `roles/resourcemanager.projectIamAdmin`

## Quick Start

### Option A: Using Environment Variables (Recommended)

```bash
# 1. Copy and configure environment variables
cp ../env.example ../.env
vi ../.env  # Edit with your values

# 2. Source the environment file
source ../.env

# 3. Run setup
./setup-wif-example-gcp.sh
```

Required environment variables:
```bash
export GCP_PROJECT_ID="your-project-id"
export HYPERSHIFT_INFRA_ID="your-cluster-id"
export JWKS_FILE="path/to/jwks.json"  # Required
```

Optional environment variables:
```bash
export GCP_IAM_ROLES="roles/compute.viewer,roles/storage.objectViewer"
export GCP_SA_NAME="wif-app"
export K8S_SA_NAME="wif-app-workload-sa"
export K8S_NAMESPACE="default"  # Namespace in the hosted cluster
```

### Option B: Using Command-Line Flags

```bash
./setup-wif-example-gcp.sh \
  --project-id your-project-id \
  --infra-id your-cluster-id \
  --jwks-file path/to/jwks.json \
  --roles roles/compute.viewer,roles/storage.objectViewer
```

## Script Options

```bash
./setup-wif-example-gcp.sh --help
```

### Required Parameters
- `--project-id` or `$GCP_PROJECT_ID`: GCP Project ID
- `--infra-id` or `$HYPERSHIFT_INFRA_ID`: Cluster/infrastructure ID (used for naming)
- `--jwks-file` or `$JWKS_FILE`: Path to JWKS file

### Optional Parameters
- `--roles` or `$GCP_IAM_ROLES`: Comma-separated list of IAM roles (default: `roles/compute.viewer`)
- `--sa-name` or `$GCP_SA_NAME`: GCP service account name (default: `wif-app`)
- `--k8s-sa-name` or `$K8S_SA_NAME`: Kubernetes service account name (default: `wif-app-workload-sa`)
- `--k8s-namespace` or `$K8S_NAMESPACE`: Kubernetes namespace in hosted cluster (default: `default`)
- `--skip-wif`: Skip WIF pool/provider creation (reuse existing)
- `--skip-sa`: Skip service account creation (reuse existing)

## What Gets Created

### 1. Workload Identity Pool
- **Name**: `${INFRA_ID}-wi-pool`
- **Location**: `global`
- **Purpose**: Trust boundary for tokens from your hosted cluster

### 2. OIDC Provider
- **Name**: `${INFRA_ID}-k8s-provider`
- **Pool**: `${INFRA_ID}-wi-pool`
- **Issuer URI**: `https://hypershift-${INFRA_ID}-oidc`
- **Allowed Audiences**: `openshift`
- **Attribute Mapping**: `google.subject=assertion.sub`
- **JWKS**: Provided via `--jwks-file`

### 3. GCP Service Account
- **Name**: `${SA_NAME}` (default: `wif-app`)
- **Email**: `${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com`
- **Roles**: As specified via `--roles` parameter

### 4. IAM Bindings

Two critical bindings are created:

**a) Workload Identity User Binding**
```bash
# Allows the Kubernetes SA to impersonate the GCP SA
gcloud iam service-accounts add-iam-policy-binding ${GSA_EMAIL} \
  --member="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/subject/system:serviceaccount:${K8S_NAMESPACE}:${K8S_SA_NAME}" \
  --role="roles/iam.workloadIdentityUser"
```

**b) Service Account Token Creator Binding**
```bash
# Allows the GCP SA to create tokens for itself (needed for token exchange)
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${GSA_EMAIL}" \
  --role="roles/iam.serviceAccountTokenCreator"
```

### 5. Credentials File

The script generates `credentials.json` with the following structure:

```json
{
  "type": "external_account",
  "audience": "//iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}",
  "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
  "token_url": "https://sts.googleapis.com/v1/token",
  "credential_source": {
    "file": "/var/run/secrets/openshift/serviceaccount/token"
  },
  "service_account_impersonation_url": "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${GSA_EMAIL}:generateAccessToken"
}
```

This file is used by the application to authenticate with GCP.

## JWKS File

The JWKS file must contain the public keys used to verify tokens issued by your hosted cluster's API server.

### Getting the JWKS File

If you have the service account signing key (`sa-signing-key.pem`), you can extract the JWKS:

```bash
# See: ../../../ho-platform-none/install-ho-platform-none/scripts/extract-jwks-from-key.sh
```

Example JWKS format:
```json
{
  "keys": [
    {
      "use": "sig",
      "kty": "RSA",
      "kid": "unique-key-id",
      "alg": "RS256",
      "n": "base64-encoded-modulus",
      "e": "AQAB"
    }
  ]
}
```

## Verification

After running the setup script, verify the resources:

```bash
# Check Workload Identity Pool
gcloud iam workload-identity-pools describe ${INFRA_ID}-wi-pool \
  --location=global

# Check OIDC Provider
gcloud iam workload-identity-pools providers describe ${INFRA_ID}-k8s-provider \
  --workload-identity-pool=${INFRA_ID}-wi-pool \
  --location=global

# Check Service Account
gcloud iam service-accounts describe ${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com

# Check IAM Bindings
gcloud iam service-accounts get-iam-policy ${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com

# Verify credentials file was created
ls -la credentials.json
```

## Troubleshooting

### Pool Already Exists
If you see "already exists" errors, you can:
1. Use `--skip-wif` to skip pool/provider creation
2. Delete and recreate: `gcloud iam workload-identity-pools delete ${POOL_ID} --location=global`

### Permission Denied
Ensure you have the required IAM roles:
```bash
gcloud projects get-iam-policy ${PROJECT_ID} \
  --flatten="bindings[].members" \
  --filter="bindings.members:user:$(gcloud config get-value account)"
```

### JWKS File Not Found
Ensure the path to the JWKS file is correct and the file exists:
```bash
ls -la path/to/jwks.json
```

### Token Exchange Fails
Common issues:
1. **Missing `serviceAccountTokenCreator` role**: The GCP SA needs this role to generate tokens
2. **Incorrect `principalSet` format**: Must match the JWT token's `sub` claim exactly
3. **JWKS mismatch**: The JWKS must match the key used to sign tokens

## Cleanup

To delete all created resources:

```bash
# Delete Service Account
gcloud iam service-accounts delete ${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com

# Delete OIDC Provider
gcloud iam workload-identity-pools providers delete ${INFRA_ID}-k8s-provider \
  --workload-identity-pool=${INFRA_ID}-wi-pool \
  --location=global

# Delete Workload Identity Pool
gcloud iam workload-identity-pools delete ${INFRA_ID}-wi-pool \
  --location=global

# Delete credentials file
rm credentials.json
```

## Advanced Usage

### Multiple Kubernetes Service Accounts

To allow multiple Kubernetes service accounts to use the same GCP service account:

```bash
# Add additional bindings
gcloud iam service-accounts add-iam-policy-binding ${GSA_EMAIL} \
  --member="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/subject/system:serviceaccount:other-namespace:other-sa" \
  --role="roles/iam.workloadIdentityUser"
```

### Custom IAM Roles

To grant specific permissions instead of predefined roles:

```bash
# Create custom role
gcloud iam roles create customWifRole \
  --project=${PROJECT_ID} \
  --title="Custom WIF Role" \
  --permissions=compute.instances.list,storage.buckets.list

# Bind to service account
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${GSA_EMAIL}" \
  --role="projects/${PROJECT_ID}/roles/customWifRole"
```

### Updating JWKS

If you need to update the JWKS (e.g., after key rotation):

```bash
gcloud iam workload-identity-pools providers update-oidc ${INFRA_ID}-k8s-provider \
  --workload-identity-pool=${INFRA_ID}-wi-pool \
  --location=global \
  --jwk-json-path=new-jwks.json
```

## Security Considerations

1. **JWKS Protection**: The JWKS file contains public keys only, but protect it from unauthorized modification
2. **Service Account Permissions**: Grant only the minimum required IAM roles
3. **Token Audience**: Always validate the `aud` claim matches `openshift`
4. **Namespace Isolation**: Use different GCP service accounts for different Kubernetes namespaces
5. **Credential File**: The `credentials.json` file should be mounted as a Kubernetes secret, not committed to git

## References

- [GCP Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation)
- [OIDC Provider Configuration](https://cloud.google.com/iam/docs/workload-identity-federation-with-other-providers)
- [External Account Credentials](https://google.aip.dev/auth/4117)

