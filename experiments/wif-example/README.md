# GCP Workload Identity Federation Example with Token Minter

This example demonstrates how to use a token-minter sidecar to provide GCP API access via Workload Identity Federation (WIF).

## Quick Start

**New to this?** Follow the step-by-step guide in [`QUICKSTART.md`](QUICKSTART.md) for detailed setup instructions with all the commands you need.

This README provides architectural details, component explanations, and reference information.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Management Cluster                           │
│                                                                   │
│  Namespace: clusters-my-hosted-cluster                          │
│                                                                   │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  Pod: wif-example-app                                   │    │
│  │                                                          │    │
│  │  ┌─────────────────┐       ┌──────────────────┐       │    │
│  │  │ token-minter    │       │   wif-app        │       │    │
│  │  │   (sidecar)     │       │  (main)          │       │    │
│  │  │                 │       │                  │       │    │
│  │  │ 1. Call API ────┼───┐   │ 4. Read token    │       │    │
│  │  │    with         │   │   │ 5. Exchange with │       │    │
│  │  │    kubeconfig   │   │   │    GCP STS       │───────┼────┼──┐
│  │  │                 │   │   │ 6. Call GCP API  │       │    │  │
│  │  │ 2. Get token    │   │   │                  │       │    │  │
│  │  │    from SA      │   │   │                  │       │    │  │
│  │  │                 │   │   │                  │       │    │  │
│  │  │ 3. Write to ────┼───┼──▶│                  │       │    │  │
│  │  │    shared vol   │   │   │                  │       │    │  │
│  │  └─────────────────┘   │   └──────────────────┘       │    │  │
│  │           │             │                               │    │  │
│  └───────────┼─────────────┼───────────────────────────────┘    │  │
│              │             │                                     │  │
│  ┌───────────┼─────────────┼───────────────────────────────┐   │  │
│  │  Pod: kube-apiserver (Hosted Control Plane)            │   │  │
│  │           │             │                                │   │  │
│  │  ┌────────▼─────────────▼────────────────────┐         │   │  │
│  │  │  Hosted Cluster API Server                 │         │   │  │
│  │  │                                             │         │   │  │
│  │  │  ServiceAccount (in hosted cluster):       │         │   │  │
│  │  │    Namespace: default                      │         │   │  │
│  │  │    Name: wif-app-workload-sa               │         │   │  │
│  │  └────────────────────────────────────────────┘         │   │  │
│  └──────────────────────────────────────────────────────────┘   │  │
│                                                                   │  │
└───────────────────────────────────────────────────────────────────┘  │
                                                                       │
                                                                       ▼
                                                           ┌─────────────────┐
                                                           │   GCP APIs      │
                                                           │                 │
                                                           │  - Compute      │
                                                           │  - Storage      │
                                                           │  - IAM          │
                                                           └─────────────────┘
```

## Components

### 1. Main Application (`wif-app`)
- Go application that calls GCP APIs
- Reads Kubernetes service account token from shared volume
- Uses GCP's external account credentials to exchange token via WIF
- Makes authenticated GCP API calls

### 2. Token Minter Sidecar (`token-minter`)
- Continuously mints fresh Kubernetes service account tokens
- Connects to the hosted cluster using kubeconfig
- Creates `TokenRequest` for the specified service account
- Writes token to shared volume for the main app to consume

### 3. Workload Identity Federation
- **GCP WIF Pool**: Trusts tokens from your hosted cluster's OIDC issuer
- **WIF Provider**: Maps token claims to GCP service account using JWKS
- **GCP Service Account**: Has permissions to access GCP resources

## Directory Structure

```
wif-example/
├── app/                           # Application code and deployment
│   ├── main.go                    # Go application
│   ├── go.mod, go.sum            # Go dependencies
│   ├── Dockerfile                 # Container build
│   ├── build-and-push.sh         # Build script
│   ├── Makefile                   # Build automation
│   └── deployment.yaml           # Kubernetes deployment + ServiceAccount
├── hosted-cluster-setup/          # Hosted cluster key generation
│   ├── 1-generate-sa-signing-key.sh  # Generate private key (PKCS#1)
│   ├── 2-create-secret.sh            # Create Kubernetes secret
│   ├── 3-extract-jwks.sh             # Extract public JWKS
│   ├── hosted-cluster-example.yaml   # Example HostedCluster spec
│   └── README.md                     # Detailed setup instructions
├── infra/                         # GCP WIF infrastructure setup
│   ├── setup-wif-example-gcp.sh  # Automated GCP setup
│   ├── credentials.json.template  # Credentials template
│   └── README.md                  # Infrastructure documentation
├── env.example                    # Environment variables template
├── QUICKSTART.md                  # Step-by-step setup guide
└── README.md                      # This file
```

## Setup Overview

The setup process involves three main phases:

### Phase 1: Hosted Cluster Setup
Generate the service account signing key for your hosted cluster:
1. Generate RSA private key (PKCS#1 format)
2. Create Kubernetes secret for the HostedCluster
3. Extract public JWKS for GCP WIF configuration

**See:** [`hosted-cluster-setup/README.md`](hosted-cluster-setup/README.md) for detailed instructions.

### Phase 2: GCP Infrastructure Setup
Configure GCP Workload Identity Federation:
1. Create Workload Identity Pool
2. Create OIDC Provider with JWKS
3. Create GCP Service Account with IAM roles
4. Configure IAM bindings (workloadIdentityUser, serviceAccountTokenCreator)
5. Generate credentials.json for the application

**See:** [`infra/README.md`](infra/README.md) for detailed instructions.

### Phase 3: Application Deployment
Build and deploy the application:
1. Build container image and push to GCR
2. Create Kubernetes resources (ConfigMap, secrets)
3. Deploy the application with token-minter sidecar

**See:** [`QUICKSTART.md`](QUICKSTART.md) for step-by-step commands.

## How It Works

### Token Flow

1. **Token Minter Sidecar**:
   - Connects to hosted cluster API using kubeconfig
   - Requests token for `system:serviceaccount:default:wif-app-workload-sa`
   - Token is signed by the hosted cluster's service account signing key
   - Writes token to `/var/run/secrets/openshift/serviceaccount/token`
   - Refreshes token before expiration

2. **JWT Token Structure**:
   The minted token contains these claims:
   ```json
   {
     "iss": "https://hypershift-INFRA_ID-oidc",
     "sub": "system:serviceaccount:default:wif-app-workload-sa",
     "aud": ["openshift"],
     "exp": 1234567890,
     "iat": 1234567890
   }
   ```

3. **GCP Token Exchange**:
   - App reads token from shared volume
   - Uses GCP's external account credentials (credentials.json)
   - GCP STS validates the token signature using the JWKS
   - WIF provider maps `sub` claim to GCP service account
   - Returns OAuth 2.0 access token for the GCP service account

4. **GCP API Call**:
   - App uses access token to authenticate with GCP APIs
   - Permissions determined by GCP service account's IAM bindings
   - Access token is cached and refreshed automatically

### Key Security Features

- **Token Isolation**: Tokens never leave the pod (shared volume only)
- **Automatic Rotation**: Token-minter refreshes tokens before expiration
- **No Long-Lived Credentials**: No service account keys stored anywhere
- **Least Privilege**: GCP service account has only required permissions
- **Signature Verification**: GCP validates all tokens using JWKS

## Configuration Options

### Environment Variables

Create a `.env` file from `env.example`:

```bash
# Required
export GCP_PROJECT_ID="your-gcp-project"
export HYPERSHIFT_INFRA_ID="your-cluster-id"
export JWKS_FILE="hosted-cluster-setup/jwks.json"

# Optional
export GCP_IAM_ROLES="roles/compute.viewer,roles/storage.objectViewer"
export GCP_SA_NAME="wif-app"
export K8S_SA_NAME="wif-app-workload-sa"
export K8S_NAMESPACE="default"  # Namespace in hosted cluster
```

### GCP IAM Roles

Common role configurations for different use cases:

**Read-only access:**
```bash
export GCP_IAM_ROLES="roles/compute.viewer,roles/storage.objectViewer"
```

**Compute management:**
```bash
export GCP_IAM_ROLES="roles/compute.instanceAdmin.v1,roles/compute.networkAdmin"
```

**Storage operations:**
```bash
export GCP_IAM_ROLES="roles/storage.objectAdmin,roles/storage.bucketAdmin"
```

**Monitoring and logging:**
```bash
export GCP_IAM_ROLES="roles/monitoring.metricWriter,roles/logging.logWriter"
```

See [`infra/README.md`](infra/README.md) for more IAM configuration options.

## Expected Output

When running successfully, you should see logs like:

```
Starting GCP WIF Example Application...
Configuration: ProjectID=my-project, TokenFile=/var/run/secrets/openshift/serviceaccount/token, Audience=openshift
=== Starting GCP API Call ===
Token read successfully (length: 847 bytes)
Token metadata - aud: [openshift], iss: https://hypershift-test-oidc, sub: system:serviceaccount:default:wif-app-workload-sa
Token expires at: 2025-11-09T12:34:56Z (in 59m30s)
Successfully created GCP client
Listing instances in zone: us-central1-a
  - Instance: my-instance-1 (Status: RUNNING, MachineType: n1-standard-1)
  - Instance: my-instance-2 (Status: STOPPED, MachineType: n1-standard-2)
=== API Call Complete: Found 2 total instances ===
```

## Troubleshooting

### Common Issues

**Token Not Found**
```
Error: failed to read token file: no such file or directory
```
- Check token-minter sidecar is running: `kubectl logs -n clusters-${HYPERSHIFT_INFRA_ID} -l app=wif-example -c token-minter`
- Verify shared volume mount is correct in deployment.yaml
- Check token-minter has kubeconfig secret

**GCP Authentication Failed**
```
Error: failed to create compute client: could not find default credentials
```
- Verify ConfigMap `gcp-wif-credentials` exists and contains valid credentials.json
- Check `GOOGLE_APPLICATION_CREDENTIALS` environment variable points to `/etc/gcp/credentials.json`
- Verify GCP service account and WIF bindings are correct

**Permission Denied**
```
Error: googleapi: Error 403: Required 'compute.instances.list' permission
```
- Grant necessary IAM roles to your GCP service account
- Verify WIF `workloadIdentityUser` binding is correct
- Check GCP service account has `serviceAccountTokenCreator` role

**Token Exchange Fails**
```
Error: Permission 'iam.serviceAccounts.getAccessToken' denied
```
- GCP service account needs `roles/iam.serviceAccountTokenCreator` role
- Verify the IAM binding uses `principal://` format (not `principalSet://`)
- Check the `sub` claim in JWT matches the IAM binding

**Token Signature Verification Fails**
```
Error: invalid token signature
```
- JWKS in GCP WIF provider doesn't match the private key
- Verify JWKS was extracted from the correct private key
- Check HostedCluster is using the correct service account signing key

See [`QUICKSTART.md`](QUICKSTART.md) for more troubleshooting steps and commands.

## Customization

### Modifying the Application

The example application (`app/main.go`) demonstrates listing GCP Compute instances. To use different GCP APIs:

1. Add the appropriate GCP client library to `app/go.mod`
2. Update `app/main.go` to use the new API
3. Grant required IAM roles to the GCP service account
4. Rebuild and redeploy

Example APIs you can use:
- **Cloud Storage**: `cloud.google.com/go/storage`
- **Pub/Sub**: `cloud.google.com/go/pubsub`
- **BigQuery**: `cloud.google.com/go/bigquery`
- **Secret Manager**: `cloud.google.com/go/secretmanager`

### Multiple Applications

To deploy multiple applications with different permissions:

1. Run `infra/setup-wif-example-gcp.sh` with different `--sa-name` for each app
2. Configure different IAM roles for each service account
3. Deploy each application with its own credentials.json
4. Use different Kubernetes service account names in each deployment

### Key Rotation

To rotate the service account signing key:

1. Generate new key: `cd hosted-cluster-setup && ./1-generate-sa-signing-key.sh new-key.pem`
2. Update secret: `./2-create-secret.sh new-key.pem`
3. Extract JWKS: `./3-extract-jwks.sh new-key.pem new-jwks.json`
4. Update GCP WIF provider:
   ```bash
   gcloud iam workload-identity-pools providers update-oidc PROVIDER_ID \
     --workload-identity-pool=POOL_ID \
     --location=global \
     --jwk-json-path=new-jwks.json
   ```

See [`hosted-cluster-setup/README.md`](hosted-cluster-setup/README.md) for detailed key rotation procedures.

## Files and Resources

### Generated Files

| File | Location | Sensitive? | Purpose |
|------|----------|------------|---------|
| `sa-signing-key.pem` | `hosted-cluster-setup/` | ⚠️ YES | Private key for HostedCluster |
| `sa-signing-key-secret.yaml` | `hosted-cluster-setup/` | ⚠️ YES | Kubernetes secret manifest |
| `jwks.json` | `hosted-cluster-setup/` | No | Public JWKS for GCP WIF |
| `credentials.json` | `infra/` | No | GCP WIF credentials for app |

### GCP Resources Created

- **Workload Identity Pool**: `${HYPERSHIFT_INFRA_ID}-wi-pool`
- **OIDC Provider**: `${HYPERSHIFT_INFRA_ID}-k8s-provider`
- **Service Account**: `${GCP_SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com`
- **IAM Bindings**: workloadIdentityUser, serviceAccountTokenCreator, custom roles

### Kubernetes Resources Created

- **Namespace**: `clusters-${HYPERSHIFT_INFRA_ID}` (on management cluster)
- **ServiceAccount**: `wif-app-workload-sa`
- **ConfigMap**: `gcp-wif-credentials`
- **Secrets**: `admin-kubeconfig`, `pull-secret`, `sa-signing-key` (in clusters namespace)
- **Deployment**: `wif-example-app` (with token-minter sidecar)

## Additional Documentation

- **[QUICKSTART.md](QUICKSTART.md)**: Step-by-step setup guide with all commands
- **[hosted-cluster-setup/README.md](hosted-cluster-setup/README.md)**: Detailed key generation and HostedCluster configuration
- **[infra/README.md](infra/README.md)**: GCP WIF infrastructure setup and advanced configuration
- **[app/Makefile](app/Makefile)**: Build automation commands

## References

- [GCP Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation)
- [OIDC Provider Configuration](https://cloud.google.com/iam/docs/workload-identity-federation-with-other-providers)
- [External Account Credentials](https://google.aip.dev/auth/4117)
- [HyperShift Documentation](https://hypershift-docs.netlify.app/)
- [Kubernetes Service Account Token Projection](https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/#serviceaccount-token-volume-projection)

## Next Steps

- Follow [`QUICKSTART.md`](QUICKSTART.md) to set up your first deployment
- Customize IAM roles for your use case
- Modify the application to use different GCP APIs
- Implement health checks and monitoring
- Add retry logic for transient failures
- Use this pattern for your own applications
