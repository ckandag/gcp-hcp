#!/bin/bash
#
# setup-wif-example-gcp.sh
#
# Automated GCP setup for the WIF example application
# This script creates all necessary GCP resources for the wif-example to work
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}INFO:${NC} $1"
}

log_success() {
    echo -e "${GREEN}SUCCESS:${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}WARNING:${NC} $1"
}

log_error() {
    echo -e "${RED}ERROR:${NC} $1"
}

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Automated GCP setup for WIF example application.

Required (can be set via env vars or flags):
  --project-id PROJECT_ID          GCP Project ID (env: GCP_PROJECT_ID)
  --infra-id INFRA_ID              Infrastructure/Cluster ID (env: HYPERSHIFT_INFRA_ID)
  --jwks-file PATH                 Path to JWKS file (env: JWKS_FILE)

Optional (can be set via env vars or flags):
  --sa-name NAME                   Service account name (env: GCP_SA_NAME, default: wif-app)
  --k8s-sa-name NAME               K8s SA name (env: K8S_SA_NAME, default: gcp-workload-sa)
  --k8s-namespace NS               K8s namespace (env: K8S_NAMESPACE, default: default)
  --roles ROLES                    Comma-separated IAM roles (env: GCP_IAM_ROLES, default: roles/compute.viewer)
  --skip-wif                       Skip WIF pool/provider creation
  --skip-sa                        Skip service account creation
  -h, --help                       Show this help

Environment Variables:
  GCP_PROJECT_ID                   GCP Project ID
  HYPERSHIFT_INFRA_ID              Infrastructure/Cluster ID
  JWKS_FILE                        Path to JWKS file
  GCP_SA_NAME                      GCP service account name
  K8S_SA_NAME                      Kubernetes service account name
  K8S_NAMESPACE                    Kubernetes namespace
  GCP_IAM_ROLES                    Comma-separated IAM roles

Examples:
  # Using environment variables
  export GCP_PROJECT_ID="my-project"
  export HYPERSHIFT_INFRA_ID="my-cluster"
  $0

  # Basic setup with flags
  $0 --project-id my-project --infra-id my-cluster

  # With JWKS file (env var)
  export JWKS_FILE="../ho-platform-none/install-ho-platform-none/jwks.json"
  $0

  # With JWKS file (flag)
  $0 --project-id my-project --infra-id my-cluster \\
     --jwks-file ../ho-platform-none/install-ho-platform-none/jwks.json

  # Custom roles (env var)
  export GCP_IAM_ROLES="roles/compute.viewer,roles/storage.objectViewer"
  $0

  # Custom roles (flag)
  $0 --project-id my-project --infra-id my-cluster \\
     --roles roles/compute.viewer,roles/storage.objectViewer

EOF
}

# Parse arguments - Environment variables as defaults
PROJECT_ID="${GCP_PROJECT_ID:-}"
INFRA_ID="${HYPERSHIFT_INFRA_ID:-}"
JWKS_FILE="${JWKS_FILE:-}"
SA_NAME="${GCP_SA_NAME:-wif-app}"
K8S_SA_NAME="${K8S_SA_NAME:-gcp-workload-sa}"
K8S_NAMESPACE="${K8S_NAMESPACE:-default}"
ROLES="${GCP_IAM_ROLES:-roles/compute.viewer}"
SKIP_WIF=false
SKIP_SA=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --project-id) PROJECT_ID="$2"; shift 2 ;;
        --infra-id) INFRA_ID="$2"; shift 2 ;;
        --jwks-file) JWKS_FILE="$2"; shift 2 ;;
        --sa-name) SA_NAME="$2"; shift 2 ;;
        --k8s-sa-name) K8S_SA_NAME="$2"; shift 2 ;;
        --k8s-namespace) K8S_NAMESPACE="$2"; shift 2 ;;
        --roles) ROLES="$2"; shift 2 ;;
        --skip-wif) SKIP_WIF=true; shift ;;
        --skip-sa) SKIP_SA=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) log_error "Unknown option: $1"; usage; exit 1 ;;
    esac
done

# Validate required parameters
if [ -z "$PROJECT_ID" ] || [ -z "$INFRA_ID" ] || [ -z "$JWKS_FILE" ]; then
    log_error "Missing required parameters"
    usage
    exit 1
fi

# Validate JWKS file exists
if [ ! -f "$JWKS_FILE" ]; then
    log_error "JWKS file not found: $JWKS_FILE"
    exit 1
fi

# Derived variables
POOL_ID="${INFRA_ID}-wi-pool"
PROVIDER_ID="${INFRA_ID}-k8s-provider"
ISSUER_URI="https://hypershift-${INFRA_ID}-oidc"
GSA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Display configuration
log_info "=== WIF Example GCP Setup Configuration ==="
echo "  Project ID:        $PROJECT_ID"
echo "  Infra ID:          $INFRA_ID"
echo "  Pool ID:           $POOL_ID"
echo "  Provider ID:       $PROVIDER_ID"
echo "  Issuer URI:        $ISSUER_URI"
echo "  GCP SA Name:       $SA_NAME"
echo "  GCP SA Email:      $GSA_EMAIL"
echo "  K8s SA:            $K8S_NAMESPACE/$K8S_SA_NAME"
echo "  IAM Roles:         $ROLES"
if [ -n "$JWKS_FILE" ]; then
    echo "  JWKS File:         $JWKS_FILE"
fi
echo ""

# Set project
log_info "Setting GCP project..."
gcloud config set project "$PROJECT_ID" --quiet

# Get project number
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
log_success "Project number: $PROJECT_NUMBER"

# Create Workload Identity Pool
if [ "$SKIP_WIF" = true ]; then
    log_warning "Skipping WIF pool/provider creation"
else
    log_info "Creating Workload Identity Pool: $POOL_ID"
    if gcloud iam workload-identity-pools describe "$POOL_ID" --location=global &>/dev/null; then
        log_warning "Pool already exists: $POOL_ID"
    else
        gcloud iam workload-identity-pools create "$POOL_ID" \
            --location=global \
            --description="WIF Pool for cluster ${INFRA_ID}" \
            --display-name="$POOL_ID"
        log_success "Created Workload Identity Pool"
    fi

    # Create OIDC Provider
    log_info "Creating OIDC Provider: $PROVIDER_ID"
    if gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" \
        --workload-identity-pool="$POOL_ID" \
        --location=global &>/dev/null; then
        log_warning "Provider already exists: $PROVIDER_ID"
    else
        if [ -n "$JWKS_FILE" ]; then
            # Create with JWKS file
            log_info "Using JWKS file: $JWKS_FILE"
            gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
                --location=global \
                --workload-identity-pool="$POOL_ID" \
                --issuer-uri="$ISSUER_URI" \
                --allowed-audiences="openshift" \
                --attribute-mapping="google.subject=assertion.sub" \
                --jwk-json-path="$JWKS_FILE"
        else
            # Create without JWKS (will try to discover from issuer)
            log_warning "No JWKS file provided - provider will attempt OIDC discovery"
            gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
                --location=global \
                --workload-identity-pool="$POOL_ID" \
                --issuer-uri="$ISSUER_URI" \
                --allowed-audiences="openshift" \
                --attribute-mapping="google.subject=assertion.sub"
        fi
        log_success "Created OIDC Provider"
    fi
fi

# Create Service Account
if [ "$SKIP_SA" = true ]; then
    log_warning "Skipping service account creation"
else
    log_info "Creating GCP Service Account: $SA_NAME"
    if gcloud iam service-accounts describe "$GSA_EMAIL" &>/dev/null; then
        log_warning "Service account already exists: $GSA_EMAIL"
    else
        gcloud iam service-accounts create "$SA_NAME" \
            --display-name="WIF Example Application SA"
        log_success "Created service account: $GSA_EMAIL"
    fi

    # Grant IAM roles
    log_info "Granting IAM roles..."
    IFS=',' read -ra ROLE_ARRAY <<< "$ROLES"
    for ROLE in "${ROLE_ARRAY[@]}"; do
        log_info "  Granting role: $ROLE"
        gcloud projects add-iam-policy-binding "$PROJECT_ID" \
            --member="serviceAccount:$GSA_EMAIL" \
            --role="$ROLE" \
            --condition=None --quiet
    done
    log_success "Granted IAM roles"

    # Setup WIF binding
    log_info "Setting up Workload Identity Federation binding..."
    WIF_MEMBER="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.sub/system:serviceaccount:${K8S_NAMESPACE}:${K8S_SA_NAME}"
    
    gcloud iam service-accounts add-iam-policy-binding "$GSA_EMAIL" \
        --member="$WIF_MEMBER" \
        --role="roles/iam.workloadIdentityUser" --quiet
    
    log_success "Configured WIF binding"
fi

# Generate credentials.json
CREDS_FILE="credentials.json"
log_info "Generating credentials file: $CREDS_FILE"

cat > "$CREDS_FILE" << EOF
{
  "type": "external_account",
  "audience": "//iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}",
  "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
  "token_url": "https://sts.googleapis.com/v1/token",
  "credential_source": {
    "file": "/var/run/secrets/openshift/serviceaccount/token"
  },
  "service_account_impersonation_url": "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${GSA_EMAIL}:generateAccessToken"
}
EOF

log_success "Created credentials file: $CREDS_FILE"

# Summary
echo ""
log_success "=== Setup Complete! ==="
echo ""
echo "GCP Resources Created:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Workload Identity Pool:    $POOL_ID"
echo "  OIDC Provider:              $PROVIDER_ID"
echo "  GCP Service Account:        $GSA_EMAIL"
echo "  Credentials File:           $CREDS_FILE"
echo ""
echo "Kubernetes Configuration:"
echo "  ServiceAccount:             $K8S_NAMESPACE/$K8S_SA_NAME"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next Steps:"
echo ""
echo "1. Update deployment.yaml with your configuration:"
echo "   - Set GCP_PROJECT_ID: $PROJECT_ID"
echo "   - Verify credentials.json configmap is created"
echo ""
echo "2. Create ConfigMap with credentials:"
echo "   kubectl create configmap gcp-wif-credentials \\"
echo "     --from-file=credentials.json=$CREDS_FILE \\"
echo "     -n wif-example"
echo ""
echo "3. Create the Kubernetes ServiceAccount in hosted cluster:"
echo "   kubectl --context=hosted-cluster create serviceaccount $K8S_SA_NAME -n $K8S_NAMESPACE"
echo ""
echo "4. Deploy the application:"
echo "   kubectl apply -f deployment.yaml"
echo ""
echo "5. Check the logs:"
echo "   kubectl logs -n wif-example -l app=wif-example -c wif-app -f"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

