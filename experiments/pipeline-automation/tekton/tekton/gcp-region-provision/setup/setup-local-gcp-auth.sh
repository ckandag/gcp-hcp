#!/usr/bin/env bash

# Setup GCP Authentication for Local Kubernetes (Kind/Minikube/Docker Desktop)
# This script sets up JSON key-based authentication for local development

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
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
    export GSA_NAME=${GSA_NAME:-"tekton-deployer-local"}
    export GSA_EMAIL="${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

    # Kubernetes namespace
    export NAMESPACE=${NAMESPACE:-"default"}

    # Key file location
    export KEY_FILE=${KEY_FILE:-"./gcp-key.json"}

    log_info "Configuration:"
    log_info "  Project ID:       $PROJECT_ID"
    log_info "  GCP SA:           $GSA_EMAIL"
    log_info "  Namespace:        $NAMESPACE"
    log_info "  Key file:         $KEY_FILE"
    echo ""

    log_warn "⚠️  This setup uses JSON key files (for local dev only)"
    log_warn "⚠️  Do NOT use this approach in production!"
    echo ""

    read -p "Continue with this configuration? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_warn "Aborted by user"
        exit 0
    fi
}

# Create GCP service account
create_gcp_sa() {
    log_step "1/5 Creating GCP service account..."

    # Check if SA already exists
    if gcloud iam service-accounts describe ${GSA_EMAIL} &>/dev/null; then
        log_warn "Service account ${GSA_EMAIL} already exists"
    else
        gcloud iam service-accounts create ${GSA_NAME} \
            --display-name="Tekton Deployer (Local Dev)" \
            --description="Service account for local Tekton development" \
            --project=${PROJECT_ID}
        log_info "✓ Created GCP service account: ${GSA_EMAIL}"
    fi
}

# Grant IAM roles
grant_iam_roles() {
    log_step "2/5 Granting IAM roles to ${GSA_EMAIL}..."

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

    # Storage Admin (for Terraform state in GCS)
    log_info "  - roles/storage.admin"
    gcloud projects add-iam-policy-binding ${PROJECT_ID} \
        --member="serviceAccount:${GSA_EMAIL}" \
        --role="roles/storage.admin" \
        --condition=None \
        > /dev/null

    log_info "✓ IAM roles granted"
}

# Create and download key
create_key() {
    log_step "3/5 Creating service account key..."

    # Check if key file already exists
    if [ -f "$KEY_FILE" ]; then
        log_warn "Key file already exists: $KEY_FILE"
        read -p "Overwrite? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Skipping key creation"
            return
        fi
        rm -f "$KEY_FILE"
    fi

    gcloud iam service-accounts keys create ${KEY_FILE} \
        --iam-account=${GSA_EMAIL} \
        --project=${PROJECT_ID}

    log_info "✓ Key file created: ${KEY_FILE}"
    log_warn "⚠️  Keep this file secure and never commit to git!"
}

# Create Kubernetes secret
create_k8s_secret() {
    log_step "4/5 Creating Kubernetes secret..."

    # Delete existing secret if present
    if kubectl get secret gcp-credentials -n ${NAMESPACE} &>/dev/null; then
        log_warn "Secret 'gcp-credentials' already exists, deleting..."
        kubectl delete secret gcp-credentials -n ${NAMESPACE}
    fi

    # Create secret from key file
    kubectl create secret generic gcp-credentials \
        --from-file=key.json=${KEY_FILE} \
        --namespace=${NAMESPACE}

    log_info "✓ Created Kubernetes secret: gcp-credentials"
}

# Update service account manifest
update_serviceaccount() {
    log_step "5/5 Updating Kubernetes ServiceAccount..."

    # Create a simple ServiceAccount without Workload Identity annotation
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: tekton-gcp-deployer
  namespace: ${NAMESPACE}
  labels:
    app: tekton
    component: gcp-deployer
    auth-method: json-key
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: tekton-gcp-deployer-role
  namespace: ${NAMESPACE}
rules:
  - apiGroups: [""]
    resources: ["configmaps", "secrets", "persistentvolumeclaims"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: tekton-gcp-deployer-binding
  namespace: ${NAMESPACE}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: tekton-gcp-deployer-role
subjects:
  - kind: ServiceAccount
    name: tekton-gcp-deployer
    namespace: ${NAMESPACE}
EOF

    log_info "✓ ServiceAccount created/updated"
}

# Create example task with GCP auth
create_example_task() {
    log_info "Creating example task..."

    cat > "./example-gcp-auth-task.yaml" <<'EOF'
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: test-gcp-auth
  namespace: default
spec:
  steps:
    - name: test-gcloud
      image: google/cloud-sdk:slim
      env:
        - name: GOOGLE_APPLICATION_CREDENTIALS
          value: /var/secrets/gcp/key.json
      volumeMounts:
        - name: gcp-credentials
          mountPath: /var/secrets/gcp
          readOnly: true
      script: |
        #!/bin/bash
        set -e

        echo "=== Testing GCP Authentication ==="

        # Activate service account
        gcloud auth activate-service-account --key-file=$GOOGLE_APPLICATION_CREDENTIALS

        # Show active account
        echo ""
        echo "Active account:"
        gcloud auth list

        # Show project info
        echo ""
        echo "Project info:"
        gcloud config get-value project

        # List compute zones (requires compute.admin permission)
        echo ""
        echo "Testing compute API access:"
        gcloud compute zones list --limit=5

        echo ""
        echo "✓ GCP authentication working!"
  volumes:
    - name: gcp-credentials
      secret:
        secretName: gcp-credentials
---
apiVersion: tekton.dev/v1
kind: TaskRun
metadata:
  name: test-gcp-auth-run
  namespace: default
spec:
  serviceAccountName: tekton-gcp-deployer
  taskRef:
    name: test-gcp-auth
EOF

    log_info "✓ Created example task: example-gcp-auth-task.yaml"
}

# Verify setup
verify_setup() {
    log_info "Verifying setup..."

    # Check secret
    if kubectl get secret gcp-credentials -n ${NAMESPACE} &>/dev/null; then
        log_info "✓ Secret 'gcp-credentials' exists"
    else
        log_error "Secret not found!"
        exit 1
    fi

    # Check service account
    if kubectl get serviceaccount tekton-gcp-deployer -n ${NAMESPACE} &>/dev/null; then
        log_info "✓ ServiceAccount 'tekton-gcp-deployer' exists"
    else
        log_error "ServiceAccount not found!"
        exit 1
    fi

    log_info "✓ Setup verification complete"
}

# Print next steps
print_next_steps() {
    echo ""
    log_info "════════════════════════════════════════════════════════════════"
    log_info "Local GCP Authentication Setup Complete!"
    log_info "════════════════════════════════════════════════════════════════"
    echo ""
    log_info "GCP Service Account: ${GSA_EMAIL}"
    log_info "Key File:            ${KEY_FILE}"
    log_info "K8s Secret:          gcp-credentials"
    log_info "K8s ServiceAccount:  tekton-gcp-deployer"
    echo ""
    log_warn "⚠️  IMPORTANT SECURITY NOTES:"
    echo "  1. Add ${KEY_FILE} to .gitignore"
    echo "  2. Never commit this key to version control"
    echo "  3. Rotate keys regularly (every 90 days)"
    echo "  4. Use Workload Identity in production (GKE only)"
    echo ""
    log_info "Next steps:"
    echo ""
    echo "1. Test the authentication:"
    echo "   kubectl apply -f example-gcp-auth-task.yaml"
    echo "   kubectl logs -f test-gcp-auth-run-pod"
    echo ""
    echo "2. Update your pipeline tasks to use GCP credentials:"
    echo "   - Add volume mount for gcp-credentials secret"
    echo "   - Set GOOGLE_APPLICATION_CREDENTIALS env var"
    echo "   - Activate service account in your scripts"
    echo ""
    echo "3. See example-gcp-auth-task.yaml for reference"
    echo ""
    log_info "Done! 🎉"
}

# Main execution
main() {
    echo ""
    log_info "════════════════════════════════════════════════════════════════"
    log_info "Local Kubernetes GCP Authentication Setup"
    log_info "════════════════════════════════════════════════════════════════"
    echo ""

    check_prerequisites
    get_config
    create_gcp_sa
    grant_iam_roles
    create_key
    create_k8s_secret
    update_serviceaccount
    create_example_task
    verify_setup
    print_next_steps
}

# Run main function
main "$@"
