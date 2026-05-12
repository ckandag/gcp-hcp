#!/usr/bin/env bash
set -euo pipefail

# Tears down all resources created by setup-cdn-hmac-test.sh.
#
# Usage:
#   ./cleanup-cdn-hmac-test.sh PROJECT_ID [BUCKET_SUFFIX]
#
# Example:
#   ./cleanup-cdn-hmac-test.sh dev-mgt-us-c1-ckandagb3fc oidc-hmac-test

PROJECT_ID="${1:?Usage: $0 PROJECT_ID [BUCKET_SUFFIX]}"
BUCKET_SUFFIX="${2:-oidc-hmac-test}"

DNS_PROJECT="${DNS_PROJECT:-dev-reg-us-c1-ckandagb3fc}"
DNS_ZONE="${DNS_ZONE:-dev-reg-us-c1-ckandagb3fc-tools}"
DNS_DOMAIN="${DNS_DOMAIN:-dev-reg-us-c1-ckandagb3fc.dev.gcp-hcp.devshift.net}"
OIDC_FQDN="oidc-hmac.${DNS_DOMAIN}"

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

echo "=== GCP-588: Cleanup CDN HMAC Test Resources ==="
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

echo ">>> Deleting LB components (order: forwarding rules -> proxies -> url-maps -> backend -> NEG -> cert)..."
delete_if_exists "forwarding-rules" "${HTTPS_FORWARDING_RULE}" "--global"
delete_if_exists "forwarding-rules" "${HTTP_FORWARDING_RULE}" "--global"
delete_if_exists "target-https-proxies" "${HTTPS_PROXY_NAME}" "--global"
delete_if_exists "target-http-proxies" "${HTTP_PROXY_NAME}" ""
delete_if_exists "url-maps" "${REDIRECT_URL_MAP}" ""
delete_if_exists "url-maps" "${URL_MAP_NAME}" ""
delete_if_exists "backend-services" "${BACKEND_SERVICE_NAME}" "--global"
delete_if_exists "network-endpoint-groups" "${NEG_NAME}" "--global"

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
echo ">>> Deleting HMAC keys for SA..."
HMAC_KEYS=$(gcloud storage hmac list \
    --service-account="${SA_EMAIL}" \
    --format="value(access_id,state)" 2>/dev/null || true)

if [[ -n "${HMAC_KEYS}" ]]; then
    while IFS=$'\t' read -r key_id state; do
        if [[ "${state}" == "ACTIVE" ]]; then
            echo "  Deactivating HMAC key: ${key_id}..."
            gcloud storage hmac update "${key_id}" --deactivate --quiet
        fi
        echo "  Deleting HMAC key: ${key_id}..."
        gcloud storage hmac delete "${key_id}" --quiet
    done <<< "${HMAC_KEYS}"
else
    echo "  No HMAC keys found for ${SA_EMAIL}, skipping."
fi

echo ""
echo ">>> Deleting service account..."
if gcloud iam service-accounts describe "${SA_EMAIL}" &>/dev/null; then
    gcloud iam service-accounts delete "${SA_EMAIL}" --quiet
    echo "  Deleted service account: ${SA_EMAIL}"
else
    echo "  Service account ${SA_EMAIL} not found, skipping."
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
echo ">>> Cleaning up local HMAC secret file..."
HMAC_SECRET_FILE="/tmp/oidc-hmac-secret-${PROJECT_ID}.txt"
if [[ -f "${HMAC_SECRET_FILE}" ]]; then
    rm -f "${HMAC_SECRET_FILE}"
    echo "  Deleted ${HMAC_SECRET_FILE}"
else
    echo "  No local secret file found, skipping."
fi

echo ""
echo "============================================"
echo "  Cleanup Complete!"
echo "============================================"
