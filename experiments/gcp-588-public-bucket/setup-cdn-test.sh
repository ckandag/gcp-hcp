#!/usr/bin/env bash
set -euo pipefail

# Provisions a private GCS bucket with sample OIDC content, then fronts it with
# a Global External Application Load Balancer + Cloud CDN using the
# cloud-cdn-fill service account for authenticated cache fills.
#
# Usage:
#   ./setup-cdn-test.sh [PROJECT_ID] [BUCKET_SUFFIX]
#
# Example:
#   ./setup-cdn-test.sh my-gcp-project oidc-test
#
# After setup completes, test with:
#   curl -s https://IP_ADDRESS/test-cluster/.well-known/openid-configuration

PROJECT_ID="${1:?Usage: $0 PROJECT_ID [BUCKET_SUFFIX]}"
BUCKET_SUFFIX="${2:-oidc-cdn-test}"
REGION="${REGION:-us-central1}"

# DNS configuration -- the DNS zone lives in the region project
DNS_PROJECT="${DNS_PROJECT:-dev-reg-us-c1-ckandagb3fc}"
DNS_ZONE="${DNS_ZONE:-dev-reg-us-c1-ckandagb3fc-tools}"
DNS_DOMAIN="${DNS_DOMAIN:-dev-reg-us-c1-ckandagb3fc.dev.gcp-hcp.devshift.net}"
OIDC_SUBDOMAIN="oidc"
OIDC_FQDN="${OIDC_SUBDOMAIN}.${DNS_DOMAIN}"

BUCKET_NAME="${PROJECT_ID}-${BUCKET_SUFFIX}"
BACKEND_BUCKET_NAME="oidc-backend-bucket"
URL_MAP_NAME="oidc-lb"
HTTP_PROXY_NAME="oidc-http-proxy"
HTTPS_PROXY_NAME="oidc-https-proxy"
IP_NAME="oidc-lb-ip"
HTTP_FORWARDING_RULE="oidc-lb-http-forwarding"
HTTPS_FORWARDING_RULE="oidc-lb-https-forwarding"
SSL_CERT_NAME="oidc-cdn-cert"
CLUSTER_PREFIX="test-cluster"

echo "=== GCP-588: Cloud CDN + Private GCS Bucket Test ==="
echo ""
echo "Project:        ${PROJECT_ID}"
echo "Bucket:         gs://${BUCKET_NAME}"
echo "Region:         ${REGION}"
echo "DNS Project:    ${DNS_PROJECT}"
echo "DNS Zone:       ${DNS_ZONE}"
echo "OIDC FQDN:     ${OIDC_FQDN}"
echo "Cluster prefix: ${CLUSTER_PREFIX}"
echo ""

gcloud config set project "${PROJECT_ID}" --quiet

# ─── Step 1: Get project number for cloud-cdn-fill SA ───
echo ">>> Step 1: Getting project number..."
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
CDN_FILL_SA="service-${PROJECT_NUMBER}@cloud-cdn-fill.iam.gserviceaccount.com"
echo "    Project number: ${PROJECT_NUMBER}"
echo "    CDN fill SA:    ${CDN_FILL_SA}"

# ─── Step 2: Create private GCS bucket ───
echo ""
echo ">>> Step 2: Creating private GCS bucket..."
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

# ─── Step 3: Upload sample OIDC discovery + JWKS documents ───
echo ""
echo ">>> Step 3: Uploading sample OIDC documents..."

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

# ─── Step 4: Reserve a global static IP ───
echo ""
echo ">>> Step 4: Reserving global static IP..."
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

# ─── Step 5: Create backend bucket with Cloud CDN enabled ───
# This must happen BEFORE granting the cloud-cdn-fill SA, because the SA
# is auto-created by GCP when the first CDN-enabled backend bucket is created.
echo ""
echo ">>> Step 5: Creating backend bucket with Cloud CDN..."
if gcloud compute backend-buckets describe "${BACKEND_BUCKET_NAME}" &>/dev/null; then
    echo "    Backend bucket ${BACKEND_BUCKET_NAME} already exists, updating..."
    gcloud compute backend-buckets update "${BACKEND_BUCKET_NAME}" \
        --gcs-bucket-name="${BUCKET_NAME}" \
        --enable-cdn \
        --cache-mode=FORCE_CACHE_ALL
else
    gcloud compute backend-buckets create "${BACKEND_BUCKET_NAME}" \
        --gcs-bucket-name="${BUCKET_NAME}" \
        --enable-cdn \
        --cache-mode=FORCE_CACHE_ALL
    echo "    Created backend bucket: ${BACKEND_BUCKET_NAME}"
fi

# ─── Step 6: Trigger cloud-cdn-fill SA creation via signed URL key ───
# The cloud-cdn-fill SA is NOT auto-created with compute API. Adding a signed
# URL key to the backend bucket triggers GCP to provision it.
echo ""
echo ">>> Step 6: Triggering cloud-cdn-fill SA creation..."
TRIGGER_KEY_FILE=$(mktemp)
head -c 16 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=' > "${TRIGGER_KEY_FILE}"
if gcloud compute backend-buckets describe "${BACKEND_BUCKET_NAME}" \
    --format="value(cdnPolicy.signedUrlKeyNames)" 2>/dev/null | grep -q "cdn-trigger-key"; then
    echo "    Signed key already exists, skipping."
else
    gcloud compute backend-buckets add-signed-url-key "${BACKEND_BUCKET_NAME}" \
        --key-name="cdn-trigger-key" \
        --key-file="${TRIGGER_KEY_FILE}"
    echo "    Added signed URL key to trigger cloud-cdn-fill SA creation"
fi
rm -f "${TRIGGER_KEY_FILE}"

echo "    Waiting 10s for SA propagation..."
sleep 10

# ─── Step 7: Grant cloud-cdn-fill SA read access to the bucket ───
echo ""
echo ">>> Step 7: Granting cloud-cdn-fill SA access to bucket..."
echo "    NOTE: This will fail if org policy blocks cloud-cdn-fill.iam.gserviceaccount.com"
echo "    In that case, request an org policy exception for the cloud-cdn-fill SA domain."
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
    --member="serviceAccount:${CDN_FILL_SA}" \
    --role="roles/storage.objectViewer" \
    --quiet
echo "    Granted roles/storage.objectViewer to ${CDN_FILL_SA}"

# ─── Step 7: Create URL map ───
echo ""
echo ">>> Step 7: Creating URL map..."
if gcloud compute url-maps describe "${URL_MAP_NAME}" &>/dev/null; then
    echo "    URL map ${URL_MAP_NAME} already exists, skipping."
else
    gcloud compute url-maps create "${URL_MAP_NAME}" \
        --default-backend-bucket="${BACKEND_BUCKET_NAME}"
    echo "    Created URL map: ${URL_MAP_NAME}"
fi

# ─── Step 8: Create DNS A record (in region project) ───
echo ""
echo ">>> Step 8: Creating DNS A record in ${DNS_PROJECT}..."
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

# ─── Step 9: Create Google-managed SSL certificate ───
echo ""
echo ">>> Step 9: Creating Google-managed SSL certificate..."
if gcloud compute ssl-certificates describe "${SSL_CERT_NAME}" --global &>/dev/null; then
    echo "    SSL cert ${SSL_CERT_NAME} already exists, skipping."
else
    gcloud compute ssl-certificates create "${SSL_CERT_NAME}" \
        --domains="${OIDC_FQDN}" \
        --global
    echo "    Created SSL cert: ${SSL_CERT_NAME} (will take ~10-30 min to provision)"
fi

# ─── Step 10: Create HTTPS target proxy ───
echo ""
echo ">>> Step 10: Creating target HTTPS proxy..."
if gcloud compute target-https-proxies describe "${HTTPS_PROXY_NAME}" --global &>/dev/null; then
    echo "    HTTPS proxy ${HTTPS_PROXY_NAME} already exists, skipping."
else
    gcloud compute target-https-proxies create "${HTTPS_PROXY_NAME}" \
        --url-map="${URL_MAP_NAME}" \
        --ssl-certificates="${SSL_CERT_NAME}" \
        --global
    echo "    Created HTTPS proxy: ${HTTPS_PROXY_NAME}"
fi

# ─── Step 11: Create HTTPS forwarding rule (port 443) ───
echo ""
echo ">>> Step 11: Creating HTTPS forwarding rule..."
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

# ─── Step 12: (Optional) HTTP -> HTTPS redirect ───
echo ""
echo ">>> Step 12: Creating HTTP-to-HTTPS redirect..."
if gcloud compute target-http-proxies describe "${HTTP_PROXY_NAME}" &>/dev/null; then
    echo "    HTTP proxy ${HTTP_PROXY_NAME} already exists, skipping."
else
    gcloud compute url-maps import oidc-lb-redirect --global --quiet <<ENDYAML
name: oidc-lb-redirect
defaultUrlRedirect:
  httpsRedirect: true
  redirectResponseCode: MOVED_PERMANENTLY_DEFAULT
ENDYAML
    gcloud compute target-http-proxies create "${HTTP_PROXY_NAME}" \
        --url-map="oidc-lb-redirect"
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
echo "Resources created:"
echo "  Bucket:             gs://${BUCKET_NAME} (private)"
echo "  Backend Bucket:     ${BACKEND_BUCKET_NAME} (CDN enabled)"
echo "  URL Map:            ${URL_MAP_NAME}"
echo "  HTTPS Proxy:        ${HTTPS_PROXY_NAME}"
echo "  HTTP Proxy:         ${HTTP_PROXY_NAME} (redirect to HTTPS)"
echo "  HTTPS Forwarding:   ${HTTPS_FORWARDING_RULE} (port 443)"
echo "  HTTP Forwarding:    ${HTTP_FORWARDING_RULE} (port 80, redirects)"
echo "  Static IP:          ${LB_IP}"
echo "  SSL Certificate:    ${SSL_CERT_NAME} (${CERT_STATUS})"
echo "  DNS Record:         ${OIDC_FQDN} -> ${LB_IP} (in ${DNS_PROJECT})"
echo ""
echo "CDN fill SA granted: ${CDN_FILL_SA}"
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
echo "  curl -s -D- -o /dev/null https://${OIDC_FQDN}/${CLUSTER_PREFIX}/openid/v1/jwks 2>&1 | grep -i age"
echo ""
echo "To clean up: ./cleanup-cdn-test.sh ${PROJECT_ID} ${BUCKET_SUFFIX}"
