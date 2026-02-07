# Service Level Objectives: SDLC PR Test Runtime Performance

***Scope***: GCP-HCP SDLC

**Date**: 2025-11-05

**Status**: Draft - Initial Targets

## Overview

This document defines "fast enough" runtime targets for automated PR tests running in Prow across GCP-HCP platform repositories. These targets guide test implementation and serve as a reference for identifying performance issues that impact developer velocity.

## Purpose

### Why SDLC SLOs Matter

- **Developer Productivity**: Slow PR tests create context-switching overhead and reduce merge velocity
- **Feedback Loop Quality**: Fast test feedback enables rapid iteration and early bug detection
- **Cost Efficiency**: Test runtime directly impacts CI/CD compute costs
- **Team Morale**: Consistently fast tests improve developer experience

### Alignment with Automation-First Philosophy

These SLOs support our "allergic to toil" approach by:
- Preventing manual investigation of slow tests through clear targets
- Establishing performance budgets that prevent test suite bloat
- Enabling data-driven optimization decisions

## Target Runtime SLOs

### Infrastructure / Terraform Repository (openshift-online/gcp-hcp-infra)

**Target: Complete PR test suite ≤ 10 minutes**

| Phase | Target Runtime | Notes |
|-----------|----------------|-------|
| **Test setup** | ≤ 5 mins | runner allocation, environment prep |
| **Terraform Validation** | ≤ 5 mins | terraform-validate, terraform-test, check-orphan-modules |

**Rationale**: Infrastructure PRs should provide quick validation feedback. Terraform operations are typically cloud API performance bound, so longer runtimes indicate network/API issues rather than test complexity.

### Hypershift Repository (openshift/hypershift)

**Target: Complete PR test suite ≤ 120 minutes**

**Rationale**: Hypershift PR testing strategy includes e2e tests across multiple cloud providers. Best-case test duration at time of writing is around 2h.

## Using These Targets

### During Development

**When adding new tests**, ask:
- Will this test push us over the target runtime?
- Can this be parallelized or optimized?
- Should this be an integration test or belong in a separate E2E suite?

### During PR Review

**Red flags** indicating optimization needed:
- Individual test type exceeds its target
- Full suite exceeds repository target (10 min for Terraform, 8 min for Go)
- Test runtime increased >20% vs. previous PR without explanation

