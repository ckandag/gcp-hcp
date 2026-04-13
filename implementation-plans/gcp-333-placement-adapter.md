# Placement Decision Adapter

**Jira**: [GCP-333](https://redhat.atlassian.net/browse/GCP-333)

| Field | Value |
|-------|-------|
| **Identifier** | `placement-adapter` |
| **Transport** | Kubernetes (placement decision Job on Region) |
| **Runs on** | Region cluster |
| **Depends on** | None (first in current chain; validation-adapter will precede once implemented) |

## Overview

Selects a target management cluster and DNS zone for a new HostedCluster, and writes the placement decision to the HyperFleet API cluster status. All downstream adapters read the chosen MC and base domain from this decision.

## Behavior

### MC Selection

Eligible MCs are identified by listing Secret Manager secrets in the regional project, created by the management-cluster Terraform module when a new MC is provisioned. These are cross-checked against Maestro's registered consumers to confirm the agent is connected and healthy. This naturally excludes MCs that are still being provisioned, have disconnected agents, or are being decommissioned. No region filtering is needed — all candidates are inherently in the same region as the placement adapter.

Among eligible MCs, the Job picks the least-loaded one by counting existing cluster placements in the HyperFleet API. When multiple MCs share the same lowest count, the Job breaks ties lexicographically by MC name for deterministic, reproducible placement.

**Capacity enforcement** is optional. Each MC's Secret Manager secret may carry a `gcp-hcp/max-clusters` label (set by Terraform) that caps how many clusters can be placed on it. If the label is absent, there is no capacity restriction — the MC is always eligible regardless of current load. When all MCs that *do* have a cap are at capacity and no uncapped MCs remain, the adapter reports `Available: False` with `MCPlacement: False` and a message such as `"No management cluster available with remaining capacity"`, and downstream adapters skip processing until capacity frees up.

### DNS Zone Selection

Available DNS domains are identified by reading the regional ArgoCD cluster secret in Secret Manager (labeled `infra-type:region`), which contains a `meta_hc_dns_domains` field — a comma-separated list of base domains provisioned for hosted clusters. The Job selects the least-loaded domain by counting existing cluster placements in the HyperFleet API per domain. When multiple domains share the same lowest count, the Job breaks ties lexicographically by domain name for deterministic, reproducible placement. Both MC and DNS load counts are derived from a single HyperFleet API query to avoid redundant calls. If no DNS domains are found or all domains are at capacity, the Job reports `Available: False` with `DNSPlacement: False` and a message such as `"No DNS domain available with remaining capacity"` and downstream adapters skip processing until capacity frees up.

### Placement Decision Output

Written to the HyperFleet API cluster status `data` field so downstream adapters can read it:

```json
{
  "adapter": "placement-adapter",
  "observed_generation": 1,
  "conditions": [
    {"type": "Applied", "status": "True"},
    {"type": "Available", "status": "True"},
    {"type": "MCPlacement", "status": "True", "message": "dev-mgt-us-c1-a1b2"},
    {"type": "DNSPlacement", "status": "True", "message": "a1b2.gcp-hcp.devshift.net"},
    {"type": "Health", "status": "True"}
  ],
  "data": {
    "managementClusterName": "dev-mgt-us-c1-a1b2",
    "managementClusterNamespace": "clusters-{clusterId}",
    "baseDomain": "a1b2.gcp-hcp.devshift.net"
  }
}
```

The placement-decision Job patches its own `.status.conditions` with `MCPlacement` and `DNSPlacement` results. The adapter framework discovers these via label selectors and maps them into the status payload posted to the HyperFleet API.

## Preconditions & Gating

| Gate | CEL Expression (summary) |
|------|--------------------------|
| No existing placement | Cluster has no prior `placement-adapter` status with `Available: True` |

The adapter skips processing if a placement decision already exists for the current cluster. This prevents re-placement on every reconcile event.

## Status Reporting

Reports the three mandatory conditions plus two adapter-specific conditions:

| Condition | Meaning |
|-----------|---------|
| `Applied` | Job was successfully created on the region cluster |
| `Available` | Both MC and DNS placement succeeded |
| `MCPlacement` | Target management cluster selected (message contains MC name) |
| `DNSPlacement` | Base domain selected (message contains domain) |
| `Health` | Job completed without errors |

## Idempotency & Edge Cases

- **First run**: performs selection algorithm, writes placement decision
- **Subsequent runs (same generation)**: reads existing placement from prior status, reports same MC and DNS — skips re-selection
- **Generation change (spec update)**: placement is sticky — reports existing MC with bumped `observed_generation`. MC assignment does not change on spec update. This means a cluster that was placed on MC-A at generation 1 remains on MC-A even if MC-A becomes the most loaded by generation 2. Sticky placement avoids costly cross-MC migrations but means load may skew over time as clusters are updated without being redistributed. If rebalancing is needed post-MVP, see re-placement below.
- **Re-placement**: not supported in MVP. If needed post-MVP, could be triggered via a dedicated annotation or admin API to clear the existing placement and allow the adapter to re-run the selection algorithm.

## Credentials

| Credential | Access | Source |
|-----------|--------|--------|
| GCP SA | Secret Manager secrets list + labels | Workload Identity on region cluster |
| Maestro API | Consumer list | In-cluster service URL (`http://maestro.hyperfleet.svc.cluster.local:8000`) |
| HyperFleet API | Cluster list + status POST | In-cluster service URL (`http://hyperfleet-api.hyperfleet.svc.cluster.local:8000`) |

## Design Alternatives Considered

None documented for MVP.

## Backlog

| Story | Jira | Status |
|-------|------|--------|
| Implement placement decision adapter for hosted cluster provisioning | [GCP-569](https://redhat.atlassian.net/browse/GCP-569) | In Progress |
