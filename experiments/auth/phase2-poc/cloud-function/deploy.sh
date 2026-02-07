#!/bin/bash
# Deploy the OAuth Helper Cloud Function
#
# Usage:
#   ./deploy.sh <project-id>
#   ./deploy.sh <project-id> <region>
#
# Example:
#   ./deploy.sh my-project
#   ./deploy.sh my-project us-east1

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Parameters
PROJECT_ID="${1:-}"
REGION="${2:-us-central1}"
FUNCTION_NAME="oauth-helper"

# Validate parameters
if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}Error: Project ID is required${NC}"
    echo ""
    echo "Usage: $0 <project-id> [region]"
    echo ""
    echo "Examples:"
    echo "  $0 my-project"
    echo "  $0 my-project us-east1"
    exit 1
fi

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Deploy OAuth Helper Cloud Function                       ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Project:  ${YELLOW}${PROJECT_ID}${NC}"
echo -e "Region:   ${YELLOW}${REGION}${NC}"
echo -e "Function: ${YELLOW}${FUNCTION_NAME}${NC}"
echo ""

# Check if gcloud is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | grep -q "@"; then
    echo -e "${RED}Error: Not authenticated with gcloud${NC}"
    echo "Run: gcloud auth login"
    exit 1
fi

# Set project
echo -e "${GREEN}[1/5] Setting project...${NC}"
gcloud config set project "$PROJECT_ID"

# Enable required APIs
echo -e "${GREEN}[2/5] Enabling required APIs...${NC}"
gcloud services enable \
    cloudfunctions.googleapis.com \
    cloudbuild.googleapis.com \
    identitytoolkit.googleapis.com \
    run.googleapis.com \
    --quiet

# Get or create IDP API key
echo -e "${GREEN}[3/5] Getting Identity Platform API key...${NC}"
IDP_API_KEY=""

# Try to find existing API key
EXISTING_KEY=$(gcloud alpha services api-keys list \
    --filter="displayName~'Browser key' OR displayName~'Identity Platform'" \
    --format="value(name)" \
    --limit=1 2>/dev/null || true)

if [ -n "$EXISTING_KEY" ]; then
    IDP_API_KEY=$(gcloud alpha services api-keys get-key-string "$EXISTING_KEY" \
        --format="value(keyString)" 2>/dev/null || true)
fi

if [ -z "$IDP_API_KEY" ]; then
    echo -e "${YELLOW}Warning: Could not find IDP API key automatically${NC}"
    echo "You may need to set it manually in the Cloud Function environment variables"
    echo ""
    echo "To find your API key:"
    echo "  1. Go to GCP Console → APIs & Services → Credentials"
    echo "  2. Find 'Browser key (auto created by Firebase)' or similar"
    echo "  3. Copy the API key"
    echo ""
    read -p "Enter IDP API Key (or press Enter to skip): " IDP_API_KEY
fi

# Get the script directory (where the function code is)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Deploy the function
echo -e "${GREEN}[4/5] Deploying Cloud Function...${NC}"
echo ""

DEPLOY_CMD="gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime=python312 \
    --region=$REGION \
    --source=$SCRIPT_DIR \
    --entry-point=oauth_handler \
    --trigger-http \
    --memory=256MB \
    --timeout=60s \
    --set-env-vars=PROJECT_ID=$PROJECT_ID"

if [ -n "$IDP_API_KEY" ]; then
    DEPLOY_CMD="$DEPLOY_CMD,IDP_API_KEY=$IDP_API_KEY"
fi

eval "$DEPLOY_CMD"

# Get the function URL
echo ""
echo -e "${GREEN}[5/5] Getting function URL...${NC}"
FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
    --region="$REGION" \
    --format="value(serviceConfig.uri)")

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Deployment Complete!                                     ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Function URL: ${YELLOW}${FUNCTION_URL}${NC}"
echo ""
echo -e "${GREEN}Endpoints:${NC}"
echo -e "  Health:   ${FUNCTION_URL}/health"
echo -e "  Exchange: ${FUNCTION_URL}/exchange"
echo ""
echo -e "${GREEN}Test with:${NC}"
echo -e "  curl -s ${FUNCTION_URL}/health | jq"
echo ""
echo -e "${GREEN}Exchange token:${NC}"
echo -e "  GCLOUD_TOKEN=\$(gcloud auth print-identity-token)"
echo -e "  curl -s -X POST ${FUNCTION_URL}/exchange \\"
echo -e "    -H \"Authorization: Bearer \$GCLOUD_TOKEN\" \\"
echo -e "    -H \"Content-Type: application/json\" \\"
echo -e "    -d '{\"google_token\": \"'\$GCLOUD_TOKEN'\"}' | jq"
echo ""

# Save config for reference
CONFIG_FILE="$SCRIPT_DIR/deployment-config.json"
cat > "$CONFIG_FILE" << EOF
{
  "project_id": "$PROJECT_ID",
  "region": "$REGION",
  "function_name": "$FUNCTION_NAME",
  "function_url": "$FUNCTION_URL",
  "deployed_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF

echo -e "Config saved to: ${YELLOW}${CONFIG_FILE}${NC}"

