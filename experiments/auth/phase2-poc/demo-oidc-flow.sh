#!/bin/bash
# Demo: Identity Platform OIDC Authentication Flow

set -e

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║     Identity Platform OIDC Authentication Demo                   ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
sleep 1

# Step 1
echo "━━━ STEP 1: Get Google Identity Token ━━━"
echo ""
echo "$ gcloud auth print-identity-token"
sleep 0.5
GCLOUD_TOKEN=$(gcloud auth print-identity-token)
echo "${GCLOUD_TOKEN:0:60}..."
echo ""
echo "Issuer: https://accounts.google.com"
echo ""
sleep 2

# Step 2
echo "━━━ STEP 2: Exchange Token via Cloud Function ━━━"
echo ""
CLOUD_FUNCTION_URL="https://<YOUR-CLOUD-FUNCTION>.run.app"
echo "$ curl -s -X POST \$CLOUD_FUNCTION_URL/exchange -d '{\"google_token\": \"\$TOKEN\"}'"
sleep 0.5
echo ""

RESPONSE=$(curl -s -X POST "${CLOUD_FUNCTION_URL}/exchange" \
  -H "Authorization: Bearer $GCLOUD_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"google_token\": \"$GCLOUD_TOKEN\"}")

echo "$RESPONSE" | jq '{
  success,
  email,
  iam_roles,
  k8s_groups,
  issuer
}'
echo ""
sleep 2

# Extract IDP token
IDP_TOKEN=$(echo "$RESPONSE" | jq -r '.idp_token')

# Step 3
echo "━━━ STEP 3: Authenticate to HostedCluster ━━━"
echo ""
API_SERVER="https://api.<cluster-name>.<region>-<id>.example.com:443"

echo "$ kubectl --token=\$IDP_TOKEN auth whoami"
sleep 0.5
kubectl --server="$API_SERVER" \
  --token="$IDP_TOKEN" \
  --insecure-skip-tls-verify \
  auth whoami

echo ""
sleep 1

echo "$ kubectl --token=\$IDP_TOKEN get namespaces"
sleep 0.5
kubectl --server="$API_SERVER" \
  --token="$IDP_TOKEN" \
  --insecure-skip-tls-verify \
  get namespaces | head -12

echo ""
echo "✅ Authentication successful with cluster-admin access!"
echo ""
