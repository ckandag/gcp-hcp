# Backend Service Architecture

The Backend Service serves as the central orchestration layer, implementing a sophisticated event-driven 
architecture that coordinates cluster lifecycle management across distributed controllers.

## Architecture Overview

```
             (frontend)
                  │ HTTPS/REST
┌─────────────────▼───────────────────┐
│    Backend Service                  │
│  ┌─────────────────────────────────┐│
│  │ REST API Server                 ││
│  │ ┌─────────────────────────────┐ ││
│  │ │ • /api/v1/clusters          │ ││
│  │ │ • /api/v1/nodepools         │ ││
│  │ │ • Status aggregation        │ ││
│  │ │ • Authentication middleware │ ││
│  │ └─────────────────────────────┘ ││
│  │                                 ││
│  │ Event Publishing Engine         ││ ┌────────────────────────────────────────────────┐
│  │ ┌─────────────────────────────┐ ││ │        Cloud Pub/Sub                           │
│  │ │ • Lightweight events (~200B)│ │──│  ┌────────────────────────────────────────────┐│
│  │ │ • Centralized reconciliation│ ││ │  │ • cluster-events                           ││
│  │ │ • Broadcast architecture    │ ││ │  │   (create/update/delete/reconcile) (~200B) ││
│  │ └─────────────────────────────┘ ││ │  │ • At-least-once delivery                   ││
│  │                                 ││ │  └────────────────────────────────────────────┘│
│  │ PostgreSQL Database             ││ └────────────────────────────────────────────────┘
│  │ ┌─────────────────────────────┐ ││                  │
│  │ │ • Cluster/NodePool state    │ ││                  │
│  │ │ • Controller status         │ ││                  │
│  │ │ • Status aggregation funcs  │ ││                  │
│  │ └─────────────────────────────┘ ││                  │
│  └─────────────────────────────────┘│                  │
│                                     │                  │
│  ┌─────────────────────────────────┐│                  │
│  │    Controller Ecosystem         │───── Event subscriptions
│  │ ┌─────────────────────────────┐ ││
│  │ │• environment-validation-    │ ││
│  │ │  controller                 │ ││
│  │ │• operator-client-           │ ││
│  │ │  controller                 │ ││
│  │ │• placement-controller       │ ││
│  │ │• dns-management-controller  │ ││
│  │ │• Event-driven processing    │ ││
│  │ │• API data fetching          │ ││
│  │ │• API Status reporting       │ ││
│  │ └─────────────────────────────┘ ││
│  └─────────────────────────────────┘│
└─────────────────┬───────────────────┘
                  │ Kubernetes Resources
                  ▼
        (hypershift operator)
```

## Core Components

### Backend Service
- **REST API Server**
- **Framework**: Gin HTTP framework with comprehensive middleware
- **Endpoints**:
    - `GET/POST/PUT/DELETE /api/v1/clusters` - Cluster lifecycle management
    - `GET/POST/PUT/DELETE /api/v1/nodepools` - NodePool management
    - `PUT /api/v1/clusters/{id}/status` - Controller status updates
- **Features**:
    - Authentication middleware with service account validation
    - Request/response logging and timeout management
    - CORS support and security headers
    - RESTful status aggregation with Kubernetes-style conditions

### **Event Publishing Engine**
- **Lightweight Events**: ~200 byte messages
- **Event Types**: `cluster.created`, `cluster.updated`, `cluster.deleted`, `cluster.reconcile`
- **Centralized Reconciliation**: Time-based reconciliation managed by backend service scheduler
- **Broadcast Architecture**: All controllers receive events, implement autonomous filtering (pre-conditions)
- **Generation Tracking**: Events include generation numbers for optimistic concurrency

### **PostgreSQL Database**
- **Tables**: Primary tables with foreign key relationships for data integrity
- **Stored Procedures**: Status aggregation functions for efficient computation
- **ACID Transactions**: Full rollback support for complex operations
- **Status Aggregation**: Real-time computation of cluster health from controller reports

### **Controller Ecosystem (Internal)**
- **environment-validation-controller**: Validates GCP environment requirements (quotas, APIs, IAM, ...)
- **operator-client-controller**: Communicates with Management GKE Cluster and HyperShift Operator
- **placement-controller**: Determines optimal placement for cluster resources and infrastructure
- **dns-management-controller**: Manages DNS configuration and routing for GKE clusters
- **Autonomous Operation**: Each controller implements independent business logic and pre-condition checking
- **Event-Driven**: All controllers react to lightweight events, no polling or time-based reconciliation
- **Internal Deployment**: Controllers run within the Backend Service boundary for operational simplicity

### Event-Driven Communication Flow

```
1. API Request → backend service REST API
2. Database Update → PostgreSQL with transaction support
3. Event Publishing → Lightweight event to Cloud Pub/Sub (~200B)
4. Controller Receipt → Event-driven processing (no polling)
5. Data Fetching → Controller calls GET /api/v1/clusters/{id}
6. Processing → Controller performs validation/reconciliation
   - environment-validation-controller: Validates GCP environment
   - operator-client-controller: Manages HyperShift resources via Kubernetes API
   - placement-controller: Determines optimal resource placement
   - dns-management-controller: Configures DNS routing
7. Status Report → Controller calls PUT /api/v1/clusters/{id}/status
8. Aggregation → PostgreSQL stored procedure computes cluster status
```