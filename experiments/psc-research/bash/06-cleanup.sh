#!/bin/bash

# GCP Private Service Connect Demo - Step 6: Cleanup Resources
# This script cleans up all resources created during the demo

set -e

# Variables
PROJECT_ID=${PROJECT_ID:-"your-project-id"}
REGION=${REGION:-"us-central1"}
ZONE=${ZONE:-"us-central1-a"}

echo "Cleaning up Private Service Connect demo resources..."

# Set the project
gcloud config set project $PROJECT_ID

echo "Step 1: Deleting PSC endpoint and consumer resources"
# Delete PSC forwarding rule
gcloud compute forwarding-rules delete customer-psc-forwarding-rule --region=$REGION --quiet || echo "PSC forwarding rule not found"

# Delete PSC endpoint IP
gcloud compute addresses delete customer-psc-endpoint-ip --region=$REGION --quiet || echo "PSC endpoint IP not found"

echo "Step 2: Deleting service attachment and provider load balancer"
# Delete service attachment
gcloud compute service-attachments delete redhat-service-attachment --region=$REGION --quiet || echo "Service attachment not found"

# Delete forwarding rule
gcloud compute forwarding-rules delete redhat-forwarding-rule --region=$REGION --quiet || echo "Forwarding rule not found"

# Delete backend service
gcloud compute backend-services delete redhat-backend-service --region=$REGION --quiet || echo "Backend service not found"

# Get the provider VM zone
PROVIDER_VM_ZONE=$(gcloud compute instances list --filter="name:redhat-service-vm" --format="value(zone)" | sed 's|.*/||' || echo "$ZONE")

# Delete instance group
gcloud compute instance-groups unmanaged delete redhat-service-group --zone=$PROVIDER_VM_ZONE --quiet || echo "Instance group not found"

# Delete health check
gcloud compute health-checks delete redhat-service-health-check --quiet || echo "Health check not found"

echo "Step 3: Deleting VMs"
# Delete VMs
gcloud compute instances delete redhat-service-vm --zone=$ZONE --quiet || echo "Provider VM not found"
gcloud compute instances delete customer-client-vm --zone=$ZONE --quiet || echo "Consumer VM not found"

echo "Step 4: Deleting firewall rules"
# Delete hypershift-redhat firewall rules
gcloud compute firewall-rules delete hypershift-redhat-allow-health-checks --quiet || echo "Health check firewall rule not found"
gcloud compute firewall-rules delete hypershift-redhat-allow-http --quiet || echo "HTTP firewall rule not found"
gcloud compute firewall-rules delete hypershift-redhat-allow-ssh --quiet || echo "SSH firewall rule not found"
gcloud compute firewall-rules delete hypershift-redhat-allow-egress --quiet || echo "Provider egress firewall rule not found"
gcloud compute firewall-rules delete hypershift-redhat-allow-psc-nat --quiet || echo "PSC NAT firewall rule not found"

# Delete hypershift-customer firewall rules
gcloud compute firewall-rules delete hypershift-customer-allow-internal --quiet || echo "Internal firewall rule not found"
gcloud compute firewall-rules delete hypershift-customer-allow-ssh --quiet || echo "SSH firewall rule not found"
gcloud compute firewall-rules delete hypershift-customer-allow-egress --quiet || echo "Consumer egress firewall rule not found"

echo "Step 5: Deleting subnets"
# Delete subnets
gcloud compute networks subnets delete hypershift-redhat-subnet --region=$REGION --quiet || echo "Provider subnet not found"
gcloud compute networks subnets delete hypershift-redhat-psc-nat --region=$REGION --quiet || echo "PSC NAT subnet not found"
gcloud compute networks subnets delete hypershift-customer-subnet --region=$REGION --quiet || echo "Consumer subnet not found"

echo "Step 6: Deleting VPCs"
# Delete VPCs
gcloud compute networks delete hypershift-redhat --quiet || echo "Provider VPC not found"
gcloud compute networks delete hypershift-customer --quiet || echo "Consumer VPC not found"

echo ""
echo "Cleanup completed successfully!"
echo "All Private Service Connect demo resources have been removed."