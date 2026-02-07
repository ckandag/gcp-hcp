#!/usr/bin/env python3
"""
Step 5: Deploy Pod Security Webhook
Deploying Pod Security Webhook
"""

import time
from pathlib import Path
from common import BaseStep, installation_step, Colors


class DeployWebhookStep(BaseStep):
    """Step 5: Deploy Pod Security Webhook with integrated functionality"""

    @installation_step("deploy_webhook", "Deploying Pod Security Webhook")
    def execute(self) -> bool:
        """Step 5: Deploy Pod Security Webhook (MANDATORY for GKE compatibility)"""
        # Use GKE management cluster kubeconfig
        self.env_gke = {'KUBECONFIG': self.config.kubeconfig_gke_path}

        self.logger.info(f"{Colors.CYAN}🔒{Colors.END} Pod Security Webhook is MANDATORY for GKE compatibility")

        webhook_dir = Path("../webhook")
        if not webhook_dir.exists():
            self.logger.error(f"❌ Webhook directory {webhook_dir} not found - webhook deployment is REQUIRED")
            return False

        # Check if webhook is fully deployed (deployment + MutatingWebhookConfiguration)
        deployment_exists, _ = self.runner.run(f"KUBECONFIG={self.config.kubeconfig_gke_path} kubectl get deployment hypershift-autopilot-webhook -n hypershift-webhooks", env=self.env_gke)
        webhook_config_exists, _ = self.runner.run(f"KUBECONFIG={self.config.kubeconfig_gke_path} kubectl get mutatingwebhookconfiguration hypershift-gke-autopilot-webhook", env=self.env_gke)

        if deployment_exists and webhook_config_exists:
            self.logger.info("Pod Security Webhook already fully deployed")
            return True

        if deployment_exists and not webhook_config_exists:
            self.logger.info(f"{Colors.YELLOW}⚠{Colors.END} Webhook deployment exists but MutatingWebhookConfiguration missing, redeploying...")
        elif not deployment_exists:
            self.logger.info("Deploying Pod Security Webhook...")

        # Deploy webhook using integrated Python implementation
        return self._deploy_webhook_integrated(webhook_dir)

    def _deploy_webhook_integrated(self, webhook_dir: Path) -> bool:
        """Deploy webhook using integrated Python implementation"""
        try:
            # Step 1: Create namespace
            success, _ = self.runner.run(f"KUBECONFIG={self.config.kubeconfig_gke_path} kubectl create namespace hypershift-webhooks --dry-run=client -o yaml | KUBECONFIG={self.config.kubeconfig_gke_path} kubectl apply -f -", env=self.env_gke)
            if not success:
                return False

            # Step 2: Enable GCR API
            success, _ = self.runner.run(f"gcloud services enable containerregistry.googleapis.com --project={self.config.project_id}")
            if not success:
                return False

            # Step 3: Authenticate with container registry
            self.logger.info("🔐 Authenticating with container registry...")
            success, _ = self.runner.run(
                f'{self.config.podman_path} login -u oauth2accesstoken -p "$(gcloud auth print-access-token)" gcr.io'
            )
            if not success:
                self.logger.error("❌ Failed to authenticate with container registry - REQUIRED for webhook deployment")
                return False

            # Step 4: Build and push webhook image
            image_name = f"gcr.io/{self.config.project_id}/hypershift-gke-autopilot-webhook:{self.config.webhook_image_tag}"
            self.logger.info(f"🔨 Building webhook image: {image_name}")
            success, _ = self.runner.run(
                f"{self.config.podman_path} build --platform linux/amd64 -t {image_name} .",
                timeout=600,
                cwd=str(webhook_dir)
            )
            if not success:
                self.logger.error("❌ Failed to build webhook image - REQUIRED for webhook deployment")
                return False

            self.logger.info(f"📤 Pushing webhook image to registry...")
            success, _ = self.runner.run(f"{self.config.podman_path} push {image_name}", timeout=300)
            if not success:
                self.logger.error("❌ Failed to push webhook image - REQUIRED for webhook deployment")
                return False

            # Step 5: Generate TLS certificates
            if not self._generate_webhook_certificates():
                return False

            # Step 6: Deploy webhook resources
            if not self._deploy_webhook_resources(image_name):
                return False

            # Step 7: Wait for webhook deployment to be ready
            self.logger.info("⏳ Waiting for webhook deployment to be ready...")
            success, _ = self.runner.run(
                "kubectl wait --for=condition=available deployment/hypershift-autopilot-webhook -n hypershift-webhooks --timeout=300s",
                env=self.env_gke
            )
            if not success:
                self.logger.error("❌ Webhook deployment failed to become ready - REQUIRED for GKE compatibility")
                return False

            # Step 8: Deploy MutatingWebhookConfiguration
            if not self._deploy_webhook_configuration():
                return False

            # Step 9: Cleanup temporary files
            self._cleanup_webhook_temp_files()

            self.logger.info(f"{Colors.GREEN}✓{Colors.END} Webhook deployment complete!")
            return True

        except Exception as e:
            self.logger.error(f"❌ Critical exception during webhook deployment: {e}")
            self._cleanup_webhook_temp_files()
            return False  # Fail the installation if webhook fails - it's MANDATORY

    def _generate_webhook_certificates(self) -> bool:
        """Generate TLS certificates for webhook"""
        self.logger.info("Generating TLS certificates...")

        service_name = "hypershift-autopilot-webhook"
        namespace = "hypershift-webhooks"

        # Generate private key
        success, _ = self.runner.run("openssl genrsa -out /tmp/webhook.key 2048")
        if not success:
            return False

        # Create CSR configuration
        csr_conf = f"""[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = CA
L = San Francisco
O = HyperShift
OU = Webhook
CN = {service_name}.{namespace}.svc

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = {service_name}
DNS.2 = {service_name}.{namespace}
DNS.3 = {service_name}.{namespace}.svc
DNS.4 = {service_name}.{namespace}.svc.cluster.local
"""

        with open('/tmp/csr.conf', 'w') as f:
            f.write(csr_conf)

        # Generate certificate signing request
        success, _ = self.runner.run("openssl req -new -key /tmp/webhook.key -out /tmp/webhook.csr -config /tmp/csr.conf")
        if not success:
            return False

        # Create Kubernetes CSR
        success, csr_b64 = self.runner.run("cat /tmp/webhook.csr | base64 | tr -d '\\n'", check_output=True)
        if not success:
            return False

        csr_yaml = f"""apiVersion: certificates.k8s.io/v1
kind: CertificateSigningRequest
metadata:
  name: {service_name}.{namespace}
spec:
  request: {csr_b64}
  signerName: kubernetes.io/kubelet-serving
  usages:
  - digital signature
  - key encipherment
  - server auth
"""

        with open('/tmp/webhook-csr.yaml', 'w') as f:
            f.write(csr_yaml)

        # Apply and approve CSR
        success, _ = self.runner.run("kubectl apply -f /tmp/webhook-csr.yaml", env=self.env_gke)
        if not success:
            return False

        success, _ = self.runner.run(f"kubectl certificate approve {service_name}.{namespace}", env=self.env_gke)
        if not success:
            return False

        # Wait for certificate to be issued
        self.logger.info("Waiting for certificate to be issued...")
        time.sleep(5)

        # Get the certificate
        success, _ = self.runner.run(
            f"KUBECONFIG={self.config.kubeconfig_gke_path} kubectl get csr {service_name}.{namespace} -o jsonpath='{{.status.certificate}}' | base64 -d > /tmp/webhook.crt",
            env=self.env_gke
        )
        if not success:
            return False

        # Create the secret with TLS cert and key
        success, _ = self.runner.run(
            f"KUBECONFIG={self.config.kubeconfig_gke_path} kubectl create secret tls hypershift-autopilot-webhook-certs "
            f"--cert=/tmp/webhook.crt --key=/tmp/webhook.key --namespace={namespace} "
            f"--dry-run=client -o yaml | KUBECONFIG={self.config.kubeconfig_gke_path} kubectl apply -f -",
            env=self.env_gke
        )
        if not success:
            return False

        return True

    def _deploy_webhook_resources(self, image_name: str) -> bool:
        """Deploy webhook ServiceAccount, RBAC, Service, and Deployment"""
        self.logger.info("Deploying webhook components...")

        # Apply the basic resources
        webhook_resources = f"""---
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
        image: {image_name}
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
"""

        with open('/tmp/webhook-resources.yaml', 'w') as f:
            f.write(webhook_resources)

        success, _ = self.runner.run("kubectl apply -f /tmp/webhook-resources.yaml", env=self.env_gke)
        return success

    def _deploy_webhook_configuration(self) -> bool:
        """Deploy MutatingWebhookConfiguration"""
        self.logger.info("Deploying mutating admission webhook...")

        # Get CA bundle for webhook configuration
        success, ca_bundle = self.runner.run(
            "kubectl config view --raw --minify --flatten -o jsonpath='{.clusters[].cluster.certificate-authority-data}'",
            check_output=True,
            env=self.env_gke
        )
        if not success:
            return False

        webhook_config = f"""apiVersion: admissionregistration.k8s.io/v1
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
    caBundle: {ca_bundle}
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
"""

        with open('/tmp/webhook-config.yaml', 'w') as f:
            f.write(webhook_config)

        success, _ = self.runner.run("kubectl apply -f /tmp/webhook-config.yaml", env=self.env_gke)
        if not success:
            return False

        # Verify webhook configuration exists
        max_attempts = 10
        for attempt in range(max_attempts):
            webhook_config_exists, _ = self.runner.run("kubectl get mutatingwebhookconfiguration hypershift-gke-autopilot-webhook", env=self.env_gke)
            if webhook_config_exists:
                self.logger.info(f"{Colors.GREEN}✓{Colors.END} Webhook MutatingWebhookConfiguration is active")
                return True
            self.logger.info(f"Waiting for webhook configuration... (attempt {attempt + 1}/{max_attempts})")
            time.sleep(10)

        self.logger.warning("Webhook configuration not found, but continuing installation...")
        return True

    def _cleanup_webhook_temp_files(self):
        """Clean up temporary webhook files"""
        temp_files = [
            '/tmp/webhook.key',
            '/tmp/webhook.csr',
            '/tmp/webhook.crt',
            '/tmp/csr.conf',
            '/tmp/webhook-csr.yaml',
            '/tmp/webhook-resources.yaml',
            '/tmp/webhook-config.yaml'
        ]

        for file_path in temp_files:
            try:
                if Path(file_path).exists():
                    Path(file_path).unlink()
            except Exception:
                pass  # Ignore cleanup errors