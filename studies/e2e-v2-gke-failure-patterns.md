# `e2e-v2-gke` Known Failure Patterns

This page catalogs the recurring, non-code failure modes seen on `pull-ci-openshift-hypershift-main-e2e-v2-gke` — a record of what kinds of errors actually show up on this job, why they happen, and what typically resolves them, independent of any specific PR.

> **Headline finding:** The large majority of observed failures are CI infrastructure flakiness, not product or test regressions. Only a small minority are genuine signals worth escalating to a code owner.

---

## Quick classification table

| # | Category | Signature (grep for) | Typical step | Root cause | PRs observed on |
|---|----------|----------------------|--------------|-------------|------------------|
| 1 | [DNS resolution failure](#1-dns-resolution-failures-to-google-apis) | `Name or service not known`, `lookup ... no such host` | `wif-auth`, `gke-provision`, `control-plane-setup`, `hosted-cluster-setup` | CI pod can't resolve `sts.googleapis.com` / `compute.googleapis.com` / `iamcredentials.googleapis.com` | [#8681](https://github.com/openshift/hypershift/pull/8681), [#8882](https://github.com/openshift/hypershift/pull/8882), [#9218](https://github.com/openshift/hypershift/pull/9218), [#9229](https://github.com/openshift/hypershift/pull/9229), [#9192](https://github.com/openshift/hypershift/pull/9192) |
| 2 | [Build farm capacity](#2-build-farm-capacity-src-arm64-build-pod-pending) | `didn't start running within 1h0m0s (phase: Pending)`, `max node group size reached` | `src-arm64-build` (pre-test, image build) | arm64 build-worker node pool at capacity ceiling | [#9192](https://github.com/openshift/hypershift/pull/9192) (4 builds) |
| 3 | [Deployment rollout timeout](#3-deployment-rollout-timeouts) | `error: timed out waiting for the condition` on `rollout status` | `control-plane-setup`, `gke-prerequisites` | Operator/cert-manager pod slow to become ready under CI load | [#9162](https://github.com/openshift/hypershift/pull/9162), [#8579](https://github.com/openshift/hypershift/pull/8579) |
| 4 | [Pod eviction](#4-pod-eviction-diskpressure) | `Evicted`, `The node was low on resource: ephemeral-storage` | Any step | CI node hit DiskPressure | [#8884](https://github.com/openshift/hypershift/pull/8884) |
| 5 | [Empty manifest / step bug](#5-empty-manifest-ci-step-rendering-bug) | `error: no objects passed to apply` | `gke-prerequisites` | CI step template rendered an empty file for that run | [#8916](https://github.com/openshift/hypershift/pull/8916) |
| 6 | [Already-fixed issue](#6-already-fixed-known-issues) | `packages.microsoft.com`, GPG import failure in Docker build | `src`/`src-arm64` image build | Stale image predates a merged fix | [#9192](https://github.com/openshift/hypershift/pull/9192) (pre-[#9290](https://github.com/openshift/hypershift/pull/9290) fix) |
| 7 | [Externally terminated](#7-externally-terminated--aborted) | `Entrypoint received interrupt: terminated` | Any step | Job killed externally (new commit pushed, manual abort, Prow restart) | [#9275](https://github.com/openshift/hypershift/pull/9275), [#9282](https://github.com/openshift/hypershift/pull/9282) |
| 8 | [Control-plane crash during tests](#8-control-plane-crash-during-tests) | `[FAIL]` in Ginkgo output, `should have no crashing pods` | `tests` (after all pre-steps pass) | Control-plane component crashed during the test run; cause undetermined without further debugging | [#9256](https://github.com/openshift/hypershift/pull/9256), [#9287](https://github.com/openshift/hypershift/pull/9287) |

---

## 1. DNS resolution failures to Google APIs

**Signature:**
```
ERROR: (gcloud.config.set) There was a problem refreshing your current auth tokens:
HTTPSConnectionPool(host='sts.googleapis.com', port=443): Max retries exceeded with url: /v1/token
(Caused by NewConnectionError('Failed to establish a new connection: [Errno -2] Name or service not known'))
```

Observed against multiple Google endpoints depending on which step ran at the time: `sts.googleapis.com` (WIF token refresh), `iamcredentials.googleapis.com` (`wif-auth`), `compute.googleapis.com` (PSC subnet / GKE provisioning).

**Root cause:** The CI pod's DNS resolver intermittently fails to resolve Google API hostnames. This is infrastructure-level flakiness in the OpenShift CI cluster's DNS path (CoreDNS under load, no local caching), unrelated to HyperShift code or the GCP platform implementation.

**Why it's the dominant failure mode:** Every `e2e-v2-gke` run makes dozens of GCP API calls across `gke-provision`, `wif-auth`, `control-plane-setup`, and `hosted-cluster-setup`. Each call is a fresh opportunity to hit a transient DNS blip, so this category dominates until it's addressed at the infra layer.

**Observed on:** [#8681](https://github.com/openshift/hypershift/pull/8681) (`gke-provision`, `compute.googleapis.com`), [#8882](https://github.com/openshift/hypershift/pull/8882) (`wif-auth`, `iamcredentials.googleapis.com`), [#9218](https://github.com/openshift/hypershift/pull/9218) (2 builds — `control-plane-setup` and `hosted-cluster-setup`, `sts.googleapis.com` / `compute.googleapis.com`), [#9229](https://github.com/openshift/hypershift/pull/9229) (`hosted-cluster-setup`, `sts.googleapis.com`), [#9192](https://github.com/openshift/hypershift/pull/9192) (`gke-provision`, `sts.googleapis.com`).

**Possible remedy:** A retry typically clears it, since the failure is transient and unrelated to the PR's diff. Failures that repeat identically 2-3 times in a row on the same PR are a stronger signal of the underlying DNS flakiness rather than the change itself (see [stability improvements](#possible-stability-improvements) below).

---

## 2. Build farm capacity (`src-arm64-build` pod Pending)

**Signature:**
```
0/64-67 nodes are available: 14-18 node(s) didn't match Pod's node affinity/selector,
44-51 node(s) had untolerated taint(s), 1-7 node(s) were unschedulable
cluster-autoscaler: pod didn't trigger scale-up: ... max node group size reached ...
```
Step fails after exactly ~1h with `build didn't start running within 1h0m0s (phase: Pending)`, or fails fast (~15s) if the pod is later evaluated as unschedulable outright.

**Root cause:** `ci-operator` builds a `pipeline:src` image per target architecture (`src` for amd64, `src-arm64` for arm64) before any test logic runs. The arm64 build pod requires nodes that are simultaneously (a) tainted for `ci-builds-worker`, (b) `kubernetes.io/arch=arm64`, and (c) within the autoscaler's configured max size for that node group. When the arm64 build-worker pool is already at its ceiling, no combination satisfies all three and the pod sits `Pending` until the build step's 1-hour timeout expires.

This happens **before** the e2e test itself starts, so it affects every multi-arch OpenShift CI job during that time window — it is not specific to `hypershift` or `e2e-v2-gke`.

**Observed on:** [#9192](https://github.com/openshift/hypershift/pull/9192) — 4 separate builds, all clustered in the same ~01:26–04:37 UTC window on Aug 12, confirming it was a shared build-farm capacity crunch at that time rather than anything PR-specific.

**Possible remedy:** Resolves once the shared arm64 build-worker pool frees up capacity — a retry usually succeeds at that point. If the pattern recurs frequently rather than showing up as an occasional capacity blip, raising the arm64 node pool's autoscaler max size with DPTP would address it at the source.

---

## 3. Deployment rollout timeouts

**Signature:**
```
error: timed out waiting for the condition
```
on an `oc rollout status deployment/operator` (in `control-plane-setup`) or a `cert-manager` deployment wait (in `gke-prerequisites`), typically after 300s.

**Root cause:** Pod scheduling/image-pull/readiness on a loaded CI-provisioned GKE cluster occasionally exceeds the fixed rollout wait window. Usually resource contention or image pull latency on the ephemeral GKE cluster, not an application bug — though a deployment that times out on every run of the same PR would point toward the change affecting that deployment's readiness rather than CI noise.

**Observed on:** [#9162](https://github.com/openshift/hypershift/pull/9162) (`control-plane-setup`, operator rollout), [#8579](https://github.com/openshift/hypershift/pull/8579) (`gke-prerequisites`, `cert-manager` deployment).

**Possible remedy:** Usually clears on a single retry. Repeated timeouts of the *same* deployment on the same PR would warrant checking whether the change affects that deployment's readiness probe, resource requests, or startup dependencies.

---

## 4. Pod eviction (DiskPressure)

**Signature:**
```
Status: Evicted
Reason: The node was low on resource: ephemeral-storage.
```

**Root cause:** The underlying CI node ran low on ephemeral storage (build artifacts, container image layers, logs accumulating) and the kubelet evicted a pod to reclaim space. Purely a CI-node capacity issue.

**Observed on:** [#8884](https://github.com/openshift/hypershift/pull/8884) (`gke-prerequisites`).

**Possible remedy:** A retry almost always lands on a healthier node.

---

## 5. Empty manifest / CI step rendering bug

**Signature:**
```
error: no objects passed to apply
```
in `gke-prerequisites`.

**Root cause:** The step's template rendered to an empty file for that particular run — most likely a race or transient bug in the CI step registry logic (`openshift/release`), not something wrong with the target manifest content itself (the same step succeeds on retries and on other PRs).

**Observed on:** [#8916](https://github.com/openshift/hypershift/pull/8916) (`gke-prerequisites`).

**Possible remedy:** A retry typically resolves it, since the same step succeeds on other runs. A failure that reproduces consistently across retries would point to a genuine bug in the `hypershift/gcp` step registry definitions in `openshift/release`.

---

## 6. Already-fixed known issues

**Signature (example, resolved):**
```
GPG key import failure fetching packages.microsoft.com/keys/microsoft.asc
```
during the `src`/`src-arm64` Docker image build.

**Root cause:** A specific dependency-fetch step (e.g., importing a third-party GPG key for a package repo) started failing upstream. This was fixed in [PR #9290](https://github.com/openshift/hypershift/pull/9290) by disabling `repo_gpgcheck` for the Microsoft package repo in the Dockerfile.

**Observed on:** [#9192](https://github.com/openshift/hypershift/pull/9192) (`src`/`src-arm64` image build, before the fix landed).

**Possible remedy:** Resolves by rebasing onto latest `main` (or later), since the failure only occurs against a stale base commit that predates the fix.

This section exists to track known, previously-recurring failures that have since been fixed upstream, so the same signature isn't re-diagnosed from scratch in future analysis.

---

## 7. Externally terminated / aborted

**Signature:**
```
Entrypoint received interrupt: terminated
```

**Root cause:** The job was killed from outside the test itself — usually because a new commit was pushed to the PR (Prow cancels in-flight runs for superseded commits) or the job was manually aborted/restarted.

**Observed on:** [#9275](https://github.com/openshift/hypershift/pull/9275), [#9282](https://github.com/openshift/hypershift/pull/9282).

**Possible remedy:** Not a real failure — a new run is typically already in flight for the latest commit. If the check still shows red with no newer run active, a retry clears it.

---

## 8. Control-plane crash during tests

**Signature:** A `[FAIL]` in the Ginkgo output *after* all pre-steps (`create-hostedcluster`) succeeded and the `tests` step actually ran — i.e., the job got all the way to real test execution before failing.

**Examples observed:**

- [#9256](https://github.com/openshift/hypershift/pull/9256): `[sig-hypershift][Feature:ControlPlaneWorkloads] Control Plane Workloads → No crashing pods → csi-snapshot-controller → should have no crashing pods` (399 passed, 1 failed)
- [#9287](https://github.com/openshift/hypershift/pull/9287): `[sig-hypershift][Feature:ControlPlaneWorkloads] Control Plane Workloads → No crashing pods → kube-apiserver → should have no crashing pods` (flagged for follow-up with [csrwng](https://github.com/csrwng); pending retest at time of triage)

**What happened:** Unlike the categories above, these got past all pre-steps and the hosted cluster came up, but a control-plane component (`csi-snapshot-controller`, `kube-apiserver`) crashed during the test run itself. That alone doesn't say much about the cause — it could be the PR's change, an unrelated upstream image/payload issue, or plain flakiness in that control-plane component. Further debugging is needed to tell which.

**Possible remedy:** Not reliably resolved by a blanket retry. Narrowing it down requires checking the crashing pod's logs in the `dump` step artifacts (`artifacts/e2e-v2-gke/dump/artifacts/namespaces/clusters-<hc-name>/core/pods/logs/`) and cross-referencing whether the PR's diff plausibly touches that component (e.g., a shared config hash, a shared image reference, an API type change). If nothing in the diff explains it, it's likely control-plane flakiness rather than a regression.

---

## Possible stability improvements

Since DNS resolution failures (category 1) are the single largest source of noise, these are the areas where a fix would have the most leverage. Roughly ordered by effort vs. impact:

**Within HyperShift repo/test control:**

1. **Retry wrapper around GCP client init/first calls** — wrapping `gke-provision`, `wif-auth`, and token-refresh calls with exponential backoff (e.g., 3 retries at 5s/10s/20s) would prevent a single transient DNS blip from failing the whole step.
2. **Detect-and-retry in CI step scripts** — a check for `dial tcp: lookup ... no such host` / `Name or service not known` in step scripts, retrying the specific `gcloud`/API call rather than failing the entire step.

**Requires CI infra / Test Platform team:**

3. **NodeLocal DNSCache** — the standard Kubernetes fix for DNS flakiness at scale; caches DNS responses on each node, insulating workloads from CoreDNS overload or upstream resolution hiccups.
4. **CoreDNS tuning** — more CoreDNS replicas, `autopath`, or fallback `forward` to `8.8.8.8`/`8.8.4.4`.

**Test design:**

5. **Idempotent setup steps** — ensuring `gke-provision` / `wif-auth` / `control-plane-setup` can be safely retried end-to-end without leaking partially-created GCP resources would make a Prow-level auto-retry-on-known-flake policy viable.

For the arm64 build-farm capacity issue (category 2), there's no fix available from the hypershift repo — it would require DPTP to raise the arm64 `ci-builds-worker` node pool's autoscaler max size, which is only worthwhile if the pattern becomes frequent rather than an occasional capacity blip.

---

## Methodology

Each failure was classified by matching its `build-log.txt` against the signature strings in the [classification table](#quick-classification-table), then reading the surrounding log context to confirm the root cause and (where relevant) which pipeline step it occurred in. Categories 1–7 represent CI infrastructure patterns confirmed to be unrelated to the PR's code; category 8 covers cases where the failure occurred after all setup steps succeeded and pointed to an actual control-plane issue.

## Data set / sources

Based on manual analysis of the following PRs against `pull-ci-openshift-hypershift-main-e2e-v2-gke` between Aug 7–12, 2026: #8579, #8681, #8882, #8884, #8916, #9162, #9192 (7 builds), #9218 (2 builds), #9229, #9256, #9275, #9282, #9287. Job history: `https://prow.ci.openshift.org/job-history/gs/test-platform-results/pr-logs/directory/pull-ci-openshift-hypershift-main-e2e-v2-gke`.
