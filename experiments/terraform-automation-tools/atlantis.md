# Atlantis - Terraform Pull Request Automation

**Website:** https://www.runatlantis.io/
**Repository:** https://github.com/runatlantis/atlantis
**Status:** Evaluated via POC
**Date Reviewed:** October 9, 2025

## Overview

Atlantis is an open-source tool for automating Terraform via pull requests. It runs as a self-hosted server that listens to GitHub webhooks and executes Terraform commands based on PR comments. Originally created as an independent open-source project, it was acquired by HashiCorp and has recently (June 2024) been donated to the CNCF as a sandbox project.

## Key Features

### Core Capabilities
- **PR Automation:** Automates Terraform plan and apply operations via pull request comments
- **Inline Plan Output:** Displays Terraform plan/apply output directly in GitHub PR comments
- **State Locking:** Locks Terraform state during operations to prevent conflicts
- **Self-Hosted:** Runs on your own infrastructure (no SaaS offering)
- **Multi-Platform Support:** Works with Terraform and OpenTofu

### Deployment Options
- **Traditional Hosting:** Can be deployed on GKE or other Kubernetes clusters
- **Serverless:** HashiCorp published guidance for running on Google Cloud Run
- **Local Development:** Can run locally with ngrok for testing

### Platform Support
- **VCS:** GitHub (primary), other platforms supported
- **Cloud Providers:** Cloud-agnostic (uses standard Terraform)
- **Deployment:** Docker images, Kubernetes, Cloud Run

## Pros

✅ **Mature & Active Development**
- Recently donated to CNCF (June 2024)
- Active community with regular releases (latest: 3 weeks ago as of Oct 2025)
- Commits as recent as today
- Community meetings available

✅ **Open Source & Self-Hostable**
- Full control over infrastructure
- No vendor lock-in
- No ongoing costs (only infrastructure)

✅ **Well-Established**
- Been around for several years
- Known tool in the Terraform ecosystem
- Proven in production environments

✅ **Flexible Deployment**
- Multiple deployment options (GKE, Cloud Run, etc.)
- Can use ngrok for development/testing
- GUI interface for configuration and monitoring

✅ **Good UX**
- Plan output directly in PR comments
- Familiar GitHub-based workflow
- Clear command structure

## Cons

⚠️ **Self-Hosting Required**
- Must run and maintain your own server
- Requires public endpoint or ngrok for webhooks
- Additional operational overhead

⚠️ **Less Polished Output**
- Plan output not as pretty as some alternatives (e.g., Digger)
- Functional but basic formatting

⚠️ **Infrastructure Dependencies**
- Needs persistent server infrastructure
- Webhook endpoint must be accessible from GitHub
- Requires more setup than CI-native solutions

⚠️ **Historical Uncertainty**
- Period of quiet development during HashiCorp ownership
- Future direction under CNCF still developing
- Backlog of open issues

## Technical Details

### Architecture
- **Server Component:** Long-running process that receives webhooks
- **Webhook Listener:** Receives events from GitHub
- **Execution Engine:** Runs Terraform commands based on PR comments
- **GUI Interface:** Basic web interface for configuration and job monitoring

### Locking Mechanism
- Locks Terraform state during plan/apply operations
- Automatically unlocks when PR is merged
- Prevents concurrent modifications

### Deployment
- Requires publicly accessible endpoint for GitHub webhooks
- Can use ngrok for development/testing
- Production deployments typically on Kubernetes or Cloud Run
- Docker images available

## Comparison to Alternatives

| Feature | Atlantis | Digger | Terraform Cloud |
|---------|----------|--------|-----------------|
| Cost | Self-hosted only | Free/Self-hosted | Paid tiers |
| Infrastructure | Dedicated server | Uses existing CI | SaaS/Managed |
| Plan Output | PR comments | PR comments (prettier) | External link |
| Maturity | Established (CNCF) | Newer | Enterprise |
| Hosting | Required | Optional | Not required |

## Recommendations

### Good Fit If:
- Team comfortable with self-hosting and maintaining services
- Want proven, established tool with active community
- Prefer dedicated server over CI-native approach
- Need flexibility in deployment options (GKE, Cloud Run, etc.)
- Want to avoid vendor lock-in

### May Not Fit If:
- Prefer CI-native solutions (GitHub Actions, etc.)
- Want to minimize operational overhead
- Need enterprise support guarantees
- Prefer prettier/more modern UX

## Next Steps

1. ⏳ Evaluate operational overhead of self-hosting
2. ⏳ Test Cloud Run deployment option
3. ⏳ Compare detailed feature set with Digger
4. ⏳ Assess community support and documentation
5. ⏳ Review configuration pipeline capabilities in GUI

## Additional Notes

- Front runner for team's Terraform automation needs
- CNCF donation (June 2024) indicates renewed community commitment
- Active development is a positive sign after period of uncertainty
- Self-hosting requirement is manageable with Cloud Run option
- Digger was influenced by Atlantis design, so similarities are intentional
- No SaaS offering available (self-hosting is only option)