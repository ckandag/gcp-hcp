# GCP-588: Public Access for GCS-hosted OIDC Issuer Documents

## Problem

For Workload Identity Federation (WIF) to work on GCP HCP, each HostedCluster needs a publicly
accessible OIDC issuer URL serving two documents:

- `{issuerURL}/.well-known/openid-configuration` -- OIDC discovery document
- `{issuerURL}/openid/v1/jwks` -- JSON Web Key Set (public key)

GCP STS (Security Token Service) must be able to fetch these via **unauthenticated HTTPS GET**
to validate service account tokens issued by the HostedCluster API server.

GCS (Google Cloud Storage) is the chosen backend for hosting these documents. The natural approach
would be to make the GCS bucket publicly readable via `allUsers` IAM binding. However, our GCP
org policy `constraints/iam.allowedPolicyMemberDomains` **blocks adding `allUsers`** as an IAM
member in regional projects, making direct public bucket access impossible.

## Org Policy Constraint

The blocking constraint is `constraints/iam.allowedPolicyMemberDomains`, NOT
`constraints/storage.publicAccessPrevention` (the latter is not enforced on region projects).

`iam.allowedPolicyMemberDomains` prevents adding **any** IAM member that doesn't belong to a
permitted domain. This blocks both:
- `allUsers` (direct public bucket access)
- `service-{NUM}@cloud-cdn-fill.iam.gserviceaccount.com` (CDN authenticated access)

**Key fact**: Even though it's Google's own STS service accessing a Google Cloud Storage URL,
STS treats the issuer as an external OpenID Connect endpoint and makes **unauthenticated HTTPS
requests**. There is no way to grant STS "private" access to a specific bucket.

## Options Under Consideration

Both options require an org policy change.

### Option A: Tagged Exception for `allUsers` (Simpler)

Allow specific buckets to be public by using [conditional org policy with resource tags](https://docs.google.com/organization-policy/restrict-domains#share-data-publicly).

- Org admins update `constraints/iam.allowedPolicyMemberDomains` to allow `allUsers` on
  resources tagged with a specific tag (e.g., `oidc-public-bucket`)
- We tag our OIDC buckets with that tag
- Grant `allUsers` -> `roles/storage.objectViewer` on the tagged bucket
- Issuer URL = direct GCS URL: `https://storage.googleapis.com/{bucket}/{infraID}`

**Pros**: Simplest setup, no LB/CDN/forwarding rule needed, no cost beyond GCS storage
**Cons**: Bucket is directly public (though content is inherently public data -- only JWKS public keys)

### Option B: Cloud CDN with `cloud-cdn-fill` SA (More Secure)

Permit `cloud-cdn-fill.iam.gserviceaccount.com` as an allowed domain in the org policy, then
front the private bucket with Cloud CDN.

- Org admins add `cloud-cdn-fill.iam.gserviceaccount.com` to allowed policy member domains
- We grant the CDN fill SA `roles/storage.objectViewer` on the bucket
- Cloud CDN fetches objects from the private bucket, serves them publicly via LB
- Issuer URL = LB endpoint: `https://oidc.{region}.gcp-hcp.devshift.net/{infraID}`

**Pros**: Bucket stays private, CDN caching, more controlled access surface
**Cons**: Requires Global LB (~$18/mo per region), more infrastructure to manage

### Side-by-Side Comparison

|                        | Option A (allUsers + tag)                            | Option B (CDN)                                          |
|------------------------|------------------------------------------------------|---------------------------------------------------------|
| **Org policy change**  | Tag exception for `allUsers` on tagged buckets       | Add `cloud-cdn-fill` SA domain to allowed members       |
| **SSL/TLS**            | Free (GCS built-in at `storage.googleapis.com`)      | Free (Google-managed cert), requires: DNS A record, HTTPS proxy, cert resource |
| **Load Balancer**      | Not needed                                           | Required (~$18/mo per region)                           |
| **Static IP**          | Not needed                                           | Required                                                |
| **DNS**                | Not needed (uses `storage.googleapis.com`)           | Optional custom domain                                  |
| **Infra to provision** | Bucket + IAM binding only                            | 6 resources (bucket, backend-bucket, URL map, proxy, forwarding rule, cert) |
| **Issuer URL**         | `https://storage.googleapis.com/{bucket}/{infraID}`  | `https://oidc.{region}.gcp-hcp.devshift.net/{infraID}`  |
| **Security posture**   | Bucket directly public (content is public keys only) | Bucket private, CDN-fronted                             |
| **Operational cost**   | Zero beyond GCS storage                              | ~$18/mo per region + LB management                      |

## Proposed Solution Detail: Cloud CDN with `cloud-cdn-fill` Service Account

Front the private bucket with a **Global External Application Load Balancer** with **Cloud CDN**
enabled via a Backend Bucket. The bucket remains private, and the CDN uses a Google-managed
service account to authenticate with the bucket.

### How It Works

```
GCP STS / Any Client
        │
        ▼
Global External HTTPS Load Balancer (static IP + optional custom domain)
        │
        ▼
Cloud CDN (caches OIDC docs at edge PoPs worldwide)
        │
        ▼
Backend Bucket (wrapper around GCS bucket, CDN enabled)
        │
        ▼  (authenticated via cloud-cdn-fill SA)
Private GCS Bucket
  ├── {infraID}/.well-known/openid-configuration
  └── {infraID}/openid/v1/jwks
```

### Key Components

1. **Private GCS Bucket**: Stores OIDC documents with uniform bucket-level access. No `allUsers`
   binding needed.

2. **`cloud-cdn-fill` Service Account**: A Google-managed service account
   (`service-{PROJECT_NUMBER}@cloud-cdn-fill.iam.gserviceaccount.com`) that Cloud CDN uses to
   fetch objects from the private bucket. We grant it `roles/storage.objectViewer` on the bucket.
   This SA is created when a **signed URL key** is added to a CDN-enabled backend bucket.

3. **Backend Bucket**: A Compute Engine resource that wraps the GCS bucket and enables Cloud CDN
   policies (cache mode, TTL, etc.).

4. **Global External Application Load Balancer**: Provides the public-facing endpoint with a
   static IP. Consists of:
   - Static external IP address (global)
   - URL map (routes requests to the backend bucket)
   - Target HTTPS proxy (terminates TLS with a Google-managed certificate)
   - Forwarding rule (binds the IP to the proxy on port 443)

5. **Google-managed SSL Certificate**: Free, auto-provisioned and auto-renewed by Google.
   Requires:
   - A **DNS A record** pointing the custom domain to the LB's static IP. The DNS zone
     can live in a different GCP project than the LB (e.g., DNS zone in the region project,
     LB in the MC project). We use existing zones like
     `dev-reg-us-c1-ckandagb3fc.dev.gcp-hcp.devshift.net`.
   - A **`gcloud compute ssl-certificates create`** resource specifying the domain. Google
     validates ownership by resolving the DNS A record to the LB IP.
   - A **Target HTTPS Proxy** that references the certificate and the URL map.
   - A **Forwarding Rule** on port 443 that binds the static IP to the HTTPS proxy.
   - Provisioning takes ~10-30 minutes after DNS is resolvable. Certificate status transitions:
     `PROVISIONING` -> `ACTIVE`. Once active, HTTPS is fully operational.

6. **DNS Record**: An A record in an existing Cloud DNS zone (e.g., the region project's tools
   zone) mapping `oidc.{region-domain}` to the LB's global static IP.

### Why Global (Not Regional)

- **GCP STS is a global service**: When a pod uses WIF, GCP STS fetches the OIDC documents. We
  don't control which region STS calls from, so the endpoint must be globally reachable.
- **Backend Buckets require Global LB**: Regional load balancers only support backend *services*
  (VMs, NEGs), not backend *buckets* (GCS). GCS backend buckets are only available with the
  Global External Application Load Balancer.
- **CDN edge caching**: OIDC documents are tiny (~1KB) and rarely change (only on key rotation).
  Global CDN caching means near-100% cache hit rates and sub-millisecond STS token exchange
  latency from any region.

## Bucket Placement Strategy

**Recommended: Per-region shared bucket with per-cluster path prefixes.**

```
gs://{region-infra-id}-oidc-issuer/
  ├── {cluster-infra-id-1}/.well-known/openid-configuration
  ├── {cluster-infra-id-1}/openid/v1/jwks
  ├── {cluster-infra-id-2}/.well-known/openid-configuration
  ├── {cluster-infra-id-2}/openid/v1/jwks
  └── ...
```

**Rationale:**
- One LB + one CDN setup per region (cost-efficient)
- Strong isolation at the region level; per-cluster prefixes provide logical separation
- Simple cleanup: delete the prefix on cluster deletion
- Issuer URL format: `https://{lb-domain}/{cluster-infra-id}`

**Alternative: Per-MC bucket** (`{mc-infra-id}-oidc-issuer`)
- Stronger isolation (per-MC)
- More LBs to manage, higher cost
- Better fit if MC decommissioning needs atomic bucket deletion

## Cost Analysis

| Resource                     | Unit Cost (approx)       | Per-Region | Per-MC  |
|------------------------------|--------------------------|------------|---------|
| Forwarding rule (global)     | ~$18/month               | 1          | N       |
| Static IP (in use)           | Free (while attached)    | 1          | N       |
| Google-managed SSL cert      | Free                     | 1          | N       |
| Cloud CDN egress             | ~$0.02-0.08/GB           | Negligible | Negligible |
| Cloud CDN cache fill         | ~$0.01/10K requests      | Negligible | Negligible |
| GCS storage                  | ~$0.02/GB/month          | Negligible | Negligible |
| **Total per-region**         |                          | **~$18/mo** | **~$18/mo × N MCs** |

OIDC documents are ~1KB each, fetched infrequently (only on STS token exchange, heavily cached).
Egress and request costs are negligible. The primary cost driver is the forwarding rule.

## Security Posture

- **Bucket stays private**: No `allUsers` or `allAuthenticatedUsers` binding.
- **`cloud-cdn-fill` SA is Google-managed**: We only grant read access; no keys to manage.
- **Content is read-only public via LB**: Only objects in the bucket are exposed; the bucket
  itself is not listable (uniform bucket-level access, no `storage.objects.list` granted).
- **OIDC docs are inherently public data**: JWKS contains only public keys. The discovery doc
  contains only metadata. No secrets are exposed.
- **Org policy compliant**: Does not require `allUsers` binding, so
  `constraints/iam.allowedPolicyMemberDomains` is not triggered.

## Infrastructure Provisioning

This setup should be provisioned by Terraform in the **region module** (`terraform/modules/region/`)
since it's per-region infrastructure. Components:

1. GCS bucket (already may exist for other purposes)
2. IAM binding for `cloud-cdn-fill` SA on the bucket
3. Backend bucket with CDN enabled
4. URL map, target HTTPS proxy, forwarding rule
5. Google-managed SSL certificate
6. DNS record (optional, for custom domain like `oidc.{region}.gcp-hcp.devshift.net`)

## Test Scripts

- `setup-cdn-test.sh` -- Creates a test bucket, uploads sample OIDC content, sets up CDN + LB
- `cleanup-cdn-test.sh` -- Tears down all test resources

## Test Results (2026-04-13)

Tested against project `dev-mgt-us-c1-ckandagb3fc` (dev MC project).

### What Worked

1. Created private GCS bucket with OIDC content (`--pap` initially, then removed)
2. Reserved global static IP (`34.149.199.55`)
3. Created backend bucket with CDN enabled (`FORCE_CACHE_ALL`)
4. Created URL map, HTTP proxy, forwarding rule -- LB is up
5. **Triggered `cloud-cdn-fill` SA creation** by adding a signed URL key:
   ```bash
   gcloud compute backend-buckets add-signed-url-key oidc-backend-bucket \
       --key-name "trigger-key" --key-file /tmp/trigger-key.txt
   ```

### Blocker: Org Policy

Granting `cloud-cdn-fill` SA access to the bucket is blocked by the org policy:

```
ERROR: HTTPError 412: One or more users named in the policy do not belong to a permitted customer.
```

This confirms that `constraints/iam.allowedPolicyMemberDomains` blocks **both**:
- `allUsers` (direct public bucket access)
- `service-{NUM}@cloud-cdn-fill.iam.gserviceaccount.com` (CDN authenticated access)

Without the IAM binding, CDN returns **403 AccessDenied** when trying to fetch from the bucket.

### Required Org-Level Change

Either option requires an org policy update to `constraints/iam.allowedPolicyMemberDomains`:

- **Option A**: Add conditional tag exception allowing `allUsers` on tagged buckets
- **Option B**: Add `cloud-cdn-fill.iam.gserviceaccount.com` to the allowed domains

### Key Learnings

- The `cloud-cdn-fill` SA is **not** auto-created with `compute.googleapis.com`. It requires
  adding a signed URL key to a CDN-enabled backend bucket to trigger its creation.
- The org policy blocks the CDN SA just like it blocks `allUsers`. This must be resolved at the
  org level before this approach can work.
- Without the IAM binding, Cloud CDN cannot access the private bucket (returns 403).

### Resources to Clean Up

```bash
./cleanup-cdn-test.sh dev-mgt-us-c1-ckandagb3fc
```

## References

- [Cloud CDN with Backend Bucket](https://cloud.google.com/cdn/docs/setting-up-cdn-with-bucket)
- [GCP-588 Jira Ticket](https://redhat.atlassian.net/browse/GCP-588)
- [GCP-589: Public Access Implementation](https://redhat.atlassian.net/browse/GCP-589)
