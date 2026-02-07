# GCP-320 Automated Remediation Platform Implementation Plan

***Scope***: GCP-HCP

**Date**: 2026-02-02

## Overview

This document provides detailed implementation guidance for the Automated Remediation Platform using Google Cloud Workflows. This implements the architectural decisions outlined in the [Cloud Workflows Automation Platform Design Decision](../design-decisions/cloud-workflows-automation-platform.md).

## Implementation Scope

This implementation covers the platform scaffolding required for GCP-320:

**Platform Scaffolding:**
- Terraform module for Cloud Workflows infrastructure
- Debug workflows (get, describe, logs) with optional AI analysis
- CLI wrapper for workflow execution
- Alerting framework integration (Eventarc triggers from GCP-319)
- Vertex AI problem analysis integration
- Compliance audit logging (BigQuery sink)
- Safety controls (PAM approval gates, kill switches, rate limiting)

**Deferred (Requires Failure Scenario Analysis):**
- Specific remediation workflows (ClusterMonitoringErrorBudgetBurn, cordon-drain-node)
- Regional failover workflow
- Q1 demo environment preparation

## Architecture

### Distributed Deployment Model

Cloud Workflows are deployed per-project to maintain regional independence:

```
                        ┌─────────────────────────────────────────┐
                        │              Trigger Sources            │
                        ├─────────────────────────────────────────┤
                        │  ┌─────────┐  ┌─────────┐  ┌─────────┐  │
                        │  │   CLI   │  │Scheduler│  │Eventarc │  │
                        │  │ (Human) │  │ (Cron)  │  │ (Alert) │  │
                        │  └────┬────┘  └────┬────┘  └────┬────┘  │
                        └───────┼────────────┼────────────┼───────┘
                                │            │            │
              ┌─────────────────┼────────────┼────────────┼─────────────────┐
              │                 ▼            ▼            ▼                 │
              │         ┌─────────────────────────────────────┐             │
              │         │       Per-Project Workflows         │             │
              │         ├─────────────────────────────────────┤             │
              │         │                                     │             │
              │         │  ┌─────────┐  ┌─────────┐           │             │
              │         │  │  Debug  │  │ Analyze │  (No PAM) │             │
              │         │  │  (get,  │  │  (AI    │           │             │
              │         │  │  logs)  │  │ triage) │           │             │
              │         │  └────┬────┘  └────┬────┘           │             │
              │         │       │            │                │             │
              │         │  ┌────┴────────────┴────┐           │             │
              │         │  │     PAM Approval     │           │             │
              │         │  │  (Required for all   │           │             │
              │         │  │  destructive actions)│           │             │
              │         │  └──────────┬───────────┘           │             │
              │         │             │                       │             │
              │         │  ┌──────────┴──────────┐            │             │
              │         │  │ Remediate │Failover │            │             │
              │         │  │ (restart, │(cordon, │            │             │
              │         │  │  scale)   │ drain)  │            │             │
              │         │  └─────┬─────┴────┬────┘            │             │
              │         │        │          │                 │             │
              │         │        ▼          ▼                 │             │
              │         │  ┌─────────────────────┐            │             │
              │         │  │     GKE Cluster     │            │             │
              │         │  └─────────────────────┘            │             │
              │         └─────────────────────────────────────┘             │
              │                        Project                              │
              └─────────────────────────────────────────────────────────────┘
```

### Workflow Categories

| Category | Purpose | Operations | Risk Level | PAM Required |
|----------|---------|------------|------------|--------------|
| **Debug** | Investigation without modification | get, describe, logs | Low | No |
| **Analyze** | AI-powered problem analysis | log analysis, root cause identification | Low | No |
| **Remediate** | State modification | restart, scale, patch | Medium-High | **Yes** |
| **Failover** | Regional operations | cordon, drain, failover | High | **Yes** |

### Trigger Methods

| Trigger | Use Case | Implementation |
|---------|----------|----------------|
| **CLI** | Human-triggered debug/remediation | `wf-cli.sh` wrapper |
| **Cloud Scheduler** | Scheduled health checks | Cron-based workflow execution |
| **Eventarc** | Alert-driven automation | GCP-319 alert policies trigger workflows |
| **API** | Integration with external systems | REST API via Cloud Run proxy |

## Component Details

### 1. Terraform Module Structure

**Location:** `terraform/modules/workflows/`

```
terraform/modules/workflows/
├── main.tf                  # Core workflow resources
├── variables.tf             # Input variables
├── outputs.tf               # Module outputs
├── iam.tf                   # Service account and permissions
├── eventarc.tf              # Alert triggers
├── scheduler.tf             # Scheduled execution
├── bigquery.tf              # Audit logging sink
├── workflows/
│   ├── debug-get.yaml       # kubectl get equivalent
│   ├── debug-describe.yaml  # kubectl describe equivalent
│   ├── debug-logs.yaml      # kubectl logs equivalent
│   ├── analyze-logs.yaml    # Vertex AI log analysis
│   ├── dispatcher.yaml      # Routes incoming triggers
│   └── remediate-restart.yaml  # Pod/deployment restart
└── README.md                # Module documentation
```

**Key Resources:**
```hcl
# Workflow service account with GKE access
resource "google_service_account" "workflow_sa" {
  account_id   = "wf-remediation-${var.environment}"
  display_name = "Cloud Workflows Remediation Service Account"
}

# GKE permissions for gke.request connector
resource "google_project_iam_member" "gke_access" {
  project = var.project_id
  role    = "roles/container.developer"
  member  = "serviceAccount:${google_service_account.workflow_sa.email}"
}

# Vertex AI permissions for AI analysis
resource "google_project_iam_member" "vertex_ai" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.workflow_sa.email}"
}

# Workflow deployment
resource "google_workflows_workflow" "debug_get" {
  name            = "debug-get-${var.environment}"
  region          = var.region
  service_account = google_service_account.workflow_sa.id
  source_contents = file("${path.module}/workflows/debug-get.yaml")
}
```

### 2. Debug Workflows

**debug-get.yaml** (kubectl get equivalent):
```yaml
main:
  params: [args]
  steps:
    - init:
        assign:
          - cluster: ${args.cluster}
          - namespace: ${args.namespace}
          - resource_type: ${args.resource_type}
          - resource_name: ${default(args.resource_name, "")}
          - correlation_id: ${sys.get_env("GOOGLE_CLOUD_WORKFLOW_EXECUTION_ID")}

    - validate_inputs:
        switch:
          - condition: ${cluster == "" OR namespace == "" OR resource_type == ""}
            raise: "Missing required parameters: cluster, namespace, resource_type"

    - log_start:
        call: sys.log
        args:
          text: ${"Starting debug-get for " + resource_type + " in " + namespace}
          severity: INFO

    - get_resource:
        call: gke.request
        args:
          project: ${sys.get_env("GOOGLE_CLOUD_PROJECT_ID")}
          cluster: ${cluster}
          location: ${sys.get_env("GOOGLE_CLOUD_LOCATION")}
          method: GET
          path: ${"/api/v1/namespaces/" + namespace + "/" + resource_type + (resource_name != "" ? "/" + resource_name : "")}
        result: api_response

    - log_complete:
        call: sys.log
        args:
          text: ${"Completed debug-get with correlation_id: " + correlation_id}
          severity: INFO

    - return_result:
        return:
          correlation_id: ${correlation_id}
          resource_type: ${resource_type}
          namespace: ${namespace}
          data: ${api_response.body}
```

**debug-logs.yaml** (kubectl logs equivalent with optional AI analysis):
```yaml
main:
  params: [args]
  steps:
    - init:
        assign:
          - cluster: ${args.cluster}
          - namespace: ${args.namespace}
          - pod_name: ${args.pod_name}
          - container: ${default(args.container, "")}
          - tail_lines: ${default(args.tail_lines, 100)}
          - analyze_with_ai: ${default(args.analyze_with_ai, false)}
          - correlation_id: ${sys.get_env("GOOGLE_CLOUD_WORKFLOW_EXECUTION_ID")}

    - get_logs:
        call: gke.request
        args:
          project: ${sys.get_env("GOOGLE_CLOUD_PROJECT_ID")}
          cluster: ${cluster}
          location: ${sys.get_env("GOOGLE_CLOUD_LOCATION")}
          method: GET
          path: ${"/api/v1/namespaces/" + namespace + "/pods/" + pod_name + "/log?tailLines=" + string(tail_lines) + (container != "" ? "&container=" + container : "")}
        result: log_response

    - check_ai_analysis:
        switch:
          - condition: ${analyze_with_ai == true}
            next: analyze_logs
          - condition: ${analyze_with_ai == false}
            next: return_logs_only

    - analyze_logs:
        call: http.post
        args:
          url: ${"https://" + sys.get_env("GOOGLE_CLOUD_LOCATION") + "-aiplatform.googleapis.com/v1/projects/" + sys.get_env("GOOGLE_CLOUD_PROJECT_ID") + "/locations/" + sys.get_env("GOOGLE_CLOUD_LOCATION") + "/publishers/google/models/gemini-1.5-pro:generateContent"}
          auth:
            type: OAuth2
          body:
            contents:
              - role: user
                parts:
                  - text: |
                      Analyze the following Kubernetes pod logs and identify:
                      1. Any errors or warnings
                      2. Potential root causes
                      3. Recommended remediation actions

                      Pod: ${pod_name}
                      Namespace: ${namespace}

                      Logs:
                      ${log_response.body}
        result: ai_analysis

    - return_with_analysis:
        return:
          correlation_id: ${correlation_id}
          pod_name: ${pod_name}
          namespace: ${namespace}
          logs: ${log_response.body}
          analysis: ${ai_analysis.body.candidates[0].content.parts[0].text}

    - return_logs_only:
        return:
          correlation_id: ${correlation_id}
          pod_name: ${pod_name}
          namespace: ${namespace}
          logs: ${log_response.body}
```

### 3. CLI Wrapper (wf-cli.sh)

**Location:** `tools/wf-cli/wf-cli.sh`

```bash
#!/usr/bin/env bash
# wf-cli.sh - kubectl-like interface for Cloud Workflows remediation
# Usage: wf get pods -n <namespace> --cluster <cluster>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${WF_CONFIG:-$HOME/.wf-cli/config.yaml}"

# Commands
cmd_get() {
    local resource_type=$1
    shift

    local namespace=""
    local cluster=""
    local resource_name=""

    while [[ $# -gt 0 ]]; do
        case $1 in
            -n|--namespace) namespace="$2"; shift 2 ;;
            --cluster) cluster="$2"; shift 2 ;;
            *) resource_name="$1"; shift ;;
        esac
    done

    execute_workflow "debug-get" \
        --data "{\"cluster\": \"$cluster\", \"namespace\": \"$namespace\", \"resource_type\": \"$resource_type\", \"resource_name\": \"$resource_name\"}"
}

cmd_logs() {
    local pod_name=$1
    shift

    local namespace=""
    local cluster=""
    local container=""
    local tail_lines=100
    local analyze=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            -n|--namespace) namespace="$2"; shift 2 ;;
            --cluster) cluster="$2"; shift 2 ;;
            -c|--container) container="$2"; shift 2 ;;
            --tail) tail_lines="$2"; shift 2 ;;
            --analyze) analyze=true; shift ;;
            *) shift ;;
        esac
    done

    execute_workflow "debug-logs" \
        --data "{\"cluster\": \"$cluster\", \"namespace\": \"$namespace\", \"pod_name\": \"$pod_name\", \"container\": \"$container\", \"tail_lines\": $tail_lines, \"analyze_with_ai\": $analyze}"
}

execute_workflow() {
    local workflow_name=$1
    shift

    local project=$(get_config "project")
    local region=$(get_config "region")

    echo "Executing workflow: $workflow_name"

    gcloud workflows run "$workflow_name" \
        --project="$project" \
        --location="$region" \
        "$@" \
        --format=json | jq -r '.result'
}

get_config() {
    local key=$1
    yq eval ".$key" "$CONFIG_FILE"
}

# Main dispatcher
main() {
    local command=${1:-help}
    shift || true

    case $command in
        get) cmd_get "$@" ;;
        logs) cmd_logs "$@" ;;
        describe) cmd_describe "$@" ;;
        restart) cmd_restart "$@" ;;
        help) show_help ;;
        *) echo "Unknown command: $command"; show_help; exit 1 ;;
    esac
}

main "$@"
```

### 4. Alerting Integration (Eventarc)

**Eventarc Trigger Configuration:**
```hcl
# Eventarc trigger for alert-driven workflows
resource "google_eventarc_trigger" "alert_trigger" {
  name     = "alert-workflow-trigger-${var.environment}"
  location = var.region

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.monitoring.alertPolicy.v1.created"
  }

  destination {
    workflow = google_workflows_workflow.dispatcher.id
  }

  service_account = google_service_account.eventarc_sa.email
}
```

**dispatcher.yaml** (Alert Handler):
```yaml
main:
  params: [event]
  steps:
    - parse_alert:
        assign:
          - alert_name: ${event.data.incident.policy_name}
          - severity: ${event.data.incident.severity}
          - resource: ${event.data.incident.resource.labels}
          - started_at: ${event.data.incident.started_at}
          - correlation_id: ${sys.get_env("GOOGLE_CLOUD_WORKFLOW_EXECUTION_ID")}

    - log_alert_received:
        call: sys.log
        args:
          text: ${"Alert received: " + alert_name + " severity: " + severity}
          severity: WARNING

    - check_kill_switch:
        call: http.get
        args:
          url: ${"https://storage.googleapis.com/" + sys.get_env("GOOGLE_CLOUD_PROJECT_ID") + "-workflow-config/kill-switches.json"}
          auth:
            type: OAuth2
        result: kill_switch_config

    - evaluate_kill_switch:
        switch:
          - condition: ${kill_switch_config.body.global_disable == true}
            next: abort_disabled
          - condition: ${kill_switch_config.body[alert_name] == true}
            next: abort_disabled

    - route_to_workflow:
        switch:
          - condition: ${text.match_regex(alert_name, ".*ErrorBudgetBurn.*")}
            next: handle_error_budget
          - condition: ${text.match_regex(alert_name, ".*PodCrashLooping.*")}
            next: handle_pod_crash
          - condition: ${text.match_regex(alert_name, ".*NodeNotReady.*")}
            next: handle_node_issue
        next: handle_unknown_alert

    - handle_error_budget:
        call: googleapis.workflowexecutions.v1.projects.locations.workflows.executions.run
        args:
          workflow: ${"projects/" + sys.get_env("GOOGLE_CLOUD_PROJECT_ID") + "/locations/" + sys.get_env("GOOGLE_CLOUD_LOCATION") + "/workflows/analyze-error-budget"}
          argument:
            alert: ${event.data}
            correlation_id: ${correlation_id}
        result: workflow_result
        next: log_completion

    # Additional handlers...

    - abort_disabled:
        call: sys.log
        args:
          text: ${"Workflow disabled by kill switch for alert: " + alert_name}
          severity: WARNING
        next: end

    - log_completion:
        call: sys.log
        args:
          text: ${"Workflow completed for alert: " + alert_name}
          severity: INFO

    - end:
        return:
          correlation_id: ${correlation_id}
          alert_name: ${alert_name}
          status: "completed"
```

### 5. Vertex AI Problem Analysis

**analyze-logs.yaml** (Comprehensive Log Analysis):
```yaml
main:
  params: [args]
  steps:
    - init:
        assign:
          - cluster: ${args.cluster}
          - namespace: ${args.namespace}
          - time_range: ${default(args.time_range, "1h")}
          - correlation_id: ${sys.get_env("GOOGLE_CLOUD_WORKFLOW_EXECUTION_ID")}

    - gather_pod_logs:
        call: gke.request
        args:
          project: ${sys.get_env("GOOGLE_CLOUD_PROJECT_ID")}
          cluster: ${cluster}
          location: ${sys.get_env("GOOGLE_CLOUD_LOCATION")}
          method: GET
          path: ${"/api/v1/namespaces/" + namespace + "/pods"}
        result: pods_response

    - gather_events:
        call: gke.request
        args:
          project: ${sys.get_env("GOOGLE_CLOUD_PROJECT_ID")}
          cluster: ${cluster}
          location: ${sys.get_env("GOOGLE_CLOUD_LOCATION")}
          method: GET
          path: ${"/api/v1/namespaces/" + namespace + "/events"}
        result: events_response

    - filter_sensitive_data:
        assign:
          - filtered_events: ${text.replace_all(json.encode(events_response.body), "(?i)(password|secret|token|key)=[^&\\s]+", "$1=REDACTED")}

    - analyze_with_gemini:
        call: http.post
        args:
          url: ${"https://" + sys.get_env("GOOGLE_CLOUD_LOCATION") + "-aiplatform.googleapis.com/v1/projects/" + sys.get_env("GOOGLE_CLOUD_PROJECT_ID") + "/locations/" + sys.get_env("GOOGLE_CLOUD_LOCATION") + "/publishers/google/models/gemini-1.5-pro:generateContent"}
          auth:
            type: OAuth2
          body:
            contents:
              - role: user
                parts:
                  - text: |
                      You are a Kubernetes SRE expert. Analyze the following cluster state and provide:

                      1. **Summary**: Brief overview of the current state
                      2. **Issues Identified**: List any problems found
                      3. **Root Cause Analysis**: For each issue, provide likely root causes
                      4. **Recommended Actions**: Specific remediation steps
                      5. **Risk Assessment**: Rate the severity (Low/Medium/High/Critical)

                      Namespace: ${namespace}
                      Cluster: ${cluster}

                      ## Pod Status
                      ${json.encode(pods_response.body.items)}

                      ## Recent Events
                      ${filtered_events}
        result: analysis_result

    - return_analysis:
        return:
          correlation_id: ${correlation_id}
          cluster: ${cluster}
          namespace: ${namespace}
          analysis: ${analysis_result.body.candidates[0].content.parts[0].text}
          raw_data:
            pod_count: ${len(pods_response.body.items)}
            event_count: ${len(events_response.body.items)}
```

### 6. Compliance Audit Logging

**BigQuery Sink Configuration:**
```hcl
# BigQuery dataset for audit logs
resource "google_bigquery_dataset" "workflow_audit" {
  dataset_id = "workflow_audit_logs"
  location   = var.region

  default_table_expiration_ms = 7776000000  # 90 days

  labels = {
    environment = var.environment
    purpose     = "compliance"
  }
}

# Log sink to BigQuery
resource "google_logging_project_sink" "workflow_audit_sink" {
  name        = "workflow-audit-sink"
  destination = "bigquery.googleapis.com/projects/${var.project_id}/datasets/${google_bigquery_dataset.workflow_audit.dataset_id}"

  filter = <<-EOF
    resource.type="workflows.googleapis.com/Workflow"
    OR resource.type="gke_cluster"
    AND protoPayload.methodName=~"^google.cloud.workflows"
  EOF

  bigquery_options {
    use_partitioned_tables = true
  }
}
```

**Query Templates:**
```sql
-- All workflow executions in the last 24 hours
SELECT
  timestamp,
  jsonPayload.correlation_id,
  jsonPayload.workflow_name,
  jsonPayload.user,
  jsonPayload.status,
  jsonPayload.duration_ms
FROM `project.workflow_audit_logs.cloudaudit_googleapis_com_activity`
WHERE timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY timestamp DESC;

-- Failed remediations requiring investigation
SELECT
  timestamp,
  jsonPayload.correlation_id,
  jsonPayload.workflow_name,
  jsonPayload.error_message,
  jsonPayload.alert_name
FROM `project.workflow_audit_logs.cloudaudit_googleapis_com_activity`
WHERE jsonPayload.status = "FAILED"
  AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY timestamp DESC;
```

### 7. Safety Controls

**PAM Approval for Destructive Actions:**

All workflows that modify cluster state (Remediate and Failover categories) require PAM approval, regardless of trigger source:
- **Human-triggered** (CLI): Operator must have PAM approval before execution
- **Automated** (Eventarc/Scheduler): Workflow requests PAM approval and waits
- **AI-recommended**: Analysis workflows only recommend; execution requires PAM

This ensures no destructive action executes without explicit approval, meeting SOC 2/HIPAA compliance requirements.

**PAM Integration for Approval Gates:**
```yaml
# In destructive workflows (remediate-*.yaml, failover-*.yaml)
main:
  params: [args]
  steps:
    - init:
        assign:
          - correlation_id: ${sys.get_env("GOOGLE_CLOUD_WORKFLOW_EXECUTION_ID")}
          - trigger_source: ${default(args.trigger_source, "unknown")}

    - log_destructive_action:
        call: sys.log
        args:
          text: ${"Destructive action requested. Trigger: " + trigger_source + ". Requesting PAM approval."}
          severity: INFO

    - request_pam_approval:
        call: http.post
        args:
          url: "https://privilegedaccessmanager.googleapis.com/v1/projects/${project}/locations/global/entitlements/${entitlement_id}:requestGrant"
          auth:
            type: OAuth2
          body:
            requestedDuration: "3600s"
            justification:
              unstructuredJustification: ${"Remediation action: " + args.action + " | Trigger: " + trigger_source + " | correlation_id: " + correlation_id}
        result: approval_request

    - wait_for_approval:
        call: sys.sleep
        args:
          seconds: 30
        next: check_approval_status

    - check_approval_status:
        call: http.get
        args:
          url: ${"https://privilegedaccessmanager.googleapis.com/v1/" + approval_request.body.name}
          auth:
            type: OAuth2
        result: approval_status

    - evaluate_approval:
        switch:
          - condition: ${approval_status.body.state == "APPROVED"}
            next: execute_action
          - condition: ${approval_status.body.state == "DENIED"}
            raise: "PAM approval denied"
          - condition: ${approval_status.body.state == "PENDING"}
            next: wait_for_approval

    - execute_action:
        # ... remediation/failover logic
```

**Kill Switch Configuration:**
```json
// Stored in GCS: gs://<project>-workflow-config/kill-switches.json
{
  "global_disable": false,
  "remediate-restart": false,
  "remediate-drain": false,
  "auto_remediation": false,
  "rate_limits": {
    "remediate-restart": {
      "max_per_hour": 10,
      "max_per_day": 50
    },
    "remediate-drain": {
      "max_per_hour": 2,
      "max_per_day": 5
    }
  }
}
```

**Rate Limiting Implementation:**
```yaml
# Rate limit check step (included in remediation workflows)
- check_rate_limit:
    call: http.get
    args:
      url: ${"https://storage.googleapis.com/" + sys.get_env("GOOGLE_CLOUD_PROJECT_ID") + "-workflow-config/rate-limits/" + workflow_name + ".json"}
      auth:
        type: OAuth2
    result: rate_limit_data

- evaluate_rate_limit:
    switch:
      - condition: ${rate_limit_data.body.executions_this_hour >= rate_limit_data.body.max_per_hour}
        next: abort_rate_limited
      - condition: ${rate_limit_data.body.executions_today >= rate_limit_data.body.max_per_day}
        next: abort_rate_limited
    next: increment_counter

- abort_rate_limited:
    call: sys.log
    args:
      text: ${"Rate limit exceeded for workflow: " + workflow_name}
      severity: WARNING
    raise: "Rate limit exceeded"
```

## Sequence Diagrams

### Human-Triggered Flow with Optional AI Analysis

```
┌──────────┐     ┌─────────┐     ┌───────────────┐     ┌─────────┐     ┌───────────┐
│ Operator │     │ wf-cli  │     │Cloud Workflows│     │   GKE   │     │ Vertex AI │
└────┬─────┘     └────┬────┘     └──────┬────────┘     └────┬────┘     └─────┬─────┘
     │                │                  │                   │                │
     │ wf logs pod-x  │                  │                   │                │
     │ --analyze      │                  │                   │                │
     ├───────────────►│                  │                   │                │
     │                │ Execute workflow │                   │                │
     │                ├─────────────────►│                   │                │
     │                │                  │ gke.request       │                │
     │                │                  │ GET /pods/logs    │                │
     │                │                  ├──────────────────►│                │
     │                │                  │◄──────────────────┤                │
     │                │                  │                   │                │
     │                │                  │ Gemini API        │                │
     │                │                  │ Analyze logs      │                │
     │                │                  ├─────────────────────────────────►  │
     │                │                  │◄─────────────────────────────────  │
     │                │                  │                   │                │
     │                │ Result + Analysis│                   │                │
     │                │◄─────────────────┤                   │                │
     │ Logs + AI      │                  │                   │                │
     │ recommendations│                  │                   │                │
     │◄───────────────┤                  │                   │                │
     │                │                  │                   │                │
```

### Alert-Driven Flow with AI Triage

```
┌───────────┐     ┌──────────┐     ┌───────────────┐     ┌───────────┐     ┌─────────┐
│Alert Fires│     │ Eventarc │     │   Dispatcher  │     │ Vertex AI │     │   GKE   │
└─────┬─────┘     └────┬─────┘     └──────┬────────┘     └─────┬─────┘     └────┬────┘
      │                │                   │                   │                │
      │ Alert payload  │                   │                   │                │
      ├───────────────►│                   │                   │                │
      │                │ Trigger workflow  │                   │                │
      │                ├──────────────────►│                   │                │
      │                │                   │                   │                │
      │                │                   │ Check kill switch │                │
      │                │                   ├──────────────────►│                │
      │                │                   │◄──────────────────┤                │
      │                │                   │                   │                │
      │                │                   │ Gather context    │                │
      │                │                   ├─────────────────────────────────►  │
      │                │                   │◄─────────────────────────────────  │
      │                │                   │                   │                │
      │                │                   │ AI Analysis       │                │
      │                │                   ├──────────────────►│                │
      │                │                   │ Recommendation    │                │
      │                │                   │◄──────────────────┤                │
      │                │                   │                   │                │
      │                │                   │ ┌─────────────────────────────────┐│
      │                │                   │ │ Destructive action detected     ││
      │                │                   │ │ → PAM approval REQUIRED         ││
      │                │                   │ └─────────────────────────────────┘│
      │                │                   │                   │                │
      │                │                   │ Execute remediation                │
      │                │                   ├─────────────────────────────────►  │
      │                │                   │◄─────────────────────────────────  │
      │                │                   │                   │                │
      │                │                   │ Log to BigQuery   │                │
      │                │                   ├──────────────────►│                │
```

## Validation and Testing Strategy

### Unit Testing
- Workflow YAML syntax validation
- Parameter validation logic testing
- Kill switch configuration parsing
- Rate limit evaluation logic

### Integration Testing
- Workflow execution against test GKE cluster
- Eventarc trigger delivery verification
- Vertex AI API integration
- BigQuery audit log sink verification

### End-to-End Testing
- Alert fires → workflow triggers → remediation executes
- Human CLI → workflow executes → results returned
- Kill switch toggle → workflows abort correctly
- Rate limiting prevents excessive executions

## Implementation Stories

Seven stories are created under GCP-320 to implement this platform scaffolding:

1. **Create Terraform module for Cloud Workflows** - API, service accounts, permissions
2. **Implement debug workflows** - get, describe, logs with gke.request
3. **Create CLI wrapper (wf-cli.sh)** - kubectl-like interface
4. **Integrate alerting framework (GCP-319) with workflows** - Eventarc triggers
5. **Implement Vertex AI problem analysis integration** - Gemini log analysis
6. **Implement compliance audit logging** - BigQuery sink, query templates
7. **Implement safety controls and kill switches** - PAM, rate limiting, emergency disable

## Dependencies

- **GCP-319** (Integrated Alerting Framework): Alert metadata format for Eventarc triggers
- **Workload Identity Federation**: Service account authentication for workflows
- **Privileged Access Manager**: Approval gates for high-risk operations
- **Vertex AI (Gemini)**: AI-powered log analysis capabilities
