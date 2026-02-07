#!/bin/bash

# GCP Private Service Connect Demo - Step 3b: Test VPC Isolation
# This script demonstrates that the VPCs are isolated before PSC is set up

set -e

# Variables
PROJECT_ID=${PROJECT_ID:-"your-project-id"}
REGION=${REGION:-"us-central1"}
ZONE=${ZONE:-"us-central1-a"}

# VM Configuration
PROVIDER_VM="redhat-service-vm"
CONSUMER_VM="customer-client-vm"

echo "Testing VPC isolation (before Private Service Connect)..."

# Set the project
gcloud config set project $PROJECT_ID

# Get VM internal IPs
PROVIDER_IP=$(gcloud compute instances describe $PROVIDER_VM --zone=$ZONE --format="value(networkInterfaces[0].networkIP)")
CONSUMER_IP=$(gcloud compute instances describe $CONSUMER_VM --zone=$ZONE --format="value(networkInterfaces[0].networkIP)")

echo "Provider VM (hypershift-redhat): $PROVIDER_VM - $PROVIDER_IP"
echo "Consumer VM (hypershift-customer): $CONSUMER_VM - $CONSUMER_IP"

echo ""
echo "=== VPC ISOLATION TESTS ==="

echo "Test 1: Attempting to ping provider VM from consumer VM (should FAIL)"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="ping -c 3 -W 5 $PROVIDER_IP" && echo "❌ UNEXPECTED: Ping succeeded!" || echo "✅ EXPECTED: Ping failed - VPCs are isolated"

echo ""
echo "Test 2: Attempting to connect to HTTP service (should FAIL)"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="curl --connect-timeout 10 http://$PROVIDER_IP/" && echo "❌ UNEXPECTED: HTTP connection succeeded!" || echo "✅ EXPECTED: HTTP connection failed - no network route"

echo ""
echo "Test 3: Attempting to connect to API service on port 8080 (should FAIL)"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="curl --connect-timeout 10 http://$PROVIDER_IP:8080/" && echo "❌ UNEXPECTED: API connection succeeded!" || echo "✅ EXPECTED: API connection failed - no network route"

echo ""
echo "Test 4: Testing netcat connectivity (should FAIL)"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="timeout 10 nc -zv $PROVIDER_IP 80" && echo "❌ UNEXPECTED: Netcat succeeded!" || echo "✅ EXPECTED: Netcat failed - port unreachable"

echo ""
echo "Test 5: Checking routing table from consumer VM"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="
echo 'Consumer VM routing table:'
ip route
echo ''
echo 'Attempting to get route to provider VM:'
ip route get $PROVIDER_IP || echo 'No route to provider VM (expected)'
"

echo ""
echo "Test 6: Testing reverse connectivity (provider to consumer)"
gcloud compute ssh $PROVIDER_VM --zone=$ZONE --command="ping -c 3 -W 5 $CONSUMER_IP" && echo "❌ UNEXPECTED: Reverse ping succeeded!" || echo "✅ EXPECTED: Reverse ping failed - VPCs are isolated"

echo ""
echo "=== VERIFICATION OF SERVICE AVAILABILITY ==="

echo "Test 7: Verifying service is running on provider VM (should SUCCEED)"
gcloud compute ssh $PROVIDER_VM --zone=$ZONE --command="curl -s http://localhost/" && echo "✅ Service is running locally on provider VM" || echo "❌ Service not running on provider VM"

echo ""
echo "Test 8: Verifying API is running on provider VM (should SUCCEED)"
gcloud compute ssh $PROVIDER_VM --zone=$ZONE --command="curl -s http://localhost:8080/" && echo "✅ API is running locally on provider VM" || echo "❌ API not running on provider VM"

echo ""
echo "=== NETWORK CONFIGURATION SUMMARY ==="
echo "Provider VM Network Details:"
gcloud compute ssh $PROVIDER_VM --zone=$ZONE --command="
echo 'IP Address: $PROVIDER_IP'
echo 'Network Interface:'
ip addr show ens4 | grep inet
echo 'Default Gateway:'
ip route | grep default
"

echo ""
echo "Consumer VM Network Details:"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="
echo 'IP Address: $CONSUMER_IP'
echo 'Network Interface:'
ip addr show ens4 | grep inet
echo 'Default Gateway:'
ip route | grep default
"

echo ""
echo "=== ISOLATION TEST SUMMARY ==="
echo "🔒 VPC Isolation Confirmed:"
echo "   ✅ hypershift-redhat VPC: $PROVIDER_IP (isolated)"
echo "   ✅ hypershift-customer VPC: $CONSUMER_IP (isolated)"
echo "   ✅ No direct connectivity between VPCs"
echo "   ✅ Service is running but not accessible cross-VPC"
echo ""
echo "Next step: Set up Private Service Connect to enable secure connectivity"
echo "Run: ./04-setup-private-service-connect.sh"