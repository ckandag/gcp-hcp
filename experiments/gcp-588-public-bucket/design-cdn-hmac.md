# Design: Cloud CDN with HMAC Private Origin Authentication

## Overview

Front a **private** GCS bucket with a Global External Application Load Balancer + Cloud CDN
using **HMAC-based Private Origin Authentication**. A project-owned service account with HMAC
keys authenticates CDN cache fill requests to GCS via the S3-compatible XML API.

This approach **avoids the org policy blocker** because the service account belongs to the
project's own domain.

## Architecture

```
GCP STS / Any Client
        │
        ▼  HTTPS
Global External Application Load Balancer
  ├── Static IP (global)
  ├── Google-managed SSL Certificate
  ├── Target HTTPS Proxy
  └── URL Map
        │
        ▼
Cloud CDN (edge caching, FORCE_CACHE_ALL)
        │
        ▼
Backend Service (EXTERNAL_MANAGED, HTTPS protocol)
  ├── HMAC Private Origin Auth (awsV4Authentication)
  └── Custom Host header: {bucket}.storage.googleapis.com
        │
        ▼
Internet NEG (FQDN: {bucket}.storage.googleapis.com:443)
        │
        ▼  HMAC-signed requests (S3 Signature V4)
Private GCS Bucket (via XML API / S3-compatible endpoint)
  ├── {infraID}/.well-known/openid-configuration
  └── {infraID}/openid/v1/jwks
```

## How It Works

1. GCS bucket is created with **uniform bucket-level access** (private, no `allUsers`).
2. A **project-owned service account** (e.g., `oidc-cdn-reader@{project}.iam.gserviceaccount.com`)
   is created and granted `roles/storage.objectViewer` on the bucket. This succeeds because
   the SA is in the project's own domain -- **no org policy conflict**.
3. An **HMAC key** is created for the service account (`gcloud storage hmac create`). GCS
   natively supports S3-compatible authentication -- HMAC keys are the GCS equivalent of AWS
   access keys (an `accessId` + `secret` pair) that enable AWS Signature V4 signing against
   GCS's XML API.
4. An **Internet NEG** (Network Endpoint Group) points to `{bucket}.storage.googleapis.com:443`.
   This treats GCS as an external HTTPS origin rather than using a Backend Bucket (which would
   require the `cloud-cdn-fill` SA blocked by org policy).
5. A **Backend Service** wraps the Internet NEG with CDN enabled and configures
   `securitySettings.awsV4Authentication` with the HMAC credentials. It also sets a custom
   `Host: {bucket}.storage.googleapis.com` header so GCS routes to the correct bucket.
6. On a **cache miss**, Cloud CDN constructs a request to the GCS origin, signs it using the
   HMAC secret with AWS Signature V4, and sends it. GCS validates the signature against the
   HMAC key, confirms the SA has `objectViewer`, and returns the object. CDN caches the
   response at edge PoPs.
7. Clients access OIDC documents via the LB's public endpoint; CDN serves cached responses.

## GCP Resources

| Resource | Purpose |
|----------|---------|
| GCS Bucket | Stores OIDC discovery + JWKS documents (private) |
| Service Account | Project-owned SA for HMAC auth (`oidc-cdn-reader`) |
| HMAC Key | S3 Signature V4 credentials for the SA |
| Internet NEG | FQDN endpoint to `{bucket}.storage.googleapis.com:443` |
| Backend Service | CDN-enabled, HMAC auth configured, HTTPS protocol |
| URL Map | Routes all requests to the backend service |
| Target HTTPS Proxy | TLS termination with Google-managed certificate |
| Forwarding Rule (HTTPS) | Binds static IP to HTTPS proxy on port 443 |
| Forwarding Rule (HTTP) | HTTP-to-HTTPS redirect |
| Static IP | Global external IP for the LB |
| SSL Certificate | Google-managed, auto-renewed |
| DNS A Record | `oidc.{region-domain}` pointing to static IP |

## Org Policy Impact

**None.** The service account is project-owned (`@{project}.iam.gserviceaccount.com`), which
is always in the permitted domain under `constraints/iam.allowedPolicyMemberDomains`. No org
policy change is required.

## Why Global (Not Regional)

Same as the Backend Bucket approach:
- **GCP STS is global**: We don't control which region STS calls from.
- **Internet NEGs require Global LB**: Only available with EXTERNAL_MANAGED scheme.
- **CDN edge caching**: Near-100% cache hit rate for ~1KB documents.

## Issuer URL Format

```
https://oidc.{region-domain}/{cluster-infraID}
```

Example: `https://oidc.int-reg-us-c1.int.gcp-hcp.devshift.net/a1b2`

## Bucket Layout

Per-region shared bucket with per-cluster path prefixes:

```
gs://{region-infra-id}-oidc-issuer/
  ├── {cluster-1}/.well-known/openid-configuration
  ├── {cluster-1}/openid/v1/jwks
  ├── {cluster-2}/.well-known/openid-configuration
  └── {cluster-2}/openid/v1/jwks
```

## Cost

| Resource | Cost |
|----------|------|
| Forwarding rule (global) | ~$18/month per region |
| Static IP (in use) | Free |
| Google-managed SSL cert | Free |
| CDN egress + cache fill | Negligible (~1KB docs) |
| GCS storage | Negligible |

Cost is identical to the Backend Bucket approach.

## Security

- Bucket stays **private** -- no `allUsers` or `allAuthenticatedUsers`.
- HMAC secret must be stored securely (GCP Secret Manager recommended for Terraform).
- HMAC key should be rotated periodically.
- Only objects in the bucket are exposed; bucket is not listable.
- OIDC docs are inherently public data (JWKS = public keys only).

## HMAC Key Management

HMAC keys require lifecycle management:

- **Creation**: `gcloud storage hmac create {sa-email}` returns `accessId` + `secret`.
  The secret is shown **once** and cannot be retrieved again.
- **Storage**: Must be stored in Secret Manager or equivalent for Terraform to reference.
- **Rotation**: Create new key, update backend service config, deactivate old key, delete old key.
- **Limit**: Up to 10 HMAC keys per service account (5 active recommended max).

### Terraform HMAC Key Management

```hcl
resource "google_storage_hmac_key" "oidc_cdn" {
  service_account_email = google_service_account.oidc_cdn_reader.email
  project               = var.project_id
}

resource "google_secret_manager_secret_version" "hmac_secret" {
  secret      = google_secret_manager_secret.oidc_hmac.id
  secret_data = google_storage_hmac_key.oidc_cdn.secret
}
```

## Advantages

- **No org policy change required**: Project-owned SA is always in permitted domain.
- **Can deploy immediately**: No dependency on org admin approval.
- **Full control**: We own the SA and HMAC keys, complete visibility.
- **Same CDN benefits**: Edge caching, global availability, auto-renewed TLS.

## Disadvantages

- **More resources**: Internet NEG + Backend Service instead of simpler Backend Bucket.
- **HMAC key management**: Secret must be stored securely and rotated.
- **More complex Terraform**: Backend service config requires export/import for
  `awsV4Authentication` settings (not all fields are natively supported in the Terraform
  provider).
- **S3 API dependency**: Relies on GCS S3-compatible XML API for HMAC auth.

## Comparison with Backend Bucket Approach

| Aspect | Backend Bucket | HMAC |
|--------|---------------|------|
| Org policy change | **Required** | Not needed |
| Deploy readiness | Blocked until approved | **Immediate** |
| Secret management | None (Google-managed SA) | HMAC key in Secret Manager |
| Key rotation | None | Required |
| GCP resources | 8 (fewer) | 10 (more) |
| Terraform complexity | Lower | Higher (export/import for auth config) |
| CDN performance | Identical | Identical |
| Cost | ~$18/mo per region | ~$18/mo per region |

## Terraform Placement

Region module (`terraform/modules/region/`) since infrastructure is per-region:
- GCS bucket, service account, IAM binding
- HMAC key + Secret Manager secret
- Internet NEG, backend service with HMAC auth
- URL map, target HTTPS proxy, forwarding rules
- Google-managed SSL certificate
- DNS record

## Test Scripts

- `setup-cdn-hmac-test.sh` -- End-to-end setup with sample OIDC content
- `cleanup-cdn-hmac-test.sh` -- Tears down all resources

## References

- [Cloud CDN Private Origin Authentication](https://cloud.google.com/cdn/docs/private-origin-authentication)
- [GCS HMAC Keys](https://cloud.google.com/storage/docs/authentication/hmackeys)
- [GCS S3-compatible XML API](https://cloud.google.com/storage/docs/xml-api/overview)
