# Terraform Cloud - HashiCorp's SaaS Terraform Platform

**Website:** https://www.terraform.io/cloud
**Status:** Demo Only (Not Pursuing)
**Date Reviewed:** October 9, 2025

## Overview

Terraform Cloud is HashiCorp's managed SaaS platform for Terraform automation. It provides enterprise-grade features including remote state management, PR automation, and private agents. While feature-rich and polished, it requires paid subscriptions and is not currently being considered due to cost.

## Key Features

- **PR Automation:** Plan/apply automation via pull requests
- **Remote State Storage:** Secure, managed state storage (more secure than basic GCS buckets)
- **Private Agents:** Run Terraform in your own infrastructure while using SaaS for orchestration
- **Workload Identity:** Agents can use workload identity for secure cloud access
- **Enterprise Support:** Backed by HashiCorp with SLA guarantees

## Why Not Pursuing

**=° Cost:** Paid subscription required
**<¯ Current Goals:** Team is looking to avoid vendor costs initially
**=. Future Consideration:** Could be explored later, especially given IBM/HashiCorp relationship

## Demo Observations

- **Setup Time:** ~10 minutes to get working
- **UX:** Very polished, well-designed interface
- **Plan Output:** Clean, but requires clicking external link (not inline in PR)
- **Workflow:** Re-runs plan after merge, then requires manual apply confirmation
- **Agent Model:** Keeps credentials in your infrastructure (good security model)

## Potential Future Fit

- IBM/HashiCorp relationship might provide discounts
- Excellent example of what enterprise Terraform tooling looks like
- Worth revisiting if team needs enterprise support guarantees
- Private agents model is solid security architecture

## Recommendation

Not recommended for initial implementation due to cost. Consider as future option if:
- Team outgrows open-source solutions
- Enterprise support becomes necessary
- IBM partnership provides favorable pricing
