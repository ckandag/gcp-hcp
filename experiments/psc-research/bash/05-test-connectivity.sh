#!/bin/bash

# GCP Private Service Connect Demo - Step 5: Test Connectivity
# This script tests the Private Service Connect connection between VPCs

set -e

# Variables
PROJECT_ID=${PROJECT_ID:-"your-project-id"}
REGION=${REGION:-"us-central1"}
ZONE=${ZONE:-"us-central1-a"}

# VM Configuration
CONSUMER_VM="customer-client-vm"
PSC_FORWARDING_RULE="customer-psc-forwarding-rule"

echo "Testing Private Service Connect connectivity..."

# Set the project
gcloud config set project $PROJECT_ID

# Get the PSC endpoint IP
PSC_IP=$(gcloud compute forwarding-rules describe $PSC_FORWARDING_RULE --region=$REGION --format="value(IPAddress)")
echo "PSC Endpoint IP: $PSC_IP"

echo ""
echo "=== DIAGNOSTIC TESTS ==="

# Get the internal load balancer IP for direct testing
LB_IP=$(gcloud compute forwarding-rules describe redhat-forwarding-rule --region=$REGION --format="value(IPAddress)")
echo "Internal Load Balancer IP: $LB_IP"
echo "PSC Endpoint IP: $PSC_IP"

echo ""
echo "=== BACKEND HEALTH CHECK ==="
gcloud compute backend-services get-health redhat-backend-service --region=$REGION

echo ""
echo "=== PSC INFRASTRUCTURE STATUS ==="

# Check PSC forwarding rule configuration
echo "PSC Forwarding Rule Configuration:"
gcloud compute forwarding-rules describe $PSC_FORWARDING_RULE --region=$REGION --format="table(IPAddress,target,loadBalancingScheme,networkTier)"

echo ""
echo "Service Attachment Status:"
gcloud compute service-attachments describe redhat-service-attachment --region=$REGION --format="table(connectionPreference,enableProxyProtocol,targetService)"

echo ""
echo "=== CONNECTIVITY TESTS ==="

# Test 1: Basic network connectivity to PSC IP (ICMP expected to fail)
echo "Test 1: Network reachability to PSC endpoint (ICMP test - expected to fail)"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="ping -c 3 -W 5 $PSC_IP && echo 'PSC IP is reachable via ICMP (unexpected)' || echo 'PSC IP is not reachable via ICMP (expected - PSC endpoints do not respond to ping)'"

echo ""
echo "Test 2: TCP port connectivity to PSC endpoint"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="timeout 10 nc -zv $PSC_IP 8080 && echo 'PSC port 8080 is OPEN' || echo 'PSC port 8080 is CLOSED or filtered'"

echo ""
echo "Test 3: Direct Load Balancer connectivity (cross-VPC should fail)"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="timeout 5 nc -zv $LB_IP 8080 && echo 'Direct LB accessible (unexpected!)' || echo 'Direct LB not accessible (expected - different VPC)'"

echo ""
echo "Test 4: PSC HTTP connectivity with verbose output"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="curl -v --connect-timeout 15 --max-time 30 http://$PSC_IP:8080/ 2>&1" || echo "PSC HTTP test failed"

echo ""
echo "Test 5: PSC Health endpoint"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="curl -s --connect-timeout 15 --max-time 30 http://$PSC_IP:8080/health 2>&1 && echo" || echo "PSC health check failed"

echo ""
echo "Test 6: Network routing analysis"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="
echo 'Route to PSC endpoint:'
ip route get $PSC_IP 2>/dev/null || echo 'No route to PSC endpoint found'
echo ''
echo 'Route to Load Balancer (should fail):'
ip route get $LB_IP 2>/dev/null || echo 'No route to Load Balancer (expected - different VPC)'
echo ''
echo 'Default gateway:'
ip route | grep default
echo ''
echo 'Consumer VM internal IP:'
ip addr show | grep 'inet 10.2'
"

echo ""
echo "Test 7: PSC Endpoint specific checks"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="
echo 'Testing PSC endpoint connectivity:'
echo '- Telnet connection test:'
timeout 5 telnet $PSC_IP 8080 < /dev/null 2>&1 | head -5
echo ''
echo '- Netcat port scan:'
timeout 3 nc -w1 $PSC_IP 8080 < /dev/null && echo 'Connection successful' || echo 'Connection failed'
echo ''
echo '- HTTP response test:'
timeout 10 wget -qO- --timeout=5 http://$PSC_IP:8080/ 2>&1 | head -3 || echo 'wget failed'
"

echo ""
echo "=== PROVIDER VM SERVICE STATUS ==="

echo "Provider VM service verification:"
gcloud compute ssh redhat-service-vm --zone=$ZONE --command="
echo 'Service status:'
systemctl is-active demo-api || echo 'demo-api service not active'
echo ''
echo 'Service listening on ports:'
ss -tlnp | grep :8080 || echo 'No service listening on port 8080'
echo ''
echo 'Service logs (last 10 lines):'
journalctl -u demo-api --no-pager -n 10 || echo 'No logs available'
echo ''
echo 'Test local connectivity:'
curl -s --connect-timeout 5 http://localhost:8080/health || echo 'Local health check failed'
"

echo ""
echo "=== LOAD BALANCER VERIFICATION ==="

echo "Testing direct access to Load Balancer from Provider VPC:"
gcloud compute ssh redhat-service-vm --zone=$ZONE --command="
echo 'Testing Load Balancer from same VPC:'
curl -s --connect-timeout 10 http://$LB_IP:8080/ || echo 'Load Balancer not accessible from provider VPC'
echo ''
echo 'Load Balancer health:'
curl -s --connect-timeout 10 http://$LB_IP:8080/health || echo 'Load Balancer health check failed'
"

echo ""
echo "=== ADVANCED PSC TESTS (if basic connectivity works) ==="

echo "Test 8: Multiple requests to verify consistent connectivity"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="
if curl -s --connect-timeout 5 http://$PSC_IP:8080/health >/dev/null 2>&1; then
  echo 'PSC is responding, testing multiple requests:'
  for i in {1..3}; do
    echo \"Request \$i:\"
    if curl -s --connect-timeout 5 http://$PSC_IP:8080/health; then
      echo ' - SUCCESS'
    else
      echo ' - FAILED'
    fi
    sleep 1
  done
else
  echo 'PSC endpoint not responding, skipping multiple request test'
fi
"

echo ""
echo "Test 9: Service discovery and metadata (if PSC works)"
gcloud compute ssh $CONSUMER_VM --zone=$ZONE --command="
if curl -s --connect-timeout 5 http://$PSC_IP:8080/health >/dev/null 2>&1; then
  echo 'Testing service discovery:'
  curl -s --connect-timeout 10 http://$PSC_IP:8080/ | python3 -c 'import sys, json; data=json.load(sys.stdin); print(f\"Service: {data.get(\"message\", \"N/A\")}\"); print(f\"Hostname: {data.get(\"hostname\", \"N/A\")}\"); print(f\"Timestamp: {data.get(\"timestamp\", \"N/A\")}\")'
else
  echo 'PSC endpoint not responding, skipping service discovery test'
fi
"

echo ""
echo "=== TEST SUMMARY ==="
echo "Private Service Connect endpoint: $PSC_IP"
echo "All tests completed. Check the output above for any failures."
echo ""
echo "If tests are successful, you have demonstrated:"
echo "✓ Cross-VPC connectivity via Private Service Connect"
echo "✓ Service isolation (no direct VPC peering required)"
echo "✓ Load balancing and health checking"
echo "✓ Service discovery through PSC endpoint"