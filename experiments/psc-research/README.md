# GCP Private Service Connect Demo

This demo demonstrates how to use Google Cloud Private Service Connect to securely connect services across two isolated VPCs: `hypershift-redhat` (service provider) and `hypershift-customer` (service consumer).

## Architecture Overview

```
┌─────────────────────────┐         ┌─────────────────────────┐
│   hypershift-redhat     │         │   hypershift-customer   │
│     (Provider VPC)      │         │    (Consumer VPC)       │
│                         │         │                         │
│  ┌─────────────────┐    │         │  ┌─────────────────┐    │
│  │   Service VM    │    │         │  │   Client VM     │    │
│  │   (nginx + API) │    │         │  │   (test tools)  │    │
│  └─────────────────┘    │         │  └─────────────────┘    │
│           │              │         │           │              │
│  ┌─────────────────┐    │         │  ┌─────────────────┐    │
│  │Internal Load    │    │         │  │ PSC Endpoint    │    │
│  │Balancer         │◄───┼─────────┼──┤ (10.2.x.x)      │    │
│  │(10.1.x.x)       │    │   PSC   │  │ Request Flow    │    │
│  └─────────────────┘    │ Tunnel  │  └─────────────────┘    │
│           │              │         │                         │
│  ┌─────────────────┐    │         │                         │
│  │Service          │    │         │                         │
│  │Attachment       │    │         │                         │
│  └─────────────────┘    │         │                         │
└─────────────────────────┘         └─────────────────────────┘
```

## Detailed Connection Flow

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                               Connection Flow                                   │
└────────────────────────────────────────────────────────────────────────────────┘

Service Provider (hypershift-redhat VPC)          Service Consumer (hypershift-customer VPC)
┌─────────────────────────────────────────┐       ┌─────────────────────────────────────────┐
│                                         │       │                                         │
│  ┌─────────────────────────────────┐    │       │    ┌─────────────────────────────────┐  │
│  │         Service VM              │    │       │    │         Client VM               │  │
│  │   IP: 10.1.0.2                  │    │       │    │   IP: 10.2.0.2                  │  │
│  │   ┌─────────────────────────┐   │    │       │    │   ┌─────────────────────────┐   │  │
│  │   │  nginx (port 80)        │   │    │       │    │   │  curl/wget              │   │  │
│  │   │  Python API (port 8080) │   │    │       │    │   │  testing tools          │   │  │
│  │   └─────────────────────────┘   │    │       │    │   └─────────────────────────┘   │  │
│  └─────────────────┬───────────────┘    │       │    └───────────────┬─────────────────┘  │
│                    │                    │       │                    │                    │
│                    │ HTTP traffic       │       │                    │ HTTP requests      │
│                    │                    │       │                    │                    │
│  ┌─────────────────▼───────────────┐    │       │    ┌───────────────▼─────────────────┐  │
│  │    Internal Load Balancer       │    │       │    │     PSC Endpoint                │  │
│  │                                 │    │       │    │                                 │  │
│  │  Frontend IP: 10.1.1.x          │    │       │    │  IP: 10.2.0.100                │  │
│  │  Backend: Service VM:8080       │    │       │    │  Target: Service Attachment     │  │
│  │  Health Check: /health          │    │       │    │                                 │  │
│  │                                 │    │       │    │                                 │  │
│  └─────────────────┬───────────────┘    │       │    └───────────────┬─────────────────┘  │
│                    │                    │       │                    │                    │
│                    │                    │       │                    │                    │
│  ┌─────────────────▼───────────────┐    │       │                    │                    │
│  │     Service Attachment          │    │       │                    │                    │
│  │                                 │    │       │                    │                    │
│  │  URI: projects/.../sa-redhat    │    │       │                    │                    │
│  │  Connection: ACCEPT_AUTOMATIC   │    │       │                    │                    │
│  │  NAT Subnet: 10.1.0.0/24       │    │       │                    │                    │
│  │                                 │    │       │                    │                    │
│  └─────────────────┬───────────────┘    │       │                    │                    │
│                    │                    │       │                    │                    │
└────────────────────┼────────────────────┘       └────────────────────┼────────────────────┘
                     │                                                 │
                     │                                                 │
             ┌───────▼─────────────────────────────────────────────────▼───────┐
             │                  Private Service Connect                        │
             │                     (Google Backbone)                           │
             │                                                                 │
             │  • Encrypted traffic over Google's private network             │
             │  • No internet routing required                                │
             │  • Automatic service discovery                                 │
             │  • Built-in load balancing support                             │
             │  • Cross-project/organization connectivity                     │
             │                                                                 │
             └─────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────────┐
│                               Traffic Flow                                     │
└────────────────────────────────────────────────────────────────────────────────┘

Step 1: Client VM makes HTTP request to PSC endpoint (10.2.0.100)
        curl http://10.2.0.100/

Step 2: PSC endpoint forwards request through Private Service Connect tunnel

Step 3: Request reaches Service Attachment in provider VPC

Step 4: Service Attachment forwards to Internal Load Balancer (10.1.1.x)

Step 5: Load Balancer performs health check and forwards to healthy backend

Step 6: Service VM processes request and returns response

Step 7: Response travels back through the same path in reverse

┌────────────────────────────────────────────────────────────────────────────────┐
│                            Network Isolation                                   │
└────────────────────────────────────────────────────────────────────────────────┘

WITHOUT Private Service Connect:
┌─────────────────┐    ❌ NO ROUTE    ┌─────────────────┐
│ hypershift-     │ ◄────────────────► │ hypershift-     │
│ redhat VPC      │    ❌ ISOLATED    │ customer VPC    │
│ (10.1.0.0/24)   │                   │ (10.2.0.0/24)   │
└─────────────────┘                   └─────────────────┘

WITH Private Service Connect:
┌─────────────────┐                   ┌─────────────────┐
│ hypershift-     │    ✅ SECURE      │ hypershift-     │
│ redhat VPC      │ ◄────────────────► │ customer VPC    │
│ (Service        │      PSC TUNNEL   │ (PSC Endpoint)  │
│ Attachment)     │                   │                 │
└─────────────────┘                   └─────────────────┘
```


```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                        Private Service Connect Deep Dive                                 │
└─────────────────────────────────────────────────────────────────────────────────────────┘

Provider VPC (hypershift-redhat)                Consumer VPC (hypershift-customer)
┌─────────────────────────────────────────┐     ┌─────────────────────────────────────────┐
│                                         │     │                                         │
│                              ◄──────────┼─────┼── Traffic Flow Direction               │
│                                         │     │                                         │
│  ┌─────────────────────────────────┐    │     │    ┌─────────────────────────────────┐  │
│  │         Service VM              │    │     │    │         Client VM               │  │
│  │                                 │    │     │    │                                 │  │
│  │  ┌─────────────────────────┐   │    │     │    │   ┌─────────────────────────┐   │  │
│  │  │  nginx (port 80)        │   │    │     │    │   │  curl                   │   │  │
│  │  │  Python API (port 8080) │   │    │     │    │   │  wget                   │   │  │
│  │  │  /health endpoint       │   │    │     │    │   │  nc                     │   │  │
│  │  └─────────────────────────┘   │    │     │    │   └─────────────────────────┘   │  │
│  │            │                    │    │     │    │            │                    │  │
│  │            │ :8080              │    │     │    │            │                    │  │
│  │            ▼                    │    │     │    │            ▼                    │  │
│  └─────────────────────────────────┘    │     │    │   curl http://10.2.0.100/      │  │
│             │                           │     │    │            │                    │  │
│             │ Named Port Mapping        │     │    │            │                    │  │
│             │ "http:8080"               │     │    │            │                    │  │
│             ▼                           │     │    │            ▼                    │  │
│  ┌─────────────────────────────────┐    │     │    │  ┌─────────────────────────────┐  │
│  │     Instance Group              │    │     │    │  │    PSC Endpoint             │  │
│  │                                 │    │     │    │  │                             │  │
│  │  • Logical VM container         │    │     │    │  │  IP: 10.2.0.100             │  │
│  │  • Scalability abstraction      │    │     │    │  │  Target: Service Attachment │  │
│  │  • Health check target          │◄───┼─────┼────┤  │  Type: Forwarding Rule      │  │
│  │  • Named ports: http:8080       │    │     │    │  │                             │  │
│  │  • Members: [service-vm]        │    │     │    │  └─────────────────────────────┘  │
│  └─────────────────┬───────────────┘    │     │    └─────────────────────────────────────────┘
│                    │                    │     │
│                    │ Health Check       │     │
│                    │ GET /health :8080  │     │
│                    ▼                    │     │
│  ┌─────────────────────────────────┐    │     │
│  │       Health Check              │    │     │
│  │                                 │    │     │
│  │  • Protocol: HTTP              │    │     │
│  │  • Port: 8080                  │    │     │
│  │  • Path: /health               │    │     │
│  │  • Interval: 10s               │    │     │
│  │  • Timeout: 5s                 │    │     │
│  │  • Healthy threshold: 2        │    │     │
│  │  • Unhealthy threshold: 3      │    │     │
│  │                                 │    │     │
│  │  Purpose: Determines if VM      │    │     │
│  │  should receive traffic         │    │     │
│  └─────────────────┬───────────────┘    │     │
│                    │                    │     │
│                    │ Health Status      │     │
│                    │ HEALTHY/UNHEALTHY  │     │
│                    ▼                    │     │
│  ┌─────────────────────────────────┐    │     │
│  │      Backend Service            │    │     │
│  │                                 │    │     │
│  │  • Protocol: TCP               │    │     │
│  │  • Load balancing scheme:      │    │     │
│  │    INTERNAL                    │    │     │
│  │  • Health check: ↑             │    │     │
│  │  • Backend: Instance Group     │    │     │
│  │  • Session affinity: None      │    │     │
│  │                                 │    │     │
│  │  Purpose: Service definition    │    │     │
│  │  and traffic distribution       │    │     │
│  └─────────────────┬───────────────┘    │     │
│                    │                    │     │
│                    │ Route traffic to   │     │
│                    │ healthy backends   │     │
│                    ▼                    │     │
│  ┌─────────────────────────────────┐    │     │
│  │    Forwarding Rule              │    │     │
│  │                                 │    │     │
│  │  • IP: 10.1.0.x (auto-assigned)│    │     │
│  │  • Port: 8080                  │    │     │
│  │  • Target: Backend Service     │    │     │
│  │  • Subnet: hypershift-redhat   │    │     │
│  │  • Type: INTERNAL               │    │     │
│  │                                 │    │     │
│  │  Purpose: Network entry point   │    │     │
│  │  Creates actual IP:PORT binding │    │     │
│  └─────────────────┬───────────────┘    │     │
│                    │                    │     │
│                    │ Expose service     │     │
│                    │ for PSC            │     │
│                    ▼                    │     │
│  ┌─────────────────────────────────┐    │     │
│  │    Service Attachment           │    │     │
│  │                                 │    │     │
│  │  • Target: Forwarding Rule ↑   │    │     │
│  │  • Connection: ACCEPT_AUTOMATIC │    │     │
│  │  • NAT subnets: provider subnet│    │     │
│  │  • Consumer projects: [allowed]│    │     │
│  │                                 │    │     │
│  │  Purpose: PSC publishing        │    │     │
│  │  Makes internal service         │    │     │
│  │  consumable across VPCs         │    │     │
│  └─────────────────────────────────┘    │     │
│                                         │     │
└─────────────────────────────────────────┘     │
                                                │
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           Why Each Component is Required                                 │
└─────────────────────────────────────────────────────────────────────────────────────────┘

🔧 NAMED PORTS (http:8080)
├── Problem: Load balancers need to know which port to send traffic to
├── Solution: Named ports create a symbolic mapping "http" → "8080"
├── Benefit: Port changes don't require LB reconfiguration
└── Alternative: None - GCP requires this for service discovery

🏥 HEALTH CHECK (/health endpoint)
├── Problem: Load balancer needs to know if backends can handle traffic
├── Solution: Regular HTTP checks to /health endpoint every 10s
├── Benefit: Automatic failover, prevents traffic to broken instances
└── Alternative: TCP checks (less application-aware)

📦 INSTANCE GROUP (logical container)
├── Problem: Load balancers can't target individual VMs directly
├── Solution: Group VMs into manageable units with shared properties
├── Benefit: Enables auto-scaling, rolling updates, centralized management
└── Alternative: None - GCP architecture requirement

⚖️ BACKEND SERVICE (service definition)
├── Problem: Need to define HOW traffic should be distributed
├── Solution: Combines health checks + instance groups + LB policies
├── Benefit: Central place for all service-level configuration
└── Alternative: None - abstraction layer required for complex routing

🌐 FORWARDING RULE (network entry point)
├── Problem: Need actual IP:PORT that clients can connect to
├── Solution: Creates network endpoint that routes to backend service
├── Benefit: Stable network interface, protocol termination
└── Alternative: Direct VM IPs (no load balancing, no health checks)

🔗 SERVICE ATTACHMENT (PSC publisher)
├── Problem: Internal services aren't accessible across VPC boundaries
├── Solution: PSC-specific component that "publishes" internal services
├── Benefit: Secure cross-VPC access without VPC peering
└── Alternative: VPC peering (complex, less secure, network-level access)

📍 PSC ENDPOINT (consumer representation)
├── Problem: Consumers need local IP to connect to remote service
├── Solution: Creates local IP that tunnels to service attachment
├── Benefit: Service appears "local" to consumer applications
└── Alternative: External load balancer (public internet, less secure)

┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                            Traffic Flow with Component Interaction                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘

1. 📱 Client: curl http://10.2.0.100/
2. 🌐 PSC Endpoint: "I represent the remote service, routing via PSC tunnel"
3. 🔗 Service Attachment: "Accepting connection, forwarding to my forwarding rule"
4. 🌐 Forwarding Rule: "I have IP 10.1.0.x:8080, sending to my backend service"
5. ⚖️ Backend Service: "Checking health status... Instance Group has healthy members"
6. 📦 Instance Group: "I have 1 member with named port http:8080"
7. 🏥 Health Check: "VM is HEALTHY (last check: 200 OK from /health)"
8. 📦 Instance Group: "Routing to service-vm:8080"
9. 📱 Service VM: "Processing request on port 8080"
10. 🔄 Response flows back through the same path

This architecture ensures enterprise-grade reliability, observability, and scalability.
```

## Prerequisites

1. **Google Cloud Project** with billing enabled
2. **gcloud CLI** installed and configured
3. **Required APIs** enabled:
   - Compute Engine API
   - Service Networking API
4. **IAM Permissions**: See [Detailed IAM Requirements](#iam-permissions-and-security) below

## Quick Start

1. **Set your project ID**:
   ```bash
   export PROJECT_ID="your-project-id"
   export REGION="us-central1"        # Optional
   export ZONE="us-central1-a"        # Optional
   ```

2. **Choose your implementation**:

   ```bash
   cd golang/
   make demo
   ```

3. **Test connectivity** (optional):

   ```bash
   cd golang/
   make test
   ```

4. **Clean up when done**:

   ### 🔧 Go Implementation
   ```bash
   cd golang/
   make cleanup
   ```

## Step-by-Step Execution

### 🐚 Bash Implementation

If you prefer to run each step manually (bash implementation):

### Step 1: Create hypershift-redhat VPC (Service Provider)
```bash
chmod +x 01-setup-hypershift-redhat-vpc.sh
./01-setup-hypershift-redhat-vpc.sh
```

Creates:
- VPC with custom subnets (10.1.0.0/24)
- Load balancer subnet (10.1.1.0/24)
- Firewall rules for health checks and HTTP traffic

### Step 2: Create hypershift-customer VPC (Service Consumer)
```bash
chmod +x 02-setup-hypershift-customer-vpc.sh
./02-setup-hypershift-customer-vpc.sh
```

Creates:
- VPC with custom subnet (10.2.0.0/24)
- Firewall rules for internal communication and egress

### Step 3: Deploy Test VMs
```bash
chmod +x 03-deploy-vms.sh
./03-deploy-vms.sh
```

Creates:
- Service VM in hypershift-redhat VPC (runs nginx + Python API)
- Client VM in hypershift-customer VPC (testing tools)

### Step 3b: Test VPC Isolation (Before PSC)
```bash
chmod +x 03b-test-isolation.sh
./03b-test-isolation.sh
```

Demonstrates:
- VPCs are completely isolated (no connectivity)
- Service is running but not accessible cross-VPC
- Network isolation before PSC is enabled

### Step 4: Setup Private Service Connect
```bash
chmod +x 04-setup-private-service-connect.sh
./04-setup-private-service-connect.sh
```

This step creates the Private Service Connect infrastructure through several components:

#### 4.1: Health Check
```bash
gcloud compute health-checks create http redhat-service-health-check \
    --port=8080 --request-path=/health
```
**Why needed**: Load balancers require health checks to determine which backend instances are healthy and can receive traffic. Without health checks, the load balancer cannot route traffic safely.

#### 4.2: Instance Group
```bash
gcloud compute instance-groups unmanaged create redhat-service-group
gcloud compute instance-groups unmanaged add-instances redhat-service-group --instances=redhat-service-vm
```
**Why needed**: Google Cloud load balancers don't target individual VMs directly. Instance groups provide a logical grouping that the load balancer can target. This allows for easy scaling and management of backend services.

#### 4.3: Backend Service
```bash
gcloud compute backend-services create redhat-backend-service \
    --load-balancing-scheme=INTERNAL --protocol=TCP
```
**Why needed**: Backend services define the business logic of load balancing - which instance groups to route to, what health checks to use, and load balancing algorithms. This is the "service definition" that Private Service Connect will expose.

#### 4.4: Internal Load Balancer Forwarding Rule
```bash
gcloud compute forwarding-rules create redhat-forwarding-rule \
    --load-balancing-scheme=INTERNAL --backend-service=redhat-backend-service
```
**Why needed**: The forwarding rule creates the actual IP address and port that receives traffic within the provider VPC. This is the "front door" of your service that the Service Attachment will reference.

#### 4.5: Service Attachment
```bash
gcloud compute service-attachments create redhat-service-attachment \
    --producer-forwarding-rule=redhat-forwarding-rule \
    --connection-preference=ACCEPT_AUTOMATIC
```
**Why needed**: This is the PSC-specific component that "publishes" your internal load balancer as a service that can be consumed across VPC boundaries. It's the bridge between your internal service and the PSC network.

#### 4.6: PSC Endpoint (Consumer Side)
```bash
gcloud compute addresses create customer-psc-endpoint-ip --subnet=hypershift-customer-subnet
gcloud compute forwarding-rules create customer-psc-forwarding-rule \
    --target-service-attachment=redhat-service-attachment
```
**Why needed**: The PSC endpoint creates a private IP address in the consumer VPC that represents the remote service. When clients connect to this IP, PSC automatically tunnels the traffic to the service attachment in the provider VPC.

#### 4.7: PSC NAT Firewall Rule (Critical)
```bash
gcloud compute firewall-rules create hypershift-redhat-allow-psc-nat \
    --network=hypershift-redhat \
    --source-ranges=10.1.1.0/24 \
    --rules=tcp:8080
```
**Why needed**: **This is the most commonly missed step in PSC setups!** When PSC forwards traffic from the consumer VPC to the provider VPC, it performs NAT translation using the PSC NAT subnet (10.1.1.0/24). The provider VM receives traffic from PSC NAT IPs (10.1.1.x), not the original consumer IP (10.2.0.2). Without this firewall rule, the default-deny-ingress rule blocks PSC traffic, causing "silent PSC failures" where the connection appears healthy in the console but traffic doesn't flow.

**Network Intelligence Center debugging reveals**: Traffic successfully flows through all PSC components but gets dropped at the final ingress firewall check.

#### Architecture Flow:
```
Consumer VM → PSC Endpoint IP → PSC Tunnel → Service Attachment →
Internal Load Balancer → Backend Service → Instance Group → Provider VM
```

### 🔧 Go Implementation

For the Go implementation, you can run individual components or use the orchestrated approach:

#### Option 1: Full Orchestrated Demo
```bash
cd golang/
make demo
```

This runs all steps automatically with proper error handling and progress reporting.

#### Option 2: Individual Steps
```bash
cd golang/

# Build the binaries
make build

# Run individual components (requires manual step management)
./bin/demo    # Full demo
./bin/test    # Connectivity testing
./bin/cleanup # Resource cleanup
```



### Step 5: Test Connectivity
```bash
chmod +x 05-test-connectivity.sh
./05-test-connectivity.sh
```

Tests:
- Basic connectivity
- HTTP service access
- API endpoint functionality
- Load balancer health checks

## Testing the Connection

Once the demo is running, you can test connectivity:

```bash
# Get the PSC endpoint IP
PSC_IP=$(gcloud compute forwarding-rules describe customer-psc-forwarding-rule --region=$REGION --format="value(IPAddress)")

# Test from the consumer VM
gcloud compute ssh customer-client-vm --zone=$ZONE --command="curl http://$PSC_IP/"
```

Expected response:
```json
{
  "message": "Hello from hypershift-redhat Private Service Connect Demo!",
  "hostname": "redhat-service-vm",
  "timestamp": "2024-01-15T10:30:45.123456"
}
```

### Step 6: Cleanup Resources
```bash
chmod +x 06-cleanup.sh
./06-cleanup.sh
```




## Cost Estimation

This demo creates the following billable resources:
- 2x e2-micro VMs (~$5.35/month each) ✨ **Cost Optimized**
- 1x Internal Load Balancer (~$18/month)
- 1x Private Service Connect endpoint (~$36/month)
- Network egress charges (minimal for testing)

**Total estimated cost**: ~$64.70/month if left running (**$39.30/month savings vs. e2-medium**)

⚠️ **Important**: Remember to run the cleanup script to avoid ongoing charges!