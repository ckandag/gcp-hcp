#!/bin/bash
# 3-extract-jwks.sh - Extract public JWKS from private key
#
# This script extracts the public JWKS (JSON Web Key Set) from the private key.
# The JWKS will be used to configure the GCP WIF OIDC provider.
#
# Usage:
#   ./3-extract-jwks.sh [private-key-file] [output-file]
#
# Arguments:
#   private-key-file  Path to the private key (default: sa-signing-key.pem)
#   output-file       Output JWKS file (default: jwks.json)
#
# Output:
#   - jwks.json (public JWKS for GCP WIF configuration)

set -euo pipefail

# Configuration
PRIVATE_KEY_FILE="${1:-sa-signing-key.pem}"
OUTPUT_FILE="${2:-jwks.json}"

# Validate private key file exists
if [ ! -f "${PRIVATE_KEY_FILE}" ]; then
    echo "Error: Private key file not found: ${PRIVATE_KEY_FILE}"
    echo ""
    echo "Run: ./1-generate-sa-signing-key.sh"
    exit 1
fi

echo "Extracting public JWKS from private key..."
echo "Private key: ${PRIVATE_KEY_FILE}"
echo "Output file: ${OUTPUT_FILE}"
echo ""

# Extract public key in PEM format
PUBLIC_KEY_PEM=$(openssl rsa -in "${PRIVATE_KEY_FILE}" -pubout -outform PEM 2>/dev/null)

# Extract modulus and exponent
MODULUS=$(echo "${PUBLIC_KEY_PEM}" | openssl rsa -pubin -noout -modulus 2>/dev/null | cut -d'=' -f2)
EXPONENT_HEX=$(echo "${PUBLIC_KEY_PEM}" | openssl rsa -pubin -text -noout 2>/dev/null | grep "Exponent:" | awk '{print $2}' | tr -d '()')

# Convert modulus from hex to base64url
MODULUS_BASE64=$(echo "${MODULUS}" | xxd -r -p | base64 | tr '+/' '-_' | tr -d '=')

# Convert exponent to base64url
# Common exponent is 65537 (0x010001)
if [ "${EXPONENT_HEX}" = "65537" ]; then
    EXPONENT_BASE64="AQAB"
else
    # Convert decimal to hex to bytes to base64url
    EXPONENT_BASE64=$(printf '%08x' "${EXPONENT_HEX}" | xxd -r -p | base64 | tr '+/' '-_' | tr -d '=')
fi

# Generate a key ID (kid) from the modulus hash
KID=$(echo -n "${MODULUS}" | openssl dgst -sha256 -binary | base64 | tr '+/' '-_' | tr -d '=' | cut -c1-43)

# Create JWKS JSON
cat > "${OUTPUT_FILE}" <<EOF
{
  "keys": [
    {
      "use": "sig",
      "kty": "RSA",
      "kid": "${KID}",
      "alg": "RS256",
      "n": "${MODULUS_BASE64}",
      "e": "${EXPONENT_BASE64}"
    }
  ]
}
EOF

echo "✓ JWKS extracted: ${OUTPUT_FILE}"
echo ""
echo "JWKS content:"
cat "${OUTPUT_FILE}"
echo ""
echo "Key ID (kid): ${KID}"
echo ""
echo "This JWKS file should be used when setting up GCP WIF:"
echo "  cd ../infra"
echo "  ./setup-wif-example-gcp.sh --jwks-file ../hosted-cluster-setup/${OUTPUT_FILE} ..."
echo ""
echo "Or set in your .env file:"
echo "  export JWKS_FILE=\"hosted-cluster-setup/${OUTPUT_FILE}\""

