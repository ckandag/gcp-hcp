#!/usr/bin/env bash
set -euo pipefail

# Deploys an nginx pod on a GKE cluster that serves OIDC documents from a
# private GCS bucket via GCS Fuse CSI driver, exposed publicly with HTTPS
# via GKE Ingress + ManagedCertificate.
#
# This bypasses the org policy constraint that blocks allUsers and
# cloud-cdn-fill SA -- Workload Identity uses the project's own domain.
#
# Usage:
#   ./setup-proxy-test.sh PROJECT_ID [BUCKET_SUFFIX]
#
# Environment variables:
#   REGION          GCP region (default: us-central1)
#   DNS_PROJECT     Project hosting the DNS zone (default: dev-reg-us-c1-ckandagb3fc)
#   DNS_ZONE        Cloud DNS zone name (default: dev-reg-us-c1-ckandagb3fc-tools)
#   DNS_DOMAIN      Base domain (default: dev-reg-us-c1-ckandagb3fc.dev.gcp-hcp.devshift.net)
#   GKE_CLUSTER     GKE cluster name (default: {PROJECT_ID}-gke)
#   NAMESPACE       K8s namespace (default: oidc-system)
#
# After setup completes, test with:
#   curl -s https://oidc.DNS_DOMAIN/test-cluster/.well-known/openid-configuration

PROJECT_ID="${1:?Usage: $0 PROJECT_ID [BUCKET_SUFFIX]}"
BUCKET_SUFFIX="${2:-oidc-proxy-test}"
REGION="${REGION:-us-central1}"

DNS_PROJECT="${DNS_PROJECT:-dev-reg-us-c1-ckandagb3fc}"
DNS_ZONE="${DNS_ZONE:-dev-reg-us-c1-ckandagb3fc-tools}"
DNS_DOMAIN="${DNS_DOMAIN:-dev-reg-us-c1-ckandagb3fc.dev.gcp-hcp.devshift.net}"
OIDC_SUBDOMAIN="oidc"
OIDC_FQDN="${OIDC_SUBDOMAIN}.${DNS_DOMAIN}"

GKE_CLUSTER="${GKE_CLUSTER:-${PROJECT_ID}-gke}"
NAMESPACE="${NAMESPACE:-oidc-system}"

BUCKET_NAME="${PROJECT_ID}-${BUCKET_SUFFIX}"
GSA_NAME="oidc-proxy"
GSA_EMAIL="${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
KSA_NAME="oidc-proxy"
IP_NAME="oidc-proxy-ip"
CLUSTER_PREFIX="test-cluster"

echo "=== GCP-588: OIDC Proxy Pod Workaround ==="
echo ""
echo "Project:     ${PROJECT_ID}"
echo "Cluster:     ${GKE_CLUSTER} (${REGION})"
echo "Namespace:   ${NAMESPACE}"
echo "Bucket:      gs://${BUCKET_NAME}"
echo "GSA:         ${GSA_EMAIL}"
echo "DNS:         ${OIDC_FQDN}"
echo ""

gcloud config set project "${PROJECT_ID}" --quiet

# ─── Step 1: Get GKE credentials ───
echo ">>> Step 1: Getting GKE credentials..."
# Private cluster -- use DNS endpoint for external access
gcloud container clusters get-credentials "${GKE_CLUSTER}" \
    --region="${REGION}" --project="${PROJECT_ID}" --dns-endpoint --quiet
echo "    Connected to ${GKE_CLUSTER} (via DNS endpoint)"

# ─── Step 2: Create private GCS bucket ───
echo ""
echo ">>> Step 2: Creating private GCS bucket..."
if gcloud storage buckets describe "gs://${BUCKET_NAME}" &>/dev/null; then
    echo "    Bucket gs://${BUCKET_NAME} already exists, skipping."
else
    gcloud storage buckets create "gs://${BUCKET_NAME}" \
        --project="${PROJECT_ID}" \
        --location="${REGION}" \
        --default-storage-class=STANDARD \
        --uniform-bucket-level-access
    echo "    Created bucket gs://${BUCKET_NAME} (private, uniform access)"
fi

# ─── Step 3: Upload sample OIDC documents ───
echo ""
echo ">>> Step 3: Uploading sample OIDC documents..."

ISSUER_URL="https://${OIDC_FQDN}/${CLUSTER_PREFIX}"

OIDC_DISCOVERY=$(cat <<ENDJSON
{
  "issuer": "${ISSUER_URL}",
  "jwks_uri": "${ISSUER_URL}/openid/v1/jwks",
  "response_types_supported": ["id_token"],
  "subject_types_supported": ["public"],
  "id_token_signing_alg_values_supported": ["RS256"]
}
ENDJSON
)

JWKS_DOC=$(cat <<'ENDJSON'
{
  "keys": [
    {
      "kty": "RSA",
      "alg": "RS256",
      "use": "sig",
      "kid": "test-key-1",
      "n": "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4cbbfAAtVT86zwu1RK7aPFFxuhDR1L6tSoc_BJECPebWKRXjBZCiFV4n3oknjhMstn64tZ_2W-5JsGY4Hc5n9yBXArwl93lqt7_RN5w6Cf0h4QyQ5v-65YGjQR0_FDW2QvzqY368QQMicAtaSqzs8KJZgnYb9c7d0zgdAZHzu6qMQvRL5hajrn1n91CbOpbISD08qNLyrdkt-bFTWhAI4vMQFh6WeZu0fM4lFd2NcRwr3XPksINHaQ-G_xBniIqbw0Ls1jF44-csFCur-kEgU8awapJzKnqDKgw",
      "e": "AQAB"
    }
  ]
}
ENDJSON
)

echo "${OIDC_DISCOVERY}" | gcloud storage cp - \
    "gs://${BUCKET_NAME}/${CLUSTER_PREFIX}/.well-known/openid-configuration" \
    --content-type="application/json" --quiet

echo "${JWKS_DOC}" | gcloud storage cp - \
    "gs://${BUCKET_NAME}/${CLUSTER_PREFIX}/openid/v1/jwks" \
    --content-type="application/json" --quiet

echo "    Uploaded:"
echo "      - gs://${BUCKET_NAME}/${CLUSTER_PREFIX}/.well-known/openid-configuration"
echo "      - gs://${BUCKET_NAME}/${CLUSTER_PREFIX}/openid/v1/jwks"

# ─── Step 4: Create GCP service account for the proxy ───
echo ""
echo ">>> Step 4: Creating GCP service account..."
if gcloud iam service-accounts describe "${GSA_EMAIL}" &>/dev/null; then
    echo "    GSA ${GSA_EMAIL} already exists, skipping."
else
    gcloud iam service-accounts create "${GSA_NAME}" \
        --display-name="OIDC Proxy - reads OIDC docs from GCS" \
        --project="${PROJECT_ID}"
    echo "    Created GSA: ${GSA_EMAIL}"
fi

# ─── Step 5: Grant GSA read access to the OIDC bucket ───
echo ""
echo ">>> Step 5: Granting GSA access to bucket..."
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
    --member="serviceAccount:${GSA_EMAIL}" \
    --role="roles/storage.objectViewer" \
    --quiet
echo "    Granted roles/storage.objectViewer to ${GSA_EMAIL}"

# ─── Step 6: Create K8s namespace and service account with WI binding ───
echo ""
echo ">>> Step 6: Creating K8s namespace and service account..."
kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${KSA_NAME}
  namespace: ${NAMESPACE}
  annotations:
    iam.gke.io/gcp-service-account: ${GSA_EMAIL}
EOF
echo "    Created KSA ${KSA_NAME} in ${NAMESPACE}"

# Bind KSA to GSA via Workload Identity
echo "    Binding KSA to GSA via Workload Identity..."
gcloud iam service-accounts add-iam-policy-binding "${GSA_EMAIL}" \
    --role="roles/iam.workloadIdentityUser" \
    --member="serviceAccount:${PROJECT_ID}.svc.id.goog[${NAMESPACE}/${KSA_NAME}]" \
    --project="${PROJECT_ID}" \
    --quiet
echo "    Workload Identity binding created"

# ─── Step 7: Deploy nginx with GCS Fuse CSI volume ───
echo ""
echo ">>> Step 7: Deploying nginx with GCS Fuse volume..."
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oidc-proxy
  namespace: ${NAMESPACE}
  labels:
    app: oidc-proxy
spec:
  replicas: 2
  selector:
    matchLabels:
      app: oidc-proxy
  template:
    metadata:
      labels:
        app: oidc-proxy
      annotations:
        gke-gcsfuse/volumes: "true"
    spec:
      serviceAccountName: ${KSA_NAME}
      terminationGracePeriodSeconds: 10
      containers:
      - name: nginx
        image: nginx:1.27-alpine
        ports:
        - containerPort: 80
          name: http
        readinessProbe:
          httpGet:
            path: /healthz
            port: 80
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /healthz
            port: 80
          initialDelaySeconds: 10
          periodSeconds: 30
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            memory: 128Mi
        volumeMounts:
        - name: oidc-bucket
          mountPath: /usr/share/nginx/html
          readOnly: true
        - name: nginx-conf
          mountPath: /etc/nginx/conf.d
          readOnly: true
      volumes:
      - name: oidc-bucket
        csi:
          driver: gcsfuse.csi.storage.gke.io
          readOnly: true
          volumeAttributes:
            bucketName: ${BUCKET_NAME}
            mountOptions: "implicit-dirs"
      - name: nginx-conf
        configMap:
          name: oidc-proxy-nginx-conf
EOF

# Nginx config: serve JSON with correct content-type, health endpoint
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: oidc-proxy-nginx-conf
  namespace: ${NAMESPACE}
data:
  default.conf: |
    server {
        listen 80;
        server_name _;

        root /usr/share/nginx/html;

        location /healthz {
            access_log off;
            return 200 'ok';
            add_header Content-Type text/plain;
        }

        location / {
            default_type application/json;
            add_header Cache-Control "public, max-age=3600";
            add_header X-Content-Type-Options nosniff;
            try_files \$uri =404;
        }
    }
EOF

echo "    Deployed oidc-proxy (2 replicas with GCS Fuse volume)"

# ─── Step 8: Create ClusterIP service ───
echo ""
echo ">>> Step 8: Creating service..."
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: oidc-proxy
  namespace: ${NAMESPACE}
  labels:
    app: oidc-proxy
spec:
  type: ClusterIP
  ports:
  - port: 80
    targetPort: http
    protocol: TCP
    name: http
  selector:
    app: oidc-proxy
EOF
echo "    Created ClusterIP service: oidc-proxy"

# ─── Step 9: Reserve global static IP for Ingress ───
echo ""
echo ">>> Step 9: Reserving global static IP for Ingress..."
if gcloud compute addresses describe "${IP_NAME}" --global &>/dev/null; then
    echo "    IP ${IP_NAME} already exists, skipping."
else
    gcloud compute addresses create "${IP_NAME}" \
        --network-tier=PREMIUM \
        --ip-version=IPV4 \
        --global
    echo "    Reserved global IP: ${IP_NAME}"
fi

LB_IP=$(gcloud compute addresses describe "${IP_NAME}" --format="get(address)" --global)
echo "    Ingress IP: ${LB_IP}"

# ─── Step 10: Create DNS A record ───
echo ""
echo ">>> Step 10: Creating DNS A record in ${DNS_PROJECT}..."
if gcloud dns record-sets describe "${OIDC_FQDN}." \
    --type=A --zone="${DNS_ZONE}" --project="${DNS_PROJECT}" &>/dev/null; then
    echo "    DNS record ${OIDC_FQDN} already exists, updating..."
    gcloud dns record-sets update "${OIDC_FQDN}." \
        --type=A --ttl=300 --rrdatas="${LB_IP}" \
        --zone="${DNS_ZONE}" --project="${DNS_PROJECT}"
else
    gcloud dns record-sets create "${OIDC_FQDN}." \
        --type=A --ttl=300 --rrdatas="${LB_IP}" \
        --zone="${DNS_ZONE}" --project="${DNS_PROJECT}"
fi
echo "    DNS: ${OIDC_FQDN} -> ${LB_IP}"

# ─── Step 11: Create ManagedCertificate + Ingress ───
echo ""
echo ">>> Step 11: Creating ManagedCertificate and Ingress..."
kubectl apply -f - <<EOF
apiVersion: networking.gke.io/v1
kind: ManagedCertificate
metadata:
  name: oidc-proxy-cert
  namespace: ${NAMESPACE}
spec:
  domains:
  - ${OIDC_FQDN}
EOF

kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: oidc-proxy
  namespace: ${NAMESPACE}
  annotations:
    kubernetes.io/ingress.global-static-ip-name: ${IP_NAME}
    networking.gke.io/managed-certificates: oidc-proxy-cert
    kubernetes.io/ingress.class: gce
spec:
  defaultBackend:
    service:
      name: oidc-proxy
      port:
        number: 80
EOF
echo "    Created ManagedCertificate and Ingress"
echo "    NOTE: Certificate provisioning takes ~10-30 min after DNS propagates"

# ─── Wait for deployment rollout ───
echo ""
echo ">>> Waiting for deployment rollout..."
kubectl rollout status deployment/oidc-proxy -n "${NAMESPACE}" --timeout=300s || true

# ─── Check certificate status ───
echo ""
echo ">>> Checking ManagedCertificate status..."
CERT_STATUS=$(kubectl get managedcertificate oidc-proxy-cert -n "${NAMESPACE}" \
    -o jsonpath='{.status.certificateStatus}' 2>/dev/null || echo "Pending")
echo "    Certificate status: ${CERT_STATUS}"

# ─── Summary ───
echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "Resources created:"
echo ""
echo "  GCP:"
echo "    Bucket:         gs://${BUCKET_NAME} (private)"
echo "    GSA:            ${GSA_EMAIL}"
echo "    Static IP:      ${LB_IP} (${IP_NAME})"
echo "    DNS:            ${OIDC_FQDN} -> ${LB_IP}"
echo ""
echo "  Kubernetes (namespace: ${NAMESPACE}):"
echo "    ServiceAccount: ${KSA_NAME} (WI -> ${GSA_EMAIL})"
echo "    Deployment:     oidc-proxy (2 replicas, nginx + GCS Fuse)"
echo "    Service:        oidc-proxy (ClusterIP:80)"
echo "    Ingress:        oidc-proxy (global static IP)"
echo "    Certificate:    oidc-proxy-cert (${CERT_STATUS})"
echo ""
echo "Issuer URL: https://${OIDC_FQDN}/${CLUSTER_PREFIX}"
echo ""
if [[ "${CERT_STATUS}" != "Active" ]]; then
    echo "Certificate is still provisioning. Check status with:"
    echo "  kubectl get managedcertificate oidc-proxy-cert -n ${NAMESPACE}"
    echo ""
    echo "Once Active, test with:"
else
    echo "Test with:"
fi
echo ""
echo "  # OIDC discovery document"
echo "  curl -s https://${OIDC_FQDN}/${CLUSTER_PREFIX}/.well-known/openid-configuration | jq ."
echo ""
echo "  # JWKS document"
echo "  curl -s https://${OIDC_FQDN}/${CLUSTER_PREFIX}/openid/v1/jwks | jq ."
echo ""
echo "  # Test via HTTP (should work immediately via pod port-forward):"
echo "  kubectl port-forward -n ${NAMESPACE} svc/oidc-proxy 8080:80"
echo "  curl -s http://localhost:8080/${CLUSTER_PREFIX}/.well-known/openid-configuration | jq ."
echo ""
echo "To clean up: ./cleanup-proxy-test.sh ${PROJECT_ID} ${BUCKET_SUFFIX}"
