# GCP Private Service Connect Demo - Go Implementation

This is a Go implementation of the GCP Private Service Connect demo that creates a complete working example of Private Service Connect between two isolated VPCs.

## Overview

This Go implementation provides the same functionality as the bash scripts but with:
- **Type Safety**: Compile-time error checking
- **Better Error Handling**: Structured error reporting and recovery
- **Concurrent Operations**: Parallel resource creation where possible
- **Rich Output**: Colored output and detailed progress reporting
- **Idempotent Operations**: Safe to re-run if partially failed

## Architecture

The implementation is organized into packages:

```
golang/
├── cmd/                    # Command-line applications
│   ├── main.go            # Main demo orchestrator
│   ├── test.go            # Connectivity testing
│   └── cleanup.go         # Resource cleanup
├── pkg/                   # Core packages
│   ├── config/            # Configuration management
│   ├── vpc/               # VPC and networking operations
│   ├── vm/                # VM deployment and management
│   ├── psc/               # Private Service Connect setup
│   └── testing/           # Connectivity testing
├── Makefile               # Build and run automation
├── go.mod                 # Go module definition
└── README.md              # This file
```

## Prerequisites

1. **Go 1.19+** installed
2. **gcloud CLI** installed and authenticated
3. **Google Cloud Project** with billing enabled
4. **Required APIs** enabled:
   - Compute Engine API
   - Service Networking API
5. **IAM Permissions**:
   - **Demo**: `roles/compute.admin` and `roles/servicenetworking.networksAdmin`
   - **Production**: See [detailed IAM requirements](../README.md#iam-permissions-and-security) in main README
   - **Cross-project**: Additional `compute.networkViewer` for service attachment access

## Quick Start

1. **Set environment variables**:
   ```bash
   export PROJECT_ID="your-project-id"
   export REGION="us-central1"        # Optional, defaults to us-central1
   export ZONE="us-central1-a"        # Optional, defaults to us-central1-a
   ```

2. **Check prerequisites**:
   ```bash
   make check
   ```

3. **Run the complete demo**:
   ```bash
   make demo
   ```

4. **Test connectivity**:
   ```bash
   make test
   ```

5. **Clean up when done**:
   ```bash
   make cleanup
   ```

## Detailed Usage

### Building

Build all binaries:
```bash
make build
```

This creates binaries in the `bin/` directory:
- `bin/demo` - Main demo orchestrator
- `bin/test` - Connectivity testing
- `bin/cleanup` - Resource cleanup

### Running the Demo

The demo creates the same infrastructure as the bash implementation:

1. **Provider VPC** (hypershift-redhat) with:
   - Main subnet (10.1.0.0/24)
   - PSC NAT subnet (10.1.1.0/24)
   - Firewall rules for health checks, HTTP, SSH, and PSC NAT

2. **Consumer VPC** (hypershift-customer) with:
   - Main subnet (10.2.0.0/24)
   - Firewall rules for internal communication and SSH

3. **Virtual Machines**:
   - Service VM in provider VPC (nginx + Python API)
   - Client VM in consumer VPC (testing tools)

4. **Private Service Connect**:
   - Health checks and backend service
   - Internal load balancer
   - Service attachment
   - PSC endpoint in consumer VPC

### Manual Execution

You can also run the binaries directly:

```bash
# Run the main demo
./bin/demo

# Test connectivity
./bin/test

# Clean up resources
./bin/cleanup
```

### Testing

The Go implementation includes comprehensive connectivity testing:

```bash
make test
```

This tests:
- **Basic HTTP connectivity** via PSC endpoint
- **API endpoint functionality** (JSON responses)
- **Health check endpoint** (load balancer health)
- **Response validation** (content verification)

### Error Handling

The Go implementation provides better error handling than the bash scripts:

- **Resource Existence Checking**: Avoids errors when resources already exist
- **Operation Status Monitoring**: Waits for GCP operations to complete
- **Detailed Error Messages**: Shows exactly what failed and why
- **Graceful Degradation**: Continues with partial failures where appropriate


## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `PROJECT_ID` | Required | Google Cloud Project ID |
| `REGION` | `us-central1` | GCP region |
| `ZONE` | `us-central1-a` | GCP zone |

Additional configuration is available in `pkg/config/config.go`:
- VPC and subnet names
- VM configuration
- Load balancer settings
- PSC component names

## Development

### Adding New Features

1. **VPC Operations**: Add to `pkg/vpc/vpc.go`
2. **VM Operations**: Add to `pkg/vm/vm.go`
3. **PSC Operations**: Add to `pkg/psc/psc.go`
4. **Testing**: Add to `pkg/testing/testing.go`

### Building for Development

```bash
# Download dependencies
make deps

# Build and test
make build
go test ./...

# Run with verbose output
./bin/demo
```

### Code Structure

Each package follows a similar pattern:
- **Manager struct**: Holds GCP clients and configuration
- **New function**: Creates and initializes the manager
- **Close method**: Cleans up client connections
- **Operation methods**: Perform specific GCP operations
- **Helper functions**: Utilities for error checking and operations

## IAM Integration Patterns

The Go implementation uses **Application Default Credentials (ADC)** for authentication, making it compatible with various authentication methods:

### Authentication Methods

```go
// The Go clients automatically use ADC:
client, err := compute.NewNetworksRESTClient(ctx)
// Uses credentials in this order:
// 1. GOOGLE_APPLICATION_CREDENTIALS environment variable
// 2. gcloud user credentials
// 3. Service account on GCE/GKE
// 4. Workload Identity (in Kubernetes)
```

### Production Integration Examples

#### 1. Service Account Key File
```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
make demo
```

#### 2. Workload Identity (Kubernetes)
```yaml
apiVersion: v1
kind: Pod
spec:
  serviceAccountName: psc-controller  # Linked to GCP SA via Workload Identity
  containers:
  - name: psc-demo
    image: your-registry/psc-demo:latest
```

#### 3. Service Account Impersonation
```go
// For cross-project scenarios, modify pkg/config/config.go:
ts, err := impersonate.CredentialsTokenSource(ctx, impersonate.CredentialsConfig{
    TargetPrincipal: "target-sa@project.iam.gserviceaccount.com",
    Scopes:          []string{"https://www.googleapis.com/auth/cloud-platform"},
})
client, err := compute.NewNetworksRESTClient(ctx, option.WithTokenSource(ts))
```

### Cross-Project Configuration

For cross-project PSC scenarios, modify the configuration:

```go
// pkg/config/config.go - Add cross-project support
type Config struct {
    // ... existing fields ...

    // Cross-project configuration
    ProviderProjectID string  // Service provider project
    ConsumerProjectID string  // Service consumer project
    ServiceAccountEmail string // For impersonation
}
```

For complete IAM requirements and security best practices, see the [detailed IAM documentation](../README.md#iam-permissions-and-security) in the main README.

## Troubleshooting

### Common Issues

1. **Authentication**: Ensure `gcloud auth login` is completed
2. **Project Access**: Verify PROJECT_ID and permissions
3. **API Enablement**: Enable Compute Engine and Service Networking APIs
4. **Quotas**: Check GCP quotas for VMs and load balancers

### Debug Mode

For detailed operation logs, you can modify the code to enable verbose logging or add debug statements.

### Cleanup Issues

If cleanup fails partially:
```bash
# Force cleanup individual resources
gcloud compute forwarding-rules delete customer-psc-forwarding-rule --region=us-central1 --quiet
gcloud compute service-attachments delete redhat-service-attachment --region=us-central1 --quiet
# ... etc
```

## Cost Estimation

Same as bash implementation:
- 2x e2-micro VMs (~$5.35/month each) ✨ **Cost Optimized**
- 1x Internal Load Balancer (~$18/month)
- 1x Private Service Connect endpoint (~$36/month)

**Total**: ~$64.70/month if left running (**$39.30/month savings vs. e2-medium**)

⚠️ **Remember to run cleanup to avoid ongoing charges!**

## Contributing

To contribute to the Go implementation:

1. Follow Go conventions and best practices
2. Add error handling for all GCP operations
3. Include tests for new functionality
4. Update documentation for new features
5. Ensure idempotent operations

## License

Same as the parent project - this is part of the GCP Private Service Connect demo.