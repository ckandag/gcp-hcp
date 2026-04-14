#!/usr/bin/env bash
set -euo pipefail

# Tears down all resources created by setup-cdn-test.sh.
#
# Usage:
#   ./cleanup-cdn-test.sh [PROJECT_ID] [BUCKET_SUFFIX]
#
# Example:
#   ./cleanup-cdn-test.sh my-gcp-project oidc-test

PROJECT_ID="${1:?Usage: $0 PROJECT_ID [BUCKET_SUFFIX]}"
BUCKET_SUFFIX="${2:-oidc-cdn-test}"

# DNS configuration -- must match setup script
DNS_PROJECT="${DNS_PROJECT:-dev-reg-us-c1-ckandagb3fc}"
DNS_ZONE="${DNS_ZONE:-dev-reg-us-c1-ckandagb3fc-tools}"
DNS_DOMAIN="${DNS_DOMAIN:-dev-reg-us-c1-ckandagb3fc.dev.gcp-hcp.devshift.net}"
OIDC_FQDN="oidc.${DNS_DOMAIN}"

BUCKET_NAME="${PROJECT_ID}-${BUCKET_SUFFIX}"
BACKEND_BUCKET_NAME="oidc-backend-bucket"
URL_MAP_NAME="oidc-lb"
HTTP_PROXY_NAME="oidc-http-proxy"
HTTPS_PROXY_NAME="oidc-https-proxy"
IP_NAME="oidc-lb-ip"
HTTP_FORWARDING_RULE="oidc-lb-http-forwarding"
HTTPS_FORWARDING_RULE="oidc-lb-https-forwarding"
SSL_CERT_NAME="oidc-cdn-cert"
REDIRECT_URL_MAP="oidc-lb-redirect"

echo "=== GCP-588: Cleanup CDN Test Resources ==="
echo ""
echo "Project: ${PROJECT_ID}"
echo "Bucket:  gs://${BUCKET_NAME}"
echo ""

gcloud config set project "${PROJECT_ID}" --quiet

delete_if_exists() {
    local resource_type="$1"
    local resource_name="$2"
    local extra_flags="${3:-}"

    if eval "gcloud compute ${resource_type} describe ${resource_name} ${extra_flags}" &>/dev/null; then
        echo "  Deleting ${resource_type}: ${resource_name}..."
        eval "gcloud compute ${resource_type} delete ${resource_name} ${extra_flags} --quiet"
    else
        echo "  ${resource_type} ${resource_name} not found, skipping."
    fi
}

echo ">>> Deleting LB components (order matters: forwarding rules -> proxies -> url-maps -> backend -> cert)..."
delete_if_exists "forwarding-rules" "${HTTPS_FORWARDING_RULE}" "--global"
delete_if_exists "forwarding-rules" "${HTTP_FORWARDING_RULE}" "--global"
delete_if_exists "target-https-proxies" "${HTTPS_PROXY_NAME}" "--global"
delete_if_exists "target-http-proxies" "${HTTP_PROXY_NAME}" ""
delete_if_exists "url-maps" "${REDIRECT_URL_MAP}" ""
delete_if_exists "url-maps" "${URL_MAP_NAME}" ""
delete_if_exists "backend-buckets" "${BACKEND_BUCKET_NAME}" ""

echo ""
echo ">>> Deleting SSL certificate..."
delete_if_exists "ssl-certificates" "${SSL_CERT_NAME}" "--global"

echo ""
echo ">>> Releasing static IP..."
delete_if_exists "addresses" "${IP_NAME}" "--global"

echo ""
echo ">>> Deleting DNS record from ${DNS_PROJECT}..."
if gcloud dns record-sets describe "${OIDC_FQDN}." \
    --type=A --zone="${DNS_ZONE}" --project="${DNS_PROJECT}" &>/dev/null; then
    gcloud dns record-sets delete "${OIDC_FQDN}." \
        --type=A --zone="${DNS_ZONE}" --project="${DNS_PROJECT}" --quiet
    echo "  Deleted DNS record: ${OIDC_FQDN}"
else
    echo "  DNS record ${OIDC_FQDN} not found, skipping."
fi

echo ""
echo ">>> Deleting GCS bucket and all objects..."
if gcloud storage buckets describe "gs://${BUCKET_NAME}" &>/dev/null; then
    gcloud storage rm -r "gs://${BUCKET_NAME}" --quiet
    echo "  Deleted bucket gs://${BUCKET_NAME}"
else
    echo "  Bucket gs://${BUCKET_NAME} not found, skipping."
fi

echo ""
echo "============================================"
echo "  Cleanup Complete!"
echo "============================================"
