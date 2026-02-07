# Bash Scripts - Manual Terraform Automation

**Status:** Not Recommended
**Date Reviewed:** October 9, 2025

## Overview

Simple bash scripts that iterate through Terraform workspaces and run `terraform init`, `terraform apply`, etc. Previously used in Dino Trace config repo for ROSA HCP's monitoring.

## Why Not Recommended

L **Poor Feedback Loop:** No interactive PR comments or status updates
L **Difficult Debugging:** Output is blob of text in job logs, hard to parse
L **No Interactivity:** Just runs in background; if it breaks, manual investigation required
L **Poor UX:** Team had to paste logs into Gemini/AI to debug failures

## Example Pattern

```bash
for workspace in $(terraform workspace list); do
  terraform init
  terraform apply -auto-approve
done
```

## When It Might Be Acceptable

- Extremely simple, one-off automation needs
- Internal tooling where UX doesn't matter
- Temporary solution while evaluating better tools

## Recommendation

**Use Atlantis or Digger instead.** Both provide significantly better UX, debugging, and team collaboration features.
