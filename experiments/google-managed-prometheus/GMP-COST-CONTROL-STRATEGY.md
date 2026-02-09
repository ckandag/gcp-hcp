# GMP Cost Control Strategy: Prometheus-Level Metric Filtering

## Overview

This document describes the recommended approach for controlling Google Managed Prometheus (GMP) costs when using self-managed Prometheus with GCM export (Google's Prometheus fork with built-in GCM exporter).

**Architecture**: Collect all metrics locally in Prometheus, but only export a filtered subset to GMP for long-term storage.

## The Problem

Without filtering, exporting all HCP metrics to GMP results in high costs

## The Solution: Two-Tier Collection Strategy

### Tier 1: Local Prometheus (Collect Everything)
- Ingest all metrics from ServiceMonitors/PodMonitors
- Store locally with short retention (6-24 hours)
- Use for:
  - Ad-hoc debugging queries
  - Incident response
  - Recording rule evaluation

### Tier 2: GMP Export (Filtered Subset)
- Export only essential metrics to GMP
- Long-term retention
- Use for:
  - Historical analysis
  - Long-term trending
  - Compliance/audit requirements
  - Cross-cluster aggregation
- Alerting
- Dashboarding

## Recommended Architecture

```
┌─────────────────────────────────────────────┐
│  HCP Namespaces (ServiceMonitors/PodMonitors) │
└──────────────────┬──────────────────────────┘
                   │ (all metrics)
                   ▼
┌─────────────────────────────────────────────┐
│         Local Prometheus                     │
│  - Collects ALL metrics                     │
│  - 6-24h retention                          │
│  - Evaluates recording rules               │
└──────────────────┬──────────────────────────┘
                   │ (filtered via metric_relabel_configs)
                   ▼
┌─────────────────────────────────────────────┐
│    GMP / Google Cloud Monitoring            │
│  - Only ALLOWLISTED metrics                │
│  - 24 month retention                       │
│  - Reduced cost (50-80% savings)           │
└─────────────────────────────────────────────┘
```

## Implementation Approach: additionalScrapeConfigs (Recommended)

**Prometheus CR Configuration:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: cluster-wide
  namespace: openshift-monitoring
spec:
  # Use Google's Prometheus image with built-in GCM exporter
  image: gke.gcr.io/prometheus-engine/prometheus:v2.53.5-gmp.1-gke.2
  version: v2.53.5-gmp.1-gke.2

  # Collect ALL ServiceMonitors/PodMonitors
  serviceMonitorSelector: {}
  podMonitorSelector: {}

  # Short local retention for cost efficiency
  retention: 24h

  # External labels for GCM
  externalLabels:
    cluster: "your-cluster-name"
    region: "us-central1"

  # Reference ConfigMap with GCM export filter
  additionalScrapeConfigs:
    name: gcm-export-filter
    key: filter.yaml
```

**ConfigMap with Allowlist Filter:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: gcm-export-filter
  namespace: openshift-monitoring
data:
  filter.yaml: |
    # Global metric relabeling for GCM export
    metric_relabel_configs:
      # ALLOWLIST: Only export these critical metrics to GCM
      - source_labels: [__name__]
        regex: '(up|apiserver_request_total|apiserver_request_duration_seconds_sum|apiserver_request_duration_seconds_count|apiserver_current_inflight_requests|etcd_server_has_leader|etcd_disk_wal_fsync_duration_seconds_sum|etcd_disk_wal_fsync_duration_seconds_count|kube_pod_status_phase|kube_deployment_status_replicas|kube_deployment_status_replicas_available|cluster_operator_up|sre:.*)'
        action: keep

      # Drop all other metrics from GCM export
      - action: drop
```

## Sample Allowlist: Essential HCP Metrics

Based on ROSA filtering and common HCP monitoring requirements:

```yaml
# Core health/availability
- up
- cluster_operator_up
- sre:hcp_servicemonitor_up:sum

# API Server
- apiserver_request_total
- apiserver_request_duration_seconds_sum
- apiserver_request_duration_seconds_count
- apiserver_current_inflight_requests
- apiserver_storage_objects

# etcd
- etcd_server_has_leader
- etcd_disk_wal_fsync_duration_seconds_sum
- etcd_disk_wal_fsync_duration_seconds_count

# Kubernetes state
- kube_pod_status_phase
- kube_deployment_status_replicas
- kube_deployment_status_replicas_available
- kube_node_status_condition

# Recording rules (if using)
- sre:.*
- hcp:.*
```

**Key principle**: Export counters and sums (for rate/average calculations), but drop high-cardinality histograms and detailed breakdowns.

## Why NOT Filter at ServiceMonitor/PodMonitor Level?

**If you configure filtering in ServiceMonitors/PodMonitors:**

❌ **Cons:**
- Metrics are never collected - lose local visibility
- Can't query dropped metrics in Prometheus UI for debugging
- Can't use dropped metrics in recording rules
- Must update each ServiceMonitor/PodMonitor individually to change allowlist
- Harder to troubleshoot incidents (metrics permanently lost)

✅ **Prometheus-level filtering advantages:**
- All metrics available locally for debugging/dashboards
- Single centralized allowlist configuration
- Easy to adjust export filter without touching monitors
- Can temporarily disable filter for deep troubleshooting
- Recording rules can use full metric set

## Verification Steps

After implementing Prometheus-level filtering:

### 1. Verify Local Collection (Should Have Everything)

```bash
# Port-forward to Prometheus
kubectl port-forward -n openshift-monitoring prometheus-cluster-wide-0 9090:9090

# Query total metric cardinality locally
# Should see ALL metrics from ServiceMonitors
curl -s http://localhost:9090/api/v1/query?query='count({__name__=~".%2B"})' | jq

# Expected: ~169,000+ time series (unfiltered)
```

### 2. Verify GCM Export (Should Be Filtered)

```bash
# Query GCM via API
gcloud monitoring time-series list \
  --filter='metric.type=starts_with("prometheus.googleapis.com/")' \
  --project=YOUR-PROJECT-ID

# Or use Google Cloud Console: Metrics Explorer
# Expected: Only allowlisted metrics appear
```

### 3. Monitor GMP Costs

```bash
# Check GMP sample ingestion in Cloud Console
# Navigate to: Cloud Monitoring > Metrics Management > Prometheus

# Verify sample count matches filtered estimate (~97B vs 484B)
# Verify cost is proportional to filtered sample count
```

### 4. Test Grafana Dashboards

```bash
# Ensure Grafana can still query all metrics from local Prometheus
# Point Grafana datasource to: http://prometheus-cluster-wide:9090

# Dashboards should work normally (querying local Prometheus)
# Only GCM export is filtered, not local queries
```

## Important: Google Prometheus Fork Behavior

**CRITICAL**: You must verify how Google's Prometheus fork with built-in GCM exporter handles filtering.

### Questions to Test:

1. **Does `metric_relabel_configs` apply to GCM export?**
   - Standard Prometheus: Yes, affects all remote_write
   - Google fork: May have custom GCM exporter that bypasses this

2. **Does the built-in GCM exporter use `remoteWrite` config?**
   - If yes: Use `writeRelabelConfigs` as shown above
   - If no: May need Google-specific configuration

3. **Are there Google-specific flags or config options?**
   - Check: `--export.label.filter` or similar flags
   - Check: Environment variables for GCM exporter behavior

### Testing Plan:

```yaml
# Step 1: Deploy with allowlist configured
# Step 2: Collect metrics for 1 hour
# Step 3: Query local Prometheus (should have all metrics)
# Step 4: Query GCM (should have only filtered metrics)
# Step 5: Check GMP billing (should show reduced sample count)

# If filtering doesn't work:
# - Check Prometheus logs for GCM exporter config
# - Review Google's Prometheus fork documentation
# - May need to use PodMonitor/ServiceMonitor filtering as fallback
```

## Fallback: If Prometheus-Level Filtering Doesn't Work

If Google's Prometheus fork doesn't support filtering at the Prometheus level, fallback options:

### Option 1: Duplicate ServiceMonitors

Create two sets of monitors:
- **Full monitors**: Collect all metrics locally
- **GCM monitors**: Collect only allowlisted metrics, with annotation to export to GCM

### Option 2: Sidecar Filter Proxy

Deploy a filtering proxy between Prometheus and GCM:
- Prometheus exports all metrics to proxy
- Proxy filters and forwards to GCM
- More complex but maintains local/export separation

### Option 3: PodMonitor/ServiceMonitor Filtering (Last Resort)

Accept the limitation and filter at collection time:
- Lose local visibility for non-essential metrics
- Simpler configuration
- Lower local storage requirements

## Recommended Allowlist Strategy

### Phase 1: Start Conservative (Export More)

```yaml
# Allow broad categories initially
regex: '(up|apiserver_.*|etcd_.*|kube_.*|cluster_operator_.*|sre:.*)'
```

- Gives you safety net during migration
- Can identify which metrics are actually needed
- Gradually tighten allowlist over time

### Phase 2: Analyze Usage and Tighten

After 30 days:
1. Query GCM to see which metrics are actually used in dashboards/alerts
2. Identify unused metrics being exported
3. Tighten allowlist to remove unused metrics
4. Monitor cost reduction

### Phase 3: Optimize with Recording Rules

Create recording rules for common aggregations:
```yaml
# Instead of exporting high-cardinality raw metrics:
# apiserver_request_duration_seconds_bucket (10,000+ series)

# Export pre-aggregated recording rule:
# hcp:apiserver_request_duration:avg (1 series per HCP)
```

## Monitoring and Alerting

### Alerts for Export Health

```yaml
# Alert if GCM export is failing
- alert: GCMExportFailing
  expr: up{job="prometheus-self"} == 1 AND prometheus_remote_storage_samples_failed_total > 0
  for: 5m

# Alert if export is significantly behind
- alert: GCMExportLagging
  expr: prometheus_remote_storage_highest_timestamp_in_seconds - time() > 300
  for: 10m
```

### Cost Monitoring Alerts

```yaml
# Alert if GMP sample ingestion spikes unexpectedly
# (Monitor via GCP Cloud Monitoring metrics)
- alert: GMPCostSpike
  expr: gmp_samples_ingested_daily > 20e9
  for: 1h
```

## Cost Control Checklist

- [ ] Implement Prometheus-level allowlist filtering
- [ ] Verify local Prometheus has all metrics
- [ ] Verify GCM only receives filtered metrics
- [ ] Monitor GMP costs for first month
- [ ] Set up GCP budget alerts at $60K/month threshold
- [ ] Document allowlist rationale for team
- [ ] Create recording rules for common aggregations
- [ ] Establish process for allowlist updates
- [ ] Test that Grafana dashboards still work (querying local Prometheus)
- [ ] Verify alerting works (consider if alerts need GCM or can use local)

## Next Steps

1. **Test Google Prometheus fork behavior** with metric filtering
2. **Define initial allowlist** based on critical monitoring needs
3. **Deploy in development environment** and validate filtering works
4. **Monitor costs** for 1 month in development
5. **Refine allowlist** based on actual usage patterns
6. **Roll out to production** with proven configuration
7. **Iterate on allowlist** to optimize costs further

---

**Document Version**: 1.0
**Last Updated**: 2026-02-05
**Key Assumption**: Google's Prometheus fork respects standard metric_relabel_configs or remoteWrite writeRelabelConfigs for GCM export filtering
