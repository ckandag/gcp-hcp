#!/bin/bash

set -e

NAMESPACE="hypershift-webhooks"
SERVICE_NAME="hypershift-autopilot-webhook"
SECRET_NAME="hypershift-autopilot-webhook-certs"

echo "Deploying HyperShift GKE Autopilot webhook..."

# Create namespace if it doesn't exist
kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

echo "Generating TLS certificates..."

# Generate private key
openssl genrsa -out webhook.key 2048

# Generate certificate signing request
cat <<EOF > csr.conf
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = CA
L = San Francisco
O = HyperShift
OU = Webhook
CN = $SERVICE_NAME.$NAMESPACE.svc

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = $SERVICE_NAME
DNS.2 = $SERVICE_NAME.$NAMESPACE
DNS.3 = $SERVICE_NAME.$NAMESPACE.svc
DNS.4 = $SERVICE_NAME.$NAMESPACE.svc.cluster.local
EOF

# Generate certificate signing request
openssl req -new -key webhook.key -out webhook.csr -config csr.conf

# Create Kubernetes CSR
cat <<EOF | kubectl apply -f -
apiVersion: certificates.k8s.io/v1
kind: CertificateSigningRequest
metadata:
  name: $SERVICE_NAME.$NAMESPACE
spec:
  request: $(cat webhook.csr | base64 | tr -d '\n')
  signerName: kubernetes.io/kubelet-serving
  usages:
  - digital signature
  - key encipherment
  - server auth
EOF

# Approve the CSR
kubectl certificate approve $SERVICE_NAME.$NAMESPACE

# Wait for certificate to be issued
echo "Waiting for certificate to be issued..."
sleep 5

# Get the certificate
kubectl get csr $SERVICE_NAME.$NAMESPACE -o jsonpath='{.status.certificate}' | base64 -d > webhook.crt

# Create the secret with TLS cert and key
kubectl create secret tls $SECRET_NAME \
  --cert=webhook.crt \
  --key=webhook.key \
  --namespace=$NAMESPACE \
  --dry-run=client -o yaml | kubectl apply -f -

# Get CA bundle for webhook configuration
CA_BUNDLE=$(kubectl config view --raw --minify --flatten -o jsonpath='{.clusters[].cluster.certificate-authority-data}')

echo "Loading webhook image into cluster..."

# Save the image and load it into the cluster (for local testing)
/opt/podman/bin/podman save localhost/hypershift-gke-autopilot-webhook:latest | docker load 2>/dev/null || echo "Docker not available, skipping image load"

# Update webhook deployment with CA bundle and deploy
echo "Deploying webhook components..."

# Apply the basic resources first (without webhook admission controller)
cat <<EOF | kubectl apply -f -
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: hypershift-autopilot-webhook
  namespace: hypershift-webhooks
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: hypershift-autopilot-webhook
rules:
- apiGroups: [""]
  resources: ["pods", "namespaces"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: hypershift-autopilot-webhook
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: hypershift-autopilot-webhook
subjects:
- kind: ServiceAccount
  name: hypershift-autopilot-webhook
  namespace: hypershift-webhooks
---
apiVersion: v1
kind: Service
metadata:
  name: hypershift-autopilot-webhook
  namespace: hypershift-webhooks
spec:
  selector:
    app: hypershift-autopilot-webhook
  ports:
  - port: 443
    targetPort: 8443
    protocol: TCP
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hypershift-autopilot-webhook
  namespace: hypershift-webhooks
  labels:
    app: hypershift-autopilot-webhook
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hypershift-autopilot-webhook
  template:
    metadata:
      labels:
        app: hypershift-autopilot-webhook
    spec:
      serviceAccountName: hypershift-autopilot-webhook
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: webhook
        image: gcr.io/<YOUR-PROJECT-ID>/hypershift-gke-autopilot-webhook:latest
        imagePullPolicy: Always
        ports:
        - containerPort: 8443
          name: https
        securityContext:
          allowPrivilegeEscalation: false
          capabilities:
            drop:
            - ALL
          readOnlyRootFilesystem: true
          runAsNonRoot: true
          runAsUser: 1001
          seccompProfile:
            type: RuntimeDefault
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
            ephemeral-storage: 1Gi
          limits:
            cpu: 200m
            memory: 128Mi
            ephemeral-storage: 1Gi
        volumeMounts:
        - name: certs
          mountPath: /etc/certs
          readOnly: true
        env:
        - name: LOG_LEVEL
          value: "info"
        livenessProbe:
          httpGet:
            path: /health
            port: 8443
            scheme: HTTPS
          initialDelaySeconds: 10
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8443
            scheme: HTTPS
          initialDelaySeconds: 5
          periodSeconds: 5
      volumes:
      - name: certs
        secret:
          secretName: hypershift-autopilot-webhook-certs
EOF

echo "Waiting for webhook deployment to be ready..."
kubectl wait --for=condition=available deployment/$SERVICE_NAME -n $NAMESPACE --timeout=300s

echo "Deploying mutating admission webhook..."

# Deploy the mutating admission webhook
cat <<EOF | kubectl apply -f -
apiVersion: admissionregistration.k8s.io/v1
kind: MutatingWebhookConfiguration
metadata:
  name: hypershift-gke-autopilot-webhook
webhooks:
- name: hypershift-autopilot-fixer.example.com
  clientConfig:
    service:
      name: hypershift-autopilot-webhook
      namespace: hypershift-webhooks
      path: "/mutate"
    caBundle: $CA_BUNDLE
  rules:
  - operations: ["CREATE", "UPDATE"]
    apiGroups: ["apps"]
    apiVersions: ["v1"]
    resources: ["deployments", "statefulsets"]
  - operations: ["CREATE"]
    apiGroups: [""]
    apiVersions: ["v1"]
    resources: ["pods"]
  admissionReviewVersions: ["v1", "v1beta1"]
  sideEffects: None
  failurePolicy: Ignore
  namespaceSelector:
    matchLabels:
      hypershift.openshift.io/hosted-control-plane: "true"
EOF

echo "Webhook deployment complete!"

# Cleanup temporary files
rm -f webhook.key webhook.csr webhook.crt csr.conf

echo ""
echo "HyperShift GKE Autopilot webhook is now installed and ready!"
echo ""
echo "The webhook will automatically fix GKE Autopilot constraints for:"
echo "  ✅ cluster-api deployment security contexts"
echo "  ✅ etcd StatefulSet CPU resource requirements"  
echo "  ✅ Pod security contexts for HyperShift components"
echo ""
echo "To test, create a HostedCluster and the webhook will automatically apply fixes."