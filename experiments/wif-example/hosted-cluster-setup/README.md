# Hosted Cluster Setup

This directory contains scripts to set up the service account signing key for your hosted cluster and extract the public JWKS for GCP WIF configuration.

## Overview

For GCP Workload Identity Federation to work with a hosted cluster, you need:

1. **Private Key**: Used by the hosted cluster's API server to sign service account tokens
2. **Kubernetes Secret**: Contains the private key, referenced by the HostedCluster spec
3. **Public JWKS**: Used by GCP WIF to verify the tokens

These scripts automate the entire process.

## Quick Start

Run the scripts in order:

```bash
# 1. Generate the private key
./1-generate-sa-signing-key.sh

# 2. Create the Kubernetes secret
./2-create-secret.sh

# 3. Extract the public JWKS
./3-extract-jwks.sh
```

This will create:
- `sa-signing-key.pem` - Private key (⚠️ keep secure, do not commit!)
- `sa-signing-key-secret.yaml` - Kubernetes secret manifest
- `jwks.json` - Public JWKS for GCP WIF

See `hosted-cluster-example.yaml` for how to reference the secret in your HostedCluster.

## Detailed Steps

### Step 1: Generate Private Key

```bash
./1-generate-sa-signing-key.sh [output-file]
```

**What it does:**
- Generates a 4096-bit RSA private key
- Ensures PKCS#1 format (required by HyperShift)
- Sets restrictive permissions (600)

**Output:**
- `sa-signing-key.pem` (default)

**Example:**
```bash
./1-generate-sa-signing-key.sh my-cluster-key.pem
```

**Key Format:**
The key must be in PKCS#1 format:
```
-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----
```

**NOT** PKCS#8 format:
```
-----BEGIN PRIVATE KEY-----  # ❌ Wrong format
```

### Step 2: Create Kubernetes Secret

```bash
./2-create-secret.sh [private-key-file] [secret-name] [namespace]
```

**What it does:**
- Validates the private key format
- Base64 encodes the key
- Generates a Kubernetes Secret YAML

**Arguments:**
- `private-key-file`: Path to private key (default: `sa-signing-key.pem`)
- `secret-name`: Name of the secret (default: `sa-signing-key`)
- `namespace`: Namespace to create secret in (default: `clusters`)

**Output:**
- `sa-signing-key-secret.yaml`

**Example:**
```bash
./2-create-secret.sh sa-signing-key.pem my-signing-key clusters-my-cluster
```

**Apply the secret:**
```bash
kubectl apply -f sa-signing-key-secret.yaml
```

**Verify:**
```bash
kubectl get secret sa-signing-key -n clusters
```

### Step 3: Extract Public JWKS

```bash
./3-extract-jwks.sh [private-key-file] [output-file]
```

**What it does:**
- Extracts the public key from the private key
- Converts to JWKS format
- Generates a unique Key ID (kid)

**Arguments:**
- `private-key-file`: Path to private key (default: `sa-signing-key.pem`)
- `output-file`: Output JWKS file (default: `jwks.json`)

**Output:**
- `jwks.json`

**Example:**
```bash
./3-extract-jwks.sh sa-signing-key.pem my-cluster-jwks.json
```

**JWKS Format:**
```json
{
  "keys": [
    {
      "use": "sig",
      "kty": "RSA",
      "kid": "unique-key-id",
      "alg": "RS256",
      "n": "base64url-encoded-modulus",
      "e": "AQAB"
    }
  ]
}
```

## Using with HostedCluster

After creating the secret, reference it in your HostedCluster spec.

### Quick Reference

Add this field to your HostedCluster spec:

```yaml
spec:
  serviceAccountSigningKey:
    name: sa-signing-key
```

### Complete Example

See [`hosted-cluster-example.yaml`](hosted-cluster-example.yaml) for a complete HostedCluster configuration.

Key sections:

```yaml
apiVersion: hypershift.openshift.io/v1beta1
kind: HostedCluster
metadata:
  name: my-hosted-cluster
  namespace: clusters
spec:
  # ... platform, networking, dns, etc ...
  
  # Secret encryption (REQUIRED)
  secretEncryption:
    aescbc:
      activeKey:
        name: etcd-encryption-key
  
  # Service Account Signing Key (THIS IS WHAT YOU NEED FOR WIF!)
  serviceAccountSigningKey:
    name: sa-signing-key
```

**Important Notes:**
- The secret must exist in the **same namespace** as the HostedCluster (e.g., `clusters`)
- The secret must be created **before** creating the HostedCluster
- The secret name in the spec must match the secret created by `2-create-secret.sh`

## Using with GCP WIF

After extracting the JWKS, use it to configure GCP WIF:

### Option 1: Using Environment Variables

```bash
# In the root wif-example directory
cp env.example .env
vi .env

# Set JWKS_FILE to point to the generated JWKS
export JWKS_FILE="hosted-cluster-setup/jwks.json"

# Run the GCP setup
cd infra
./setup-wif-example-gcp.sh
```

### Option 2: Using Command-Line Flags

```bash
cd infra
./setup-wif-example-gcp.sh \
  --project-id your-project \
  --infra-id your-cluster \
  --jwks-file ../hosted-cluster-setup/jwks.json
```

## Complete Workflow Example

Here's a complete example from scratch:

```bash
# 1. Generate all the keys and configs
cd hosted-cluster-setup

./1-generate-sa-signing-key.sh
# Output: sa-signing-key.pem

./2-create-secret.sh
# Output: sa-signing-key-secret.yaml

./3-extract-jwks.sh
# Output: jwks.json

# 2. Create the secret in your management cluster
kubectl apply -f sa-signing-key-secret.yaml

# 3. Update your HostedCluster spec to reference the secret
# (Add serviceAccountSigningKey field)

# 4. Set up GCP WIF using the JWKS
cd ../infra
./setup-wif-example-gcp.sh \
  --project-id <YOUR-PROJECT-ID> \
  --infra-id my-hosted-cluster \
  --jwks-file ../hosted-cluster-setup/jwks.json

# 5. Deploy the application
cd ..
kubectl create configmap gcp-wif-credentials \
  --from-file=credentials.json=infra/credentials.json \
  -n clusters-my-hosted-cluster

kubectl apply -f app/deployment.yaml
```

## Security Considerations

### Private Key Security

⚠️ **CRITICAL**: The private key (`sa-signing-key.pem`) is highly sensitive!

- **DO NOT** commit it to git (it's in `.gitignore`)
- **DO** store it securely (password manager, secrets vault)
- **DO** use restrictive file permissions (600)
- **DO** delete it after creating the Kubernetes secret
- **DO** rotate it periodically

### JWKS Security

The JWKS file (`jwks.json`) contains only public keys and is safe to share, but:

- Protect it from unauthorized modification
- Anyone with this file can verify tokens from your cluster
- If you rotate the private key, you must update the JWKS in GCP WIF

### Key Rotation

To rotate the service account signing key:

1. Generate a new private key
2. Update the Kubernetes secret
3. Extract the new JWKS
4. Update the GCP WIF provider with the new JWKS:
   ```bash
   gcloud iam workload-identity-pools providers update-oidc PROVIDER_ID \
     --workload-identity-pool=POOL_ID \
     --location=global \
     --jwk-json-path=new-jwks.json
   ```

## Troubleshooting

### Wrong Key Format Error

```
Error: x509: failed to parse private key (use ParsePKCS8PrivateKey instead)
```

**Solution**: The key is in PKCS#8 format instead of PKCS#1. Regenerate using script 1:
```bash
./1-generate-sa-signing-key.sh
```

### JWKS Extraction Fails

```
Error: unable to load Private Key
```

**Solution**: Ensure the private key file exists and is readable:
```bash
ls -la sa-signing-key.pem
chmod 600 sa-signing-key.pem
```

### Token Verification Fails in GCP

```
Error: invalid token signature
```

**Possible causes:**
1. JWKS in GCP doesn't match the private key
2. Private key was rotated but JWKS wasn't updated
3. Wrong key ID (kid) in the token

**Solution**: Re-extract JWKS and update GCP WIF provider:
```bash
./3-extract-jwks.sh
cd ../infra
# Update the provider with new JWKS
```

## Files Generated

| File | Description | Sensitive? | Commit? |
|------|-------------|------------|---------|
| `sa-signing-key.pem` | Private key | ⚠️ YES | ❌ NO |
| `sa-signing-key-secret.yaml` | Kubernetes secret | ⚠️ YES | ❌ NO |
| `jwks.json` | Public JWKS | No | ✅ Optional |
| `hosted-cluster-example.yaml` | Example HostedCluster spec | No | ✅ Yes (template) |

## References

- [HyperShift Service Account Signing](https://hypershift-docs.netlify.app/)
- [OpenSSL RSA Key Generation](https://www.openssl.org/docs/man1.1.1/man1/genrsa.html)
- [JWKS Format Specification](https://datatracker.ietf.org/doc/html/rfc7517)
- [GCP Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation)

