# GCP-Native Data Lake for AI Diagnostics and Compliance Audit Logs

***Scope***: GCP-HCP

**Date**: 2026-04-06

## Decision

Use a two-tier GCP-native data lake architecture: BigQuery for streaming AI diagnostic findings (small volume, actively queried) and GCS for compliance audit logs (high volume, rarely queried) with BigQuery external tables for ad-hoc access. The diagnose-agent uses Google's managed BigQuery MCP server to query its own diagnostic history before investigating new alerts, creating a feedback loop that improves diagnosis quality over time. Two reusable Terraform child modules (`data-lake` and `data-lake-sink`) provide the infrastructure, deployed per region with sinks per source project.

## Context

### Problem Statement

The GCP HCP platform generates three categories of operational data with no durable, queryable persistence:

1. **AI diagnostic findings are discarded after routing.** The Cloud Run diagnose-agent processes Prometheus alerts via Pub/Sub and routes analysis to PagerDuty, but the findings themselves (root cause analysis, confidence scores, evidence, recommendations) are lost. There is no historical record of what the AI diagnosed, making it impossible to detect recurring patterns, enrich future diagnoses with prior context, or provide SREs with a per-cluster diagnostic timeline.

2. **E2E test logs are destroyed with ephemeral projects.** Integration test pipelines create temporary GCP projects that are torn down after each run, permanently destroying all operational logs and diagnostic history.

3. **Audit logs lack long-term queryable retention.** GKE audit logs and policy denied events are available in Cloud Logging with limited retention (30 days for Data Access, 400 days for Admin Activity). Future compliance certifications (ISO 27001, SOC 2 Type II) require durable, queryable audit log retention with controlled access. Establishing this pattern now positions the platform for certification readiness.

All three use cases share a common architectural pattern: route logs from source projects to a centralized, queryable data store.

### Constraints

- **Sovereignty**: Per-region data storage — no cross-region data movement. Each region project hosts its own data lake.
- **Cost**: Audit log volume can reach 10-50 GiB/day/cluster unfiltered. Tight inclusion filters and cost-efficient storage tiers are essential.
- **Schema-on-first-write**: Cloud Logging determines BigQuery table schema from the first log entry. Type mismatches silently route to error tables. The diagnostic agent's Pydantic schema must be locked before the first write.
- **Existing patterns**: Infrastructure modules must follow the established child module pattern (similar to the `workflows` module).
- **Automation tooling**: All infrastructure must be expressible as Terraform, deployable via Atlantis. No manual `gcloud` commands or shell scripts in the provisioning path.
- **Compliance readiness**: Audit log retention and access patterns should support future ISO 27001 (A.12.4) and SOC 2 Type II (CC6, CC7, CC8) certification requirements without re-architecture.

### Assumptions

- The diagnose-agent will continue running on Cloud Run, emitting structured JSON to stdout (captured by Cloud Logging automatically).
- Admin Activity and System Event audit logs will remain free in Cloud Logging's `_Required` bucket with 400-day retention — no need to duplicate them to GCS.
- Policy Denied audit logs (stored in `_Default` bucket with 30-day retention) are the only audit log type requiring GCS archival for compliance.
- Per-region datasets are sufficient; cross-region federated queries are not required.
- Production deployment will eventually move audit log storage to a dedicated, locked-down GCP project with restricted IAM. The module design must support configurable destination projects.

## Alternatives Considered

1. **BigQuery streaming for all log types (diagnostic findings + audit logs)**: Route everything to BigQuery via Cloud Logging sinks with `use_partitioned_tables = true`. Single destination, uniform query surface.

2. **GCS for all log types with BigQuery external tables**: Route everything to GCS buckets with lifecycle policies. Create BigQuery external tables for ad-hoc querying. Cheapest storage, but higher query latency and no streaming capability.

3. **Two-tier: BigQuery streaming for diagnostics + GCS for audit logs (chosen)**: Route diagnostic findings to BigQuery (small volume, frequent queries, real-time visibility) and audit logs to GCS (high volume, compliance retention, rare queries) with BigQuery external tables for ad-hoc access.

4. **Cloud Logging Log Analytics linked datasets**: Use Cloud Logging's built-in BigQuery integration. Zero configuration — just enable Log Analytics on the log bucket.

5. **Third-party solutions (Datadog, Splunk, Elastic)**: External log aggregation and analysis platforms.

## Decision Rationale

### Justification

The two-tier approach optimizes for the different access patterns and cost profiles of diagnostic findings vs audit logs:

- **Diagnostic findings** are small (KB per finding), queried frequently (SRE investigations, AI enrichment, trend analysis), and need real-time visibility. BigQuery streaming is ideal — near-instant query availability at negligible cost for this volume.

- **Audit logs** are high volume (potentially GiB/day/cluster), queried rarely (compliance audits, security investigations), and primarily need durable retention. GCS is 5-10x cheaper than BigQuery for storage, with lifecycle policies that automatically transition to Nearline (90 days) and Archive (365 days) storage classes.

BigQuery external tables bridge the gap — audit logs in GCS are queryable via standard SQL with zero data duplication. The external tables cost nothing until queried, and when queried, only scan the relevant files.

### Evidence

Spike validation ([GCP-497](https://redhat.atlassian.net/browse/GCP-497)) confirmed:

- End-to-end flow validated: Cloud Monitoring alert → Pub/Sub → Eventarc → Cloud Run diagnose-agent → structured JSON stdout → Cloud Logging → Sink → BigQuery table → SQL query returns results
- Diagnostic findings arrive in BigQuery within 1-2 minutes of the agent emitting them
- Cloud Logging sinks to GCS deliver in hourly batches (up to 3 hours for first batch)
- GCS lifecycle policies (Standard → Nearline → Archive → Delete) work correctly with Cloud Logging sink output
- BigQuery external tables successfully read Cloud Logging JSON files from GCS with explicit schema (required to skip fields with invalid column name characters like `@type` and `k8s.io/`)
- BigQuery views provide a clean query surface that flattens `jsonPayload.*` fields — users query `SELECT * FROM view_recent_findings` without needing to know the Cloud Logging envelope schema
- Admin Activity and System Event logs are free in Cloud Logging's `_Required` bucket (400-day retention) — sinking them to GCS wastes ~$1,500/month per 100 clusters
- `require_partition_filter` is NOT inherited by sink-auto-created tables. The Terraform-managed `diagnostic_findings_table` variable allows views to reference a stable table name, and `default_table_expiration_ms` on the dataset provides cost protection
- Pydantic schema validation (`DiagnosticFinding` model) ensures type consistency before the first write to BigQuery, preventing silent schema-on-first-write errors

### Comparison

**Alternative 1 (BigQuery for everything)** was rejected because:
- Audit log volume at scale (10-50 GiB/day/cluster) makes BigQuery streaming ingestion expensive ($0.05/GiB)
- Audit logs are rarely queried — paying for BigQuery active storage ($0.02/GiB/month) when GCS Archive is $0.0012/GiB/month wastes 94% of the storage budget
- At 200 clusters: ~$5,800/month (BigQuery) vs ~$281/month (GCS with lifecycle)

**Alternative 4 (Log Analytics)** was rejected because:
- Log Analytics linked datasets are read-only — no DML, no clustering, no views
- Cannot create external tables or materialized views
- Limited SQL dialect compared to standard BigQuery
- No partition filter enforcement

**Alternative 5 (Third-party)** was rejected because:
- Adds external dependency and vendor lock-in
- Requires data egress from GCP (cost and sovereignty concerns)
- GCP-native solution aligns with the platform's observability stack (GMP, Cloud Monitoring, Cloud Logging)

## Consequences

### Positive

- **Cost-optimized storage**: Diagnostic findings in BigQuery (pennies/month at expected volume), audit logs in GCS with automatic tiering (Standard → Nearline → Archive) — 94% cheaper than all-BigQuery at scale
- **Unified query surface**: BigQuery SQL for both data tiers — native tables for diagnostics, external tables for audit logs. Views flatten the Cloud Logging envelope schema for ease of use
- **Compliance-ready**: GCS bucket with versioning, public access prevention, and configurable retention (default 365 days) meets ISO 27001 and SOC 2 audit log retention requirements. Destination project is configurable for future migration to a dedicated compliance project
- **Reusable modules**: `data-lake` (dataset + bucket + external tables + views) and `data-lake-sink` (configurable sink supporting BigQuery or GCS destinations) follow the established child module pattern and can be composed flexibly
- **AI enrichment via MCP**: The diagnose-agent connects to Google's managed BigQuery MCP server to query a cluster's prior diagnostic history before investigating new alerts. This creates a feedback loop — the agent references prior root causes, detects recurring patterns, and escalates systemic issues instead of repeating point remediations. Validated end-to-end: agent queries history, finds prior PVC alerts, and incorporates that context into current etcd diagnosis.
- **Extensible MCP pattern**: The MCP client bridge (`McpToolRegistry`) is generic — any MCP server can be registered with a prefix. Future integrations (Cloud Logging MCP, custom MCPs) follow the same pattern with no agent code changes.
- **SRE investigation**: Per-cluster diagnostic timeline available via `view_recent_findings` with `WHERE cluster_id = '...'`
- **No infrastructure to manage**: Cloud Logging handles sink routing, BigQuery handles query execution, GCS handles storage lifecycle — no ETL pipelines, no Dataflow, no custom code

### Negative

- **Two-phase external table deployment**: BigQuery external tables require data in GCS before they can be created with autodetect. The `enable_audit_external_tables` flag gates creation — operators must set it to `true` after audit sinks deliver their first batch (up to 3 hours). This adds operational friction to initial deployment.
- **Explicit audit schema maintenance**: The external table schema must be maintained manually in Terraform (JSON) because Cloud Audit Log entries contain fields with characters invalid in BigQuery column names (`@type`, `authorization.k8s.io/`). If Google adds important new fields to the audit log format, the schema must be updated manually. The `ignore_unknown_values = true` setting prevents breakage but silently drops unrecognized fields.
- **Sink-auto-created table name fragility**: The diagnostic findings table is auto-created by Cloud Logging with a name derived from the log source (e.g., `run_googleapis_com_stdout` for Cloud Run stdout). If the agent moves to a different execution environment, the table name changes. The `diagnostic_findings_table` variable mitigates this but doesn't eliminate the coupling.
- **No real-time audit log queries**: GCS sink delivery is batched (hourly). Audit logs are not queryable in BigQuery until the next batch arrives. For real-time audit queries, use Cloud Logging directly.
- **Cross-project IAM complexity**: Sinks use `unique_writer_identity = true` which creates per-sink service accounts that need cross-project IAM grants (BigQuery dataEditor or GCS objectCreator) on the destination. This is correct but adds IAM resources to track.

## Cross-Cutting Concerns

### Reliability

* **Sink delivery guarantees**: Cloud Logging sinks provide at-least-once delivery. BigQuery streaming sinks deliver within minutes. GCS sinks deliver in hourly batches. Both handle transient failures with built-in retry.
* **Sink health monitoring**: The `data-lake-sink` module does not include per-sink error alerts (removed during review — the sink_stopped alert was a false positive on idle periods). Sink health should be monitored via Cloud Monitoring's `logging.googleapis.com/exports/error_count` metric at the project level.
* **Schema evolution**: The diagnostic agent uses a versioned Pydantic schema (`schema_version` field). New fields are additive and safe — BigQuery auto-extends the schema on new columns. Type changes or renames require a schema version bump and migration plan. The `evidence` field is serialized as a JSON string to avoid repeated field schema complexity.

### Security

* **Encryption at rest**: For the spike, Google-managed encryption is used. Production deployment MUST add CMEK (Customer-Managed Encryption Keys) to both the GCS bucket (`encryption` block) and BigQuery dataset (`default_encryption_configuration`).
* **Public access prevention**: GCS bucket enforces `public_access_prevention = "enforced"` and `uniform_bucket_level_access = true`.
* **Bucket versioning**: Enabled for audit log immutability — prevents accidental overwrites or deletes.
* **IAM least privilege**: Sink writer identities get only the minimum required role (BigQuery `dataEditor` or GCS `objectCreator`). Atlantis service account uses `bigquery.admin` (should be narrowed to `dataOwner` + `jobUser` for production).
* **MCP security**: The MCP client uses Application Default Credentials with `bigquery.readonly` scope (read-only). Access tokens are cached with thread-safe refresh. Error messages are sanitized to strip project IDs and service account emails before returning to the model. The `DATA_LAKE_PROJECT_ID` env var is validated against GCP project ID format regex before prompt injection.
* **SQL injection prevention**: Alert payload fields (cluster_id, namespace, region) are validated against strict format regexes (UUID, k8s namespace, GCP region) before the model constructs SQL queries. SQL metacharacters (`;`, `'`, `"`, `\`) are stripped.
* **Future: Dedicated compliance project**: Production audit logs should eventually move to a dedicated GCP project with restricted IAM (security team access only), VPC Service Controls, and locked retention policies. The module's configurable destination project supports this migration path.

### Cost

**Estimated monthly costs (Policy Denied logs only, on-demand BigQuery pricing):**

| Component | 10 Clusters | 50 Clusters | 200 Clusters |
|-----------|-------------|-------------|--------------|
| BigQuery streaming (diagnostics) | $0.02 | $0.08 | $0.30 |
| BigQuery storage (diagnostics) | $0.02 | $0.09 | $0.36 |
| BigQuery queries (on-demand) | FREE (<1 TB) | FREE (<1 TB) | $0.01 |
| GCS storage (audit, tiered) | $14 | $70 | $270 |
| **Total** | **~$14** | **~$70** | **~$281** |

**Key cost decisions:**
- Admin Activity and System Event logs are NOT sunk to GCS — they're free in Cloud Logging for 400 days. This saves ~$1,500/month per 100 clusters.
- GCS lifecycle automatically transitions to cheaper tiers: Standard ($0.020/GiB) → Nearline ($0.010/GiB at 90 days) → Archive ($0.0012/GiB at 365 days).
- Default retention is 365 days (compliance minimum). Configurable up to 10 years.
- BigQuery storage alert (configurable threshold, default 10 GiB) and GCS storage alert provide bill shock protection.
- Filter validation on the sink module (minimum 10 characters) prevents accidental empty-filter cost explosion.

### Operability

* **Deployment model**: `data-lake` module deploys from the region module (dataset, bucket, external tables, views, alerts). `data-lake-sink` module deploys per source project from the caller (dev-all-in-one, region config, or MC config).
* **Two-phase for external tables**: Initial deploy creates bucket and sinks. After audit data arrives (up to 3 hours), set `enable_audit_external_tables = true` and re-apply.
* **BigQuery views**: Four pre-built views (`view_recent_findings`, `view_findings_by_cluster`, `view_repeat_offenders`, `view_daily_summary`) provide immediate value without SQL knowledge.
* **Notebook templates**: Jupyter notebooks for diagnostic findings analysis and audit log investigation are provided for local use (VS Code) with BigQuery Python client.
* **Atlantis compatibility**: All resources are pure Terraform — no shell commands, no local-exec provisioners, no external scripts. Fully compatible with Atlantis and Terraform Cloud.

## Architecture

### Data Flow

```
Source Projects (Region, MC, Global)
    │
    ├── Cloud Run diagnose-agent
    │       │
    │       ├── Step 1: Query history via MCP ──→ BigQuery MCP Server
    │       │     "Has this cluster had this alert before?"    │
    │       │     ◄──── Prior findings ────────────────────────┘
    │       │
    │       ├── Steps 2-N: Investigate cluster via Cloud Workflows
    │       │
    │       └── Structured JSON (stdout) ──→ Cloud Logging
    │                                            │
    │                   ┌────────────────────────┘
    │                   ▼
    │            Log Sink (BigQuery)
    │            filter: jsonPayload.log_type="diagnostic_finding"
    │                   │
    │                   ▼
    │            BigQuery Dataset (data_lake)
    │            ├── run_googleapis_com_stdout (streaming, auto-created)
    │            ├── view_recent_findings
    │            ├── view_findings_by_cluster
    │            ├── view_repeat_offenders
    │            └── view_daily_summary
    │
    ├── GKE / GCP API Operations
    │       │
    │       └── Policy Denied audit logs ──→ Cloud Logging
    │                                            │
    │                   ┌────────────────────────┘
    │                   ▼
    │            Log Sink (GCS)
    │            filter: log_id("cloudaudit.googleapis.com/policy")
    │                   │
    │                   ▼
    │            GCS Bucket (data-lake-audit-{env}-{project})
    │            ├── cloudaudit.googleapis.com/policy/YYYY/MM/DD/*.json
    │            └── Lifecycle: Standard → Nearline (90d) → Archive (365d) → Delete
    │                   │
    │                   ▼
    │            BigQuery External Table (audit_policy_denied)
    │            └── Reads GCS files on-demand, zero storage cost
    │
    └── Admin Activity / System Event logs
            │
            └── FREE in Cloud Logging _Required bucket (400-day retention)
                └── Query via: gcloud logging read
```

### Module Structure

| Module | Purpose | Deploys From |
|--------|---------|-------------|
| `data-lake` | BigQuery dataset, GCS bucket, external tables, views, alerts | Region module |
| `data-lake-sink` | Configurable log sink (BigQuery or GCS destination) | Caller (dev-all-in-one, region config, MC config) |

### Component Summary

| Component | Resource Type | Managed By | Purpose |
|-----------|-------------|-----------|---------|
| BigQuery dataset | `google_bigquery_dataset` | Terraform (data-lake module) | Houses diagnostic findings and external tables |
| GCS audit bucket | `google_storage_bucket` | Terraform (data-lake module) | Stores Policy Denied audit logs |
| External table | `google_bigquery_table` (external) | Terraform (data-lake module) | Queryable view over GCS audit data |
| BigQuery views | `google_bigquery_table` (view) | Terraform (data-lake module) | Pre-built diagnostic queries |
| Storage alerts | `google_monitoring_alert_policy` | Terraform (data-lake module) | BigQuery and GCS cost guardrails |
| Log sink | `google_logging_project_sink` | Terraform (data-lake-sink module) | Routes logs to BigQuery or GCS |
| Sink IAM | `google_bigquery_dataset_iam_member` / `google_storage_bucket_iam_member` | Terraform (data-lake-sink module) | Cross-project write access for sink identity |
| MCP client bridge | `mcp_client.py` (Python) | Agent code | Connects agent to BigQuery MCP for history queries |
| MCP cross-project IAM | `google_project_iam_member` | Terraform (MC region-iam.tf) | `bigquery.dataViewer`, `bigquery.jobUser`, `mcp.toolUser` for MC agent → region data lake |

## Spike Findings Summary

| Question | Finding |
|----------|---------|
| Native tables vs external tables? | Use both: native for diagnostics (streaming), external for audit logs (GCS) |
| `require_partition_filter` on auto-created tables? | NOT inherited from dataset. Use `default_table_expiration_ms` as cost guard instead |
| `_Default` sink exclusion? | Configurable flag, default off for dev (preserves Logs Explorer), recommend on for production |
| Sink Admin Activity/System Event to GCS? | NO — they're free in Cloud Logging for 400 days. Only sink Policy Denied |
| Schema-on-first-write risk? | Mitigated by Pydantic schema validation in agent code. Schema version field tracks evolution |
| Cost at scale? | ~$281/month at 200 clusters (Policy Denied only). Would be ~$5,800 if sinking free logs |
| External table schema? | Must be explicit (not autodetect) due to `@type` and `k8s.io/` field name characters |
| Two-phase deployment? | Required — external tables gated by `enable_audit_external_tables` flag |
| MCP BigQuery integration? | Google Managed MCP server works for cross-project queries. Requires `roles/mcp.toolUser`, `bigquery.dataViewer`, `bigquery.jobUser` on the data lake project |
| Does the agent use history? | YES — agent queries prior findings as Step 1, references recurring patterns in diagnosis, and escalates systemic issues |
| MCP endpoint URL? | `https://bigquery.googleapis.com/mcp` — project scope determined by auth credentials, not URL |
| SQL injection risk? | Mitigated via UUID validation on cluster_id, namespace regex, SQL metacharacter stripping |

## Next Steps

Implementation will be split into the following PRs, each with a corresponding Jira story under an Epic:

1. **Structured diagnostic logging** (`agent/diagnose/schema.py`): Pydantic schema for `DiagnosticFinding`, emission at all agent exit paths
2. **Data lake Terraform module** (`terraform/modules/data-lake/`): BigQuery dataset, GCS bucket, external tables, views, alerts
3. **Data lake sink Terraform module** (`terraform/modules/data-lake-sink/`): Configurable sink with BigQuery and GCS support, filter validation
4. **Region module integration**: Wire data-lake into region module, Atlantis IAM, variables, outputs
5. **MC module integration**: Cross-project BigQuery/MCP IAM grants, `DATA_LAKE_PROJECT_ID` env var, `agent_image_override` variable
6. **MCP BigQuery integration** (`agent/diagnose/mcp_client.py`): MCP-to-Gemini bridge, `gemini_schema.py` shared module, knowledge docs, investigation strategy updates
7. **Dev-all-in-one integration**: Enable data lake in example config with diagnostic + audit sinks
8. **Production hardening**: CMEK encryption, narrow Atlantis IAM, VPC Service Controls, dedicated compliance project evaluation

---

**Related Documentation:**
- Jira Spike: [GCP-497](https://redhat.atlassian.net/browse/GCP-497) — BigQuery Observability Lake Spike
- Alerting Framework: [integrated-alerting-framework.md](integrated-alerting-framework.md)
- Observability Platform: [observability-google-managed-prometheus.md](observability-google-managed-prometheus.md)
