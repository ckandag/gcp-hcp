#!/bin/bash

# GCP Private Service Connect Demo - Step 2: Setup hypershift-customer VPC (Service Consumer)
# This script creates the service consumer VPC

set -e

# Variables
PROJECT_ID=${PROJECT_ID:-"your-project-id"}
REGION=${REGION:-"us-central1"}
ZONE=${ZONE:-"us-central1-a"}

# VPC and Subnet Configuration
CONSUMER_VPC="hypershift-customer"
CONSUMER_SUBNET="hypershift-customer-subnet"
CONSUMER_SUBNET_RANGE="10.2.0.0/24"

echo "Setting up hypershift-customer VPC (Service Consumer)..."

# Set the project
gcloud config set project $PROJECT_ID

# Create the VPC
echo "Creating VPC: $CONSUMER_VPC"
if ! gcloud compute networks describe $CONSUMER_VPC >/dev/null 2>&1; then
    gcloud compute networks create $CONSUMER_VPC \
        --subnet-mode=custom \
        --bgp-routing-mode=regional
    echo "VPC $CONSUMER_VPC created"
else
    echo "VPC $CONSUMER_VPC already exists, skipping"
fi

# Create the main subnet
echo "Creating subnet: $CONSUMER_SUBNET"
if ! gcloud compute networks subnets describe $CONSUMER_SUBNET --region=$REGION >/dev/null 2>&1; then
    gcloud compute networks subnets create $CONSUMER_SUBNET \
        --network=$CONSUMER_VPC \
        --range=$CONSUMER_SUBNET_RANGE \
        --region=$REGION \
        --enable-private-ip-google-access
    echo "Subnet $CONSUMER_SUBNET created"
else
    echo "Subnet $CONSUMER_SUBNET already exists, skipping"
fi

# Create firewall rules
echo "Creating firewall rules for $CONSUMER_VPC"

# Allow internal communication within the subnet
if ! gcloud compute firewall-rules describe ${CONSUMER_VPC}-allow-internal >/dev/null 2>&1; then
    gcloud compute firewall-rules create ${CONSUMER_VPC}-allow-internal \
        --network=$CONSUMER_VPC \
        --action=allow \
        --direction=ingress \
        --source-ranges=$CONSUMER_SUBNET_RANGE \
        --rules=tcp,udp,icmp
    echo "Internal firewall rule created"
else
    echo "Internal firewall rule already exists, skipping"
fi

# Allow SSH for management
if ! gcloud compute firewall-rules describe ${CONSUMER_VPC}-allow-ssh >/dev/null 2>&1; then
    gcloud compute firewall-rules create ${CONSUMER_VPC}-allow-ssh \
        --network=$CONSUMER_VPC \
        --action=allow \
        --direction=ingress \
        --source-ranges=0.0.0.0/0 \
        --rules=tcp:22
    echo "SSH firewall rule created"
else
    echo "SSH firewall rule already exists, skipping"
fi

# Allow PSC endpoint communication
if ! gcloud compute firewall-rules describe ${CONSUMER_VPC}-allow-psc >/dev/null 2>&1; then
    gcloud compute firewall-rules create ${CONSUMER_VPC}-allow-psc \
        --network=$CONSUMER_VPC \
        --action=allow \
        --direction=ingress \
        --source-ranges=$CONSUMER_SUBNET_RANGE \
        --rules=tcp:8080 \
        --description="Allow Private Service Connect endpoint traffic"
    echo "PSC firewall rule created"
else
    echo "PSC firewall rule already exists, skipping"
fi

# Allow all egress traffic (required for PSC and package installation)
if ! gcloud compute firewall-rules describe ${CONSUMER_VPC}-allow-egress >/dev/null 2>&1; then
    gcloud compute firewall-rules create ${CONSUMER_VPC}-allow-egress \
        --network=$CONSUMER_VPC \
        --action=allow \
        --direction=egress \
        --destination-ranges=0.0.0.0/0 \
        --rules=all
    echo "Egress firewall rule created"
else
    echo "Egress firewall rule already exists, skipping"
fi

echo "hypershift-customer VPC setup completed successfully!"
echo "VPC: $CONSUMER_VPC"
echo "Subnet: $CONSUMER_SUBNET ($CONSUMER_SUBNET_RANGE)"