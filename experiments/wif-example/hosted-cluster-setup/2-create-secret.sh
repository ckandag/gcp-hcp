#!/bin/bash
# 2-create-secret.sh - Create Kubernetes secret for service account signing key
#
# This script creates a Kubernetes secret containing the service account signing key
# that will be referenced by the HostedCluster spec.
#
# Usage:
#   ./2-create-secret.sh [private-key-file] [secret-name] [namespace]
#
# Arguments:
#   private-key-file  Path to the private key (default: sa-signing-key.pem)
#   secret-name       Name of the secret (default: sa-signing-key)
#   namespace         Namespace to create secret in (default: clusters)
#
# Output:
#   - Creates secret in Kubernetes
#   - Generates sa-signing-key-secret.yaml for reference

set -euo pipefail

# Configuration
PRIVATE_KEY_FILE="${1:-sa-signing-key.pem}"
SECRET_NAME="${2:-sa-signing-key}"
NAMESPACE="${3:-clusters}"

# Validate private key file exists
if [ ! -f "${PRIVATE_KEY_FILE}" ]; then
    echo "Error: Private key file not found: ${PRIVATE_KEY_FILE}"
    echo ""
    echo "Run: ./1-generate-sa-signing-key.sh"
    exit 1
fi

# Validate key format
if ! head -1 "${PRIVATE_KEY_FILE}" | grep -q "BEGIN RSA PRIVATE KEY"; then
    echo "Error: Private key is not in PKCS#1 format"
    echo "Expected: -----BEGIN RSA PRIVATE KEY-----"
    echo "Found: $(head -1 ${PRIVATE_KEY_FILE})"
    echo ""
    echo "Run: ./1-generate-sa-signing-key.sh to generate a new key"
    exit 1
fi

echo "Creating Kubernetes secret for service account signing key..."
echo "Private key: ${PRIVATE_KEY_FILE}"
echo "Secret name: ${SECRET_NAME}"
echo "Namespace: ${NAMESPACE}"
echo ""

# Encode the private key in base64
KEY_BASE64=$(base64 < "${PRIVATE_KEY_FILE}" | tr -d '\n')

# Generate the secret YAML
cat > sa-signing-key-secret.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${SECRET_NAME}
  namespace: ${NAMESPACE}
type: Opaque
data:
  key: ${KEY_BASE64}
EOF

echo "✓ Secret YAML generated: sa-signing-key-secret.yaml"
echo ""
echo "To apply the secret, run:"
echo "  kubectl apply -f sa-signing-key-secret.yaml"
echo ""
echo "To verify the secret:"
echo "  kubectl get secret ${SECRET_NAME} -n ${NAMESPACE}"
echo ""
echo "Reference this secret in your HostedCluster spec:"
echo ""
cat <<'EOF'
spec:
  secretEncryption:
    aescbc:
      activeKey:
        name: <your-encryption-key-secret>
  serviceAccountSigningKey:
    name: sa-signing-key
EOF
echo ""
echo "Next step:"
echo "  Run: ./3-extract-jwks.sh ${PRIVATE_KEY_FILE}"

