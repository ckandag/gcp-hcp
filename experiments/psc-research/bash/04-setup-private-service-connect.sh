#!/bin/bash

# GCP Private Service Connect Demo - Step 4: Setup Private Service Connect
# This script creates the internal load balancer, service attachment, and PSC endpoint

set -e

# Variables
PROJECT_ID=${PROJECT_ID:-"your-project-id"}
REGION=${REGION:-"us-central1"}
ZONE=${ZONE:-"us-central1-a"}

# Network Configuration
PROVIDER_VPC="hypershift-redhat"
PROVIDER_SUBNET="hypershift-redhat-subnet"
PSC_NAT_SUBNET="hypershift-redhat-psc-nat"
CONSUMER_VPC="hypershift-customer"
CONSUMER_SUBNET="hypershift-customer-subnet"

# Load Balancer Configuration
HEALTH_CHECK="redhat-service-health-check"
BACKEND_SERVICE="redhat-backend-service"
FORWARDING_RULE="redhat-forwarding-rule"
SERVICE_ATTACHMENT="redhat-service-attachment"

# PSC Configuration
PSC_ENDPOINT="customer-psc-endpoint"
PSC_FORWARDING_RULE="customer-psc-forwarding-rule"

# VM Configuration
PROVIDER_VM="redhat-service-vm"

echo "Setting up Private Service Connect components..."

# Set the project
gcloud config set project $PROJECT_ID

echo "Step 1: Creating health check for internal load balancer"
if ! gcloud compute health-checks describe $HEALTH_CHECK >/dev/null 2>&1; then
    gcloud compute health-checks create tcp $HEALTH_CHECK \
        --port=8080 \
        --check-interval=10s \
        --timeout=5s \
        --healthy-threshold=2 \
        --unhealthy-threshold=3
    echo "Health check $HEALTH_CHECK created"
else
    echo "Health check $HEALTH_CHECK already exists, skipping"
fi

echo "Step 2: Creating instance group for the service VM"
# Get the zone of the provider VM
PROVIDER_VM_ZONE=$(gcloud compute instances list --filter="name:$PROVIDER_VM" --format="value(zone)" | sed 's|.*/||')

# Create unmanaged instance group
if ! gcloud compute instance-groups unmanaged describe redhat-service-group --zone=$PROVIDER_VM_ZONE >/dev/null 2>&1; then
    gcloud compute instance-groups unmanaged create redhat-service-group \
        --zone=$PROVIDER_VM_ZONE
    echo "Instance group redhat-service-group created"
else
    echo "Instance group redhat-service-group already exists, skipping creation"
fi

# Add the VM to the instance group (check if not already a member)
CURRENT_INSTANCES=$(gcloud compute instance-groups unmanaged list-instances redhat-service-group --zone=$PROVIDER_VM_ZONE --format="value(instance)" 2>/dev/null | grep "$PROVIDER_VM" || echo "")
if [ -z "$CURRENT_INSTANCES" ]; then
    gcloud compute instance-groups unmanaged add-instances redhat-service-group \
        --zone=$PROVIDER_VM_ZONE \
        --instances=$PROVIDER_VM
    echo "VM $PROVIDER_VM added to instance group"
else
    echo "VM $PROVIDER_VM already in instance group, skipping"
fi

# Set named ports for the instance group
gcloud compute instance-groups unmanaged set-named-ports redhat-service-group \
    --zone=$PROVIDER_VM_ZONE \
    --named-ports=http:8080

echo "Step 3: Creating backend service"
if ! gcloud compute backend-services describe $BACKEND_SERVICE --region=$REGION >/dev/null 2>&1; then
    gcloud compute backend-services create $BACKEND_SERVICE \
        --load-balancing-scheme=INTERNAL \
        --protocol=TCP \
        --health-checks=$HEALTH_CHECK \
        --region=$REGION
    echo "Backend service $BACKEND_SERVICE created"
else
    echo "Backend service $BACKEND_SERVICE already exists, skipping creation"
fi

# Add the instance group as a backend (check if not already added)
CURRENT_BACKENDS=$(gcloud compute backend-services describe $BACKEND_SERVICE --region=$REGION --format="value(backends[].group)" 2>/dev/null | grep "redhat-service-group" || echo "")
if [ -z "$CURRENT_BACKENDS" ]; then
    gcloud compute backend-services add-backend $BACKEND_SERVICE \
        --instance-group=redhat-service-group \
        --instance-group-zone=$PROVIDER_VM_ZONE \
        --region=$REGION
    echo "Instance group added to backend service"
else
    echo "Instance group already added to backend service, skipping"
fi

echo "Step 4: Creating internal load balancer forwarding rule"
if ! gcloud compute forwarding-rules describe $FORWARDING_RULE --region=$REGION >/dev/null 2>&1; then
    gcloud compute forwarding-rules create $FORWARDING_RULE \
        --load-balancing-scheme=INTERNAL \
        --backend-service=$BACKEND_SERVICE \
        --subnet=$PROVIDER_SUBNET \
        --region=$REGION \
        --ports=8080
    echo "Forwarding rule $FORWARDING_RULE created"
else
    echo "Forwarding rule $FORWARDING_RULE already exists, skipping"
fi

# Get the internal load balancer IP
LB_IP=$(gcloud compute forwarding-rules describe $FORWARDING_RULE --region=$REGION --format="value(IPAddress)")
echo "Internal Load Balancer IP: $LB_IP"

echo "Step 5: Creating service attachment for Private Service Connect"
if ! gcloud compute service-attachments describe $SERVICE_ATTACHMENT --region=$REGION >/dev/null 2>&1; then
    gcloud compute service-attachments create $SERVICE_ATTACHMENT \
        --region=$REGION \
        --producer-forwarding-rule=$FORWARDING_RULE \
        --connection-preference=ACCEPT_AUTOMATIC \
        --nat-subnets=$PSC_NAT_SUBNET
    echo "Service attachment $SERVICE_ATTACHMENT created"
else
    echo "Service attachment $SERVICE_ATTACHMENT already exists, skipping"
fi

# Get the service attachment URI
SERVICE_ATTACHMENT_URI=$(gcloud compute service-attachments describe $SERVICE_ATTACHMENT --region=$REGION --format="value(selfLink)")
echo "Service Attachment URI: $SERVICE_ATTACHMENT_URI"

echo "Step 6: Creating Private Service Connect endpoint in consumer VPC"
if ! gcloud compute addresses describe $PSC_ENDPOINT-ip --region=$REGION >/dev/null 2>&1; then
    gcloud compute addresses create $PSC_ENDPOINT-ip \
        --subnet=$CONSUMER_SUBNET \
        --region=$REGION
    echo "PSC endpoint IP address $PSC_ENDPOINT-ip created"
else
    echo "PSC endpoint IP address $PSC_ENDPOINT-ip already exists, skipping"
fi

# Get the reserved IP address
PSC_IP=$(gcloud compute addresses describe $PSC_ENDPOINT-ip --region=$REGION --format="value(address)")
echo "Reserved PSC Endpoint IP: $PSC_IP"

# Create the PSC endpoint
if ! gcloud compute forwarding-rules describe $PSC_FORWARDING_RULE --region=$REGION >/dev/null 2>&1; then
    gcloud compute forwarding-rules create $PSC_FORWARDING_RULE \
        --network=$CONSUMER_VPC \
        --subnet=$CONSUMER_SUBNET \
        --address=$PSC_ENDPOINT-ip \
        --target-service-attachment=$SERVICE_ATTACHMENT_URI \
        --region=$REGION
    echo "PSC forwarding rule $PSC_FORWARDING_RULE created"
else
    echo "PSC forwarding rule $PSC_FORWARDING_RULE already exists, skipping"
fi

echo "Step 7: Creating firewall rule to allow PSC NAT subnet traffic"
# Critical: Allow traffic from PSC NAT subnet to reach the service
# PSC translates consumer traffic (10.2.0.2) to PSC NAT subnet IPs (10.1.1.x)
# Without this rule, traffic reaches the provider VM but is blocked by default-deny-ingress
if ! gcloud compute firewall-rules describe ${PROVIDER_VPC}-allow-psc-nat >/dev/null 2>&1; then
    gcloud compute firewall-rules create ${PROVIDER_VPC}-allow-psc-nat \
        --network=$PROVIDER_VPC \
        --action=allow \
        --direction=ingress \
        --source-ranges=$PSC_NAT_SUBNET_RANGE \
        --rules=tcp:8080 \
        --description="Allow PSC NAT subnet traffic to reach service"
    echo "PSC NAT firewall rule created"
else
    echo "PSC NAT firewall rule already exists, skipping"
fi

echo "Private Service Connect setup completed successfully!"
echo ""
echo "=== CONFIGURATION SUMMARY ==="
echo "Service Provider (hypershift-redhat):"
echo "  - Internal Load Balancer IP: $LB_IP"
echo "  - Service Attachment: $SERVICE_ATTACHMENT"
echo "  - Service Attachment URI: $SERVICE_ATTACHMENT_URI"
echo ""
echo "Service Consumer (hypershift-customer):"
echo "  - PSC Endpoint IP: $PSC_IP"
echo "  - PSC Forwarding Rule: $PSC_FORWARDING_RULE"
echo ""
echo "Next step: Test connectivity from consumer VM to PSC endpoint IP ($PSC_IP)"