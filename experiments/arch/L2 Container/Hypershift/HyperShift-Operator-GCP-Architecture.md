# HyperShift Operator GCP Architecture (L2 Container)

## Document Information
- **Level**: L2 Container Architecture
- **Scope**: HyperShift Operator with GCP Platform Support
- **Date**: September 2024
- **Version**: 1.0

## Executive Summary

This document describes the container-level architecture for HyperShift Operator with Google Cloud Platform (GCP) support, enabling hosted OpenShift control planes with worker nodes deployed across customer GCP projects using Private Service Connect (PSC) for secure cross-project networking.

## Architecture Overview

### Core Architecture Pattern
HyperShift with GCP follows a **Control-Plane-First** architecture where dedicated PSC infrastructure is established per HostedCluster before worker node deployment, ensuring complete network isolation between clusters while enabling cross-project worker node deployment.

### High-Level Container Flow
```
┌─────────────────────────────────────────────────────────────────┐
│                    Management GCP Project                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   GKE Cluster   │  │ HyperShift Ops  │  │ PSC/ILB Infra   │ │
│  │ (Control Plane) │→ │   Container     │→ │   Container     │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                                   │
                            PSC Connection
                                   │
┌─────────────────────────────────────────────────────────────────┐
│                    Customer GCP Project                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │ PSC Consumer    │  │ Worker Nodes    │  │  Customer VPC   │ │
│  │   Container     │← │   Container     │← │   Container     │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Container Architecture

### 1. HyperShift Operator Container
**Purpose**: Core orchestration and cluster lifecycle management
**Location**: Management GCP Project GKE cluster
**Key Responsibilities**:
- HostedCluster resource reconciliation
- PSC Service Attachment lifecycle management
- Internal Load Balancer provisioning
- Cross-project IAM orchestration
- Platform integration with Cluster API

**Container Interfaces**:
- **Input**: HostedCluster/NodePool CRDs
- **Output**: GCP PSC infrastructure, CAPI resources
- **Authentication**: Workload Identity (no service account keys)
- **Networking**: Management cluster internal networking

### 2. GCP Infrastructure Container
**Purpose**: GCP-specific resource management
**Location**: Management GCP Project
**Key Responsibilities**:
- PSC Service Attachment creation/deletion
- Internal Load Balancer management
- Health check configuration
- Firewall rule automation
- DNS zone management

**Container Components**:
- PSC Service Attachment (1:1 per HostedCluster)
- Internal Load Balancer (dedicated per cluster)
- Health checks (API server connectivity)
- NAT subnets (PSC connectivity)

### 3. Cluster API Provider GCP Container
**Purpose**: Worker node infrastructure management
**Location**: Management GCP Project GKE cluster
**Key Responsibilities**:
- GCPCluster resource reconciliation
- Worker node instance lifecycle
- Cross-project resource deployment
- Machine template management
- Bootstrap configuration

**Container Interfaces**:
- **Input**: CAPI Cluster/Machine resources
- **Output**: Customer project GCE instances
- **Authentication**: Cross-project service account impersonation
- **Networking**: PSC consumer endpoints

### 4. Control Plane Container
**Purpose**: OpenShift control plane services
**Location**: Management GCP Project GKE cluster
**Key Responsibilities**:
- Kubernetes API server
- etcd cluster
- Controller managers
- Scheduler
- OpenShift-specific controllers

**Container Characteristics**:
- **Isolation**: Dedicated namespace per HostedCluster
- **Networking**: Internal Load Balancer backend
- **Storage**: GCP persistent disks
- **Authentication**: Workload Identity integration

### 5. PSC Consumer Container
**Purpose**: Customer-side PSC connectivity
**Location**: Customer GCP Project
**Key Responsibilities**:
- PSC consumer endpoint management
- Customer VPC integration
- Private IP allocation
- DNS resolution configuration

**Container Interfaces**:
- **Input**: PSC Service Attachment URI
- **Output**: Private IP endpoint for API access
- **Networking**: Customer VPC integration
- **Management**: Automated via CAPI GCP provider

## Network Architecture

### Private Service Connect (PSC) Design
```
Management Project PSC Producer:
┌─────────────────────────────────────────────────────────────┐
│ Control Plane → ILB → PSC Service Attachment (dedicated)   │
│                       ↓                                     │
│                   Unique PSC URI                           │
└─────────────────────────────────────────────────────────────┘
                         │
                  PSC Connection
                         │
Customer Project PSC Consumer:
┌─────────────────────────────────────────────────────────────┐
│ PSC Consumer Endpoint → Private IP → Worker Nodes          │
│                        ↑                                    │
│                Customer VPC Integration                    │
└─────────────────────────────────────────────────────────────┘
```

### Connectivity Patterns
- **Control Plane Access**: Worker nodes → PSC Consumer IP → PSC Connection → ILB → Control Plane
- **Cross-Project Isolation**: Dedicated PSC per HostedCluster ensures complete network isolation
- **Authentication Flow**: Workload Identity → Cross-project impersonation → Customer resources

## Authentication Architecture

### Workload Identity Integration
```
Management Cluster:
┌─────────────────────────────────────────────────────────────┐
│ K8s ServiceAccount → GCP ServiceAccount → IAM Roles        │
│                                    ↓                       │
│                         Cross-Project Impersonation        │
└─────────────────────────────────────────────────────────────┘
                         │
Customer Project:
┌─────────────────────────────────────────────────────────────┐
│ Impersonated ServiceAccount → Customer Resources           │
└─────────────────────────────────────────────────────────────┘
```

### Controller Authentication Matrix
| Controller | Management Project Roles | Cross-Project Capabilities |
|------------|-------------------------|---------------------------|
| hypershift-operator | compute.networkAdmin, dns.admin | serviceAccountTokenCreator |
| cluster-api-provider-gcp | compute.instanceAdmin, networkUser | compute.instanceAdmin |
| control-plane-operator | compute.viewer | - |
| gcp-cloud-controller-manager | compute.instanceAdmin, loadBalancerAdmin | - |
| gcp-csi-driver | compute.storageAdmin | - |

## Scalability Architecture

### Per-Management-Cluster Limits
- **HostedClusters**: 50-500 (PSC quota dependent)
- **PSC Service Attachments**: 1:1 ratio with HostedClusters
- **Internal Load Balancers**: 1:1 ratio with HostedClusters
- **Cross-Project Connections**: Unlimited (customer project quotas)

### Regional Scale Strategy
```
Region: us-central1
├── Management Cluster A (Project: mgmt-a)
│   ├── PSC Service Attachments: 1-500
│   └── HostedClusters: 1-500
├── Management Cluster B (Project: mgmt-b)
│   ├── PSC Service Attachments: 1-500
│   └── HostedClusters: 1-500
└── Management Cluster N...
    └── Total Regional Capacity: 2500+ HostedClusters
```

## Container Lifecycle Management

### HostedCluster Creation Flow
1. **HyperShift Operator**: Validates GCP platform spec
2. **GCP Infrastructure Container**: Creates PSC Service Attachment + ILB
3. **Control Plane Container**: Deploys OpenShift control plane
4. **HyperShift Operator**: Creates CAPI cluster resources
5. **CAPI GCP Provider**: Creates PSC consumer in customer project

### HostedCluster Deletion Flow
1. **CAPI GCP Provider**: Deletes customer project resources
2. **Control Plane Container**: Graceful control plane shutdown
3. **GCP Infrastructure Container**: Deletes PSC/ILB resources
4. **HyperShift Operator**: Removes finalizers and CRDs

## Security Architecture

### Network Security
- **Isolation**: Dedicated PSC per cluster prevents cross-cluster access
- **Encryption**: TLS for all API communication over PSC
- **Firewall**: Automated rules for minimum required access
- **Private Networking**: No public IP exposure for control planes

### Identity Security
- **Zero Service Account Keys**: Workload Identity only
- **Least Privilege**: Minimal IAM roles per controller
- **Cross-Project Boundaries**: Controlled impersonation for customer resources
- **Audit Logging**: All cross-project operations logged

## Operational Architecture

### Monitoring & Observability
- **PSC Health**: Service attachment connection status
- **ILB Health**: Backend service health checks
- **Cross-Project Metrics**: Authentication success rates
- **Resource Utilization**: Quota consumption tracking

### High Availability
- **Control Plane**: Multi-zone GKE deployment
- **PSC Infrastructure**: Regional service attachment placement
- **Database**: etcd with persistent disk snapshots
- **Network**: Multiple availability zone ILB backends

## Technology Stack

### Infrastructure Components
- **Container Orchestration**: Google Kubernetes Engine (GKE)
- **Networking**: Private Service Connect + Internal Load Balancers
- **Authentication**: Google Cloud Workload Identity
- **Infrastructure as Code**: Terraform with instance management
- **DNS**: Google Cloud DNS private zones

### Software Components
- **Cluster Management**: HyperShift Operator + Cluster API Provider GCP
- **Control Plane**: OpenShift 4.14+ components
- **Storage**: GCP CSI Driver with Persistent Disks
- **Networking**: GCP Cloud Controller Manager

## Integration Points

### External Dependencies
- **Terraform Infrastructure**: Workload Identity automation via tf.sh
- **Customer Projects**: Pre-existing GCP projects with proper IAM
- **DNS Delegation**: Customer DNS zones for cluster endpoints
- **Quota Management**: Sufficient PSC and compute quotas

### Internal Dependencies
- **HyperShift Core**: Platform interface implementation
- **Cluster API**: GCP provider integration
- **OpenShift**: Control plane component compatibility
- **GCP APIs**: Compute, IAM, DNS, and networking services

## Future Considerations

### Planned Enhancements
- **KMS Integration**: Google Cloud KMS for secret encryption
- **Multi-Region**: Cross-region PSC for disaster recovery
- **Autoscaling**: Dynamic cluster scaling based on demand
- **Cost Optimization**: Preemptible instance support

### Architectural Evolution
- **Shared PSC**: Potential migration to shared service attachments for scale
- **Hybrid Networking**: Integration with on-premises connectivity
- **Service Mesh**: Istio integration for advanced networking
- **GitOps**: Integration with Flux/ArgoCD for cluster configuration

## Compliance & Standards

### Security Standards
- **SOC 2 Type II**: Infrastructure compliance requirements
- **GDPR**: Data protection for EU customer data
- **Industry Standards**: Healthcare and financial compliance support

### Operational Standards
- **SLA Targets**: 99.9% uptime for PSC connectivity
- **RTO/RPO**: Recovery time/point objectives for disaster scenarios
- **Change Management**: GitOps-based infrastructure updates