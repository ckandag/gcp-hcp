.PHONY: help build run test clean container

# Configuration
BINARY_NAME := wif-example
GCP_PROJECT_ID ?= $(shell echo $$GCP_PROJECT_ID)
PLATFORM ?= linux/amd64

help: ## Show this help
	@echo "WIF Example App - Makefile"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

build: ## Build the Go binary
	go build -o $(BINARY_NAME) .

run: ## Run the application locally (requires credentials)
	go run .

test: ## Run tests
	go test -v ./...

clean: ## Clean build artifacts
	rm -f $(BINARY_NAME)
	go clean

container: ## Build and push container image to GCR
	@if [ -z "$(GCP_PROJECT_ID)" ]; then \
		echo "Error: GCP_PROJECT_ID is not set"; \
		echo "Usage: make container GCP_PROJECT_ID=your-project-id"; \
		exit 1; \
	fi
	GCP_PROJECT_ID=$(GCP_PROJECT_ID) PLATFORM=$(PLATFORM) ./build-and-push.sh

