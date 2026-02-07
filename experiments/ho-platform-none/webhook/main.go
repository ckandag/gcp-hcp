package main

import (
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"

	admissionv1 "k8s.io/api/admission/v1"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/serializer"
)

var (
	scheme = runtime.NewScheme()
	codecs = serializer.NewCodecFactory(scheme)
)

type WebhookServer struct {
	server *http.Server
}

type patchOperation struct {
	Op    string      `json:"op"`
	Path  string      `json:"path"`
	Value interface{} `json:"value,omitempty"`
}

func main() {
	certPath := "/etc/certs/tls.crt"
	keyPath := "/etc/certs/tls.key"

	cert, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		log.Fatalf("Failed to load key pair: %v", err)
	}

	server := &WebhookServer{
		server: &http.Server{
			Addr:      ":8443",
			TLSConfig: &tls.Config{Certificates: []tls.Certificate{cert}},
		},
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/mutate", server.mutate)
	mux.HandleFunc("/health", server.health)
	server.server.Handler = mux

	log.Println("Starting HyperShift GKE Autopilot webhook server on :8443")
	if err := server.server.ListenAndServeTLS("", ""); err != nil {
		log.Fatalf("Failed to start webhook server: %v", err)
	}
}

func (ws *WebhookServer) health(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	w.Write([]byte("OK"))
}

func (ws *WebhookServer) mutate(w http.ResponseWriter, r *http.Request) {
	var body []byte
	if r.Body != nil {
		if data, err := io.ReadAll(r.Body); err == nil {
			body = data
		}
	}

	if len(body) == 0 {
		log.Println("Empty request body")
		http.Error(w, "Empty request body", http.StatusBadRequest)
		return
	}

	var admissionReview admissionv1.AdmissionReview
	if err := json.Unmarshal(body, &admissionReview); err != nil {
		log.Printf("Could not decode admission review: %v", err)
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	req := admissionReview.Request
	var patches []patchOperation

	// Check if this is a HyperShift control plane namespace
	namespace := req.Namespace
	if !isHyperShiftControlPlane(namespace) {
		log.Printf("Skipping non-HyperShift namespace: %s", namespace)
		ws.sendResponse(w, &admissionReview, patches)
		return
	}

	log.Printf("Processing %s %s in namespace %s", req.Kind.Kind, req.Name, namespace)

	switch req.Kind.Kind {
	case "Deployment":
		patches = ws.mutateDeployment(req, patches)
	case "StatefulSet":
		patches = ws.mutateStatefulSet(req, patches)
	case "Pod":
		patches = ws.mutatePod(req, patches)
	}

	log.Printf("Applied %d patches to %s %s", len(patches), req.Kind.Kind, req.Name)
	ws.sendResponse(w, &admissionReview, patches)
}

func (ws *WebhookServer) mutateDeployment(req *admissionv1.AdmissionRequest, patches []patchOperation) []patchOperation {
	var deployment appsv1.Deployment
	if err := json.Unmarshal(req.Object.Raw, &deployment); err != nil {
		log.Printf("Could not unmarshal deployment: %v", err)
		return patches
	}

	// Apply generic GKE Autopilot fixes to all HyperShift control plane deployments
	log.Printf("Applying generic GKE Autopilot fixes for deployment %s", deployment.Name)
	
	// Check if deployment has anti-affinity rules (requires 500m CPU minimum)
	hasAntiAffinity := ws.hasAntiAffinityRules(&deployment)
	
	// Apply generic fixes based on deployment characteristics
	patches = append(patches, ws.fixGenericDeploymentForGKEAutopilot(&deployment, hasAntiAffinity)...)
	
	// Apply specific fixes for known components that need special handling
	switch deployment.Name {
	case "kube-apiserver":
		log.Println("Applying additional kube-apiserver specific fixes")
		patches = append(patches, ws.fixKubeAPIServerSpecificPatches()...)
	case "etcd":
		// etcd is handled as StatefulSet, not Deployment
	default:
		// All other deployments get generic treatment only
	}

	return patches
}

func (ws *WebhookServer) mutateStatefulSet(req *admissionv1.AdmissionRequest, patches []patchOperation) []patchOperation {
	var statefulSet appsv1.StatefulSet
	if err := json.Unmarshal(req.Object.Raw, &statefulSet); err != nil {
		log.Printf("Could not unmarshal statefulset: %v", err)
		return patches
	}

	// Fix etcd StatefulSet
	if statefulSet.Name == "etcd" {
		log.Println("Applying etcd fixes for GKE Autopilot")
		patches = append(patches, ws.fixEtcdResources()...)
	}

	return patches
}

func (ws *WebhookServer) mutatePod(req *admissionv1.AdmissionRequest, patches []patchOperation) []patchOperation {
	var pod corev1.Pod
	if err := json.Unmarshal(req.Object.Raw, &pod); err != nil {
		log.Printf("Could not unmarshal pod: %v", err)
		return patches
	}

	// Apply general security context fixes for all HyperShift pods
	if hasHyperShiftLabels(pod.Labels) {
		log.Printf("Applying general security context fixes for pod %s", pod.Name)
		patches = append(patches, ws.fixPodSecurityContext()...)
	}

	return patches
}

func (ws *WebhookServer) fixClusterAPISecurityContext() []patchOperation {
	return []patchOperation{
		{
			Op:   "add",
			Path: "/spec/template/spec/securityContext",
			Value: map[string]interface{}{
				"runAsNonRoot": true,
				"runAsUser":    1001,
				"seccompProfile": map[string]interface{}{
					"type": "RuntimeDefault",
				},
			},
		},
		{
			Op:   "replace",
			Path: "/spec/template/spec/containers/0/securityContext",
			Value: map[string]interface{}{
				"allowPrivilegeEscalation": false,
				"capabilities": map[string]interface{}{
					"drop": []string{"ALL"},
				},
				"readOnlyRootFilesystem": true,
				"runAsNonRoot":           true,
				"runAsUser":              1001,
				"seccompProfile": map[string]interface{}{
					"type": "RuntimeDefault",
				},
			},
		},
	}
}

func (ws *WebhookServer) fixControlPlaneOperatorSecurityContext() []patchOperation {
	return []patchOperation{
		{
			Op:   "add",
			Path: "/spec/template/spec/securityContext",
			Value: map[string]interface{}{
				"runAsNonRoot": true,
				"runAsUser":    1001,
				"seccompProfile": map[string]interface{}{
					"type": "RuntimeDefault",
				},
			},
		},
		{
			Op:   "replace",
			Path: "/spec/template/spec/containers/0/securityContext",
			Value: map[string]interface{}{
				"allowPrivilegeEscalation": false,
				"capabilities": map[string]interface{}{
					"drop": []string{"ALL"},
				},
				"readOnlyRootFilesystem": true,
				"runAsNonRoot":           true,
				"runAsUser":              1001,
				"seccompProfile": map[string]interface{}{
					"type": "RuntimeDefault",
				},
			},
		},
	}
}

func (ws *WebhookServer) fixEtcdResources() []patchOperation {
	minCPU := resource.MustParse("500m") // GKE Autopilot minimum for pod anti-affinity

	resourcesSpec := map[string]interface{}{
		"requests": map[string]interface{}{
			"cpu":    minCPU.String(),
			"memory": "600Mi",
		},
	}

	// GKE Autopilot compliant security context for init containers and sidecar containers
	securityContextSpec := map[string]interface{}{
		"allowPrivilegeEscalation": false,
		"capabilities": map[string]interface{}{
			"drop": []string{"ALL"},
		},
		"readOnlyRootFilesystem": true,
		"runAsNonRoot":           true,
		"runAsUser":              1001,
		"seccompProfile": map[string]interface{}{
			"type": "RuntimeDefault",
		},
	}

	// GKE Autopilot compliant security context for etcd main container (needs write access to data dir)
	etcdSecurityContextSpec := map[string]interface{}{
		"allowPrivilegeEscalation": false,
		"capabilities": map[string]interface{}{
			"drop": []string{"ALL"},
		},
		"readOnlyRootFilesystem": false, // etcd needs to write to /var/lib/data
		"runAsNonRoot":           true,
		"runAsUser":              1001,
		"seccompProfile": map[string]interface{}{
			"type": "RuntimeDefault",
		},
	}

	return []patchOperation{
		// Fix pod-level security context
		{
			Op:   "replace",
			Path: "/spec/template/spec/securityContext",
			Value: map[string]interface{}{
				"runAsNonRoot": true,
				"runAsUser":    1001,
				"fsGroup":      1001, // Ensure volumes are writable by user 1001
				"fsGroupChangePolicy": "Always", // Force volume ownership change in GKE Autopilot
				"supplementalGroups": []int{1001}, // Alternative to fsGroup for GKE Autopilot
				"seccompProfile": map[string]interface{}{
					"type": "RuntimeDefault",
				},
			},
		},
		// Fix pod anti-affinity rules for GKE Autopilot compatibility
		{
			Op:   "replace",
			Path: "/spec/template/spec/affinity",
			Value: map[string]interface{}{
				"podAntiAffinity": map[string]interface{}{
					"preferredDuringSchedulingIgnoredDuringExecution": []map[string]interface{}{
						{
							"weight": 100,
							"podAffinityTerm": map[string]interface{}{
								"labelSelector": map[string]interface{}{
									"matchLabels": map[string]interface{}{
										"app": "etcd",
									},
								},
								"topologyKey": "kubernetes.io/hostname",
							},
						},
					},
				},
			},
		},
		// Change volume mount path from /var/lib to /var/lib/data to avoid directory creation
		{
			Op:   "replace",
			Path: "/spec/template/spec/containers/0/volumeMounts",
			Value: []map[string]interface{}{
				{
					"name":      "data",
					"mountPath": "/var/lib/data", // Mount directly at data directory
				},
				{
					"name":      "peer-tls",
					"mountPath": "/etc/etcd/tls/peer",
				},
				{
					"name":      "server-tls",
					"mountPath": "/etc/etcd/tls/server",
				},
				{
					"name":      "client-tls",
					"mountPath": "/etc/etcd/tls/client",
				},
				{
					"name":      "etcd-ca",
					"mountPath": "/etc/etcd/tls/etcd-ca",
				},
			},
		},
		// Fix ensure-dns init container resources (back to position 0)
		{
			Op:   "replace",
			Path: "/spec/template/spec/initContainers/0/resources",
			Value: resourcesSpec,
		},
		// Fix ensure-dns init container security context
		{
			Op:   "replace",
			Path: "/spec/template/spec/initContainers/0/securityContext",
			Value: securityContextSpec,
		},
		// Fix reset-member init container resources (back to position 1)
		{
			Op:   "replace",
			Path: "/spec/template/spec/initContainers/1/resources",
			Value: resourcesSpec,
		},
		// Fix reset-member init container security context
		{
			Op:   "replace",
			Path: "/spec/template/spec/initContainers/1/securityContext",
			Value: securityContextSpec,
		},
		// Fix etcd container resources
		{
			Op:   "replace",
			Path: "/spec/template/spec/containers/0/resources",
			Value: resourcesSpec,
		},
		// Fix etcd container security context (allow filesystem writes for data directory)
		{
			Op:   "replace",
			Path: "/spec/template/spec/containers/0/securityContext",
			Value: etcdSecurityContextSpec,
		},
		// Fix etcd-metrics container security context
		{
			Op:   "replace",
			Path: "/spec/template/spec/containers/1/securityContext",
			Value: securityContextSpec,
		},
		// Fix healthz container security context
		{
			Op:   "replace",
			Path: "/spec/template/spec/containers/2/securityContext",
			Value: securityContextSpec,
		},
		// SOLUTION: Replace persistent volume with EmptyDir to fix GKE Autopilot permissions
		{
			Op:   "replace",
			Path: "/spec/volumeClaimTemplates",
			Value: []interface{}{},
		},
		// Add EmptyDir volume for etcd data
		{
			Op:   "add",
			Path: "/spec/template/spec/volumes/-",
			Value: map[string]interface{}{
				"name": "data",
				"emptyDir": map[string]interface{}{},
			},
		},
	}
}

func (ws *WebhookServer) fixKubeAPIServerResources() []patchOperation {
	// Fix CPU resources for containers that have pod anti-affinity
	// GKE Autopilot requires minimum 500m CPU for pods with anti-affinity
	resourcesSpec := map[string]interface{}{
		"requests": map[string]interface{}{
			"cpu":               "500m",
			"memory":            "2Gi",
			"ephemeral-storage": "1Gi",
		},
		"limits": map[string]interface{}{
			"ephemeral-storage": "1Gi",
		},
	}

	initContainerResourcesSpec := map[string]interface{}{
		"requests": map[string]interface{}{
			"cpu":               "500m",
			"memory":            "2118Mi",
			"ephemeral-storage": "4Gi",
		},
		"limits": map[string]interface{}{
			"ephemeral-storage": "4Gi",
		},
	}

	// Security context for all containers
	securityContextSpec := map[string]interface{}{
		"allowPrivilegeEscalation": false,
		"capabilities": map[string]interface{}{
			"drop": []string{"ALL"},
		},
		"readOnlyRootFilesystem": false, // kube-apiserver needs write access
		"runAsNonRoot":           true,
		"runAsUser":              1001,
		"seccompProfile": map[string]interface{}{
			"type": "RuntimeDefault",
		},
	}

	// Pod security context
	podSecurityContextSpec := map[string]interface{}{
		"runAsNonRoot": true,
		"runAsUser":    1001,
		"seccompProfile": map[string]interface{}{
			"type": "RuntimeDefault",
		},
	}

	return []patchOperation{
		// Add pod security context
		{
			Op:   "add",
			Path: "/spec/template/spec/securityContext",
			Value: podSecurityContextSpec,
		},
		// Fix wait-for-etcd init container resources
		{
			Op:   "replace",
			Path: "/spec/template/spec/initContainers/1/resources",
			Value: initContainerResourcesSpec,
		},
		// Fix wait-for-etcd init container security context
		{
			Op:   "add",
			Path: "/spec/template/spec/initContainers/1/securityContext",
			Value: securityContextSpec,
		},
		// Fix init-bootstrap init container security context
		{
			Op:   "add",
			Path: "/spec/template/spec/initContainers/0/securityContext",
			Value: securityContextSpec,
		},
		// Fix kube-apiserver container resources
		{
			Op:   "replace",
			Path: "/spec/template/spec/containers/1/resources",
			Value: resourcesSpec,
		},
		// Fix kube-apiserver container security context
		{
			Op:   "add",
			Path: "/spec/template/spec/containers/1/securityContext",
			Value: securityContextSpec,
		},
		// Fix apply-bootstrap container security context
		{
			Op:   "add",
			Path: "/spec/template/spec/containers/0/securityContext",
			Value: securityContextSpec,
		},
		// Fix konnectivity-server container security context
		{
			Op:   "add",
			Path: "/spec/template/spec/containers/2/securityContext",
			Value: securityContextSpec,
		},
		// Fix audit-logs container security context
		{
			Op:   "add",
			Path: "/spec/template/spec/containers/3/securityContext",
			Value: securityContextSpec,
		},
	}
}

func (ws *WebhookServer) fixKubeControllerManagerSecurityContext() []patchOperation {
	// Fix CPU resources for containers that have pod anti-affinity
	// GKE Autopilot requires minimum 500m CPU for pods with anti-affinity
	resourcesSpec := map[string]interface{}{
		"requests": map[string]interface{}{
			"cpu":               "500m",
			"memory":            "400Mi",
			"ephemeral-storage": "1Gi",
		},
		"limits": map[string]interface{}{
			"ephemeral-storage": "1Gi",
		},
	}

	initContainerResourcesSpec := map[string]interface{}{
		"requests": map[string]interface{}{
			"cpu":               "500m",
			"memory":            "400Mi",
			"ephemeral-storage": "1Gi",
		},
		"limits": map[string]interface{}{
			"ephemeral-storage": "1Gi",
		},
	}

	// Security context for all containers in kube-controller-manager
	securityContextSpec := map[string]interface{}{
		"allowPrivilegeEscalation": false,
		"capabilities": map[string]interface{}{
			"drop": []string{"ALL"},
		},
		"readOnlyRootFilesystem": false, // kube-controller-manager needs write access
		"runAsNonRoot":           true,
		"runAsUser":              1001,
		"seccompProfile": map[string]interface{}{
			"type": "RuntimeDefault",
		},
	}

	// Pod security context
	podSecurityContextSpec := map[string]interface{}{
		"runAsNonRoot": true,
		"runAsUser":    1001,
		"seccompProfile": map[string]interface{}{
			"type": "RuntimeDefault",
		},
	}

	return []patchOperation{
		// Add pod security context
		{
			Op:   "add",
			Path: "/spec/template/spec/securityContext",
			Value: podSecurityContextSpec,
		},
		// Fix availability-prober init container resources
		{
			Op:   "replace",
			Path: "/spec/template/spec/initContainers/0/resources",
			Value: initContainerResourcesSpec,
		},
		// Fix availability-prober init container security context
		{
			Op:   "add",
			Path: "/spec/template/spec/initContainers/0/securityContext",
			Value: securityContextSpec,
		},
		// Fix kube-controller-manager container resources
		{
			Op:   "replace",
			Path: "/spec/template/spec/containers/0/resources",
			Value: resourcesSpec,
		},
		// Fix kube-controller-manager container security context
		{
			Op:   "add",
			Path: "/spec/template/spec/containers/0/securityContext",
			Value: securityContextSpec,
		},
	}
}

func (ws *WebhookServer) fixPodSecurityContext() []patchOperation {
	return []patchOperation{
		{
			Op:   "add",
			Path: "/spec/securityContext",
			Value: map[string]interface{}{
				"runAsNonRoot": true,
				"runAsUser":    1001,
				"seccompProfile": map[string]interface{}{
					"type": "RuntimeDefault",
				},
			},
		},
	}
}

func (ws *WebhookServer) sendResponse(w http.ResponseWriter, admissionReview *admissionv1.AdmissionReview, patches []patchOperation) {
	var patchBytes []byte
	var err error

	if len(patches) > 0 {
		patchBytes, err = json.Marshal(patches)
		if err != nil {
			log.Printf("Could not marshal patches: %v", err)
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
	}

	admissionResponse := &admissionv1.AdmissionResponse{
		UID:     admissionReview.Request.UID,
		Allowed: true,
	}

	if len(patchBytes) > 0 {
		patchType := admissionv1.PatchTypeJSONPatch
		admissionResponse.PatchType = &patchType
		admissionResponse.Patch = patchBytes
	}

	admissionReview.Response = admissionResponse
	respBytes, err := json.Marshal(admissionReview)
	if err != nil {
		log.Printf("Could not marshal response: %v", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Write(respBytes)
}

func isHyperShiftControlPlane(namespace string) bool {
	// Check if this is a HyperShift control plane namespace
	return strings.HasPrefix(namespace, "clusters-") || namespace == "hypershift"
}

func hasHyperShiftLabels(labels map[string]string) bool {
	if labels == nil {
		return false
	}
	
	for key := range labels {
		if strings.Contains(key, "hypershift.openshift.io") {
			return true
		}
	}
	return false
}

// hasAntiAffinityRules checks if deployment has pod anti-affinity rules
func (ws *WebhookServer) hasAntiAffinityRules(deployment *appsv1.Deployment) bool {
	if deployment.Spec.Template.Spec.Affinity == nil {
		return false
	}
	if deployment.Spec.Template.Spec.Affinity.PodAntiAffinity == nil {
		return false
	}
	// Check for either required or preferred anti-affinity rules
	return len(deployment.Spec.Template.Spec.Affinity.PodAntiAffinity.RequiredDuringSchedulingIgnoredDuringExecution) > 0 ||
		   len(deployment.Spec.Template.Spec.Affinity.PodAntiAffinity.PreferredDuringSchedulingIgnoredDuringExecution) > 0
}

// fixGenericDeploymentForGKEAutopilot applies standard GKE Autopilot fixes to any deployment
func (ws *WebhookServer) fixGenericDeploymentForGKEAutopilot(deployment *appsv1.Deployment, hasAntiAffinity bool) []patchOperation {
	var patches []patchOperation
	
	// Check if this deployment needs network capabilities (like haproxy)
	needsNetworkCapabilities := ws.needsNetworkCapabilities(deployment)
	
	// Standard security context for all containers
	var securityContextSpec map[string]interface{}
	if needsNetworkCapabilities {
		// For components like haproxy that need to bind to ports
		securityContextSpec = map[string]interface{}{
			"allowPrivilegeEscalation": false,
			"capabilities": map[string]interface{}{
				"drop": []string{"ALL"},
				"add":  []string{"NET_BIND_SERVICE"},
			},
			"readOnlyRootFilesystem": false,
			"runAsNonRoot":           true,
			"runAsUser":              1001,
			"seccompProfile": map[string]interface{}{
				"type": "RuntimeDefault",
			},
		}
	} else {
		// Standard security context for most components
		securityContextSpec = map[string]interface{}{
			"allowPrivilegeEscalation": false,
			"capabilities": map[string]interface{}{
				"drop": []string{"ALL"},
			},
			"readOnlyRootFilesystem": false, // Most control plane components need write access
			"runAsNonRoot":           true,
			"runAsUser":              1001,
			"seccompProfile": map[string]interface{}{
				"type": "RuntimeDefault",
			},
		}
	}

	// Pod security context
	podSecurityContextSpec := map[string]interface{}{
		"runAsNonRoot": true,
		"runAsUser":    1001,
		"seccompProfile": map[string]interface{}{
			"type": "RuntimeDefault",
		},
	}

	// Resource specifications - use 100m CPU for all containers for demo purposes
	var cpuRequest string
	if hasAntiAffinity {
		cpuRequest = "100m" // Further reduced for demo cluster
	} else {
		cpuRequest = "50m" // Minimal for demo
	}

	resourcesSpec := map[string]interface{}{
		"requests": map[string]interface{}{
			"cpu":               cpuRequest,
			"memory":            "512Mi",
			"ephemeral-storage": "1Gi",
		},
		"limits": map[string]interface{}{
			"ephemeral-storage": "1Gi",
		},
	}

	initContainerResourcesSpec := map[string]interface{}{
		"requests": map[string]interface{}{
			"cpu":               cpuRequest,
			"memory":            "400Mi",
			"ephemeral-storage": "1Gi",
		},
		"limits": map[string]interface{}{
			"ephemeral-storage": "1Gi",
		},
	}

	// Always add pod security context
	patches = append(patches, patchOperation{
		Op:   "add",
		Path: "/spec/template/spec/securityContext",
		Value: podSecurityContextSpec,
	})

	// Fix all init containers
	for i := range deployment.Spec.Template.Spec.InitContainers {
		// Add security context for each init container
		patches = append(patches, patchOperation{
			Op:   "add",
			Path: fmt.Sprintf("/spec/template/spec/initContainers/%d/securityContext", i),
			Value: securityContextSpec,
		})
		// Update resources for each init container
		patches = append(patches, patchOperation{
			Op:   "replace",
			Path: fmt.Sprintf("/spec/template/spec/initContainers/%d/resources", i),
			Value: initContainerResourcesSpec,
		})
	}

	// Fix all main containers
	for i := range deployment.Spec.Template.Spec.Containers {
		// Add security context for each container
		patches = append(patches, patchOperation{
			Op:   "add",
			Path: fmt.Sprintf("/spec/template/spec/containers/%d/securityContext", i),
			Value: securityContextSpec,
		})
		// Update resources for each container
		patches = append(patches, patchOperation{
			Op:   "replace",
			Path: fmt.Sprintf("/spec/template/spec/containers/%d/resources", i),
			Value: resourcesSpec,
		})
	}

	return patches
}

// fixKubeAPIServerSpecificPatches handles kube-apiserver specific requirements beyond generic fixes
func (ws *WebhookServer) fixKubeAPIServerSpecificPatches() []patchOperation {
	// kube-apiserver has some specific resource requirements that differ from generic
	// For now, the generic fixes handle most cases, but we can add specific overrides here
	var patches []patchOperation
	
	// Example: kube-apiserver might need higher memory limits
	kubeAPIServerResourcesSpec := map[string]interface{}{
		"requests": map[string]interface{}{
			"cpu":               "100m",
			"memory":            "512Mi", // Further reduced for demo cluster
			"ephemeral-storage": "1Gi",
		},
		"limits": map[string]interface{}{
			"ephemeral-storage": "1Gi",
		},
	}

	// Update main kube-apiserver container (index 1) with higher resources
	patches = append(patches, patchOperation{
		Op:   "replace",
		Path: "/spec/template/spec/containers/1/resources",
		Value: kubeAPIServerResourcesSpec,
	})

	return patches
}

// needsNetworkCapabilities checks if a deployment needs network capabilities like NET_BIND_SERVICE
func (ws *WebhookServer) needsNetworkCapabilities(deployment *appsv1.Deployment) bool {
	// Check deployment name patterns
	if strings.Contains(deployment.Name, "proxy") || 
	   strings.Contains(deployment.Name, "haproxy") ||
	   strings.Contains(deployment.Name, "nginx") ||
	   strings.Contains(deployment.Name, "router") ||
	   strings.Contains(deployment.Name, "ingress") {
		return true
	}
	
	// Check for containers that typically need network capabilities
	for _, container := range deployment.Spec.Template.Spec.Containers {
		// Check container command for network-related binaries
		for _, arg := range container.Command {
			if strings.Contains(arg, "haproxy") || 
			   strings.Contains(arg, "nginx") ||
			   strings.Contains(arg, "proxy") {
				return true
			}
		}
		
		// Check container args for network-related operations
		for _, arg := range container.Args {
			if strings.Contains(arg, "haproxy") || 
			   strings.Contains(arg, "nginx") ||
			   strings.Contains(arg, "bind") ||
			   strings.Contains(arg, "listen") {
				return true
			}
		}
		
		// Check for ports that typically require binding capabilities
		for _, port := range container.Ports {
			if port.ContainerPort > 0 && port.ContainerPort < 1024 {
				return true // Privileged ports need NET_BIND_SERVICE
			}
		}
	}
	
	return false
}