#!/bin/bash
# 1-generate-sa-signing-key.sh - Generate RSA private key for service account signing
#
# This script generates a private key in PKCS#1 format that HyperShift expects.
# The key will be used to sign service account tokens in the hosted cluster.
#
# Usage:
#   ./1-generate-sa-signing-key.sh [output-file]
#
# Output:
#   - sa-signing-key.pem (private key in PKCS#1 format)

set -euo pipefail

# Configuration
OUTPUT_FILE="${1:-sa-signing-key.pem}"
KEY_SIZE=4096

echo "Generating RSA private key for service account signing..."
echo "Key size: ${KEY_SIZE} bits"
echo "Output file: ${OUTPUT_FILE}"
echo ""

# Generate RSA private key in PKCS#1 format
# The -traditional flag ensures PKCS#1 format (BEGIN RSA PRIVATE KEY)
# instead of PKCS#8 format (BEGIN PRIVATE KEY)
openssl genrsa -out "${OUTPUT_FILE}.tmp" ${KEY_SIZE}

# Explicitly convert to PKCS#1 format to ensure compatibility
openssl rsa -in "${OUTPUT_FILE}.tmp" -out "${OUTPUT_FILE}" -traditional

# Clean up temporary file
rm "${OUTPUT_FILE}.tmp"

# Set restrictive permissions
chmod 600 "${OUTPUT_FILE}"

echo "✓ Private key generated: ${OUTPUT_FILE}"
echo ""
echo "Key format verification:"
head -1 "${OUTPUT_FILE}"
echo ""
echo "⚠️  IMPORTANT: Keep this private key secure!"
echo "   - Do NOT commit it to git"
echo "   - Store it in a secure location"
echo "   - Use it only for creating the Kubernetes secret"
echo ""
echo "Next steps:"
echo "  1. Run: ./2-create-secret.sh ${OUTPUT_FILE}"
echo "  2. Run: ./3-extract-jwks.sh ${OUTPUT_FILE}"

