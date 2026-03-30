---
name: Risk Tracking Process
description: How the GCP HCP team identifies, assesses, tracks, and mitigates project risks using Jira Risk issue types.
---

# Risk Tracking Process

***Scope***: GCP-HCP

**Date**: 2026-03-30

This document defines how the GCP HCP team identifies, assesses, tracks, and mitigates project risks.

## Tooling

Use the **Risk issue type** in the GCP Jira project. The Risk issue type is available in the Red Hat Jira Cloud instance and comes with pre-configured custom fields for risk management.

### Prerequisites

1. Enable the **Risk** issue type in the GCP project settings (Project Settings > Issue Types)
2. Verify the following custom fields are visible on the Risk issue screen:

| Field | Jira Field ID | Type | Purpose |
|-------|---------------|------|---------|
| Risk Probability | customfield_10642 | Dropdown | How likely is this risk to occur |
| Risk Impact | customfield_10842 | Dropdown | Severity if the risk materializes |
| Risk Score | customfield_10976 | Number | Calculated severity (Probability x Impact) |
| Risk Proximity | customfield_10645 | Dropdown | How soon the risk could materialize |
| Risk Response | customfield_10846 | Dropdown | Response strategy (Avoid, Mitigate, Transfer, Accept) |
| Risk Category | customfield_10679 | Dropdown | Classification (Technical, Schedule, Resource, etc.) |
| Risk Type | customfield_10683 | Dropdown | Type of risk |
| Risk Mitigation Strategy | customfield_10680 | Multi-select | Mitigation approaches |
| Risk impact description | customfield_10684 | Paragraph | Detailed description of potential impact |
| Risk mitigation/contingency | customfield_10686 | Paragraph | Mitigation and contingency plans |
| Risk Score Assessment | customfield_10974 | Paragraph | Qualitative risk assessment narrative |
| Risk Identified Date | customfield_10943 | Date | When the risk was first identified |

Standard Jira fields are also used:

- **Summary** -- one-line risk statement
- **Description** -- detailed risk context and background
- **Assignee** -- risk owner responsible for monitoring and response
- **Reporter** -- person who identified the risk
- **Components** -- GCP component area the risk relates to
- **Labels** -- use `milestone:<name>` to associate risks with milestones (e.g., `milestone:mvp`, `milestone:ga`)

### Workflow

The Risk issue type uses the following workflow statuses:

```
New  -->  Refinement  -->  In Progress  -->  Review  -->  Closed
```

- **New** -- risk has been raised but not yet assessed
- **Refinement** -- risk is being evaluated for probability, impact, and response strategy
- **In Progress** -- active mitigation or response plan is underway
- **Review** -- mitigation actions are complete; risk is being validated as resolved
- **Closed** -- risk has been resolved, accepted, or is no longer relevant

### Board

Create a **Risk Board** (Kanban) filtered to `issuetype = Risk AND project = GCP` to provide a dedicated view of all team risks and their current status.

### JQL Queries

Useful queries for risk management:

- **All open risks**: `issuetype = Risk AND project = GCP AND status != Closed`
- **High-severity risks**: `issuetype = Risk AND project = GCP AND "Risk Score" >= 10`
- **Risks needing owners**: `issuetype = Risk AND project = GCP AND assignee = EMPTY AND status != Closed`
- **Risks by milestone**: `issuetype = Risk AND project = GCP AND labels = "milestone:mvp"`

## Process

### 1. Identify

Anyone on the team can raise a risk at any time by creating a Risk issue in the GCP project. Include:

- A clear, specific summary (e.g., "GCP API Gateway region availability may limit customer deployments")
- A description covering: what could go wrong, what triggers it, and what would be affected
- The **Risk Identified Date**
- Set status to **New**

Good times to identify risks:
- Sprint planning
- Design reviews and architecture discussions
- Retrospectives
- Incident postmortems
- External dependency changes

### 2. Assess

The risk owner (or the team during grooming) evaluates the risk:

1. Set **Risk Probability** and **Risk Impact**
2. Calculate and set **Risk Score** (Probability x Impact)
3. Set **Risk Response** strategy
4. Write a mitigation/contingency plan in the **Risk mitigation/contingency** field
5. Set **Risk Proximity** to indicate urgency
6. Set **Risk Category** and **Risk Type**
7. Link the risk to any related epics, stories, or features using issue links
8. Transition status to **Refinement** or directly to **In Progress** if mitigation is already underway

### 3. Track

- **Grooming**: Triage newly identified risks (status = New). Assign owners. Assess probability and impact.
- **Sprint reviews**: Review the Risk Board. Update status and scores for any risks that have changed.
- **Monthly**: Review all open risks with the full team. Close risks that are no longer relevant. Identify new risks.

### 4. Respond

For risks in **In Progress** status:

- Create linked stories or tasks for specific mitigation actions
- Track mitigation progress through those linked issues
- Update the **Risk mitigation/contingency** field with progress
- Reassess probability and impact as mitigation actions complete
- When mitigation is complete, transition to **Review**

### 5. Close

Transition a risk to **Closed** when:

- The mitigation plan has been fully executed and the risk is resolved
- The risk is accepted with documented rationale (note the decision in the description)
- The risk is no longer applicable (document why)
- The risk materialized and has been handled through incident response

Add a comment explaining the closure rationale.

## Escalation

Escalate a risk to leadership when:

- Risk Score is >= 10
- The risk affects a milestone commitment
- The risk requires cross-team coordination or external dependencies
- The risk has been open for more than two sprints without progress on mitigation

## Related Documents

- [Definition of Done](definition-of-done.md)
- [Jira Story Template](jira-story-template.md)
