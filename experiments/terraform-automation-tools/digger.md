# Digger - Terraform Pull Request Automation

**Website:** https://digger.dev
**Repository:** https://github.com/diggerhq/digger
**Status:** POC In Progress
**Date Reviewed:** October 7, 2025

## Overview

Digger is an open-source Terraform pull request automation tool that runs natively within existing CI/CD pipelines. It positions itself as a secure, self-hostable alternative to solutions like Terraform Cloud and Atlantis.

## Key Features

### Core Capabilities
- **PR Automation:** Automates Terraform plan and apply operations via pull request comments
- **Concurrency:** Plan and apply jobs run in parallel without dependencies or blocking
- **Enhanced Locking:** PR-level locks (locks when PR opens, unlocks when merged) - more restrictive than default Terraform behavior
- **Inline Plan Output:** Displays Terraform plan/apply output directly in GitHub PR comments (no external tool navigation required)
- **Drift Detection:** Free drift detection included to identify manual or out-of-band changes
- **Private Runners:** Uses existing CI environment - no separate runner infrastructure needed
- **Multi-Platform Support:** Works with Terraform and OpenTofu

### Security Features
- **Secrets Management:** Secrets remain in Git repository only, not shared with third party
- **Self-Hostable:** Can be deployed on your own infrastructure (e.g., GKE cluster via Helm)
- **OPA Integration:** Open Policy Agent support for RBAC and policy enforcement
- **CI-Native Security:** Cloud access secrets stay within existing CI pipeline

### Platform Support
- **CI/CD:** GitHub Actions (primary), other CI platforms supported
- **Cloud Providers:** Google Cloud, AWS (out of the box)
- **Deployment:** Helm chart available for self-hosting

## Pros

✅ **Open Source & Self-Hostable**
- Full control over infrastructure reduces security risk
- Helm chart makes self-hosting on GKE straightforward

✅ **Cost Effective**
- Free tier with unlimited usage (SaaS offering)
- $50/month paid plan (only adds founder access and expedited feature requests)
- Uses existing CI infrastructure (no additional compute costs)

✅ **Security First**
- Secrets never leave your CI environment
- Complete control when self-hosted
- No third-party secret sharing

✅ **Excellent UX**
- Clean plan output directly in PRs
- No context switching between tools
- Familiar GitHub-based workflow

✅ **Concurrency & Performance**
- Parallel job execution
- Each repo triggers independent CI jobs

✅ **Feature Rich**
- Drift detection included
- OPA support for policy enforcement
- SSO support
- Telemetry capabilities
- Apply before merge support

✅ **Mature & Stable**
- Works very well despite feeling new
- Good documentation and active development

## Cons

⚠️ **Sustainability Concerns**
- Free unlimited tier seems unsustainable long-term
- Unclear how the business model supports this
- Risk that free tier may be discontinued

⚠️ **Maturity Questions**
- Product feels like it's in infancy
- Doesn't appear to have large company backing
- Limited paid tier benefits ($50/month only gets founder access)

⚠️ **PR Locking Behavior**
- Extended lock duration (entire PR lifecycle vs. apply-time only)
- Could cause blocking issues in high-velocity environments
- Mitigation: Auto-merge capabilities exist for approved PRs

⚠️ **Drift Detection Uncertainty**
- Implementation details unclear
- Likely uses scheduled plans (requires investigation)
- Not fully tested yet

⚠️ **Limited Ecosystem**
- Smaller community compared to established tools
- Less third-party integrations
- Fewer examples and use cases documented

## Technical Details

### Architecture
- **CLI Component:** Executes Terraform with appropriate arguments
- **Orchestrator Backend:** Triggers CI jobs based on repository events
- **Deployment Model:** Runs within existing CI (GitHub Actions, etc.)

### Locking Mechanism
- Locks at PR open (vs. Terraform's default apply-time locking)
- Unlocks at PR merge
- Prevents conflicting changes across multiple PRs
- Trade-off: Adds safety but may slow down rapid iteration

### Installation
- Simple integration via existing CI workflows
- Helm chart for self-hosted deployment
- Minimal configuration required

## Comparison to Alternatives

| Feature | Digger | Atlantis | Terraform Cloud |
|---------|--------|----------|-----------------|
| Cost | Free/Self-hosted | Self-hosted only | Paid tiers |
| Secret Management | In CI | In Atlantis | External |
| Infrastructure | Uses existing CI | Requires dedicated server | SaaS/Managed |
| Plan Output | Inline PR comments | Inline PR comments | External link required |
| Locking | PR-level | Apply-level | State-level |

## Recommendations

### Good Fit If:
- Security and secret management are top priorities
- Team prefers open-source, self-hostable solutions
- Existing CI/CD infrastructure is robust (GitHub Actions)
- Want to avoid vendor lock-in
- Cost optimization is important

### May Not Fit If:
- Require enterprise support guarantees
- Need proven long-term vendor stability
- High-velocity environment where PR-level locking is problematic
- Require extensive third-party integrations

## Next Steps

1. ✅ Test drift detection capabilities
2. ⏳ Evaluate PR locking impact on workflow velocity
3. ⏳ Test auto-merge functionality with approved PRs
4. ⏳ Assess self-hosting requirements and operational overhead
5. ⏳ Compare with other tools (Atlantis, Terraform Cloud)
6. ⏳ Validate telemetry and monitoring capabilities
7. ⏳ Review community support and documentation depth

## Additional Notes

- Tested and working well in initial POC
- Strong alignment with security principles (least privilege, defense in depth)
- Consider long-term sustainability when making final decision
- Plan for migration path if free tier is discontinued
- Self-hosting may be the most sustainable approach
