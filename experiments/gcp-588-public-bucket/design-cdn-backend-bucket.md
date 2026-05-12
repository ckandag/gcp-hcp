# Design: Cloud CDN with Backend Bucket

## Overview

Front a **private** GCS bucket with a Global External Application Load Balancer + Cloud CDN
using a **Backend Bucket** resource. The Google-managed `cloud-cdn-fill` service account
authenticates cache fill requests to the private bucket.

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
Backend Bucket (CDN-enabled wrapper around GCS)
        │
        ▼  Authenticated via cloud-cdn-fill SA
Private GCS Bucket
  ├── {infraID}/.well-known/openid-configuration
  └── {infraID}/openid/v1/jwks
```

## How It Works

1. GCS bucket is created with **uniform bucket-level access** (private, no `allUsers`).
2. A **Backend Bucket** resource wraps the GCS bucket and enables Cloud CDN.
3. Adding a **signed URL key** to the backend bucket triggers GCP to provision the
   `service-{PROJECT_NUMBER}@cloud-cdn-fill.iam.gserviceaccount.com` service account.
4. We grant the CDN fill SA `roles/storage.objectViewer` on the GCS bucket.
5. Cloud CDN authenticates to GCS using this SA when filling the cache.
6. Clients access OIDC documents via the LB's public endpoint; CDN serves cached responses.

## GCP Resources

| Resource | Purpose |
|----------|---------|
| GCS Bucket | Stores OIDC discovery + JWKS documents (private) |
| Backend Bucket | CDN-enabled wrapper, `FORCE_CACHE_ALL` mode |
| URL Map | Routes all requests to the backend bucket |
| Target HTTPS Proxy | TLS termination with Google-managed certificate |
| Forwarding Rule (HTTPS) | Binds static IP to HTTPS proxy on port 443 |
| Forwarding Rule (HTTP) | HTTP-to-HTTPS redirect |
| Static IP | Global external IP for the LB |
| SSL Certificate | Google-managed, auto-renewed |
| DNS A Record | `oidc.{region-domain}` pointing to static IP |

## Org Policy Requirement

The `cloud-cdn-fill` SA (`service-{NUM}@cloud-cdn-fill.iam.gserviceaccount.com`) is **not** in
any permitted domain under `constraints/iam.allowedPolicyMemberDomains`. Granting it
`objectViewer` on the bucket is blocked.

**Required change**: One of the approaches described in the org policy proposals:
- Plan A: Custom constraint allowing `@cloud-cdn-fill.iam.gserviceaccount.com` suffix
- Plan B: Tag-based conditional `allowAll` on the legacy constraint

See `org-policy-planA-custom-constraint.md` and `org-policy-planB-tag-based.md`.

## Why Global (Not Regional)

- **GCP STS is global**: We don't control which region STS calls from.
- **Backend Buckets require Global LB**: Regional LBs only support backend *services*, not
  backend *buckets*.
- **CDN edge caching**: OIDC docs are ~1KB, rarely change. Near-100% cache hit rate from any
  region.

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

## Security

- Bucket stays **private** -- no `allUsers` or `allAuthenticatedUsers`.
- `cloud-cdn-fill` SA is Google-managed -- no keys to rotate.
- Only objects in the bucket are exposed; bucket is not listable.
- OIDC docs are inherently public data (JWKS = public keys only).

## Advantages

- **Simple architecture**: Backend Bucket is a native CDN-to-GCS integration.
- **No secrets to manage**: The CDN fill SA is fully Google-managed.
- **No HMAC keys**: No key rotation, no Secret Manager storage.
- **Fewer resources**: No Internet NEG or Backend Service needed.

## Disadvantages

- **Requires org policy change**: Cannot grant `cloud-cdn-fill` SA bucket access without it.
- **Cloud-cdn-fill SA is opaque**: Google-managed, limited visibility into its behavior.
- **SA creation is non-obvious**: Requires a signed URL key to trigger SA provisioning.

## Terraform Placement

Region module (`terraform/modules/region/`) since infrastructure is per-region:
- GCS bucket, IAM binding for CDN fill SA
- Backend bucket with CDN
- URL map, target HTTPS proxy, forwarding rules
- Google-managed SSL certificate
- DNS record

## Test Scripts

- `setup-cdn-test.sh` -- End-to-end setup with sample OIDC content
- `cleanup-cdn-test.sh` -- Tears down all resources

## References

- [Cloud CDN with Backend Bucket](https://cloud.google.com/cdn/docs/setting-up-cdn-with-bucket)
- [Cloud CDN fill service account](https://cloud.google.com/cdn/docs/cloud-cdn-fill-service-account)
