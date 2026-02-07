# Google Cloud Infrastructure Manager - Terraform Automation

**Website:** https://cloud.google.com/infrastructure-manager/docs/overview
**Status:** POC Complete
**Date Reviewed:** October 8, 2025

## Overview

Google Cloud Infrastructure Manager is a managed service for deploying and managing Terraform configurations directly within Google Cloud. It orchestrates Cloud Build jobs to execute Terraform operations (init, validate, plan, apply, destroy) with integrated state storage and IAM-based authentication.

## Key Features

### Core Capabilities
- **Managed Terraform Execution:** Orchestrates Terraform commands through Cloud Build
- **Git Integration:** Supports using Git source references for infrastructure definitions
- **Automated State Management:** Built-in state storage in Google Cloud Storage (no backend configuration needed)
- **IAM-based Authentication:** Jobs run as GCP service accounts (no credential keys required)
- **Private Repository Support:** Works with private GitHub repositories
- **Preview Deployments:** Generates Terraform plans on pull requests

### Platform Support
- **VCS:** GitHub (requires GitHub App installation and PAT)
- **Cloud Provider:** Google Cloud (native integration)
- **IaC Tools:** Terraform only (OpenTofu not supported)

## Pros

 **Native GCP Integration**
- Seamless integration with Google Cloud services
- No additional infrastructure required
- Built-in state storage management

 **Security-First Authentication**
- Uses IAM service accounts (no credential keys)
- Secrets managed through Google Secret Manager
- Cloud-native security controls

 **Managed Service**
- No separate infrastructure to maintain
- Google-managed orchestration backend
- Automatic state storage provisioning

 **Git Source Support**
- Direct repository integration
- Support for private repositories
- Version-controlled infrastructure definitions

## Cons

L **OpenTofu Not Supported**
- Terraform-only support limits tooling flexibility
- Cannot leverage OpenTofu features or ecosystem

L **No PR Plan Feedback**
- Terraform plan output not displayed in PR body
- Requires navigating to Cloud Build to view results
- Poor developer experience compared to inline tools

L **Complex Setup**
- Requires installing Google Cloud Build app on repository
- Must generate and store GitHub PAT in Secret Manager
- Separate Infrastructure Manager setup needed for each regional cluster or environment
- Service account configuration required for Terraform operations

L **Preview Job Behavior**
- Spins up new Cloud Build instance for every PR
- Preview jobs fail frequently ("plans don't work most of the time")
- Reliability issues impact developer workflow

L **No Automatic Lifecycle Triggers**
- Deployments don't automatically trigger on lifecycle events
- Requires manual Cloud Build trigger configuration
- Additional setup overhead for automation

L **Multi-Deployment Issues**
- All Infrastructure Manager setups sharing the same repo trigger checks on PRs
- Difficult to identify which job is relevant for a given PR
- Clutters PR status checks with irrelevant jobs

L **State Storage Proliferation**
- Auto-generated GCS buckets for each deployment
- Risk of cluttering projects with numerous state buckets
- Requires careful bucket lifecycle management

## Technical Details

### Architecture
- **Orchestration:** Cloud Build executes Terraform commands
- **State Storage:** Automatic GCS bucket provisioning (or use existing bucket)
- **Authentication:** Service account-based execution
- **Repository Access:** GitHub App + PAT for private repos

### Setup Requirements
1. Install Google Cloud Build app to GitHub repository
2. Add repository in Cloud Build console
3. Generate GitHub PAT and store in Secret Manager
4. Create service account for Terraform operations
5. Configure Infrastructure Manager deployment:
   - Specify Terraform version
   - Define service account
   - Set Git repository and path to Terraform configs
   - Create separate setup for each regional/environment deployment

### Deployment Configuration
Each Infrastructure Manager deployment requires:
- Repository URL
- Path to Terraform configuration
- Terraform version specification
- Service account for execution
- Separate configuration per region/environment

## Comparison to Alternatives

| Feature | Infrastructure Manager | Digger | Atlantis | Terraform Cloud |
|---------|----------------------|--------|----------|-----------------|
| Cost | GCP service costs | Free/Self-hosted | Self-hosted only | Paid tiers |
| Plan Output | External (Cloud Build) | Inline PR comments | Inline PR comments | External link |
| Secret Management | Secret Manager + IAM | In CI | In Atlantis | External |
| Infrastructure | Managed (Cloud Build) | Uses existing CI | Requires dedicated server | SaaS/Managed |
| OpenTofu Support | L No |  Yes |  Yes | L No |
| Setup Complexity | High | Low | Medium | Low |
| Preview Reliability | Low (frequent failures) | High | High | High |

## Recommendations

### Good Fit If:
- Exclusively using Google Cloud
- Strong preference for managed services
- IAM-based security is critical requirement
- Team comfortable with Cloud Build workflows
- OpenTofu support not needed

### May Not Fit If:
- Need inline PR plan feedback (poor UX)
- Require reliable preview jobs (frequent failures)
- Want to use OpenTofu
- Multi-cloud or hybrid infrastructure
- High-velocity environment (preview job issues would be blocking)
- Prefer simpler setup and configuration

## Known Issues

1. **Preview Job Failures:** Plans fail frequently, impacting reliability
2. **Multi-Deployment PR Checks:** All deployments sharing a repo trigger on every PR
3. **No Root-Level Config Support:** Configurations not at repository root may need custom patches
4. **Preview Instance Spinning:** New Cloud Build instance per PR (potentially tunable)

## Next Steps

1.  Complete POC evaluation
2. ó Investigate preview job failure rate and potential fixes
3. ó Test tuning preview instance behavior
4. ó Evaluate cost implications of Cloud Build usage
5. ó Assess bucket lifecycle management strategies
6. ó Compare total cost of ownership vs. alternatives
7. ó Decision: Continue evaluation or move to alternative tool

## Additional Notes

- Tested in POC with multiple failure points identified
- Setup complexity and reliability concerns outweigh managed service benefits
- Digger provides superior UX with inline PR feedback and better reliability
- Consider Infrastructure Manager only if GCP-native requirements mandate it
- For most use cases, Digger or Atlantis are stronger alternatives
