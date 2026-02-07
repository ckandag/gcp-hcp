# PMR ITN-0000 - GCP HCP - Infinite Machine Creation Due to Selector Label Mismatch

## RCA Status
Draft

## Incident Date
2025-12-12

## Product
GCP HCP

## PMR Author(s)
Amador Pahim

## PMR Approver
[Pending]

## Ticket(s)
[OHSS-XXXXX or support ticket number]

## Incident
[ITN-2025-XXXXX or IcM number]

---

## Executive Summary

HyperShift uses Cluster API (CAPI) to manage worker node infrastructure through MachineSets and MachineDeployments. These controllers use label selectors to track which Machines belong to which parent resources. For GCP clusters, CAPI cluster names must comply with GCP network tag requirements (must start with a lowercase letter).

After rolling out a new version of Hypershift which changed the CPI Cluster name, multiple GCP HCP clusters experienced infinite Machine creation loops, causing resource exhaustion and unexpected infrastructure costs. This occurred because the MachineSet selector accumulated both old and new resource labels while the Machine template only contained new labels, preventing Machines from matching their parent MachineSets. GCP HCP Engineering identified the root cause as a bug in the selector reconciliation logic that appended labels to existing selectors instead of recreating them. The engineering team deployed a fix to the upstream HyperShift repository that recreates selector maps to match template labels.

## Customer Impact

**Affected Customers:**
- No customers affected, impact limited to development environment and internal development clusters

**Duration:**
- Impact began: 2025-12-12 (date when hypershift was rolled out)
- Impact finished: 2025-12-12 (date when CAPI was scalled down on affected clusters)

**Nature of Impact:**
- Infinite Machine creation leading to:
  - Unexpected cloud infrastructure costs
  - Resource quota exhaustion in GCP projects
  - Cluster instability due to excessive Machine reconciliation
  - Potential node count limits being reached
  - Wasted compute resources (Machines created but never joining cluster)

## Service Impact

| Component | Status |
|-----------|--------|
| Provisioning of new clusters or instances | Operational |
| API Endpoint | Operational |
| Router / Ingress (ie. Console) | Operational |
| On-cluster Registry | Operational |
| Platform Monitoring (Red Hat) | Operational |
| Customer workloads | **Degraded** - Nodes creating but not joining, resource exhaustion |

## High Level Timeline

| Date | Event |
|------|-------|
| 2024-[XX-XX] | Initial commit 127f409 introduces `gcpCompliantClusterName()` with conditional "hcp-" prefix to satisfy GCP network tag requirements |
| 2024-[XX-XX] | Inconsistent naming pattern causes issues with kubeconfig secret discovery in downstream systems |
| 2025-12-12 09:39 UTC | **Commit 489c5f99d merged** - Simplifies GCP CAPI cluster naming by using fixed "capi-cluster" name instead of conditional gcpCompliantClusterName() |
| 2025-12-12 [XX:XX] UTC | HyperShift operators begin rolling out to customer clusters |
| 2025-12-12 [XX:XX] UTC | **Start of Impact** - First clusters experience infinite Machine creation as MachineSets fail to recognize new Machines |
| 2025-12-12 [XX:XX] UTC | Developers report unexpected increase in GCP infrastructure and rapid Machine creation |
| 2025-12-12 [XX:XX] UTC | **GCP HCP Engineering Involvement** - GCP HCP Engineering begins investigating reports of infinite Machine creation |
| 2025-12-12 [XX:XX] UTC | **GCP HCP Engineering Declares Incident** |
| 2025-12-12 [XX:XX] UTC | Engineering team identifies root cause: selector label accumulation bug in capi.go |
| 2025-12-13 [XX:XX] UTC | **Partial Remediation** - Commit af60ea19c reverts the "capi-cluster" naming change |
| 2025-12-13 [XX:XX] UTC | Engineering team realizes revert alone won't fix accumulated state in existing clusters |
| 2025-12-13 07:50 UTC | **Fix Developed** - Commit 8e4d5be78 fixes selector reconciliation bug (PR #7384) |
| 2025-12-13 13:26 UTC | **Additional Fix** - Commit d92be48e5 simplifies naming to always use "hcp-" prefix |
| 2025-12-13 [XX:XX] UTC | **End of Impact** - Fixed HyperShift version deployed to affected clusters, manual cleanup performed where needed |
| 2025-12-[XX] [XX:XX] UTC | GCP HCP Engineering resolves incident after confirming no new occurrences |

## Questions

### What went well during this incident?
1. Root cause was identified relatively quickly through code analysis
2. Fix was developed, tested, and merged within 24 hours
3. Clear understanding of why simple revert wouldn't solve the problem

### Do we remember recent, similar incidents?
No similar incidents with infinite resource creation in HyperShift CAPI integration. However, there have been related issues:
- Previous incidents with label selector mismatches in other Kubernetes controllers
- Issues with state accumulation during resource reconciliation

### Was there an item in the team backlog that, if finished, would have prevented this incident?
No specific backlog item would have prevented this. However:
- Better test coverage for CAPI cluster name changes would have caught this
- Integration tests for selector/label matching would have identified the accumulation bug
- The conditional naming logic was known to be confusing but was not prioritized for simplification

### Was there something we could have done to end the impact on customers sooner?
Yes:
- **Automated detection**: Alerts for abnormal Machine creation rates would have identified the issue immediately
- **Faster manual remediation**: Documentation for emergency MachineSet/MachineDeployment deletion could have provided interim relief
- **Rollback capability**: Pre-tested rollback procedures could have provided temporary mitigation (though wouldn't fix accumulated state)
- **Circuit breaker**: Rate limiting on Machine creation could have prevented runaway creation

### Do we have any best practices recommendations to the customer?
1. Monitor GCP resource quota usage and set alerts for unusual consumption
2. Review cloud infrastructure costs regularly for unexpected increases
3. Set up billing alerts in GCP for rapid cost increases
4. For clusters with nodepool autoscaling, ensure maximum node counts are set appropriately

## Issue Tree

### Why did machines create infinitely?

**MachineSet selector didn't match Machine labels**
- Why didn't the selector match Machine labels?
  - **Selector contained both old and new labels**
    - Old label: `b87bf696-8c13-4-d248824f-<cluster>-nodepool-1`
    - New label: `capi-cluster-<cluster>-<cluster>-nodepool-1`
  - **Machine template contained only new labels**
    - New label: `capi-cluster-<cluster>-<cluster>-nodepool-1`
  - Why did the selector accumulate labels while template didn't?
    - **ROOT CAUSE #1: Code appended to existing selector map instead of recreating it**
      - Lines 395-400 in `reconcileMachineDeployment()` used append pattern
      - Lines 841-844 in `reconcileMachineSet()` used append pattern
      - Template always created fresh map (lines 407-410)
      - Why wasn't this caught in testing?
        - **ROOT CAUSE #2: No tests covering CAPI cluster name changes**
        - **ROOT CAUSE #3: No integration tests validating selector/label matching after reconciliation**
    - Why did the label change at all?
      - **CAPI cluster name changed from conditional to fixed value**
        - Old: `gcpCompliantClusterName(infraID)` → varied based on infraID first character
        - New: `"capi-cluster"` → fixed value
        - Why was this changed?
          - **ROOT CAUSE #4: Conditional naming logic was complex and error-prone**
            - Caused inconsistent kubeconfig secret naming
            - Led to discovery issues in downstream systems
            - Why was conditional naming used originally?
              - **GCP network tag requirement: must start with lowercase letter**
              - InfraIDs could start with digits or uppercase letters
              - Why not always use prefix?
                - Original design attempted to minimize changes for "compliant" infraIDs
                - **ROOT CAUSE #5: Insufficient consideration of naming consistency impact**

### Why was the revert insufficient?

**Accumulated state in existing MachineSets**
- Reverting code doesn't remove labels already added to selectors
- Selector would still have both old labels and "new" (actually reverted) labels
- **ROOT CAUSE #6: No cleanup/migration logic for selector labels**

## Conclusions

### Root Causes

1. **Selector Reconciliation Bug**: The `reconcileMachineSet()` and `reconcileMachineDeployment()` functions appended labels to existing selector maps instead of recreating them, causing selectors to accumulate stale labels over time.

2. **Lack of Test Coverage**: No tests validated behavior when CAPI cluster names change, and no integration tests verified selector/label matching after reconciliation.

3. **Design Complexity**: Conditional naming logic (`gcpCompliantClusterName`) introduced inconsistency and was error-prone, leading to downstream issues that prompted the simplification attempt.

4. **Absence of Migration Logic**: No cleanup mechanism existed to handle selector labels when resource naming patterns changed.

5. **Missing Safeguards**: No rate limiting, monitoring, or circuit breakers to detect and prevent infinite resource creation.

### Recommended Actions

- **Immediate**: Fix selector reconciliation to use map recreation instead of appending (completed: PR #7384)
- **Short-term**: Simplify GCP naming to always use "hcp-" prefix for consistency (completed: commit d92be48e5)
- **Medium-term**: Add comprehensive tests for CAPI resource reconciliation including name changes
- **Long-term**: Implement resource creation rate limiting and monitoring

## Corrective Actions

### Performed While Handling the Incident

| Issue Addressed | Description |
|----------------|-------------|
| Selector label accumulation causing infinite Machine creation | **2025-12-13**: Upstream fix (PR #7384, commit 8e4d5be78) that recreates selector maps instead of appending to them. This ensures selectors always match template labels. |
| Complex conditional naming logic | **2025-12-13**: Simplified GCP CAPI cluster naming (commit d92be48e5) to always use "hcp-" prefix, eliminating conditional logic and ensuring consistent naming. |
| Affected customer clusters | **2025-12-13**: Manually deleted broken MachineSets/MachineDeployments on affected clusters to stop infinite creation loop. Fixed HyperShift version deployed to allow clean recreation. |

### Pending Corrections (PMR Action Items)

| Priority | Issue to be Addressed | Details |
|----------|----------------------|---------|
| **High** | Lack of resource creation rate limiting | **Summary**: Implement circuit breaker or rate limiting for Machine creation to prevent runaway loops<br>**Owner**: HyperShift Engineering Team<br>**Ticket(s)**: [TBD]<br>**Notes**: Should trigger alerts when creation rate exceeds threshold (e.g., >5 machines/min) |
| **High** | Missing monitoring for abnormal Machine creation | **Summary**: Add alerts for unusual Machine creation rates and selector/label mismatches<br>**Owner**: SRE Team<br>**Ticket(s)**: [TBD]<br>**Notes**: Alert on Machine creation >3x expected rate for >10 minutes |
| **High** | Insufficient test coverage for CAPI reconciliation | **Summary**: Add integration tests that validate selector/label matching after resource name changes<br>**Owner**: HyperShift Engineering Team<br>**Ticket(s)**: [TBD]<br>**Notes**: Tests should cover: label changes, selector reconciliation, CAPI cluster name changes |
| **Medium** | No migration/cleanup logic for state changes | **Summary**: Implement migration controller or cleanup logic to handle selector updates when naming patterns change<br>**Owner**: HyperShift Engineering Team<br>**Ticket(s)**: [TBD]<br>**Notes**: Consider version-based migrations or automatic cleanup of stale selector labels |
| **Medium** | Missing documentation for emergency remediation | **Summary**: Create runbook for infinite Machine creation incidents<br>**Owner**: SRE Team<br>**Ticket(s)**: [TBD]<br>**Notes**: Should include: detection steps, manual remediation (delete MachineSet), rollback considerations |
| **Low** | GCP cost monitoring not integrated | **Summary**: Add GCP cost anomaly detection to cluster monitoring<br>**Owner**: SRE Team<br>**Ticket(s)**: [TBD]<br>**Notes**: Integration with GCP billing API to alert on unusual spend patterns |

## Appendices

### Technical Details: Selector vs Template Label Mismatch

**Buggy Code (Before Fix)**:
```go
// Appends to existing selector - accumulates old labels
if machineDeployment.Spec.Selector.MatchLabels == nil {
    machineDeployment.Spec.Selector.MatchLabels = map[string]string{}
}
machineDeployment.Spec.Selector.MatchLabels[capiv1.ClusterNameLabel] = capiClusterName
machineDeployment.Spec.Selector.MatchLabels[resourcesName] = resourcesName  // APPEND

// Creates fresh template labels - only new labels
machineDeployment.Spec.Template = capiv1.MachineTemplateSpec{
    ObjectMeta: capiv1.ObjectMeta{
        Labels: map[string]string{  // FRESH MAP
            resourcesName:           resourcesName,
            capiv1.ClusterNameLabel: capiClusterName,
        },
    },
}
```

**Fixed Code**:
```go
// Recreates selector - matches template
resourcesName := generateName(capiClusterName, nodePool.Spec.ClusterName, nodePool.GetName())
machineDeployment.Spec.Selector.MatchLabels = map[string]string{  // RECREATE
    capiv1.ClusterNameLabel: capiClusterName,
    resourcesName:           resourcesName,
}

// Template unchanged - fresh map
machineDeployment.Spec.Template = capiv1.MachineTemplateSpec{
    ObjectMeta: capiv1.ObjectMeta{
        Labels: map[string]string{  // FRESH MAP
            resourcesName:           resourcesName,
            capiv1.ClusterNameLabel: capiClusterName,
        },
    },
}
```

### Related Commits

- **127f409**: Initial introduction of conditional `gcpCompliantClusterName()`
- **489c5f99d**: Attempted simplification using fixed "capi-cluster" name (triggered the incident)
- **af60ea19c**: Revert of 489c5f99d (insufficient - didn't fix accumulated state)
- **8e4d5be78**: Fix for selector accumulation bug (PR #7384)
- **d92be48e5**: Simplification to always use "hcp-" prefix

### Resource Naming Evolution

| Version | CAPI Cluster Name | Kubeconfig Secret | Notes |
|---------|------------------|-------------------|-------|
| Pre-127f409 | `{infraID}` | `{infraID}-kubeconfig` | All infraIDs used directly |
| 127f409 - 489c5f99d | `{infraID}` or `hcp-{infraID}` | `{infraID}-kubeconfig` or `hcp-{infraID}-kubeconfig` | Conditional based on first character |
| 489c5f99d | `capi-cluster` | `capi-cluster-kubeconfig` | Fixed name (caused incident) |
| Current (d92be48e5) | `hcp-{infraID}` | `hcp-{infraID}-kubeconfig` | Always prefixed for consistency |
