#!/usr/bin/env bash

# Grant storage.admin permission to the Tekton service account
# This allows the service account to create/manage GCS buckets

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Configuration
PROJECT_ID="<YOUR-PROJECT-ID>"
GSA_NAME="tekton-deployer-local"
GSA_EMAIL="${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

log_info "Granting storage.admin to ${GSA_EMAIL}"

# Check if service account exists
if ! gcloud iam service-accounts describe ${GSA_EMAIL} --project=${PROJECT_ID} &>/dev/null; then
    log_warn "Service account ${GSA_EMAIL} does not exist!"
    echo "Please run ./setup-local-gcp-auth.sh first"
    exit 1
fi

# Grant storage.admin role
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${GSA_EMAIL}" \
    --role="roles/storage.admin" \
    --condition=None

log_info "✓ storage.admin role granted"

# Verify the permission
echo ""
log_info "Verifying permissions for ${GSA_EMAIL}:"
gcloud projects get-iam-policy ${PROJECT_ID} \
    --flatten="bindings[].members" \
    --format="table(bindings.role)" \
    --filter="bindings.members:${GSA_EMAIL}"

echo ""
log_info "Done! The service account can now create GCS buckets."
