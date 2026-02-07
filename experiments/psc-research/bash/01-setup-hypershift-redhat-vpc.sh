#!/bin/bash

# GCP Private Service Connect Demo - Step 1: Setup hypershift-redhat VPC (Service Provider)
# This script creates the service provider VPC with all necessary components

set -e

# Variables
PROJECT_ID=${PROJECT_ID:-"your-project-id"}
REGION=${REGION:-"us-central1"}
ZONE=${ZONE:-"us-central1-a"}

# VPC and Subnet Configuration
PROVIDER_VPC="hypershift-redhat"
PROVIDER_SUBNET="hypershift-redhat-subnet"
PROVIDER_SUBNET_RANGE="10.1.0.0/24"

# PSC NAT Subnet (required for Private Service Connect)
PSC_NAT_SUBNET="hypershift-redhat-psc-nat"
PSC_NAT_SUBNET_RANGE="10.1.1.0/24"

echo "Setting up hypershift-redhat VPC (Service Provider)..."

# Set the project
gcloud config set project $PROJECT_ID

# Create the VPC
echo "Creating VPC: $PROVIDER_VPC"
if ! gcloud compute networks describe $PROVIDER_VPC >/dev/null 2>&1; then
    gcloud compute networks create $PROVIDER_VPC \
        --subnet-mode=custom \
        --bgp-routing-mode=regional
    echo "VPC $PROVIDER_VPC created"
else
    echo "VPC $PROVIDER_VPC already exists, skipping"
fi

# Create the main subnet
echo "Creating subnet: $PROVIDER_SUBNET"
if ! gcloud compute networks subnets describe $PROVIDER_SUBNET --region=$REGION >/dev/null 2>&1; then
    gcloud compute networks subnets create $PROVIDER_SUBNET \
        --network=$PROVIDER_VPC \
        --range=$PROVIDER_SUBNET_RANGE \
        --region=$REGION \
        --enable-private-ip-google-access
    echo "Subnet $PROVIDER_SUBNET created"
else
    echo "Subnet $PROVIDER_SUBNET already exists, skipping"
fi

# Create the PSC NAT subnet (required for Service Attachment)
echo "Creating PSC NAT subnet: $PSC_NAT_SUBNET"
if ! gcloud compute networks subnets describe $PSC_NAT_SUBNET --region=$REGION >/dev/null 2>&1; then
    gcloud compute networks subnets create $PSC_NAT_SUBNET \
        --network=$PROVIDER_VPC \
        --range=$PSC_NAT_SUBNET_RANGE \
        --region=$REGION \
        --purpose=PRIVATE_SERVICE_CONNECT \
        --enable-private-ip-google-access
    echo "PSC NAT subnet $PSC_NAT_SUBNET created"
else
    echo "PSC NAT subnet $PSC_NAT_SUBNET already exists, skipping"
fi

# Create firewall rules
echo "Creating firewall rules for $PROVIDER_VPC"

# Allow health checks from Google's health check ranges
if ! gcloud compute firewall-rules describe ${PROVIDER_VPC}-allow-health-checks >/dev/null 2>&1; then
    gcloud compute firewall-rules create ${PROVIDER_VPC}-allow-health-checks \
        --network=$PROVIDER_VPC \
        --action=allow \
        --direction=ingress \
        --source-ranges=130.211.0.0/22,35.191.0.0/16 \
        --rules=tcp
    echo "Health check firewall rule created"
else
    echo "Health check firewall rule already exists, skipping"
fi

# Allow HTTP traffic for the demo service
if ! gcloud compute firewall-rules describe ${PROVIDER_VPC}-allow-http >/dev/null 2>&1; then
    gcloud compute firewall-rules create ${PROVIDER_VPC}-allow-http \
        --network=$PROVIDER_VPC \
        --action=allow \
        --direction=ingress \
        --source-ranges=$PROVIDER_SUBNET_RANGE \
        --rules=tcp:80,tcp:8080
    echo "HTTP firewall rule created"
else
    echo "HTTP firewall rule already exists, skipping"
fi

# Allow SSH for management
if ! gcloud compute firewall-rules describe ${PROVIDER_VPC}-allow-ssh >/dev/null 2>&1; then
    gcloud compute firewall-rules create ${PROVIDER_VPC}-allow-ssh \
        --network=$PROVIDER_VPC \
        --action=allow \
        --direction=ingress \
        --source-ranges=0.0.0.0/0 \
        --rules=tcp:22
    echo "SSH firewall rule created"
else
    echo "SSH firewall rule already exists, skipping"
fi

# Allow all egress traffic (required for VMs without external IPs to reach internet)
if ! gcloud compute firewall-rules describe ${PROVIDER_VPC}-allow-egress >/dev/null 2>&1; then
    gcloud compute firewall-rules create ${PROVIDER_VPC}-allow-egress \
        --network=$PROVIDER_VPC \
        --action=allow \
        --direction=egress \
        --destination-ranges=0.0.0.0/0 \
        --rules=all
    echo "Egress firewall rule created"
else
    echo "Egress firewall rule already exists, skipping"
fi

echo "hypershift-redhat VPC setup completed successfully!"
echo "VPC: $PROVIDER_VPC"
echo "Main Subnet: $PROVIDER_SUBNET ($PROVIDER_SUBNET_RANGE)"
echo "PSC NAT Subnet: $PSC_NAT_SUBNET ($PSC_NAT_SUBNET_RANGE)"