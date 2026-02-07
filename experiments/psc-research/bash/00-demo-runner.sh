#!/bin/bash

# GCP Private Service Connect Demo - Complete Demo Runner
# This script runs the entire demo from start to finish

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID=${PROJECT_ID}
REGION=${REGION:-"us-central1"}
ZONE=${ZONE:-"us-central1-a"}

# Function to print colored output
print_step() {
    echo -e "${BLUE}=== $1 ===${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Function to check prerequisites
check_prerequisites() {
    print_step "Checking Prerequisites"

    # Check if gcloud is installed
    if ! command -v gcloud &> /dev/null; then
        print_error "gcloud CLI is not installed. Please install it first."
        exit 1
    fi

    # Check if PROJECT_ID is set
    if [ -z "$PROJECT_ID" ]; then
        print_error "PROJECT_ID is not set. Please set it as an environment variable:"
        echo "export PROJECT_ID=your-project-id"
        exit 1
    fi

    # Check if user is authenticated
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -n1 > /dev/null; then
        print_error "Not authenticated with gcloud. Please run: gcloud auth login"
        exit 1
    fi

    # Check if project exists and we have access
    if ! gcloud projects describe $PROJECT_ID > /dev/null 2>&1; then
        print_error "Cannot access project $PROJECT_ID. Please check the project ID and permissions."
        exit 1
    fi

    print_success "Prerequisites check passed"
}

# Function to enable required APIs
enable_apis() {
    print_step "Enabling Required APIs"

    gcloud services enable compute.googleapis.com --project=$PROJECT_ID
    gcloud services enable servicenetworking.googleapis.com --project=$PROJECT_ID

    print_success "APIs enabled"
}

# Function to run each step
run_step() {
    local step_num=$1
    local step_name=$2
    local script_name=$3

    print_step "Step $step_num: $step_name"

    if [ -f "$script_name" ]; then
        chmod +x "$script_name"
        bash "$script_name"
        if [ $? -eq 0 ]; then
            print_success "Step $step_num completed successfully"
        else
            print_error "Step $step_num failed"
            exit 1
        fi
    else
        print_error "Script $script_name not found"
        exit 1
    fi

    # Wait a bit between steps for resources to stabilize
    echo "Waiting 30 seconds for resources to stabilize..."
    sleep 30
}

# Function to wait for VMs to be ready
wait_for_vms() {
    print_step "Waiting for VMs to be ready"

    echo "Waiting for VM startup scripts to complete (this may take 3-5 minutes)..."
    sleep 180

    # Check if VMs are running
    local provider_status=$(gcloud compute instances describe redhat-service-vm --zone=$ZONE --format="value(status)" 2>/dev/null || echo "NOT_FOUND")
    local consumer_status=$(gcloud compute instances describe customer-client-vm --zone=$ZONE --format="value(status)" 2>/dev/null || echo "NOT_FOUND")

    if [ "$provider_status" = "RUNNING" ] && [ "$consumer_status" = "RUNNING" ]; then
        print_success "VMs are ready"
    else
        print_warning "VMs may not be fully ready yet. Continuing anyway..."
    fi
}

# Main execution
main() {
    echo -e "${BLUE}"
    echo "=================================================="
    echo "  GCP Private Service Connect Demo"
    echo "  Connecting hypershift-redhat ↔ hypershift-customer"
    echo "=================================================="
    echo -e "${NC}"

    echo "Configuration:"
    echo "  Project ID: $PROJECT_ID"
    echo "  Region: $REGION"
    echo "  Zone: $ZONE"
    echo ""

    # Ask for confirmation
    read -p "Do you want to proceed with the demo? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Demo cancelled."
        exit 0
    fi

    # Run the demo steps
    check_prerequisites
    enable_apis

    run_step 1 "Setup hypershift-redhat VPC (Service Provider)" "./01-setup-hypershift-redhat-vpc.sh"
    run_step 2 "Setup hypershift-customer VPC (Service Consumer)" "./02-setup-hypershift-customer-vpc.sh"
    run_step 3 "Deploy Test VMs" "./03-deploy-vms.sh"

    wait_for_vms

    run_step "3b" "Test VPC Isolation (Before PSC)" "./03b-test-isolation.sh"
    run_step 4 "Setup Private Service Connect" "./04-setup-private-service-connect.sh"

    # Wait a bit longer for PSC to be fully ready
    echo "Waiting 60 seconds for Private Service Connect to be fully ready..."
    sleep 60

    run_step 5 "Test Connectivity" "./05-test-connectivity.sh"

    print_step "Demo Completed Successfully!"
    echo ""
    echo -e "${GREEN}🎉 Private Service Connect demo is now running!${NC}"
    echo ""
    echo "What was demonstrated:"
    echo "✓ Two isolated VPCs: hypershift-redhat and hypershift-customer"
    echo "✓ Service in hypershift-redhat VPC behind internal load balancer"
    echo "✓ Private Service Connect endpoint in hypershift-customer VPC"
    echo "✓ Secure cross-VPC communication without VPC peering"
    echo "✓ Service discovery and load balancing"
    echo ""
    echo "Next steps:"
    echo "• Review the connectivity test results above"
    echo "• Explore the GCP Console to see the created resources"
    echo "• Run additional tests if needed"
    echo "• When finished, run: ./06-cleanup.sh"
    echo ""
    print_warning "Remember to clean up resources when done to avoid charges!"
}

# Run the main function
main "$@"