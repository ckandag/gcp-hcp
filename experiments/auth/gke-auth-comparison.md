# GKE Auth Plugin vs gcphcp Login

A comparison of authentication workflows for GKE clusters and GCP Hosted Clusters.

## Overview

| Aspect | GKE | GCP HCP |
|--------|-----|---------|
| Auth Plugin | `gke-gcloud-auth-plugin` | `gcloud auth print-identity-token` (via exec) |
| Token Type | OAuth2 Access Token | OIDC Identity Token (JWT) |
| Token Validation | Google infrastructure (internal) | Kubernetes OIDC validation (public JWKS) |
| Setup Command | `gcloud container clusters get-credentials` | `gcphcp clusters login` |

## GKE Authentication Flow

```
┌─────────────┐     ┌──────────────────────────┐     ┌─────────────────┐
│   kubectl   │────▶│  gke-gcloud-auth-plugin  │────▶│   GKE API       │
└─────────────┘     └──────────────────────────┘     └─────────────────┘
                              │                              │
                              ▼                              ▼
                    ┌──────────────────┐          ┌──────────────────┐
                    │ ~/.config/gcloud │          │ Google Token     │
                    │ (credentials)    │          │ Validation       │
                    └──────────────────┘          └──────────────────┘
```

### Kubeconfig Structure

```yaml
users:
- name: gke_project_zone_cluster
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1beta1
      command: gke-gcloud-auth-plugin
      provisionClusterInfo: true
```

### How It Works

1. kubectl makes API request, needs authentication
2. Invokes `gke-gcloud-auth-plugin` (compiled Go binary)
3. Plugin reads gcloud credentials from `~/.config/gcloud/`
4. Returns OAuth2 access token in ExecCredential format
5. kubectl sends token to GKE API server
6. GKE validates token internally with Google infrastructure
7. GKE queries IAM to determine user's roles for RBAC

### Token Format

```
ya29.a0AfH6SMBx...  (opaque string, ~200 chars)
```

- Not decodable - only Google can validate
- Contains scopes and expiry (internal to Google)

## gcphcp Authentication Flow

```
┌─────────────┐     ┌─────────────────────────────┐     ┌─────────────────┐
│   kubectl   │────▶│  bash -c "gcloud auth       │────▶│ HostedCluster   │
└─────────────┘     │  print-identity-token"      │     │ API Server      │
                    └─────────────────────────────┘     └─────────────────┘
                              │                                 │
                              ▼                                 ▼
                    ┌──────────────────┐          ┌──────────────────────┐
                    │ Google OAuth     │          │ OIDC Validation via  │
                    │ (user creds)     │          │ accounts.google.com  │
                    └──────────────────┘          │ public JWKS          │
                                                  └──────────────────────┘
```

### Kubeconfig Structure

```yaml
users:
- name: my-cluster
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1beta1
      command: bash
      args:
      - -c
      - |
        cat <<EOT
        {
          "apiVersion": "client.authentication.k8s.io/v1beta1",
          "kind": "ExecCredential",
          "status": {
            "token": "$(gcloud auth print-identity-token)"
          }
        }
        EOT
```

### How It Works

1. kubectl makes API request, needs authentication
2. Invokes bash which calls `gcloud auth print-identity-token`
3. Returns OIDC identity token (JWT) in ExecCredential format
4. kubectl sends token to HostedCluster API server
5. API server validates JWT signature using Google's public JWKS
6. API server extracts claims (email, hd) for user identity
7. Kubernetes RBAC determines authorization based on user/groups

### Token Format

```
eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOi...  (JWT, decodable)
```

Decoded payload:
```json
{
  "iss": "https://accounts.google.com",
  "email": "user@redhat.com",
  "hd": "redhat.com",
  "sub": "1234567890",
  "exp": 1704825600
}
```

## Key Differences

### Token Validation

| GKE | GCP HCP |
|-----|---------|
| Token validated by Google internally | Token validated using public OIDC/JWKS |
| Requires Google infrastructure access | Standard OIDC - works anywhere |
| Opaque token | Transparent JWT with claims |

### Authorization (RBAC)

| GKE | GCP HCP |
|-----|---------|
| IAM roles queried at request time | Claims extracted from token |
| `roles/container.admin` → cluster-admin | `email` → username, `hd` → group |
| Dynamic - IAM changes apply immediately | Static - claims fixed at token issuance |

### Performance

| GKE | GCP HCP |
|-----|---------|
| ~50ms (compiled Go binary) | ~500ms (gcloud CLI startup) |
| Reads credentials directly | Shells out to gcloud |
| Optimized for high-frequency calls | Acceptable for interactive use |

### Dependencies

| GKE | GCP HCP |
|-----|---------|
| Requires `gke-gcloud-auth-plugin` binary | Requires `gcloud` CLI |
| ~15MB standalone | Part of 200MB+ gcloud SDK |

## Why the Approaches Differ

**GKE** is a Google-managed service with privileged access to Google infrastructure:
- Can validate opaque access tokens internally
- Can query IAM APIs on every request
- Deeply integrated with Google Cloud

**GCP HCP** runs on customer infrastructure without Google privileges:
- Must use standard OIDC that can be validated publicly
- Cannot query Google IAM at request time
- Uses token claims for authorization decisions

## Historical Context

Before Kubernetes v1.26, kubectl had built-in GCP auth support:

```yaml
# Old way (deprecated)
users:
- name: gke-user
  user:
    auth-provider:
      name: gcp
      config:
        cmd-path: /path/to/gcloud
        token-key: '{.credential.access_token}'
```

Kubernetes removed vendor-specific auth code, requiring all providers to use the exec plugin pattern. This led to the creation of `gke-gcloud-auth-plugin`.

## Future Considerations

For production gcphcp, potential optimizations:
1. Use Google auth libraries directly (skip gcloud CLI overhead)
2. Create dedicated auth binary (like gke-gcloud-auth-plugin)
3. Cache tokens with expiry awareness

For enhanced authorization (Phase 2 POC):
- Identity Platform integration for IAM-to-RBAC mapping
- Custom claims with GCP roles embedded in token

