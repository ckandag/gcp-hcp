#!/usr/bin/env bash
set -euo pipefail

# Tears down all resources created by setup-proxy-test.sh.
#
# Usage:
#   ./cleanup-proxy-test.sh PROJECT_ID [BUCKET_SUFFIX]
#
# Example:
#   ./cleanup-proxy-test.sh dev-mgt-us-c1-ckandagb3fc

PROJECT_ID="${1:?Usage: $0 PROJECT_ID [BUCKET_SUFFIX]}"
BUCKET_SUFFIX="${2:-oidc-proxy-test}"
REGION="${REGION:-us-central1}"

DNS_PROJECT="${DNS_PROJECT:-dev-reg-us-c1-ckandagb3fc}"
DNS_ZONE="${DNS_ZONE:-dev-reg-us-c1-ckandagb3fc-tools}"
DNS_DOMAIN="${DNS_DOMAIN:-dev-reg-us-c1-ckandagb3fc.dev.gcp-hcp.devshift.net}"
OIDC_FQDN="oidc.${DNS_DOMAIN}"

GKE_CLUSTER="${GKE_CLUSTER:-${PROJECT_ID}-gke}"
NAMESPACE="${NAMESPACE:-oidc-system}"

BUCKET_NAME="${PROJECT_ID}-${BUCKET_SUFFIX}"
GSA_NAME="oidc-proxy"
GSA_EMAIL="${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
KSA_NAME="oidc-proxy"
IP_NAME="oidc-proxy-ip"

echo "=== GCP-588: Cleanup OIDC Proxy Test Resources ==="
echo ""
echo "Project:   ${PROJECT_ID}"
echo "Cluster:   ${GKE_CLUSTER}"
echo "Namespace: ${NAMESPACE}"
echo "Bucket:    gs://${BUCKET_NAME}"
echo ""

gcloud config set project "${PROJECT_ID}" --quiet

# ─── Step 1: Get GKE credentials ───
echo ">>> Step 1: Getting GKE credentials..."
gcloud container clusters get-credentials "${GKE_CLUSTER}" \
    --region="${REGION}" --project="${PROJECT_ID}" --dns-endpoint --quiet 2>/dev/null || {
    echo "    WARNING: Could not connect to cluster. Skipping K8s cleanup."
}

# ─── Step 2: Delete K8s resources ───
echo ""
echo ">>> Step 2: Deleting Kubernetes resources..."
for resource in ingress/oidc-proxy managedcertificate/oidc-proxy-cert \
    service/oidc-proxy deployment/oidc-proxy configmap/oidc-proxy-nginx-conf \
    serviceaccount/${KSA_NAME}; do
    if kubectl get "${resource}" -n "${NAMESPACE}" &>/dev/null; then
        echo "    Deleting ${resource}..."
        kubectl delete "${resource}" -n "${NAMESPACE}" --wait=false
    else
        echo "    ${resource} not found, skipping."
    fi
done

# Wait for Ingress deletion to release the backend service
echo "    Waiting 10s for Ingress backend cleanup..."
sleep 10

echo "    Deleting namespace ${NAMESPACE}..."
kubectl delete namespace "${NAMESPACE}" --wait=false --ignore-not-found

# ─── Step 3: Remove Workload Identity binding ───
echo ""
echo ">>> Step 3: Removing Workload Identity binding..."
if gcloud iam service-accounts describe "${GSA_EMAIL}" &>/dev/null; then
    gcloud iam service-accounts remove-iam-policy-binding "${GSA_EMAIL}" \
        --role="roles/iam.workloadIdentityUser" \
        --member="serviceAccount:${PROJECT_ID}.svc.id.goog[${NAMESPACE}/${KSA_NAME}]" \
        --project="${PROJECT_ID}" --quiet 2>/dev/null || \
        echo "    WI binding not found or already removed."
    echo "    Removed WI binding"
else
    echo "    GSA ${GSA_EMAIL} not found, skipping WI binding removal."
fi

# ─── Step 4: Remove bucket IAM binding and delete GSA ───
echo ""
echo ">>> Step 4: Removing bucket IAM binding..."
if gcloud storage buckets describe "gs://${BUCKET_NAME}" &>/dev/null; then
    gcloud storage buckets remove-iam-policy-binding "gs://${BUCKET_NAME}" \
        --member="serviceAccount:${GSA_EMAIL}" \
        --role="roles/storage.objectViewer" \
        --quiet 2>/dev/null || \
        echo "    Bucket IAM binding not found or already removed."
    echo "    Removed bucket IAM binding"
fi

echo ""
echo ">>> Step 5: Deleting GCP service account..."
if gcloud iam service-accounts describe "${GSA_EMAIL}" &>/dev/null; then
    gcloud iam service-accounts delete "${GSA_EMAIL}" --quiet
    echo "    Deleted GSA: ${GSA_EMAIL}"
else
    echo "    GSA ${GSA_EMAIL} not found, skipping."
fi

# ─── Step 6: Release static IP ───
echo ""
echo ">>> Step 6: Releasing static IP..."
if gcloud compute addresses describe "${IP_NAME}" --global &>/dev/null; then
    gcloud compute addresses delete "${IP_NAME}" --global --quiet
    echo "    Released static IP: ${IP_NAME}"
else
    echo "    Static IP ${IP_NAME} not found, skipping."
fi

# ─── Step 7: Delete DNS record ───
echo ""
echo ">>> Step 7: Deleting DNS record from ${DNS_PROJECT}..."
if gcloud dns record-sets describe "${OIDC_FQDN}." \
    --type=A --zone="${DNS_ZONE}" --project="${DNS_PROJECT}" &>/dev/null; then
    gcloud dns record-sets delete "${OIDC_FQDN}." \
        --type=A --zone="${DNS_ZONE}" --project="${DNS_PROJECT}" --quiet
    echo "    Deleted DNS record: ${OIDC_FQDN}"
else
    echo "    DNS record ${OIDC_FQDN} not found, skipping."
fi

# ─── Step 8: Delete GCS bucket ───
echo ""
echo ">>> Step 8: Deleting GCS bucket..."
if gcloud storage buckets describe "gs://${BUCKET_NAME}" &>/dev/null; then
    gcloud storage rm -r "gs://${BUCKET_NAME}" --quiet
    echo "    Deleted bucket gs://${BUCKET_NAME}"
else
    echo "    Bucket gs://${BUCKET_NAME} not found, skipping."
fi

echo ""
echo "============================================"
echo "  Cleanup Complete!"
echo "============================================"
