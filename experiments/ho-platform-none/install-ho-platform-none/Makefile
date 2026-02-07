# HyperShift GKE Platform None Installer Makefile

.PHONY: help install validate cleanup dry-run check-env

# Default target
help:
	@echo "HyperShift GKE Platform None Installer"
	@echo ""
	@echo "Targets:"
	@echo "  help      - Show this help message"
	@echo "  check-env - Check if environment variables are set"
	@echo "  validate  - Validate prerequisites before installation"
	@echo "  dry-run   - Run installation in dry-run mode"
	@echo "  install   - Run the installation"
	@echo "  cleanup   - Clean up installation resources"
	@echo "  clean     - Clean up local files only"
	@echo ""
	@echo "Required environment variables:"
	@echo "  PROJECT_ID, GKE_CLUSTER_NAME, HOSTED_CLUSTER_NAME,"
	@echo "  HOSTED_CLUSTER_DOMAIN, PULL_SECRET_PATH"
	@echo ""
	@echo "Example usage:"
	@echo "  cp example.env .env"
	@echo "  # Edit .env with your values"
	@echo "  source .env"
	@echo "  make validate"
	@echo "  make install"

# Check if required environment variables are set
check-env:
	@echo "Checking required environment variables..."
	@test -n "$(PROJECT_ID)" || (echo "ERROR: PROJECT_ID not set"; exit 1)
	@test -n "$(GKE_CLUSTER_NAME)" || (echo "ERROR: GKE_CLUSTER_NAME not set"; exit 1)
	@test -n "$(HOSTED_CLUSTER_NAME)" || (echo "ERROR: HOSTED_CLUSTER_NAME not set"; exit 1)
	@test -n "$(HOSTED_CLUSTER_DOMAIN)" || (echo "ERROR: HOSTED_CLUSTER_DOMAIN not set"; exit 1)
	@test -n "$(PULL_SECRET_PATH)" || (echo "ERROR: PULL_SECRET_PATH not set"; exit 1)
	@echo "✓ All required environment variables are set"

# Validate prerequisites
validate:
	@echo "Running prerequisite validation..."
	python3 scripts/validate.py

# Run installation in dry-run mode
dry-run: check-env
	@echo "Running installation in dry-run mode..."
	python3 hypershift_installer.py --dry-run

# Run the installation
install: check-env
	@echo "Starting HyperShift installation..."
	python3 hypershift_installer.py

# Clean up installation resources
cleanup:
	@echo "Cleaning up installation resources..."
	@if [ -n "$(HOSTED_CLUSTER_NAME)" ] && [ -n "$(PROJECT_ID)" ] && [ -n "$(ZONE)" ]; then \
		python3 scripts/cleanup.py --cluster-name "$(HOSTED_CLUSTER_NAME)" --project-id "$(PROJECT_ID)" --zone "$(ZONE)"; \
	else \
		echo "ERROR: HOSTED_CLUSTER_NAME, PROJECT_ID, and ZONE must be set for cleanup"; \
		echo "For local cleanup only, use: make clean"; \
		exit 1; \
	fi

# Clean up local files only
clean:
	@echo "Cleaning up local files..."
	@if [ -n "$(HOSTED_CLUSTER_NAME)" ]; then \
		python3 scripts/cleanup.py --cluster-name "$(HOSTED_CLUSTER_NAME)" --local-only; \
	else \
		echo "ERROR: HOSTED_CLUSTER_NAME must be set"; \
		exit 1; \
	fi

# Install Python dependencies
deps:
	@echo "Installing Python dependencies..."
	pip3 install -r requirements.txt

# List installation steps
steps:
	@echo "Installation steps:"
	python3 hypershift_installer.py --list-steps

# Check logs for the most recent installation
logs:
	@if [ -n "$(HOSTED_CLUSTER_NAME)" ]; then \
		if [ -f "logs/hypershift_install_$(HOSTED_CLUSTER_NAME).log" ]; then \
			tail -f "logs/hypershift_install_$(HOSTED_CLUSTER_NAME).log"; \
		else \
			echo "No log file found for cluster: $(HOSTED_CLUSTER_NAME)"; \
		fi; \
	else \
		echo "ERROR: HOSTED_CLUSTER_NAME must be set"; \
		exit 1; \
	fi