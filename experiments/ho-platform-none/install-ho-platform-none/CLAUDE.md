# CLAUDE.md - HyperShift Installer Refactoring Documentation

## Session Summary: Monolithic to Modular Architecture

This document captures the key learnings and decisions from refactoring the HyperShift GKE installer from a monolithic 2800+ line file into a clean, modular architecture.

## What Was Accomplished

### Original Problem
- **Monolithic file**: `hypershift_installer.py` was 2821 lines long
- **Hard to maintain**: All 18 installation steps were in one massive file
- **User request**: "the @hypershift_installer.py file is to big - let's break it down in multiple files - one file per step"
- **Specific guidance**: "keep it simple - don't do a full refactor - simply split it in multiple files"

### Solution Implemented
- **Simple approach**: Split files without complex architectural changes
- **Modular structure**: One file per installation step
- **Clean naming**: Descriptive filenames without numeric prefixes
- **Shared infrastructure**: Common utilities extracted to avoid duplication

## Architecture Overview

### File Structure
```
📁 install-ho-platform-none/
├── 🔧 installer_main.py            # Main orchestrator
├── 🔧 common.py                    # Shared infrastructure
├── 📄 setup_environment.py         # Step 1: Environment setup
├── 📄 create_gke_cluster.py        # Step 2: GKE cluster creation
├── 📄 install_prometheus_operator.py # Step 3: Prometheus operator
├── 📄 install_cert_manager.py      # Step 4: cert-manager
├── 📄 build_hypershift.py          # Step 5: HyperShift binary & operator
├── 📄 deploy_webhook.py             # Step 6: Pod Security webhook
├── 📄 create_namespace_secrets.py  # Step 7: Namespace & secrets
├── 📄 deploy_hosted_cluster.py     # Step 8: HostedCluster manifest
├── 📄 wait_control_plane.py        # Step 9: Control plane readiness
├── 📄 fix_service_ca.py            # Step 10: Service CA configuration
├── 📄 fix_ovn_networking.py        # Step 11: OVN networking fixes
├── 📄 extract_hosted_access.py     # Step 12: Hosted cluster access
├── 📄 create_worker_node.py        # Step 13: Red Hat CoreOS worker node
├── 📄 generate_worker_certs.py     # Step 14: Worker certificates
├── 📄 configure_kubelet.py         # Step 15: Kubelet configuration
├── 📄 setup_worker_networking.py   # Step 16: OpenVSwitch & CNI
├── 📄 fix_ovn_networking_final.py  # Step 17: Final OVN setup
└── 📄 verify_installation.py       # Step 18: Installation verification
```

### Core Infrastructure (`common.py`)

**Key Classes:**
- `InstallConfig`: Configuration dataclass with all environment variables
- `Colors`: Terminal color codes for formatted output
- `TemplateManager`: YAML template rendering with variable substitution
- `StepTracker`: JSON-based state tracking for resumable installations
- `CommandRunner`: Shell command execution with error handling and dry-run support
- `BaseStep`: Abstract base class for all installation steps

**Design Pattern:**
```python
@installation_step("step_name", "Human readable description")
def execute(self) -> bool:
    # Step implementation
    return success
```

## Technical Insights

### HyperShift Architecture
- **Management cluster**: GKE Standard cluster hosting HyperShift operator
- **Hosted cluster**: OpenShift control plane running as workloads
- **Worker nodes**: Separate Red Hat CoreOS VMs joining the hosted cluster
- **Networking**: Complex OVN-Kubernetes with OpenVSwitch infrastructure

### Critical Components
1. **Pod Security Webhook**: Auto-fixes GKE Autopilot compatibility issues
2. **Certificate Management**: Worker node CSR approval and cert-manager integration
3. **OVN Networking**: Multiple phases of setup before/after worker nodes
4. **State Management**: JSON-based tracking for resumable installations

### Complex Networking Setup
- **OpenVSwitch**: Requires database initialization and proper user permissions
- **CNI Configuration**: Manual setup for ovn-k8s-cni-overlay binary
- **MTU Probes**: Network operator failures until worker nodes are available
- **Certificate Dependencies**: Multiple OVN metrics certificates needed

## Design Decisions

### Why This Approach Works
1. **Simplicity**: No complex inheritance hierarchies or abstract factories
2. **Consistency**: Every step follows the same pattern
3. **Resumability**: State tracking allows continuing failed installations
4. **Maintainability**: Each step is self-contained and focused

### Key Patterns
- **Decorator-based steps**: `@installation_step()` provides consistent logging and state
- **Shared dependencies**: All steps receive the same constructor arguments
- **Error handling**: CommandRunner provides consistent command execution
- **Template rendering**: Variable substitution for Kubernetes manifests

## Security Considerations

### Protected Files (.gitignore)
```
pull-secret.txt          # OpenShift registry credentials
my-cluster.env          # Project-specific configuration
*.env                   # Any environment files
work_*/                 # Temporary directories
logs/                   # Installation logs
.hypershift_install_state_*.json # State files
```

### Environment Variables
- **Required**: PROJECT_ID, GKE_CLUSTER_NAME, HOSTED_CLUSTER_NAME, etc.
- **Optional**: All have sensible defaults
- **Sensitive**: Pull secrets and project IDs kept out of git

## Usage Examples

### Basic Installation
```bash
source my-cluster.env
python3 installer_main.py
```

### Advanced Options
```bash
python3 installer_main.py --dry-run      # Preview actions
python3 installer_main.py --skip-webhook # Skip Pod Security webhook
python3 installer_main.py --continue     # Resume failed installation
python3 installer_main.py --cleanup      # Clean up all resources
```

## Lessons Learned

### What Worked Well
- **Simple file splitting**: No over-engineering, just clean separation
- **Consistent patterns**: Every step follows the same structure
- **State preservation**: All original functionality maintained
- **User guidance**: Following explicit user direction led to the right solution

### Technical Challenges
- **Import dependencies**: Updating all imports after file renaming
- **State management**: Ensuring step tracking works across modules
- **Complex networking**: Understanding OVN-Kubernetes setup phases
- **Error handling**: Maintaining robust error recovery

### Best Practices Discovered
- **Descriptive filenames**: Better than numeric prefixes for maintainability
- **Shared infrastructure**: Common utilities prevent code duplication
- **Decorator pattern**: Elegant way to add consistent behavior
- **Environment validation**: Early validation prevents runtime failures

## Future Considerations

### Potential Improvements
- **Parallel execution**: Some steps could run concurrently
- **Better error recovery**: More granular retry mechanisms
- **Configuration validation**: Schema validation for environment variables
- **Testing framework**: Unit tests for individual steps

### Scalability
- **Additional platforms**: Easy to add AWS, Azure variants
- **Step composition**: Steps could be combined for different scenarios
- **Plugin architecture**: External steps could extend functionality

## Git Integration

### Commit Strategy
- **Atomic refactoring**: All changes in single comprehensive commit
- **Descriptive message**: Clear explanation of what changed and why
- **Security**: Sensitive files properly ignored

### Branch Management
- **Feature branch**: GCP-119 for this refactoring work
- **Clean history**: Squashed commits for clean git log