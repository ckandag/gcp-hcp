# OAuth Helper Cloud Function

A Google Cloud Function that exchanges Google identity tokens for Identity Platform tokens with custom IAM role claims.

## Purpose

This function enables **IAM-based access control** for OpenShift HostedClusters by:

1. Accepting a Google identity token (from `gcloud auth print-identity-token`)
2. **Checking if the user has any IAM role on the GCP project** (access gate)
3. Mapping IAM roles to Kubernetes groups
4. Minting an Identity Platform token with the mapped groups as custom claims

## How It Works

```
┌──────────┐    ┌──────────────────┐    ┌─────────────┐    ┌───────────────────┐
│  User    │    │  Cloud Function  │    │  GCP IAM    │    │ Identity Platform │
│ (gcloud) │    │  (oauth-helper)  │    │    API      │    │    (Firebase)     │
└────┬─────┘    └────────┬─────────┘    └──────┬──────┘    └─────────┬─────────┘
     │                   │                     │                     │
     │ 1. POST /exchange │                     │                     │
     │    {google_token} │                     │                     │
     ├──────────────────►│                     │                     │
     │                   │                     │                     │
     │                   │ 2. Query IAM policy │                     │
     │                   │    for user's roles │                     │
     │                   ├────────────────────►│                     │
     │                   │                     │                     │
     │                   │ 3. Return roles     │                     │
     │                   │◄────────────────────┤                     │
     │                   │                     │                     │
     │                   │ 4. ACCESS CHECK:    │                     │
     │                   │    Has IAM role?    │                     │
     │                   │    NO  → 403 Denied │                     │
     │                   │    YES → Continue   │                     │
     │                   │                     │                     │
     │                   │ 5. Map roles → K8s groups                 │
     │                   │                     │                     │
     │                   │ 6. Mint IDP token   │                     │
     │                   │    with custom claims                     │
     │                   ├───────────────────────────────────────────►
     │                   │                     │                     │
     │                   │ 7. Signed IDP token │                     │
     │                   │◄───────────────────────────────────────────
     │                   │                     │                     │
     │ 8. Return IDP     │                     │                     │
     │    token with     │                     │                     │
     │    gcp.iam.roles  │                     │                     │
     │◄──────────────────┤                     │                     │
     │                   │                     │                     │
```

**Key:** Step 4 is the access gate - users without any IAM role on the project are denied.

## IAM Role Mapping

| GCP IAM Role | Kubernetes Group |
|--------------|------------------|
| `roles/owner` | `cluster-admin` |
| `roles/editor` | `cluster-admin` |
| `roles/container.clusterAdmin` | `cluster-admin` |
| `roles/container.admin` | `cluster-admin` |
| `roles/viewer` | `cluster-viewer` |
| `roles/container.viewer` | `cluster-viewer` |
| `roles/container.clusterViewer` | `cluster-viewer` |

Users without a mapped role but with any project access get `cluster-viewer` by default.

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/exchange` | POST | Exchange Google token for IDP token |
| `/health` | GET | Health check |
| `/` | GET | Usage information |

## Deployment

```bash
# Deploy to your project
./deploy.sh <project-id>

# Deploy to specific region
./deploy.sh <project-id> us-east1
```

## Usage

### Exchange Token

```bash
# Get Google identity token
GCLOUD_TOKEN=$(gcloud auth print-identity-token)

# Exchange for IDP token
curl -s -X POST "https://<function-url>/exchange" \
  -H "Authorization: Bearer $GCLOUD_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"google_token\": \"$GCLOUD_TOKEN\"}"
```

### Response

```json
{
  "success": true,
  "email": "user@example.com",
  "iam_roles": ["roles/owner"],
  "k8s_groups": ["cluster-admin"],
  "issuer": "https://securetoken.google.com/<project-id>",
  "idp_token": "eyJhbG..."
}
```

### IDP Token Claims

The returned token includes these claims:

```json
{
  "iss": "https://securetoken.google.com/<project-id>",
  "aud": "<project-id>",
  "email": "user@example.com",
  "gcp.iam.roles": ["cluster-admin"],
  "gcp.project": "<project-id>"
}
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PROJECT_ID` | Yes | GCP Project ID |
| `IDP_API_KEY` | Yes | Identity Platform API Key |
| `REQUIRE_PROJECT_ACCESS` | No | Require IAM role (default: true) |

## Prerequisites

- Google Cloud project with Identity Platform enabled
- Identity Platform OIDC provider configured for Google
- API key with Identity Platform access

## Files

```
cloud-function/
├── README.md           # This file
├── deploy.sh           # Deployment script
├── main.py             # Cloud Function code
└── requirements.txt    # Python dependencies
```

## Security

- **Authenticated access**: Function requires valid Google identity token
- **Project-scoped**: Only users with IAM roles on the project can get tokens
- **Short-lived tokens**: IDP tokens expire after 1 hour
- **No stored credentials**: All authentication is token-based

