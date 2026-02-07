# GCP Hypershift Control Plane (HCP) Service - Level 1 Architecture Specification

## Executive Summary

This document defines an architecture for a GCP service that provides
managed Hypershift clusters.

## Architecture Overview

```
              Customer
                  │ HTTP Request
                  │ CRUD Clusters/Nodes
┌─────────────────↓─────────────────────┐
│    Frontend Service                   │
│    • GCP API Gateway                  │
│    • Customer AuthN/AuthZ             │
│    • Usage Metering                   │
└─────────────────┬─────────────────────┘
                  │ HTTP Request
                  │ Clusters/Nodes Spec
┌─────────────────↓───────────────────┐
│    Backend Service                  │
│    • Persist Desired State          │
│    • Realize Desired State          │
│    • Aggregate/Report Current State │ 
└─────────────────┬───────────────────┘
                  │ HTTP Request
                  │ Kubernetes Resources
┌─────────────────↓────────────────────┐
│     Management GKE Cluster           │
│  ┌──────────────────────────────────┐│
│  │ Hypershift Operator              ││
│  │ • HostedCluster                  ││
│  │ • Private Service Connect        ││
│  │ • Load Balancer                  ││
│  └──────────────────────────────────┘│
└─────────────────↑────────────────────┘
                  │ Private Network Connection
┌─────────────────┴───────────────────┐
│       Customer Project              │
│  ┌─────────────────────────────────┐│
│  │ WorkerNode Pools                ││
│  │ • Customer Workloads            ││
│  │ • PSC Consumer Endpoints        ││
│  └─────────────────────────────────┘│
└─────────────────────────────────────┘
```