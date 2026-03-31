---
name: fix-implementation-plan-drifts
description: >
  Use when an implementation plan in gcp-hcp may have drifted from actual code,
  or when code may have drifted from the plan's design intent. Typically after
  a feature has landed or a PR has merged. Checks API surface, behavior,
  interfaces, and structure across repositories.
---

# Fix Implementation Plan Drifts

## Overview

Implementation plans are living documents. When code ships, the plan should reflect what was built. This skill detects the gap and determines whether to update the plan or flag the code for review.

## When to Use

- A feature PR merged that implements part of a plan
- A Jira epic moved to Done but the plan wasn't updated
- Reviewing a plan before starting new work on top of it
- Code review flagged something that contradicts the plan

## How to Start

1. **Ask the user**: verify a specific plan or all plans?
2. **Ask which repos to verify against.** Plans often span multiple repositories. The user can choose the current repo, a specific repo, or all repos referenced in the plan. Default to the current repo.
3. Use the cross-repo map from the `gcp-hcp-architecture` skill to identify which repo owns each component. If the plan references repos beyond the user's selection, list them and ask if the user wants to include them.

## What Is Drift

Drift is the gap between what the plan says and what the code does. It goes both ways:

- **Plan drifted from code** — the code evolved but the plan was never updated. Fix: update the plan.
- **Code drifted from plan** — the implementation deviated from the planned design, especially when it breaks architectural invariants or core principles. Fix: flag for team review.

Focus on meaningful differences — API contracts, behavior, architecture. Don't nitpick formatting or stylistic choices.

### Drift Categories

For each plan, verify these against actual code:

**API surface** — types, structs, or fields don't match actual definitions. Grep for every type and field mentioned. Compare names, tags, and markers. (e.g., plan references `GCPNetworkSpec` but code renamed it to `GCPNetworkConfig`)

**Behavior** — controller reconciliation logic, ownership patterns, or data flow differ from actual code. Read the actual reconcilers. (e.g., plan describes credentials managed in HO layer but code manages them in CPO)

**Interfaces** — CLI commands, flags, or workflows don't match actual implementation. Grep for every flag name. (e.g., plan describes infra creation as a single command but code splits it into separate `create infra` and `create iam` commands)

**Structure** — component organization doesn't match actual code. Check file paths and packages. (e.g., plan describes a single controller for PSC and DNS but code has separate controllers)

**Diagrams** — Mermaid or sequence diagrams use names, flows, or participants that don't match actual code

### NOT Drift

The plan should reflect what IS implemented. It is not a tracker for what ISN'T.

- Feature not yet implemented — tracked in Jira
- Progress or status of implementation — tracked in Jira
- Code improvement suggestions — file a Jira ticket
- Line number references — always stale, not worth maintaining

## How to Run

1. **Read the plan(s)** from `gcp-hcp/implementation-plans/`
2. **For each code artifact** (type, field, flag, controller), grep the selected repo(s). Compare plan description against actual code.
3. **If not found**, check Jira — unimplemented (not drift) or renamed/moved (drift)?
4. **Classify**:
   - **Update plan** — plan is stale, code is clearly correct
   - **Needs review** — not clear which side is right. Flag for team discussion. Ask the user if they want to create a Jira issue (use `jira:create` with the appropriate template from `gcp-hcp/docs/`).
5. **Output a drift report** — see format below.

## Output Format

```markdown
## Drift Report: {plan-name}

### Drift Items
| # | Plan Says | Code Does | Fix |
|---|-----------|-----------|-----|
| 1 | Infra creation handles WIF setup | WIF is a separate command | Update plan workflow |

### Verified (no drift)
Summary of what was checked and found to match.

### Needs Review
| # | Plan Says | Code Does | Concern |
|---|-----------|-----------|---------|
| 1 | Credentials in CPO storage component | HO creates secret directly | Breaks ownership pattern |

### Other Repos Referenced
> Ask: "This plan also references {repos}. Want me to verify against those too?"
```

## Common Drift Patterns

**Update this list when you find new patterns.**

1. **API evolution outpaces plan** — new fields or components added during implementation but never reflected.
2. **Naming divergence** — types, flags, or resources renamed during implementation. Plan keeps the original name.
3. **Behavior divergence** — reconciliation logic or ownership patterns differ from what the plan describes.
4. **Stale temporal notes** — time-stamped statements become false after implementation lands.

## Common Mistakes

- **Reporting unimplemented features as drift** — check Jira first. If the feature isn't built yet, it's not drift.
- **Nitpicking tag options or formatting** — focus on API contracts and behavior, not `omitempty` vs `omitzero`.
- **Silently fixing "needs review" items** — if the code may have violated the plan's design intent, flag it for discussion rather than updating the plan to match.
- **Skipping repos without asking** — if the plan spans repos, ask the user before excluding any.