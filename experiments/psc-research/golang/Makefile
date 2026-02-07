# GCP Private Service Connect Demo - Go Implementation
# Makefile for building and running the demo

.PHONY: build demo test cleanup clean help

# Build all binaries
build:
	@echo "Building Go binaries..."
	go build -o bin/demo cmd/main.go
	go build -o bin/test cmd/test.go
	go build -o bin/cleanup cmd/cleanup.go
	@echo "✓ Binaries built in bin/ directory"

# Run the full demo
demo: build
	@echo "Running GCP Private Service Connect Demo..."
	./bin/demo

# Run connectivity tests
test: build
	@echo "Running connectivity tests..."
	./bin/test

# Run cleanup
cleanup: build
	@echo "Running cleanup..."
	./bin/cleanup

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	rm -rf bin/
	@echo "✓ Build artifacts cleaned"

# Download dependencies
deps:
	@echo "Downloading Go dependencies..."
	go mod download
	go mod tidy
	@echo "✓ Dependencies updated"

# Verify prerequisites
check:
	@echo "Checking prerequisites..."
	@command -v gcloud >/dev/null 2>&1 || { echo "❌ gcloud CLI not found"; exit 1; }
	@gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -n1 >/dev/null || { echo "❌ Not authenticated with gcloud"; exit 1; }
	@test -n "$$PROJECT_ID" || { echo "❌ PROJECT_ID environment variable not set"; exit 1; }
	@echo "✓ Prerequisites check passed"

# Run with verbose output
demo-verbose: build
	@echo "Running demo with verbose output..."
	./bin/demo -v

# Help
help:
	@echo "GCP Private Service Connect Demo - Go Implementation"
	@echo ""
	@echo "Available targets:"
	@echo "  build         Build all Go binaries"
	@echo "  demo          Run the complete PSC demo"
	@echo "  test          Run connectivity tests"
	@echo "  cleanup       Delete all demo resources"
	@echo "  clean         Clean build artifacts"
	@echo "  deps          Download and update dependencies"
	@echo "  check         Check prerequisites"
	@echo "  help          Show this help message"
	@echo ""
	@echo "Prerequisites:"
	@echo "  - gcloud CLI installed and authenticated"
	@echo "  - PROJECT_ID environment variable set"
	@echo "  - Go 1.19+ installed"
	@echo ""
	@echo "Example usage:"
	@echo "  export PROJECT_ID=your-project-id"
	@echo "  make check"
	@echo "  make demo"
	@echo "  make test"
	@echo "  make cleanup"

# Default target
all: build