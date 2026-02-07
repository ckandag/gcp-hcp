# Which Authentication Setup Should I Use?

## Quick Decision Tree

```
Are you running on GKE (Google Kubernetes Engine)?
│
├─ YES → Use Workload Identity
│         Run: ./setup-workload-identity.sh
│         ✅ Production-ready
│         ✅ No credential files
│         ✅ Automatic rotation
│
└─ NO → Are you on local Kubernetes (Kind/Minikube/Docker Desktop)?
         │
         ├─ YES → Use JSON Key Authentication
         │        Run: ./setup-local-gcp-auth.sh
         │        ⚠️  Dev/testing only
         │        ⚠️  Requires manual key management
         │
         └─ NO → Are you on another cloud provider (EKS/AKS)?
                  Use JSON Key Authentication for now
                  Run: ./setup-local-gcp-auth.sh
```

## Detailed Comparison

### Workload Identity (GKE Only)

**When to use:**
- Running on Google Kubernetes Engine (GKE)
- Production workloads
- When security is a priority

**Pros:**
- ✅ No credential files to manage
- ✅ Automatic credential rotation
- ✅ Google's recommended approach
- ✅ Full audit trail
- ✅ Fine-grained IAM control

**Cons:**
- ❌ Only works on GKE
- ❌ Requires cluster configuration

**Setup:**
```bash
./setup-workload-identity.sh
```

---

### JSON Key Authentication (Local/Non-GKE)

**When to use:**
- Local development (Kind, Minikube, Docker Desktop)
- Testing
- Running on non-GCP Kubernetes (EKS, AKS, on-prem)
- Quick prototyping

**Pros:**
- ✅ Works on any Kubernetes cluster
- ✅ Simple to set up
- ✅ Good for local development

**Cons:**
- ❌ Manual key rotation required
- ❌ Keys can be compromised
- ❌ Not recommended for production
- ❌ Keys stored in cluster secrets

**Setup:**
```bash
./setup-local-gcp-auth.sh
```

**Security Requirements:**
- Rotate keys every 90 days
- Add `gcp-key.json` to `.gitignore`
- Never commit keys to version control
- Delete unused keys immediately
- Use least-privilege IAM roles

---

## How to Identify Your Cluster Type

### Check if you're on GKE:

```bash
# Method 1: Check kubectl context
kubectl config current-context
# If it contains "gke_", you're on GKE

# Method 2: Check node labels
kubectl get nodes -o wide
# If provider is "gce", you're on GKE

# Method 3: Check cluster info
kubectl cluster-info
# If it shows a GKE master URL, you're on GKE
```

### Check if you're on Kind:

```bash
kubectl config current-context
# If it shows "kind-*", you're on Kind

kind get clusters
# Lists all Kind clusters
```

---

## Your Current Situation

Based on the error you encountered:

```
ERROR: NOT_FOUND: projects/.../clusters/kind-kind
```

**You are running:**
- ✅ Kind (local Kubernetes)
- ✅ Not on GKE

**You should use:**
- ✅ `setup-local-gcp-auth.sh`
- ❌ NOT `setup-workload-identity.sh`

---

## Migration Path

### Starting with Local Development

1. **Now:** Use JSON Key Authentication
   ```bash
   ./setup-local-gcp-auth.sh
   ```

2. **Later:** When deploying to GKE, switch to Workload Identity
   ```bash
   # On GKE cluster
   ./setup-workload-identity.sh

   # Update your pipeline (remove volume mounts for secrets)
   # The script will guide you
   ```

### Moving to Production

When you're ready to deploy to production:

1. Create a GKE cluster with Workload Identity
2. Run `setup-workload-identity.sh`
3. Update pipeline tasks to remove manual auth
4. Delete the JSON key from GCP
5. Remove the Kubernetes secret

---

## Common Scenarios

### Scenario 1: Local Development
**Cluster:** Kind/Minikube/Docker Desktop
**Setup:** `setup-local-gcp-auth.sh`
**Auth Method:** JSON Key

### Scenario 2: Production on GKE
**Cluster:** GKE
**Setup:** `setup-workload-identity.sh`
**Auth Method:** Workload Identity

### Scenario 3: Multi-Cloud (e.g., EKS + GCP)
**Cluster:** AWS EKS
**Setup:** `setup-local-gcp-auth.sh`
**Auth Method:** JSON Key (with extra security measures)

### Scenario 4: Hybrid (Local Dev + GKE Prod)
**Local:** `setup-local-gcp-auth.sh`
**GKE:** `setup-workload-identity.sh`
Use separate service accounts for each environment

---

## Need Help?

**For local setup issues:**
```bash
cat ./setup-local-gcp-auth.sh --help
```

**For GKE/Workload Identity issues:**
```bash
cat ./setup-workload-identity.sh --help
cat ../docs/GCP_AUTH_SETUP.md
```

**Still stuck?**
Check the troubleshooting section in `../docs/GCP_AUTH_SETUP.md`
