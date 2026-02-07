# gcpctl

A production-grade CLI tool for managing GCP resources through Tekton webhooks.

## Features

- Clean, intuitive command-line interface using Cobra
- Robust error handling and validation
- Asynchronous pipeline triggering with event tracking
- Real-time pipeline status checking via kubectl or Tekton API
- Configurable via config file, environment variables, or CLI flags
- Verbose mode for debugging
- Proper timeout handling for webhook requests
- Well-structured codebase following Go best practices

## Project Structure

```
gcpctl/
├── main.go                           # Application entry point
├── go.mod                            # Go module dependencies
├── cmd/
│   └── gcpctl/
│       ├── root.go                   # Root command and global flags
│       └── region.go                 # Region management commands
├── internal/
│   ├── client/
│   │   ├── tekton.go                # Tekton webhook HTTP client
│   │   ├── tekton_api.go            # Tekton API client for status queries
│   │   └── kubectl.go               # kubectl-based client (primary method)
│   └── config/
│       └── config.go                # Configuration management
└── pkg/
    └── api/
        └── types.go                  # API request/response types
```

## Installation

### Build from source

```bash
go build -o gcpctl .
```

### Install to GOPATH

```bash
go install
```

## Usage

### Basic Workflow

1. **Trigger a pipeline** to provision a region:
```bash
gcpctl region add --environment production --region us-central1 --sector main
```

2. **Check the status** using the event ID returned:
```bash
gcpctl region status <event-id>
```

### Command Reference

#### `region add` - Trigger Region Provisioning

Add a region configuration by triggering a Tekton pipeline:

```bash
# Using long flags
gcpctl region add --environment production --region us-central1 --sector main

# Using short flags
gcpctl region add -e production -r us-central1 -s main

# With custom Tekton URL
gcpctl region add -e integration -r asia-east1 -s test \
  --tekton-url http://tekton.example.com:8080

# With verbose output
gcpctl region add -e staging -r europe-west1 -s backup -v

# With custom timeout
gcpctl region add -e production -r us-east1 -s primary --timeout 60s
```

**Output:**
```
✓ Region provisioning initiated

  Event ID:       63950e1f-7ffe-4d14-bc0e-121cee88942e
  Namespace:      default
  Event Listener: gcp-region-provisioning-listener

  Check status:
    gcpctl region status 63950e1f-7ffe-4d14-bc0e-121cee88942e

Note: Pipeline execution may take 10-15 minutes to complete.
```

#### `region status` - Check Pipeline Status

Query the status of a running or completed pipeline:

```bash
# Check status by event ID
gcpctl region status 63950e1f-7ffe-4d14-bc0e-121cee88942e

# Check status in a different namespace
gcpctl region status <event-id> --namespace production

# With verbose output
gcpctl region status <event-id> -v
```

**Output (Running):**
```
Pipeline Run: gcp-region-provision-jf8v5
Namespace:    default

Status:       ⏳ Running
Started:      2025-10-15 18:08:31 (3s ago)
Duration:     3s (running)

Tasks (5):
  ✓ fetch-terraform-config (2s)
  ⏳ terraform-plan
  ⏸ terraform-apply
  ⏸ configure-networking
  ⏸ validate-deployment

Progress:     1/5 tasks completed
```

**Output (Succeeded):**
```
Pipeline Run: gcp-region-provision-6kjs6
Namespace:    default

Status:       ✓ Succeeded
Started:      2025-10-15 18:03:44 (4m ago)
Completed:    2025-10-15 18:04:15 (took 31s)
```

### Global Flags

- `--tekton-url`: Override the Tekton webhook URL (default: http://localhost:8080)
- `--verbose`, `-v`: Enable verbose output for debugging
- `--config`: Specify a custom config file path

## Configuration

### Config File

Create a config file at `~/.gcpctl/config.yaml`:

```yaml
# Tekton webhook URL (for triggering pipelines)
tekton_url: http://localhost:8080

# Tekton API URL (for querying pipeline status)
# This should be the Kubernetes API server URL with Tekton API path
tekton_api_url: https://kubernetes.example.com

# Tekton Dashboard URL (optional, for displaying links to the web UI)
tekton_dashboard_url: http://tekton-dashboard.example.com

# Enable verbose output
verbose: false
```

**Important:** The `region status` command uses **kubectl by default** to query Tekton resources, which is the most reliable method. The `tekton_api_url` is only used as a fallback if kubectl is not available.

If you need to use direct API access (without kubectl), the `tekton_api_url` must point to a Kubernetes API server that has the Tekton APIs available at `/apis/tekton.dev/v1`. This is typically:
- A Kubernetes API server proxy (e.g., `kubectl proxy --port=8001` → `http://localhost:8001`)
- An API gateway with appropriate authentication
- Direct access to the Kubernetes API server (with proper credentials)

### Environment Variables

All configuration can be set via environment variables with the `GCPCTL_` prefix:

```bash
export GCPCTL_TEKTON_URL=http://tekton.example.com:8080
export GCPCTL_TEKTON_API_URL=https://kubernetes.example.com
export GCPCTL_TEKTON_DASHBOARD_URL=http://tekton-dashboard.example.com
export GCPCTL_VERBOSE=true
```

### Priority Order

Configuration is resolved in the following order (highest to lowest priority):

1. CLI flags
2. Environment variables
3. Config file
4. Default values

## API

The CLI sends JSON payloads to the Tekton webhook in the following format:

```json
{
  "environment": "production",
  "region": "us-central1",
  "sector": "main"
}
```

## Troubleshooting

### "failed to get pipeline status: Tekton API returned status 400"

This error means the CLI is trying to query the webhook endpoint instead of the Kubernetes API. The `region status` command needs to query Tekton resources via kubectl or the Kubernetes API.

**Solution:** The CLI automatically uses kubectl if available (recommended). If kubectl is not available, you need to configure `tekton_api_url` to point to a Kubernetes API server, not the webhook endpoint.

```bash
# Verify kubectl is working
kubectl get pipelineruns

# Or start a kubectl proxy and configure the CLI
kubectl proxy --port=8001 &
export GCPCTL_TEKTON_API_URL=http://localhost:8001
```

### "no pipeline runs found for event ID"

This can happen if:
1. The event ID is incorrect
2. The pipeline hasn't been created yet (takes a few seconds after triggering)
3. You're looking in the wrong namespace

**Solution:** Wait a few seconds after triggering, then check again. Use `--namespace` flag if your pipelines are in a different namespace.

```bash
# Wait a moment after triggering
gcpctl region add -e prod -r us-central1 -s main
sleep 3

# Then check status
gcpctl region status <event-id>

# Or specify namespace
gcpctl region status <event-id> --namespace production
```

## Development

### Project Layout

This project follows the [Standard Go Project Layout](https://github.com/golang-standards/project-layout):

- `cmd/`: Command-line applications
- `internal/`: Private application code
- `pkg/`: Public library code that can be imported by other projects

### Code Quality Features

- **Proper error handling**: All errors are wrapped with context
- **Input validation**: Request validation before sending to webhook
- **Context support**: Proper context handling for timeouts and cancellation
- **Separation of concerns**: Clean separation between CLI, client, and business logic
- **Type safety**: Strong typing for API requests and responses
- **Testability**: Dependency injection and interfaces for easy testing

### Building

```bash
# Build for current platform
go build -o gcpctl .

# Build with version info
go build -ldflags "-X main.Version=1.0.0" -o gcpctl .

# Cross-compile for Linux
GOOS=linux GOARCH=amd64 go build -o gcpctl-linux .

# Cross-compile for macOS
GOOS=darwin GOARCH=amd64 go build -o gcpctl-darwin .
```

### Testing

```bash
# Run tests
go test ./...

# Run tests with coverage
go test -cover ./...

# Run tests with race detector
go test -race ./...
```

## Extending the CLI

### Adding New Commands

1. Create a new file in `cmd/gcpctl/` (e.g., `environment.go`)
2. Define your command using Cobra's command structure
3. Register it in `root.go` by adding it to the root command

Example:

```go
var environmentCmd = &cobra.Command{
    Use:   "environment",
    Short: "Manage environments",
    RunE: func(cmd *cobra.Command, args []string) error {
        // Implementation
        return nil
    },
}

func init() {
    rootCmd.AddCommand(environmentCmd)
}
```

### Adding New API Types

Add new types to `pkg/api/types.go`:

```go
type EnvironmentRequest struct {
    Name        string `json:"name"`
    Description string `json:"description"`
}

func (r *EnvironmentRequest) Validate() error {
    if r.Name == "" {
        return &ValidationError{Field: "name", Message: "name is required"}
    }
    return nil
}
```

## License

Copyright 2025

## Support

For issues and questions, please contact your DevOps team.
