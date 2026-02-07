#!/usr/bin/env bash

# Setup Workload Identity for Tekton GCP Authentication
# This script automates the process of setting up Workload Identity for Tekton pipelines

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v gcloud &> /dev/null; then
        log_error "gcloud CLI not found. Please install: https://cloud.google.com/sdk/docs/install"
        exit 1
    fi

    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl not found. Please install: https://kubernetes.io/docs/tasks/tools/"
        exit 1
    fi

    log_info "✓ Prerequisites met"
}

# Get configuration
get_config() {
    log_info "Gathering configuration..."

    # Get current project
    export PROJECT_ID=${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}
    if [ -z "$PROJECT_ID" ]; then
        log_error "PROJECT_ID not set. Run: gcloud config set project YOUR_PROJECT_ID"
        exit 1
    fi

    # Service account names
    export GSA_NAME=${GSA_NAME:-"tekton-deployer"}
    export GSA_EMAIL="${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

    # Kubernetes service account
    export KSA_NAME=${KSA_NAME:-"tekton-gcp-deployer"}
    export NAMESPACE=${NAMESPACE:-"default"}

    # GKE cluster info
    export CLUSTER_NAME=${CLUSTER_NAME:-$(kubectl config current-context | cut -d_ -f4 2>/dev/null || echo "")}
    if [ -z "$CLUSTER_NAME" ]; then
        read -p "Enter GKE cluster name: " CLUSTER_NAME
    fi

    export REGION=${REGION:-"us-central1"}

    log_info "Configuration:"
    log_info "  Project ID:       $PROJECT_ID"
    log_info "  GCP SA:           $GSA_EMAIL"
    log_info "  K8s SA:           $KSA_NAME"
    log_info "  Namespace:        $NAMESPACE"
    log_info "  Cluster:          $CLUSTER_NAME"
    log_info "  Region:           $REGION"
    echo ""

    read -p "Continue with this configuration? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_warn "Aborted by user"
        exit 0
    fi
}

# Check if Workload Identity is enabled
check_workload_identity() {
    log_info "Checking if Workload Identity is enabled on cluster..."

    WI_POOL=$(gcloud container clusters describe ${CLUSTER_NAME} \
        --region=${REGION} \
        --format="value(workloadIdentityConfig.workloadPool)" 2>/dev/null || echo "")

    if [ -z "$WI_POOL" ]; then
        log_warn "Workload Identity is NOT enabled on cluster ${CLUSTER_NAME}"
        log_warn "Enable it with:"
        log_warn "  gcloud container clusters update ${CLUSTER_NAME} \\"
        log_warn "      --workload-pool=${PROJECT_ID}.svc.id.goog \\"
        log_warn "      --region=${REGION}"
        read -p "Do you want to enable it now? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "Enabling Workload Identity on cluster..."
            gcloud container clusters update ${CLUSTER_NAME} \
                --workload-pool=${PROJECT_ID}.svc.id.goog \
                --region=${REGION}
            log_info "✓ Workload Identity enabled"
        else
            log_error "Workload Identity is required. Exiting."
            exit 1
        fi
    else
        log_info "✓ Workload Identity is enabled: $WI_POOL"
    fi
}

# Create GCP service account
create_gcp_sa() {
    log_info "Creating GCP service account..."

    # Check if SA already exists
    if gcloud iam service-accounts describe ${GSA_EMAIL} &>/dev/null; then
        log_warn "Service account ${GSA_EMAIL} already exists"
    else
        gcloud iam service-accounts create ${GSA_NAME} \
            --display-name="Tekton Pipeline Deployer" \
            --description="Service account for Tekton to manage GCP resources" \
            --project=${PROJECT_ID}
        log_info "✓ Created GCP service account: ${GSA_EMAIL}"
    fi
}

# Grant IAM roles
grant_iam_roles() {
    log_info "Granting IAM roles to ${GSA_EMAIL}..."

    # Compute Admin (for managing VMs)
    log_info "  - roles/compute.admin"
    gcloud projects add-iam-policy-binding ${PROJECT_ID} \
        --member="serviceAccount:${GSA_EMAIL}" \
        --role="roles/compute.admin" \
        --condition=None \
        > /dev/null

    # Service Account User (for attaching SAs to VMs)
    log_info "  - roles/iam.serviceAccountUser"
    gcloud projects add-iam-policy-binding ${PROJECT_ID} \
        --member="serviceAccount:${GSA_EMAIL}" \
        --role="roles/iam.serviceAccountUser" \
        --condition=None \
        > /dev/null

    # Viewer (for reading project resources)
    log_info "  - roles/viewer"
    gcloud projects add-iam-policy-binding ${PROJECT_ID} \
        --member="serviceAccount:${GSA_EMAIL}" \
        --role="roles/viewer" \
        --condition=None \
        > /dev/null

    log_info "✓ IAM roles granted"
}

# Create Kubernetes service account
create_k8s_sa() {
    log_info "Creating Kubernetes service account..."

    if kubectl get serviceaccount ${KSA_NAME} -n ${NAMESPACE} &>/dev/null; then
        log_warn "Kubernetes service account ${KSA_NAME} already exists"
    else
        kubectl create serviceaccount ${KSA_NAME} -n ${NAMESPACE}
        log_info "✓ Created Kubernetes service account: ${KSA_NAME}"
    fi
}

# Bind K8s SA to GCP SA
bind_service_accounts() {
    log_info "Binding Kubernetes SA to GCP SA..."

    # Allow K8s SA to impersonate GCP SA
    gcloud iam service-accounts add-iam-policy-binding ${GSA_EMAIL} \
        --role=roles/iam.workloadIdentityUser \
        --member="serviceAccount:${PROJECT_ID}.svc.id.goog[${NAMESPACE}/${KSA_NAME}]" \
        > /dev/null

    # Annotate K8s SA
    kubectl annotate serviceaccount ${KSA_NAME} \
        -n ${NAMESPACE} \
        iam.gke.io/gcp-service-account=${GSA_EMAIL} \
        --overwrite

    log_info "✓ Service accounts bound"
}

# Verify setup
verify_setup() {
    log_info "Verifying setup..."

    # Check annotation
    ANNOTATION=$(kubectl get serviceaccount ${KSA_NAME} -n ${NAMESPACE} \
        -o jsonpath='{.metadata.annotations.iam\.gke\.io/gcp-service-account}' 2>/dev/null || echo "")

    if [ "$ANNOTATION" = "$GSA_EMAIL" ]; then
        log_info "✓ Annotation verified: $ANNOTATION"
    else
        log_error "Annotation mismatch! Expected: $GSA_EMAIL, Got: $ANNOTATION"
        exit 1
    fi

    # Check IAM binding
    if gcloud iam service-accounts get-iam-policy ${GSA_EMAIL} \
        --format="value(bindings.members)" \
        | grep -q "serviceAccount:${PROJECT_ID}.svc.id.goog\[${NAMESPACE}/${KSA_NAME}\]"; then
        log_info "✓ IAM binding verified"
    else
        log_error "IAM binding not found!"
        exit 1
    fi

    log_info "✓ Setup verification complete"
}

# Print next steps
print_next_steps() {
    echo ""
    log_info "════════════════════════════════════════════════════════════════"
    log_info "Workload Identity Setup Complete!"
    log_info "════════════════════════════════════════════════════════════════"
    echo ""
    log_info "Kubernetes Service Account: ${KSA_NAME} (namespace: ${NAMESPACE})"
    log_info "GCP Service Account:        ${GSA_EMAIL}"
    echo ""
    log_info "Next steps:"
    echo ""
    echo "1. Update your PipelineRun to use this service account:"
    echo "   spec:"
    echo "     serviceAccountName: ${KSA_NAME}"
    echo ""
    echo "2. Test authentication:"
    echo "   kubectl run -it --rm gcloud-test \\"
    echo "     --image=google/cloud-sdk:slim \\"
    echo "     --serviceaccount=${KSA_NAME} \\"
    echo "     --namespace=${NAMESPACE} \\"
    echo "     -- gcloud auth list"
    echo ""
    echo "3. Apply your updated pipeline:"
    echo "   kubectl apply -f pipeline.yaml"
    echo ""
    log_info "Done! 🎉"
}

# Main execution
main() {
    echo ""
    log_info "════════════════════════════════════════════════════════════════"
    log_info "Tekton Workload Identity Setup"
    log_info "════════════════════════════════════════════════════════════════"
    echo ""

    check_prerequisites
    get_config
    check_workload_identity
    create_gcp_sa
    grant_iam_roles
    create_k8s_sa
    bind_service_accounts
    verify_setup
    print_next_steps
}

# Run main function
main "$@"
