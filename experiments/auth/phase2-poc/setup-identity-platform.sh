#!/bin/bash
# =============================================================================
# Identity Platform Setup for Phase 2 (Token Exchange Flow)
# =============================================================================
#
# This script configures GCP Identity Platform for the Cloud Function token
# exchange flow. It sets up the minimum required configuration.
#
# What this script does:
#   1. Enables Identity Platform API
#   2. Configures OIDC provider to accept gcloud identity tokens
#   3. Creates/retrieves API key for Cloud Function
#
# Usage:
#   ./setup-identity-platform.sh <project-id>
#   ./setup-identity-platform.sh my-project
#
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
PROJECT_ID="${1:-}"

if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}Error: Project ID is required${NC}"
    echo ""
    echo "Usage: $0 <project-id>"
    echo ""
    echo "Example:"
    echo "  $0 my-project"
    exit 1
fi

echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Identity Platform Setup for Phase 2                      ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Project: ${YELLOW}${PROJECT_ID}${NC}"
echo ""

# =============================================================================
# Step 1: Enable Required APIs
# =============================================================================
echo -e "${GREEN}[1/4] Enabling required APIs...${NC}"

gcloud services enable identitytoolkit.googleapis.com --project "$PROJECT_ID" --quiet
echo "  ✓ Identity Platform API enabled"

gcloud services enable cloudresourcemanager.googleapis.com --project "$PROJECT_ID" --quiet
echo "  ✓ Cloud Resource Manager API enabled"

gcloud services enable cloudfunctions.googleapis.com --project "$PROJECT_ID" --quiet
echo "  ✓ Cloud Functions API enabled"

echo ""

# =============================================================================
# Step 2: Configure OIDC Provider for gcloud tokens
# =============================================================================
# Identity Platform needs an OIDC provider configuration to accept tokens
# from gcloud CLI (which uses accounts.google.com as issuer).
#
# Provider ID: oidc.gcloud
# Issuer: https://accounts.google.com
# Client ID: 32555940559.apps.googleusercontent.com (gcloud CLI client)
# =============================================================================
echo -e "${GREEN}[2/4] Configuring OIDC provider for gcloud tokens...${NC}"

ACCESS_TOKEN=$(gcloud auth print-access-token)

# Check if the provider already exists
EXISTING_PROVIDER=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" \
    "https://identitytoolkit.googleapis.com/v2/projects/${PROJECT_ID}/oauthIdpConfigs/oidc.gcloud" 2>/dev/null | jq -r '.name // empty')

if [ -n "$EXISTING_PROVIDER" ]; then
    echo "  ✓ OIDC provider 'oidc.gcloud' already exists"
else
    # Create the OIDC provider
    curl -s -X POST \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        "https://identitytoolkit.googleapis.com/v2/projects/${PROJECT_ID}/oauthIdpConfigs?oauthIdpConfigId=oidc.gcloud" \
        -d '{
            "displayName": "gcloud CLI",
            "enabled": true,
            "issuer": "https://accounts.google.com",
            "clientId": "32555940559.apps.googleusercontent.com",
            "clientSecret": "placeholder"
        }' > /dev/null
    
    echo "  ✓ OIDC provider 'oidc.gcloud' created"
fi

echo ""

# =============================================================================
# Step 3: Get or Create API Key
# =============================================================================
# The Cloud Function needs an API key to call Identity Platform APIs
# for minting custom tokens.
# =============================================================================
echo -e "${GREEN}[3/4] Getting Identity Platform API key...${NC}"

# Try to find existing API key
EXISTING_KEY=$(gcloud alpha services api-keys list \
    --project="$PROJECT_ID" \
    --filter="displayName~'Browser key' OR displayName~'Identity Platform' OR displayName~'idp-key'" \
    --format="value(name)" \
    --limit=1 2>/dev/null || true)

if [ -n "$EXISTING_KEY" ]; then
    API_KEY=$(gcloud alpha services api-keys get-key-string "$EXISTING_KEY" \
        --format="value(keyString)" 2>/dev/null || true)
    echo "  ✓ Found existing API key"
else
    # Create a new API key
    echo "  Creating new API key for Identity Platform..."
    gcloud alpha services api-keys create \
        --display-name="idp-key-for-cloud-function" \
        --project="$PROJECT_ID" \
        --api-target=service=identitytoolkit.googleapis.com \
        --quiet 2>/dev/null || true
    
    # Get the newly created key
    sleep 2
    NEW_KEY=$(gcloud alpha services api-keys list \
        --project="$PROJECT_ID" \
        --filter="displayName='idp-key-for-cloud-function'" \
        --format="value(name)" \
        --limit=1 2>/dev/null || true)
    
    if [ -n "$NEW_KEY" ]; then
        API_KEY=$(gcloud alpha services api-keys get-key-string "$NEW_KEY" \
            --format="value(keyString)" 2>/dev/null || true)
        echo "  ✓ Created new API key"
    fi
fi

echo ""

# =============================================================================
# Step 4: Summary and Next Steps
# =============================================================================
echo -e "${GREEN}[4/4] Setup complete!${NC}"
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Setup Complete                                           ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Project:       ${YELLOW}${PROJECT_ID}${NC}"
echo -e "OIDC Provider: ${YELLOW}oidc.gcloud${NC}"
if [ -n "$API_KEY" ]; then
    echo -e "API Key:       ${YELLOW}${API_KEY:0:10}...${NC}"
else
    echo -e "API Key:       ${RED}Not found - check GCP Console${NC}"
fi
echo ""
echo -e "${GREEN}Next Steps:${NC}"
echo ""
echo "1. Deploy the Cloud Function:"
echo -e "   ${YELLOW}cd cloud-function && ./deploy.sh $PROJECT_ID${NC}"
echo ""
echo "2. If API key wasn't found automatically, set it in Cloud Function:"
echo "   - Go to GCP Console → APIs & Services → Credentials"
echo "   - Find 'Browser key (auto created by Firebase)' or create one"
echo "   - Update Cloud Function environment variable: IDP_API_KEY"
echo ""
echo "3. Test the token exchange:"
echo "   GCLOUD_TOKEN=\$(gcloud auth print-identity-token)"
echo "   curl -X POST <cloud-function-url>/exchange \\"
echo "     -H \"Authorization: Bearer \$GCLOUD_TOKEN\" \\"
echo "     -d '{\"google_token\": \"'\$GCLOUD_TOKEN'\"}'"
echo ""

# Save configuration
CONFIG_FILE="$(dirname "$0")/idp-config.json"
cat > "$CONFIG_FILE" << EOF
{
  "project_id": "$PROJECT_ID",
  "oidc_provider": "oidc.gcloud",
  "issuer_url": "https://securetoken.google.com/$PROJECT_ID",
  "audience": "$PROJECT_ID",
  "api_key": "${API_KEY:-"CHECK_GCP_CONSOLE"}",
  "setup_date": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF
echo -e "Config saved to: ${YELLOW}${CONFIG_FILE}${NC}"

