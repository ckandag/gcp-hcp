# Frontend Service Architecture

The Frontend Service provides the customer-facing API interface for the GCP Hypershift Control Plane service, implementing comprehensive authentication, authorization, usage metering, and request routing.

## Architecture Overview

The Frontend Service acts as the primary customer touchpoint, handling all external API requests and providing essential platform services before routing requests to the Backend Service for cluster lifecycle management.

```
                    Customer Applications
                           │ HTTPS/REST
                           │ OAuth 2.0
                           ▼
    ┌─────────────────────────────────────────────────────────┐
    │                Frontend Service                         │
    │                                                         │
    │  ┌──────────────────────────────────────────────────┐  │
    │  │          API Gateway / Frontend Service          │  │
    │  │  ┌────────────────────────────────────────────┐  │  │
    │  │  │ • OAuth 2.0 Authentication                 │  │  │
    │  │  │ • Rate Limiting                            │  │  │
    │  │  │ • Request Routing                          │  │  │
    │  │  │ • Monitoring                               │  │  │
    │  │  │ • SSL/TLS                                  │  │  │
    │  │  └────────────────────────────────────────────┘  │  │
    │  └──────────────────────────────────────────────────┘  │
    │                                                         │
    │  ┌─────────────────────────────────────────────────────┐│
    │  │            Common Components                        ││
    │  │  ┌─────────────────────────────────────────────────┐││
    │  │  │ • Customer Authentication & Authorization       │││
    │  │  │ • Usage Metering & Tracking                     │││
    │  │  │ • Request Validation & Transformation           │││
    │  │  │ • Backend Service Communication                 │││
    │  │  │ • Error Handling & Customer Response Mapping    │││
    │  │  │ • Audit Logging & Compliance                    │││
    │  │  └─────────────────────────────────────────────────┘││
    │  └─────────────────────────────────────────────────────┘│
    └─────────────────────┬───────────────────────────────────┘
                          │ Authenticated HTTPS/REST
                          │ Service Account
                          ▼
    ┌─────────────────────────────────────────────────────────┐
    │                Backend Service                          │
    │    • Cluster Lifecycle Management                       │
    │    • State Persistence & Reconciliation                 │
    │    • Controller Orchestration                           │
    └─────────────────────────────────────────────────────────┘
```

## API Gateway Architecture

```
    Customer Applications
            │ HTTPS/REST + OAuth 2.0
            ▼
┌───────────────────────────────────────┐
│       Load Balancer / Ingress         │
│  • SSL/TLS Termination                │
│  • Geographic Traffic Distribution    │
│  • DDoS Protection                    │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│         Frontend Service              │    ┌─────────────────────────────┐
│  ┌─────────────────────────────────┐  │    │    Authentication Service   │
│  │        API Server               │  │    │ • OAuth 2.0 Provider        │
│  │ ┌─────────────────────────────┐ │◄─┼────┤ • JWT Token Validation      │
│  │ │ • HTTP Framework            │ │  │    │ • Service Account Auth      │
│  │ │ • Middleware Pipeline       │ │  │    │ • RBAC Policy Engine        │
│  │ │ • Request/Response Logging  │ │  │    └─────────────────────────────┘
│  │ │ • Health Check Endpoints    │ │  │
│  │ └─────────────────────────────┘ │  │    ┌─────────────────────────────┐
│  │                                 │  │    │      Monitoring Stack       │
│  │        Rate Limiting            │  │    │ • Prometheus Metrics        │
│  │ ┌─────────────────────────────┐ │◄─┼────┤ • Distributed Tracing       │
│  │ │ • Token Bucket Algorithm    │ │  │    │ • Structured Logging        │
│  │ │ • Per-User/Global Limits    │ │  │    │ • Custom SLA Dashboards     │
│  │ │ • Sliding Window Counters   │ │  │    └─────────────────────────────┘
│  │ └─────────────────────────────┘ │  │
│  │                                 │  │
│  │    Backend Communication        │  │
│  │ ┌─────────────────────────────┐ │  │
│  │ │ • HTTP Client with Retry    │ │  │
│  │ │ • Circuit Breaker Pattern   │ │  │
│  │ │ • Request Context Passing   │ │  │
│  │ └─────────────────────────────┘ │  │
│  └─────────────────────────────────┘  │
└─────────────────┬─────────────────────┘
                  │ Authenticated Internal REST
                  ▼
┌───────────────────────────────────────┐
│        Backend Service                │
│   • Cluster Lifecycle Management      │
│   • State Persistence                 │
└───────────────────────────────────────┘
```

## Core Components Analysis

### Customer Authentication & Authorization

#### Authentication Flow
```
1. Customer Request → Custom Frontend Service
   ├─ JWT Token Validation (Custom OAuth Provider)
   ├─ API Key Validation (Custom Implementation)
   └─ Session Management

2. Frontend Service → Authentication Service
   ├─ Token Introspection
   ├─ User Permission Resolution
   └─ RBAC Policy Evaluation

3. Frontend Service → Backend Service
   ├─ Service Account Token Generation
   ├─ Customer Context Propagation
   └─ Request Authorization Headers

4. Backend Service Processing
   ├─ Service Account Validation
   ├─ Resource-level Authorization
   └─ Audit Trail Creation
```

### API Interface Architecture

#### OpenAPI Specification
```yaml
openapi: 3.0.0
info:
  title: GCP Hypershift Control Plane API
  version: v1
  description: Managed Hypershift cluster lifecycle API

servers:
  - url: https://<api-endpoint>/v1

paths:
  /clusters:
    get:
      summary: List clusters
      security:
        - oauth2: [https://www.googleapis.com/auth/cloud-platform]
        - apiKey: []
      parameters:
        - name: project_id
          in: query
          required: true
          schema:
            type: string
      responses:
        200:
          description: List of clusters
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ClusterList'
    post:
      summary: Create cluster
      security:
        - oauth2: [https://www.googleapis.com/auth/cloud-platform]
        - apiKey: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ClusterSpec'

  /clusters/{cluster_id}:
    get:
      summary: Get cluster
      parameters:
        - name: cluster_id
          in: path
          required: true
          schema:
            type: string
      responses:
        200:
          description: Cluster details
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Cluster'

components:
  securitySchemes:
    oauth2:
      type: oauth2
      flows:
        implicit:
          authorizationUrl: https://accounts.google.com/oauth/authorize
          scopes:
            https://www.googleapis.com/auth/cloud-platform: Full access to GCP resources
    apiKey:
      type: apiKey
      in: header
      name: X-API-Key
```

### Usage Metering Architecture

```
┌─────────────────────────────────────────┐
│         Frontend Service                │
│  ┌───────────────────────────────────┐  │
│  │    Usage Metering Middleware      │  │
│  │ • API Call Counting               │  │
│  │ • Resource Usage Tracking         │  │
│  │ • Usage Attribution               │  │
│  └─────────────────┬─────────────────┘  │
└────────────────────┼────────────────────┘
                     │ Usage Events
                     ▼
┌─────────────────────────────────────────┐
│        Metering Service                 │
│  • Usage Aggregation                    │
│  • Report Generation                    │
│  • Project-level Attribution            │
└─────────────────────────────────────────┘
```

## Integration Patterns with Backend Service

### Request Flow Architecture
```
Customer Request
      │
      ▼
┌─────────────────────────────────────┐
│         Frontend Service            │
│ 1. JWT Token Validation             │
│ 2. Rate Limiting Check              │
│ 3. Request Schema Validation        │
│ 4. Customer Context Resolution      │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│      Authentication Service         │
│ 1. Token Introspection              │
│ 2. Permission Resolution            │
│ 3. RBAC Policy Evaluation           │
└─────────────────┬───────────────────┘
                  │ Auth Context
                  ▼
┌─────────────────────────────────────┐
│         Frontend Service            │
│ 1. Service Account Token Generation │
│ 2. Request Context Enrichment       │
│ 3. Backend Service Call             │
└─────────────────┬───────────────────┘
                  │ Internal HTTPS
                  │ Headers:
                  │ • Authorization: Bearer <sa_token>
                  │ • X-Customer-Project: <project_id>
                  │ • X-Customer-User: <user_id>
                  │ • X-Request-ID: <trace_id>
                  ▼
┌─────────────────────────────────────┐
│         Backend Service             │
│ 1. Service Account Validation       │
│ 2. Customer Context Extraction      │
│ 3. Resource Authorization Check     │
│ 4. Business Logic Processing        │
└─────────────────┬───────────────────┘
                  │ Response
                  ▼
┌─────────────────────────────────────┐
│         Frontend Service            │
│ 1. Response Processing              │
│ 2. Error Handling & Mapping         │
│ 3. Usage Metering Event Generation  │
│ 4. Customer Response Formatting     │
└─────────────────┬───────────────────┘
                  │
                  ▼
            Customer Response
```

### Error Handling and Customer Experience

#### Error Mapping Strategy
The frontend service implements comprehensive error handling to translate technical backend errors into customer-friendly responses:

```go
// Error mapping example for both models
type CustomerErrorResponse struct {
    Error struct {
        Code    string            `json:"code"`
        Message string            `json:"message"`
        Details []ErrorDetail     `json:"details,omitempty"`
        Metadata map[string]string `json:"metadata,omitempty"`
    } `json:"error"`
}

// Backend error to customer error mapping
var errorMappings = map[string]CustomerErrorResponse{
    "CLUSTER_QUOTA_EXCEEDED": {
        Error: {
            Code:    "RESOURCE_QUOTA_EXCEEDED",
            Message: "Your project has reached the maximum number of clusters. Please delete unused clusters or request a quota increase.",
            Details: []ErrorDetail{
                {
                    Type: "quota_info",
                    Metadata: map[string]string{
                        "current_usage": "10",
                        "quota_limit":   "10",
                        "resource_type": "clusters",
                    },
                },
            },
        },
    },
    "VALIDATION_FAILED": {
        Error: {
            Code:    "INVALID_ARGUMENT",
            Message: "The request contains invalid parameters.",
            Details: []ErrorDetail{
                {
                    Type: "field_violation",
                    Metadata: map[string]string{
                        "field": "cluster.name",
                        "description": "Cluster name must be between 1-63 characters and contain only lowercase letters, numbers, and hyphens.",
                    },
                },
            },
        },
    },
}
```

## Operational Considerations

### Monitoring and Observability
```
┌─────────────────────────────────────┐
│         Monitoring Stack            │
│  ┌───────────────────────────────┐  │
│  │      Prometheus Metrics       │  │
│  │ • HTTP Request Metrics        │  │
│  │ • Custom Business Metrics     │  │
│  │ • Infrastructure Metrics      │  │
│  └───────────────────────────────┘  │
│  ┌───────────────────────────────┐  │
│  │     Distributed Tracing       │  │
│  │ • Request Flow Visualization  │  │
│  │ • Performance Analysis        │  │
│  └───────────────────────────────┘  │
│  ┌───────────────────────────────┐  │
│  │      Structured Logging       │  │
│  │ • Log Aggregation             │  │
│  │ • Custom Log Processing       │  │
│  │ • Audit Trail Management      │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

### Security Architecture

- **DDoS Protection**: Network-level protection
- **SSL/TLS**: Certificate management and automatic renewal
- **API Security**: Rate limiting and abuse detection
- **Compliance**: Security compliance implementation and validation
- **Audit Logging**: Comprehensive audit trail and log management
