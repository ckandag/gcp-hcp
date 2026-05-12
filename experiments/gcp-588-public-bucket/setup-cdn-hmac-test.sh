#!/usr/bin/env bash
set -euo pipefail

# Provisions a private GCS bucket with sample OIDC content, then fronts it with
# a Global External Application Load Balancer + Cloud CDN using HMAC-based
# Private Origin Authentication.
#
# This approach uses a project-owned Service Account with HMAC keys instead of
# the cloud-cdn-fill SA, avoiding the iam.allowedPolicyMemberDomains org policy
# blocker entirely.
#
# Architecture:
#   Client -> Global HTTPS LB -> Cloud CDN -> Backend Service (HMAC auth)
#          -> Internet NEG -> {bucket}.storage.googleapis.com -> Private GCS
#
# Usage:
#   ./setup-cdn-hmac-test.sh PROJECT_ID [BUCKET_SUFFIX]
#
# Example:
#   ./setup-cdn-hmac-test.sh dev-mgt-us-c1-ckandagb3fc oidc-hmac-test

PROJECT_ID="${1:?Usage: $0 PROJECT_ID [BUCKET_SUFFIX]}"
BUCKET_SUFFIX="${2:-oidc-hmac-test}"
REGION="${REGION:-us-central1}"

DNS_PROJECT="${DNS_PROJECT:-dev-reg-us-c1-ckandagb3fc}"
DNS_ZONE="${DNS_ZONE:-dev-reg-us-c1-ckandagb3fc-tools}"
DNS_DOMAIN="${DNS_DOMAIN:-dev-reg-us-c1-ckandagb3fc.dev.gcp-hcp.devshift.net}"
OIDC_SUBDOMAIN="oidc-hmac"
OIDC_FQDN="${OIDC_SUBDOMAIN}.${DNS_DOMAIN}"

BUCKET_NAME="${PROJECT_ID}-${BUCKET_SUFFIX}"
SA_NAME="oidc-cdn-reader"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
NEG_NAME="oidc-gcs-neg"
BACKEND_SERVICE_NAME="oidc-cdn-backend"
URL_MAP_NAME="oidc-hmac-lb"
HTTP_PROXY_NAME="oidc-hmac-http-proxy"
HTTPS_PROXY_NAME="oidc-hmac-https-proxy"
IP_NAME="oidc-hmac-lb-ip"
HTTP_FORWARDING_RULE="oidc-hmac-http-fwd"
HTTPS_FORWARDING_RULE="oidc-hmac-https-fwd"
SSL_CERT_NAME="oidc-hmac-cert"
REDIRECT_URL_MAP="oidc-hmac-redirect"
CLUSTER_PREFIX="test-cluster"

echo "=== GCP-588: Cloud CDN + HMAC Private Origin Auth Test ==="
echo ""
echo "Project:        ${PROJECT_ID}"
echo "Bucket:         gs://${BUCKET_NAME}"
echo "Region:         ${REGION}"
echo "Service Account: ${SA_EMAIL}"
echo "DNS Project:    ${DNS_PROJECT}"
echo "DNS Zone:       ${DNS_ZONE}"
echo "OIDC FQDN:      ${OIDC_FQDN}"
echo "Cluster prefix: ${CLUSTER_PREFIX}"
echo ""

gcloud config set project "${PROJECT_ID}" --quiet

# ─── Step 1: Create private GCS bucket ───
echo ">>> Step 1: Creating private GCS bucket..."
if gcloud storage buckets describe "gs://${BUCKET_NAME}" &>/dev/null; then
    echo "    Bucket gs://${BUCKET_NAME} already exists, skipping."
else
    gcloud storage buckets create "gs://${BUCKET_NAME}" \
        --project="${PROJECT_ID}" \
        --location="${REGION}" \
        --default-storage-class=STANDARD \
        --uniform-bucket-level-access
    echo "    Created bucket gs://${BUCKET_NAME} (private, uniform access)"
fi

# ─── Step 2: Upload sample OIDC discovery + JWKS documents ───
echo ""
echo ">>> Step 2: Uploading sample OIDC documents..."

ISSUER_URL="https://${OIDC_FQDN}/${CLUSTER_PREFIX}"

OIDC_DISCOVERY=$(cat <<ENDJSON
{
  "issuer": "${ISSUER_URL}",
  "jwks_uri": "${ISSUER_URL}/openid/v1/jwks",
  "response_types_supported": ["id_token"],
  "subject_types_supported": ["public"],
  "id_token_signing_alg_values_supported": ["RS256"]
}
ENDJSON
)

JWKS_DOC=$(cat <<'ENDJSON'
{
  "keys": [
    {
      "kty": "RSA",
      "alg": "RS256",
      "use": "sig",
      "kid": "test-key-1",
      "n": "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4cbbfAAtVT86zwu1RK7aPFFxuhDR1L6tSoc_BJECPebWKRXjBZCiFV4n3oknjhMstn64tZ_2W-5JsGY4Hc5n9yBXArwl93lqt7_RN5w6Cf0h4QyQ5v-65YGjQR0_FDW2QvzqY368QQMicAtaSqzs8KJZgnYb9c7d0zgdAZHzu6qMQvRL5hajrn1n91CbOpbISD08qNLyrdkt-bFTWhAI4vMQFh6WeZu0fM4lFd2NcRwr3XPksINHaQ-G_xBniIqbw0Ls1jF44-csFCur-kEgU8awapJzKnqDKgw",
      "e": "AQAB"
    }
  ]
}
ENDJSON
)

echo "${OIDC_DISCOVERY}" | gcloud storage cp - \
    "gs://${BUCKET_NAME}/${CLUSTER_PREFIX}/.well-known/openid-configuration" \
    --content-type="application/json" --quiet

echo "${JWKS_DOC}" | gcloud storage cp - \
    "gs://${BUCKET_NAME}/${CLUSTER_PREFIX}/openid/v1/jwks" \
    --content-type="application/json" --quiet

echo "    Uploaded:"
echo "      - gs://${BUCKET_NAME}/${CLUSTER_PREFIX}/.well-known/openid-configuration"
echo "      - gs://${BUCKET_NAME}/${CLUSTER_PREFIX}/openid/v1/jwks"

# ─── Step 3: Create project-owned Service Account ───
echo ""
echo ">>> Step 3: Creating service account for HMAC authentication..."
if gcloud iam service-accounts describe "${SA_EMAIL}" &>/dev/null; then
    echo "    Service account ${SA_EMAIL} already exists, skipping."
else
    gcloud iam service-accounts create "${SA_NAME}" \
        --display-name="OIDC CDN Reader (HMAC)" \
        --description="SA for Cloud CDN HMAC auth to read OIDC docs from GCS"
    echo "    Created service account: ${SA_EMAIL}"
    echo "    Waiting 10s for SA propagation..."
    sleep 10
fi

# ─── Step 4: Grant SA read access to bucket (no org policy issue!) ───
echo ""
echo ">>> Step 4: Granting SA access to bucket..."
echo "    NOTE: This SA is project-owned, so iam.allowedPolicyMemberDomains does NOT block it."
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/storage.objectViewer" \
    --quiet
echo "    Granted roles/storage.objectViewer to ${SA_EMAIL}"

# ─── Step 5: Create HMAC key for the SA ───
echo ""
echo ">>> Step 5: Creating HMAC key for service account..."

EXISTING_KEYS=$(gcloud storage hmac list \
    --service-account="${SA_EMAIL}" \
    --filter="state=ACTIVE" \
    --format="value(access_id)" 2>/dev/null || true)

if [[ -n "${EXISTING_KEYS}" ]]; then
    HMAC_ACCESS_KEY=$(echo "${EXISTING_KEYS}" | head -1)
    echo "    Active HMAC key already exists: ${HMAC_ACCESS_KEY}"
    echo ""
    echo "    WARNING: Cannot retrieve the secret for an existing key."
    echo "    If you don't have the secret saved, delete the old key and re-run:"
    echo "      gcloud storage hmac update ${HMAC_ACCESS_KEY} --deactivate"
    echo "      gcloud storage hmac delete ${HMAC_ACCESS_KEY}"
    echo "      Then re-run this script."
    echo ""

    HMAC_SECRET=""
    HMAC_SECRET_FILE="/tmp/oidc-hmac-secret-${PROJECT_ID}.txt"
    if [[ -f "${HMAC_SECRET_FILE}" ]]; then
        HMAC_SECRET=$(cat "${HMAC_SECRET_FILE}")
        echo "    Found saved secret in ${HMAC_SECRET_FILE}"
    else
        echo "    ERROR: No saved secret found. Delete the key and re-run."
        echo "    Continuing anyway (backend service config may fail)..."
    fi
else
    echo "    Creating new HMAC key..."
    HMAC_OUTPUT=$(gcloud storage hmac create "${SA_EMAIL}" --format="json")
    HMAC_ACCESS_KEY=$(echo "${HMAC_OUTPUT}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['metadata']['accessId'])")
    HMAC_SECRET=$(echo "${HMAC_OUTPUT}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['secret'])")

    HMAC_SECRET_FILE="/tmp/oidc-hmac-secret-${PROJECT_ID}.txt"
    echo "${HMAC_SECRET}" > "${HMAC_SECRET_FILE}"
    chmod 600 "${HMAC_SECRET_FILE}"

    echo "    HMAC Access Key ID: ${HMAC_ACCESS_KEY}"
    echo "    HMAC Secret saved to: ${HMAC_SECRET_FILE}"
    echo "    IMPORTANT: Save this secret securely. It cannot be retrieved again."
fi

# ─── Step 6: Reserve global static IP ───
echo ""
echo ">>> Step 6: Reserving global static IP..."
if gcloud compute addresses describe "${IP_NAME}" --global &>/dev/null; then
    echo "    IP ${IP_NAME} already exists, skipping."
else
    gcloud compute addresses create "${IP_NAME}" \
        --network-tier=PREMIUM \
        --ip-version=IPV4 \
        --global
    echo "    Reserved global IP: ${IP_NAME}"
fi

LB_IP=$(gcloud compute addresses describe "${IP_NAME}" --format="get(address)" --global)
echo "    LB IP address: ${LB_IP}"

# ─── Step 7: Create Internet NEG pointing to GCS ───
echo ""
echo ">>> Step 7: Creating Internet NEG for GCS..."
GCS_FQDN="${BUCKET_NAME}.storage.googleapis.com"

if gcloud compute network-endpoint-groups describe "${NEG_NAME}" --global &>/dev/null; then
    echo "    NEG ${NEG_NAME} already exists, skipping."
else
    gcloud compute network-endpoint-groups create "${NEG_NAME}" \
        --network-endpoint-type=internet-fqdn-port \
        --default-port=443 \
        --global
    echo "    Created Internet NEG: ${NEG_NAME}"

    gcloud compute network-endpoint-groups update "${NEG_NAME}" \
        --global \
        --add-endpoint="fqdn=${GCS_FQDN},port=443"
    echo "    Added endpoint: ${GCS_FQDN}:443"
fi

# ─── Step 8: Create Backend Service with CDN enabled ───
# Note: Internet NEGs with EXTERNAL_MANAGED do not support health checks.
echo ""
echo ">>> Step 8: Creating backend service with Cloud CDN..."
if gcloud compute backend-services describe "${BACKEND_SERVICE_NAME}" --global &>/dev/null; then
    echo "    Backend service ${BACKEND_SERVICE_NAME} already exists, skipping."
else
    gcloud compute backend-services create "${BACKEND_SERVICE_NAME}" \
        --global \
        --load-balancing-scheme=EXTERNAL_MANAGED \
        --protocol=HTTPS \
        --enable-cdn \
        --cache-mode=FORCE_CACHE_ALL \
        --default-ttl=3600 \
        --custom-request-header="Host:${GCS_FQDN}"
    echo "    Created backend service: ${BACKEND_SERVICE_NAME}"

    gcloud compute backend-services add-backend "${BACKEND_SERVICE_NAME}" \
        --global \
        --network-endpoint-group="${NEG_NAME}" \
        --global-network-endpoint-group
    echo "    Added Internet NEG as backend"
fi

# ─── Step 9: Configure HMAC authentication on backend service ───
echo ""
echo ">>> Step 9: Configuring HMAC private origin authentication..."

if [[ -z "${HMAC_SECRET:-}" ]]; then
    echo "    ERROR: HMAC secret not available. Cannot configure authentication."
    echo "    Delete existing HMAC keys and re-run the script."
    exit 1
fi

BACKEND_CONFIG_FILE=$(mktemp)
gcloud compute backend-services export "${BACKEND_SERVICE_NAME}" \
    --global \
    --destination="${BACKEND_CONFIG_FILE}"

if grep -q "awsV4Authentication" "${BACKEND_CONFIG_FILE}"; then
    echo "    HMAC auth already configured, updating..."
    python3 -c "
import yaml, sys

with open('${BACKEND_CONFIG_FILE}', 'r') as f:
    config = yaml.safe_load(f)

config.setdefault('securitySettings', {})
config['securitySettings']['awsV4Authentication'] = {
    'accessKeyId': '${HMAC_ACCESS_KEY}',
    'accessKey': '${HMAC_SECRET}',
    'accessKeyVersion': 'v1',
    'originRegion': 'auto',
}

with open('${BACKEND_CONFIG_FILE}', 'w') as f:
    yaml.dump(config, f, default_flow_style=False)
"
else
    python3 -c "
import yaml, sys

with open('${BACKEND_CONFIG_FILE}', 'r') as f:
    config = yaml.safe_load(f)

config['securitySettings'] = {
    'awsV4Authentication': {
        'accessKeyId': '${HMAC_ACCESS_KEY}',
        'accessKey': '${HMAC_SECRET}',
        'accessKeyVersion': 'v1',
        'originRegion': 'auto',
    }
}

with open('${BACKEND_CONFIG_FILE}', 'w') as f:
    yaml.dump(config, f, default_flow_style=False)
"
fi

gcloud compute backend-services import "${BACKEND_SERVICE_NAME}" \
    --global \
    --source="${BACKEND_CONFIG_FILE}" \
    --quiet
rm -f "${BACKEND_CONFIG_FILE}"
echo "    Configured HMAC auth (accessKeyId: ${HMAC_ACCESS_KEY})"

# ─── Step 10: Create URL map ───
echo ""
echo ">>> Step 10: Creating URL map..."
if gcloud compute url-maps describe "${URL_MAP_NAME}" &>/dev/null; then
    echo "    URL map ${URL_MAP_NAME} already exists, skipping."
else
    gcloud compute url-maps create "${URL_MAP_NAME}" \
        --default-service="${BACKEND_SERVICE_NAME}" \
        --global
    echo "    Created URL map: ${URL_MAP_NAME}"
fi

# ─── Step 11: Create DNS A record (in region project) ───
echo ""
echo ">>> Step 11: Creating DNS A record in ${DNS_PROJECT}..."
if gcloud dns record-sets describe "${OIDC_FQDN}." \
    --type=A --zone="${DNS_ZONE}" --project="${DNS_PROJECT}" &>/dev/null; then
    echo "    DNS record ${OIDC_FQDN} already exists, updating..."
    gcloud dns record-sets update "${OIDC_FQDN}." \
        --type=A --ttl=300 --rrdatas="${LB_IP}" \
        --zone="${DNS_ZONE}" --project="${DNS_PROJECT}"
else
    gcloud dns record-sets create "${OIDC_FQDN}." \
        --type=A --ttl=300 --rrdatas="${LB_IP}" \
        --zone="${DNS_ZONE}" --project="${DNS_PROJECT}"
fi
echo "    DNS: ${OIDC_FQDN} -> ${LB_IP}"

# ─── Step 12: Create Google-managed SSL certificate ───
echo ""
echo ">>> Step 12: Creating Google-managed SSL certificate..."
if gcloud compute ssl-certificates describe "${SSL_CERT_NAME}" --global &>/dev/null; then
    echo "    SSL cert ${SSL_CERT_NAME} already exists, skipping."
else
    gcloud compute ssl-certificates create "${SSL_CERT_NAME}" \
        --domains="${OIDC_FQDN}" \
        --global
    echo "    Created SSL cert: ${SSL_CERT_NAME} (will take ~10-30 min to provision)"
fi

# ─── Step 13: Create HTTPS target proxy ───
echo ""
echo ">>> Step 13: Creating target HTTPS proxy..."
if gcloud compute target-https-proxies describe "${HTTPS_PROXY_NAME}" --global &>/dev/null; then
    echo "    HTTPS proxy ${HTTPS_PROXY_NAME} already exists, skipping."
else
    gcloud compute target-https-proxies create "${HTTPS_PROXY_NAME}" \
        --url-map="${URL_MAP_NAME}" \
        --ssl-certificates="${SSL_CERT_NAME}" \
        --global
    echo "    Created HTTPS proxy: ${HTTPS_PROXY_NAME}"
fi

# ─── Step 14: Create HTTPS forwarding rule (port 443) ───
echo ""
echo ">>> Step 14: Creating HTTPS forwarding rule..."
if gcloud compute forwarding-rules describe "${HTTPS_FORWARDING_RULE}" --global &>/dev/null; then
    echo "    Forwarding rule ${HTTPS_FORWARDING_RULE} already exists, skipping."
else
    gcloud compute forwarding-rules create "${HTTPS_FORWARDING_RULE}" \
        --load-balancing-scheme=EXTERNAL_MANAGED \
        --network-tier=PREMIUM \
        --address="${IP_NAME}" \
        --global \
        --target-https-proxy="${HTTPS_PROXY_NAME}" \
        --ports=443
    echo "    Created HTTPS forwarding rule: ${HTTPS_FORWARDING_RULE}"
fi

# ─── Step 15: HTTP -> HTTPS redirect ───
echo ""
echo ">>> Step 15: Creating HTTP-to-HTTPS redirect..."
if gcloud compute target-http-proxies describe "${HTTP_PROXY_NAME}" &>/dev/null; then
    echo "    HTTP proxy ${HTTP_PROXY_NAME} already exists, skipping."
else
    gcloud compute url-maps import "${REDIRECT_URL_MAP}" --global --quiet <<ENDYAML
name: ${REDIRECT_URL_MAP}
defaultUrlRedirect:
  httpsRedirect: true
  redirectResponseCode: MOVED_PERMANENTLY_DEFAULT
ENDYAML
    gcloud compute target-http-proxies create "${HTTP_PROXY_NAME}" \
        --url-map="${REDIRECT_URL_MAP}"
    echo "    Created HTTP proxy with HTTPS redirect"
fi

if gcloud compute forwarding-rules describe "${HTTP_FORWARDING_RULE}" --global &>/dev/null; then
    echo "    HTTP forwarding rule ${HTTP_FORWARDING_RULE} already exists, skipping."
else
    gcloud compute forwarding-rules create "${HTTP_FORWARDING_RULE}" \
        --load-balancing-scheme=EXTERNAL_MANAGED \
        --network-tier=PREMIUM \
        --address="${IP_NAME}" \
        --global \
        --target-http-proxy="${HTTP_PROXY_NAME}" \
        --ports=80
    echo "    Created HTTP forwarding rule (redirects to HTTPS)"
fi

# ─── Check SSL certificate status ───
echo ""
echo ">>> Checking SSL certificate status..."
CERT_STATUS=$(gcloud compute ssl-certificates describe "${SSL_CERT_NAME}" \
    --global --format="value(managed.status)" 2>/dev/null || echo "UNKNOWN")
echo "    Certificate status: ${CERT_STATUS}"
if [[ "${CERT_STATUS}" != "ACTIVE" ]]; then
    echo "    NOTE: Certificate is still provisioning. HTTPS will work once status is ACTIVE (~10-30 min)."
    echo "    Check status:  gcloud compute ssl-certificates describe ${SSL_CERT_NAME} --global --format='yaml(managed)'"
fi

# ─── Summary ───
echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "Approach: Cloud CDN + HMAC Private Origin Auth (NO org policy change needed)"
echo ""
echo "Resources created:"
echo "  Bucket:             gs://${BUCKET_NAME} (private)"
echo "  Service Account:    ${SA_EMAIL}"
echo "  HMAC Key:           ${HMAC_ACCESS_KEY}"
echo "  Internet NEG:       ${NEG_NAME} -> ${GCS_FQDN}:443"
echo "  Backend Service:    ${BACKEND_SERVICE_NAME} (CDN + HMAC auth)"
echo "  URL Map:            ${URL_MAP_NAME}"
echo "  HTTPS Proxy:        ${HTTPS_PROXY_NAME}"
echo "  HTTP Proxy:         ${HTTP_PROXY_NAME} (redirect to HTTPS)"
echo "  HTTPS Forwarding:   ${HTTPS_FORWARDING_RULE} (port 443)"
echo "  HTTP Forwarding:    ${HTTP_FORWARDING_RULE} (port 80, redirects)"
echo "  Static IP:          ${LB_IP}"
echo "  SSL Certificate:    ${SSL_CERT_NAME} (${CERT_STATUS})"
echo "  DNS Record:         ${OIDC_FQDN} -> ${LB_IP} (in ${DNS_PROJECT})"
echo ""
echo "Key difference from Backend Bucket approach:"
echo "  - Uses project-owned SA (${SA_EMAIL}) instead of cloud-cdn-fill"
echo "  - SA is in your project domain -> NO org policy blocker"
echo "  - HMAC secret saved at: /tmp/oidc-hmac-secret-${PROJECT_ID}.txt"
echo ""
echo "Issuer URL: https://${OIDC_FQDN}/${CLUSTER_PREFIX}"
echo ""
echo "Wait for SSL cert to become ACTIVE (~10-30 min), then test:"
echo ""
echo "  # OIDC discovery document"
echo "  curl -s https://${OIDC_FQDN}/${CLUSTER_PREFIX}/.well-known/openid-configuration | jq ."
echo ""
echo "  # JWKS document"
echo "  curl -s https://${OIDC_FQDN}/${CLUSTER_PREFIX}/openid/v1/jwks | jq ."
echo ""
echo "  # Verify CDN cache hit (after second request)"
echo "  curl -s -D- -o /dev/null https://${OIDC_FQDN}/${CLUSTER_PREFIX}/openid/v1/jwks 2>&1 | grep -i 'age\\|x-cache'"
echo ""
echo "  # Test via HTTP (should redirect to HTTPS)"
echo "  curl -s -o /dev/null -w '%{http_code}' http://${OIDC_FQDN}/${CLUSTER_PREFIX}/openid/v1/jwks"
echo ""
echo "To clean up: ./cleanup-cdn-hmac-test.sh ${PROJECT_ID} ${BUCKET_SUFFIX}"
