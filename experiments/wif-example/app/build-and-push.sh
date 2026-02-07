#!/bin/bash
# build-and-push.sh - Build and push the WIF example container image
#
# Usage:
#   export GCP_PROJECT_ID="my-project"
#   ./build-and-push.sh
#
# Environment Variables:
#   GCP_PROJECT_ID    GCP Project ID (required)
#   PLATFORM          Target platform (default: linux/amd64)

set -euo pipefail

# Configuration
GCP_PROJECT_ID="${GCP_PROJECT_ID:?GCP_PROJECT_ID must be set}"
PLATFORM="${PLATFORM:-linux/amd64}"
IMAGE_NAME="gcr.io/${GCP_PROJECT_ID}/wif-example:latest"

# Check if podman is available
if ! command -v podman &> /dev/null; then
  echo "Error: podman is not installed"
  exit 1
fi

echo "Logging into gcr.io with podman"
podman login -u oauth2accesstoken -p "$(gcloud auth print-access-token)" gcr.io || true

echo "Building image: ${IMAGE_NAME}"
podman build --platform "${PLATFORM}" -t "${IMAGE_NAME}" -f Dockerfile .

echo "Pushing image to GCR"
podman push "${IMAGE_NAME}"

echo "✓ Done: ${IMAGE_NAME}"
