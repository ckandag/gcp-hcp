# Monitoring HyperShift Control Planes with Google Cloud Monitoring

## Executive Summary

**Goal**: Collect Prometheus metrics from HyperShift Hosted Control Plane (HCP) components and export to Google Cloud Monitoring (GCM).

**Two Viable Approaches**:
1. **GMP PodMonitoring** - Use Google's native PodMonitoring CRDs
2. **Cluster-Wide Prometheus** - Deploy self-managed Prometheus with GMP export

This document provides a detailed comparison to support team decision-making.

---

## Comparison Overview

| Factor | GMP PodMonitoring | Cluster-Wide Prometheus |
|--------|-------------------|-------------------------|
| **Migration Effort** | High - Rewrite all monitors and rules | Zero - Use existing configs |
| **Consistency Across Clouds** | Different configs for GCP vs ROSA/ARO | Same configs across all clouds |
| **Recording Rules** | Must migrate to Rules CRD | Native PrometheusRules support |
| **Network Policy Changes** | Required in every HCP namespace | No changes needed |
| **Additional RBAC** | ClusterRoleBinding needed | Built-in via ClusterRole |
| **Infrastructure to Manage** | None (GMP managed) | Prometheus Operator + Prometheus |
| **Resource Overhead** | DaemonSet (1 pod/node) | Single pod (500m-2000m CPU, 2-8Gi RAM est.) |
| **Cost Optimization** | Possible via metricRelabeling in PodMonitoring | Easier via metricRelabelConfigs + Prometheus UI |
| **Uptime Responsibility** | Google manages collector pods | You manage Prometheus pods |

---

## Option 1: GMP PodMonitoring

Use Google's native Managed Prometheus with PodMonitoring CRDs.

### What This Requires

1. **Rewrite all ServiceMonitors** → PodMonitoring CRD format
2. **Rewrite all PodMonitors** → PodMonitoring CRD format
3. **Rewrite all PrometheusRules** → Rules CRD (rules.monitoring.googleapis.com)
4. **Update network policies** in every HCP namespace to allow `gke-gmp-system` namespace
5. **Add ClusterRoleBinding** to grant GMP collectors cross-namespace secret access

**See `gmp-podmonitoring-example.yaml` for complete example resources including ClusterRole, ClusterRoleBinding, PodMonitoring examples, and Rules CRD examples.**

### Technical Implementation

**Network Policy Changes**:
```yaml
# Add to each HCP namespace's NetworkPolicy
- from:
  - namespaceSelector:
      matchLabels:
        # Allow gke-gmp-system (in addition to existing monitoring namespaces)
        kubernetes.io/metadata.name: gke-gmp-system
```

**RBAC Addition**:
```yaml
# One-time cluster-wide configuration
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: gmp-collector-secret-access
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: gmp-collector-secret-access
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: gmp-collector-secret-access
subjects:
- kind: ServiceAccount
  name: collector
  namespace: gke-gmp-system
```

### Architecture

```
gke-gmp-system namespace (GKE-managed)
  └── GMP Collector DaemonSet (1 pod per node)
      ├── Watches PodMonitoring CRs cluster-wide
      ├── Scrapes HCP namespaces (after network policy changes)
      ├── Accesses secrets (after ClusterRoleBinding added)
      └── Exports directly to GCM

HCP Namespaces (clusters-xxx-test-hc-1, ...)
  ├── PodMonitoring CRs (rewritten from ServiceMonitors/PodMonitors)
  └── Rules CRs (rewritten from PrometheusRules)
```

### Advantages

- ✅ **No infrastructure to manage**: GMP collector pods managed by Google
- ✅ **Google manages uptime**: If collector pods crash, Google fixes them
- ✅ **Native GCP integration**: Purpose-built for GKE/GCP
- ✅ **Automatic scaling**: DaemonSet scales with nodes

**Note**: Google's SLA covers the managed service availability (collector pods running), not delivery of metrics if your NetworkPolicies or RBAC are misconfigured.

### Challenges

- ❌ **High migration effort**: Rewrite all ServiceMonitors, PodMonitors, PrometheusRules
- ❌ **Different syntax**: Rules CRD has different syntax/capabilities than PrometheusRules
- ❌ **Config divergence**: Maintain separate configs for GCP vs ROSA/ARO
- ❌ **Security boundary changes**: Modify network policies in every HCP namespace
- ❌ **Custom RBAC**: Maintain ClusterRoleBinding (may conflict with GKE updates)
- ❌ **Higher resource usage**: DaemonSet consumes resources on every node

---

## Option 2: Cluster-Wide Prometheus

Deploy a self-managed Prometheus instance using Google's GMP-enabled Prometheus image.

### What This Requires

1. **Deploy Prometheus Operator** (if not already deployed)
2. **Create `openshift-monitoring` namespace** with network policy label
3. **Deploy Prometheus instance** with ClusterRole for cross-namespace access
4. **Configure Workload Identity** for GCM export

### Architecture

```
openshift-monitoring namespace (labeled: network.openshift.io/policy-group=monitoring)
  └── prometheus-cluster-wide
      ├── Discovers ServiceMonitors/PodMonitors from ALL namespaces
      ├── Evaluates PrometheusRules (recording rules)
      ├── Stores locally (20Gi PVC, 6h retention)
      └── Exports to GCM via built-in exporter (Google's Prometheus image)

HCP Namespaces (clusters-xxx-test-hc-1, ...)
  ├── ServiceMonitors (existing, no changes)
  ├── PodMonitors (existing, no changes)
  └── PrometheusRules (existing, no changes)
```

### Advantages

- ✅ **Zero migration**: Use existing ServiceMonitors, PodMonitors, PrometheusRules
- ✅ **Cross-cloud consistency**: Same configs for GCP, ROSA, ARO
- ✅ **No network policy changes**: Works with existing policies via namespace label
- ✅ **No custom RBAC**: ClusterRole is part of standard Prometheus deployment
- ✅ **Predictable resource usage**: Single pod vs DaemonSet (1 pod/node)
- ✅ **Native Prometheus features**: Full recording rules, alerting rules, query engine
- ✅ **Debugging capability**: Prometheus UI available via port-forward

### Challenges

- ❌ **Infrastructure to manage**: Prometheus Operator + Prometheus instance
- ❌ **You manage uptime**: If Prometheus pods crash, you must fix them (not Google)
- ❌ **Storage required**: 50Gi PVC for rule evaluation
- ❌ **Patching responsibility**: Must maintain Prometheus Operator and Prometheus versions

**Note**: Both options use the same Google-provided Prometheus image, so GCM export reliability is identical. The difference is who manages the Prometheus/collector pod uptime.

---

## Detailed Comparison

### Migration Effort

**GMP PodMonitoring**:
- Per HCP namespace: ~42 ServiceMonitors + ~4 PrometheusRules to rewrite
- **Total for 100 clusters**: ~4,200 ServiceMonitors + ~400 PrometheusRules
- Different syntax and capabilities (learning curve)
- Testing required for each rewritten resource
- Estimated effort: Significant (scales with cluster count)

**Cluster-Wide Prometheus**:
- No rewrites needed
- Deploy Prometheus with existing configs
- Estimated effort: A few days

### Recording Rules

**GMP PodMonitoring**:
- Uses Rules CRD (rules.monitoring.googleapis.com)
- Different syntax from Prometheus PromQL
- Evaluated by Google's rule engine
- May have different capabilities/limitations

**Cluster-Wide Prometheus**:
- Uses PrometheusRules (existing format)
- Standard Prometheus PromQL
- Evaluated locally by Prometheus
- Full Prometheus capabilities

### Network Policies

**GMP PodMonitoring**:
- Requires modifying NetworkPolicy in every HCP namespace
- Changes maintained in hypershift repository
- Broadens security boundary to include `gke-gmp-system`

**Cluster-Wide Prometheus**:
- No NetworkPolicy changes required
- Uses existing `network.openshift.io/policy-group=monitoring` label
- Maintains current security boundaries

### Cross-Namespace Secret Access

**GMP PodMonitoring**:
- Requires custom ClusterRoleBinding
- Grants `gke-gmp-system/collector` service account cluster-wide secret access
- Must be maintained outside GKE management
- Potential for conflicts with GKE updates

**Cluster-Wide Prometheus**:
- ClusterRole is standard Prometheus Operator pattern
- Part of normal Prometheus deployment
- No special RBAC considerations

### Resource Usage

**GMP PodMonitoring**:
- DaemonSet: 1 pod per node
- Scales with cluster size (more nodes = more pods)
- Each pod: ~100-200m CPU, ~256Mi RAM
- Total: N × resources (where N = number of nodes)
- Example: 50 nodes = 50 pods = 5-10 CPU cores, 12-25Gi RAM total

**Cluster-Wide Prometheus**:
- Single pod (or 2 for HA)
- Resource usage scales with number of HCP namespaces and metrics
- **Test environment** (3 clusters): ~40m CPU, ~280Mi RAM actual
- **Production estimate** (100 clusters): 1000m-4000m CPU, 4-8Gi RAM
- Recommended requests: 1000m CPU, 4Gi RAM (tune based on actual usage)
- Storage: 50Gi PVC recommended for 100 clusters (tune based on metrics cardinality)

### Operational Burden

**GMP PodMonitoring**:
- ✅ No Prometheus to manage
- ✅ No Prometheus Operator to manage
- ❌ Maintain network policy templates in hypershift
- ❌ Maintain custom ClusterRoleBinding
- ❌ Maintain separate configs for GCP vs ROSA/ARO

**Cluster-Wide Prometheus**:
- ❌ Manage Prometheus Operator upgrades
- ❌ Manage Prometheus version updates
- ❌ Monitor Prometheus health and restart if needed
- ✅ Same configs across all clouds
- ✅ Standard deployment pattern

**Both Options**: Use the same Google-provided Prometheus image for GCM export, so export reliability is identical.

### Uptime Responsibility and Support

**GMP PodMonitoring**:
- ✅ **Google manages collector pods**: If they crash, Google fixes them
- ✅ **Google SLA**: Covers managed service availability (pods running)
- ⚠️ **SLA does NOT cover**: Metric delivery if your config is wrong (NetworkPolicies, RBAC, etc.)
- ✅ Google support for GMP collector issues
- Support boundary: GMP collector pods and GCM API

**Cluster-Wide Prometheus**:
- ❌ **You manage Prometheus pods**: If they crash, you fix them
- ✅ **Same GCM export code**: Uses Google-provided Prometheus image (same reliability as Option 1)
- ⚠️ **No SLA on**: Prometheus pod uptime, scraping, or local storage
- ✅ Google support for GCM export issues (same as Option 1)
- Support boundary: Starts at GCM export (after Prometheus)

**Key Insight**: Both options use the **same Google-provided Prometheus image** for GCM export. The difference is **who keeps the pods running**, not the reliability of export to GCM.

---

## Cost Considerations: Metric Volume and Cardinality

### The GMP Pricing Challenge

**Critical**: Google Managed Prometheus charges based on **samples ingested**, not just number of metrics. HyperShift control planes, especially kube-apiserver, generate high-cardinality metrics that can result in significant costs at scale.

### High-Cardinality Metrics in HyperShift

**Example**: `apiserver_request_duration_seconds_bucket`
- Has labels: `verb`, `resource`, `subresource`, `component`, `scope`, `dry_run`
- Has multiple histogram buckets (le="0.1", le="0.2", le="0.5", etc.)
- **Result**: Easily generates thousands of time series per API server

**Scale Impact**:
- 1 HCP namespace: Thousands of time series
- 100 HCP namespaces: **Millions of time series**
- Without filtering: Potentially very high GCM costs

### Cost Optimization Approaches

**Option 1: GMP PodMonitoring**
```yaml
# In PodMonitoring spec
endpoints:
- port: https
  metricRelabeling:
  - sourceLabels: [__name__]
    regex: 'apiserver_request_duration_seconds_bucket|apiserver_request_total'
    action: drop
```

**Pros**:
- ✅ Supported via `metricRelabeling` field in PodMonitoring
- ✅ Applied at collection time (before GCM)

**Cons**:
- ❌ No UI to visualize what you're dropping
- ❌ Harder to test and validate filters
- ❌ Must redeploy PodMonitoring to test changes
- ❌ No way to query dropped metrics locally

**Option 2: Cluster-Wide Prometheus**
```yaml
# In Prometheus CR spec
spec:
  additionalScrapeConfigs:
    metricRelabelConfigs:
    - sourceLabels: [__name__]
      regex: 'apiserver_request_duration_seconds_bucket'
      action: drop
```

**Pros**:
- ✅ **Prometheus UI**: See exactly what metrics exist before filtering
- ✅ **Easy testing**: Query metrics locally to understand cardinality
- ✅ **Iterative optimization**: Test filters without affecting GCM
- ✅ **Debug capability**: If you accidentally drop needed metrics, you can query local storage
- ✅ **Standard Prometheus**: Well-documented relabeling syntax

**Cons**:
- ❌ Requires managing Prometheus configuration

### Cost Optimization Workflow Comparison

**GMP PodMonitoring Workflow**:
1. Deploy PodMonitoring (metrics go to GCM immediately)
2. Check GCM bill / sample count
3. Guess which metrics to drop
4. Update PodMonitoring metricRelabeling
5. Redeploy and wait
6. Check GCM bill again
7. Repeat until costs acceptable

**Cluster-Wide Prometheus Workflow**:
1. Deploy Prometheus (metrics visible in UI)
2. Query Prometheus UI to see top cardinality metrics
3. Use `topk()` queries to identify expensive metrics
4. Test metricRelabelConfigs locally
5. Verify in Prometheus UI that correct metrics are dropped
6. Once satisfied, metrics export to GCM
7. Monitor GCM costs and adjust as needed

### Example: Identifying High-Cardinality Metrics

With Cluster-Wide Prometheus, you can run queries like:

```promql
# Find metrics with most time series
topk(10, count by (__name__)({__name__=~".+"}))

# Estimate sample rate per metric
topk(10, rate({__name__=~".+"}[5m]))

# Find high-cardinality labels
count by (resource, verb)(apiserver_request_duration_seconds_bucket)
```

With GMP PodMonitoring, you must rely on GCM queries which:
- May have sampling applied
- Incur query costs
- Don't show what was dropped

### Recommended Metrics to Consider Dropping

Based on HyperShift experience, consider dropping or sampling:

```yaml
metricRelabelConfigs:
# Drop high-cardinality histogram buckets
- sourceLabels: [__name__]
  regex: '.*_bucket'
  action: drop

# Keep only summary quantiles, drop histograms
- sourceLabels: [__name__]
  regex: 'apiserver_request_duration_seconds_bucket'
  action: drop

# Drop verbose workqueue metrics
- sourceLabels: [__name__]
  regex: 'workqueue_.*'
  action: drop

# Keep specific metrics you need for alerts/dashboards
- sourceLabels: [__name__]
  regex: 'up|kube_.*_status_.*'
  action: keep
```

### Cost Impact at Scale

**Without Filtering** (100 clusters):
- Estimated samples/sec: ~500,000 - 2,000,000
- Monthly GMP cost: Potentially $$$$ (varies by region/volume)

**With Aggressive Filtering** (100 clusters):
- Estimated samples/sec: ~50,000 - 200,000 (90% reduction possible)
- Monthly GMP cost: Significantly reduced

**Note**: Actual costs depend on your specific metrics, cardinality, and GCP pricing tier.

### Recommendation

For production deployments monitoring 100+ clusters:
1. **Start with Cluster-Wide Prometheus** to understand your metric landscape
2. Use Prometheus UI to identify high-cardinality metrics
3. Iteratively develop and test metric filters
4. Monitor GCM costs and adjust filters as needed
5. Consider whether you need all histogram buckets or if summaries suffice

The cost savings from effective metric filtering can easily offset the operational overhead of managing Prometheus.

---

## Implementation Details

### Option 1: GMP PodMonitoring Implementation

#### Step 1: Add ClusterRoleBinding

```bash
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: gmp-collector-secret-access
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: gmp-collector-secret-access
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: gmp-collector-secret-access
subjects:
- kind: ServiceAccount
  name: collector
  namespace: gke-gmp-system
EOF
```

#### Step 2: Update NetworkPolicy Template (in hypershift repo)

Modify the `openshift-monitoring` NetworkPolicy template to allow `gke-gmp-system`:

```yaml
spec:
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          network.openshift.io/policy-group: monitoring
    # Add this to allow GMP collectors
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: gke-gmp-system
```

#### Step 3: Convert Monitoring Resources

Example ServiceMonitor → PodMonitoring conversion:

**Before (ServiceMonitor)**:
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: kube-apiserver
  namespace: clusters-xxx-test-hc-2
spec:
  selector:
    matchLabels:
      app: kube-apiserver
  endpoints:
  - port: https
    scheme: https
    tlsConfig:
      ca:
        configMap:
          name: root-ca
          key: ca.crt
      cert:
        secret:
          name: metrics-client
          key: tls.crt
      keySecret:
        name: metrics-client
        key: tls.key
```

**After (PodMonitoring)**:
```yaml
apiVersion: monitoring.googleapis.com/v1
kind: PodMonitoring
metadata:
  name: kube-apiserver
  namespace: clusters-xxx-test-hc-2
spec:
  selector:
    matchLabels:
      app: kube-apiserver
  endpoints:
  - port: https
    scheme: https
    interval: 30s
    tls:
      ca:
        secret:
          name: root-ca
          key: ca.crt
      cert:
        secret:
          name: metrics-client
          key: tls.crt
      key:
        secret:
          name: metrics-client
          key: tls.key
```

### Option 2: Cluster-Wide Prometheus Implementation

#### Step 1: Create GCP Service Account

```bash
PROJECT_ID="your-project-id"

gcloud iam service-accounts create prometheus-agent-hcp \
  --project="${PROJECT_ID}" \
  --display-name="Prometheus for HCP Monitoring"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:prometheus-agent-hcp@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/monitoring.metricWriter"
```

#### Step 2: Create Namespace with Label

```bash
kubectl create namespace openshift-monitoring

# CRITICAL: Add label for network policy compliance
kubectl label namespace openshift-monitoring \
  network.openshift.io/policy-group=monitoring
```

#### Step 3: Deploy Prometheus

Edit `prometheus-cluster-wide.yaml` to set your project details, then:

```bash
kubectl apply -f prometheus-cluster-wide.yaml
```

#### Step 4: Create Workload Identity Binding

```bash
gcloud iam service-accounts add-iam-policy-binding \
  prometheus-agent-hcp@${PROJECT_ID}.iam.gserviceaccount.com \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:${PROJECT_ID}.svc.id.goog[openshift-monitoring/prometheus-cluster-wide]"
```

#### Step 5: Verify

```bash
kubectl get prometheus -n openshift-monitoring
kubectl get pods -n openshift-monitoring
kubectl get servicemonitors,podmonitors -A
```

---

## Technical Deep Dive

### Why Recording Rules Require Special Consideration

HyperShift uses PrometheusRules for recording rules, which pre-compute expensive queries. Recording rules require:
- **Local storage** (TSDB) to store time-series data
- **Query engine** to evaluate expressions over time windows

**GMP PodMonitoring**: Uses Rules CRD evaluated by Google's backend (different syntax/capabilities)

**Cluster-Wide Prometheus**: Uses standard PrometheusRules evaluated locally (same as ROSA/ARO)

### Network Policy Architecture

HCP namespaces include a NetworkPolicy named `openshift-monitoring`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: openshift-monitoring
  namespace: clusters-xxx-test-hc-2
spec:
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          network.openshift.io/policy-group: monitoring
  podSelector: {}
```

This policy:
- Blocks all ingress except from namespaces with specific label
- Protects HCP control plane components
- Standard across all HCP deployments

**GMP collectors** run in `gke-gmp-system` (GKE-managed, cannot add label)
**Prometheus** runs in `openshift-monitoring` (user-managed, can add label)

### Google's GMP-Enabled Prometheus Image

`gke.gcr.io/prometheus-engine/prometheus:v2.53.5-gmp.1-gke.2` includes:
- Built-in GCM exporter (NOT standard `remoteWrite`)
- Automatic metric export to Cloud Monitoring
- Workload Identity authentication

**Important**: Do NOT configure `remoteWrite` - the GCM exporter is built-in.

---

## Testing Results

Both approaches have been validated in test environment:

**Test Cluster**: 3 HCP namespaces
**Monitoring Resources Per Namespace**: ~14 ServiceMonitors/PodMonitors, ~1-2 PrometheusRules
**Total Test Resources**: 42 ServiceMonitors/PodMonitors, 4 PrometheusRules (across 3 namespaces)
**Production Scale**: For 100 clusters, expect ~4,200 monitors and ~400 rules
**Test Duration**: Multiple days

### GMP PodMonitoring Test Results

- ✅ PodMonitoring CRD accepted by GMP
- ✅ Secret access works after ClusterRoleBinding
- ✅ Metrics collected successfully after network policy changes
- ✅ Exports to GCM working

### Cluster-Wide Prometheus Test Results

- ✅ All ServiceMonitors/PodMonitors auto-discovered
- ✅ All PrometheusRules auto-evaluated
- ✅ Metrics exported to GCM
- ✅ Resource usage (test): ~40m CPU, ~280Mi RAM (3 clusters)

**Note**: Production with ~100 clusters will require significantly more resources (estimated 500m-2000m CPU, 2-8Gi RAM). Resource requests should be tuned based on actual production metrics volume.

---

## Decision Criteria

Consider these factors for your team discussion:

### Favor GMP PodMonitoring If:
- Avoiding infrastructure management is highest priority
- **Want Google to manage collector pod uptime** (not you)
- Team has capacity for migration effort (~4,200 monitors + ~400 rules for 100 clusters)
- Willing to maintain divergent configs for GCP vs ROSA/ARO
- Comfortable with network policy security boundary changes
- Acceptable to optimize costs via trial-and-error in GCM

**Note**: Google's SLA covers the managed service (pods running), not metric delivery if your NetworkPolicies/RBAC are misconfigured.

### Favor Cluster-Wide Prometheus If:
- Minimizing migration effort is highest priority
- Cross-cloud consistency is important
- Prefer not to change network policies
- Team comfortable managing Prometheus infrastructure
- Want standard Prometheus capabilities (UI, query engine, etc.)
- **Need cost optimization**: Easier to identify and filter high-cardinality metrics
- Want to iteratively test metric filters before they hit GCM
- Value visibility into what metrics are being collected/dropped

---

## Next Steps

1. **Review this comparison** with your team
2. **Discuss trade-offs** based on your priorities
3. **Decide on approach** based on team consensus
4. **Implement chosen solution** following guides above

---

## Files

- `README.md` - This comparison document
- `gmp-podmonitoring-example.yaml` - Example resources for Option 1 (GMP PodMonitoring)
- `prometheus-cluster-wide.yaml` - Deployment manifest for Option 2 (Cluster-Wide Prometheus)

---

## References

- [Google Managed Prometheus Documentation](https://cloud.google.com/stackdriver/docs/managed-prometheus)
- [Prometheus Operator Documentation](https://prometheus-operator.dev/)
- [GKE Workload Identity](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity)
- [Kubernetes Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)

---

**Document Status**: Ready for team review
**Last Updated**: 2026-02-04
**Testing**: Both approaches validated in test environment
