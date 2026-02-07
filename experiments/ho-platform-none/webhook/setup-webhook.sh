#!/bin/bash

set -e

NAMESPACE="hypershift-webhooks"
SERVICE_NAME="hypershift-autopilot-webhook"
SECRET_NAME="hypershift-autopilot-webhook-certs"

echo "Setting up HyperShift GKE Autopilot webhook..."

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

echo "Building webhook container image..."

# Build the webhook image
cd webhook
docker build -t hypershift-gke-autopilot-webhook:latest .
cd ..

# Load image into kind cluster if using kind
if kubectl config current-context | grep -q kind; then
    echo "Loading image into kind cluster..."
    kind load docker-image hypershift-gke-autopilot-webhook:latest
fi

echo "Deploying webhook..."

# Update webhook deployment with CA bundle
sed "s/caBundle: \"\"/caBundle: $CA_BUNDLE/" webhook-deployment.yaml > webhook-deployment-configured.yaml

# Apply the webhook deployment
kubectl apply -f webhook-deployment-configured.yaml

echo "Waiting for webhook deployment to be ready..."
kubectl wait --for=condition=available deployment/$SERVICE_NAME -n $NAMESPACE --timeout=300s

echo "Webhook setup complete!"

# Cleanup temporary files
rm -f webhook.key webhook.csr webhook.crt csr.conf webhook-deployment-configured.yaml

echo "HyperShift GKE Autopilot webhook is now installed and ready to use."
echo ""
echo "To test the webhook, create a HostedCluster in a namespace with the label:"
echo "  hypershift.openshift.io/hosted-control-plane: \"true\""
echo ""
echo "The webhook will automatically fix:"
echo "  - cluster-api deployment security contexts"
echo "  - etcd StatefulSet CPU resource requirements"
echo "  - Pod security contexts for all HyperShift components"