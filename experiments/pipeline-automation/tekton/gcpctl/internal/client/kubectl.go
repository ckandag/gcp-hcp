package client

import (
	"context"
	"encoding/json"
	"fmt"
	"os/exec"

	"github.com/openshift-online/gcp-hcp/experiments/pipeline-automation/tekton/gcpctl/pkg/api"
)

// KubectlClient uses kubectl to query Tekton resources
type KubectlClient struct{}

// NewKubectlClient creates a new kubectl-based client
func NewKubectlClient() *KubectlClient {
	return &KubectlClient{}
}

// GetPipelineRunsByEventID queries for pipeline runs using kubectl
func (c *KubectlClient) GetPipelineRunsByEventID(ctx context.Context, namespace, eventID string) (*api.PipelineRunStatus, error) {
	if namespace == "" {
		namespace = "default"
	}

	// Build kubectl command
	labelSelector := fmt.Sprintf("triggers.tekton.dev/triggers-eventid=%s", eventID)
	args := []string{
		"get", "pipelineruns",
		"-n", namespace,
		"-l", labelSelector,
		"-o", "json",
	}

	cmd := exec.CommandContext(ctx, "kubectl", args...)
	output, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("kubectl command failed: %s", string(exitErr.Stderr))
		}
		return nil, fmt.Errorf("failed to execute kubectl: %w", err)
	}

	// Parse the response
	var pipelineList TektonPipelineRunList
	if err := json.Unmarshal(output, &pipelineList); err != nil {
		return nil, fmt.Errorf("failed to parse kubectl output: %w", err)
	}

	if len(pipelineList.Items) == 0 {
		return nil, fmt.Errorf("no pipeline runs found for event ID: %s", eventID)
	}

	// Get the most recent pipeline run
	pr := pipelineList.Items[0]

	// Create a temporary API client just to reuse the conversion function
	apiClient := &TektonAPIClient{}
	status := apiClient.convertPipelineRunToStatus(&pr)

	return status, nil
}

// GetPipelineRun queries for a specific pipeline run by name
func (c *KubectlClient) GetPipelineRun(ctx context.Context, namespace, name string) (*api.PipelineRunStatus, error) {
	if namespace == "" {
		namespace = "default"
	}

	args := []string{
		"get", "pipelinerun",
		name,
		"-n", namespace,
		"-o", "json",
	}

	cmd := exec.CommandContext(ctx, "kubectl", args...)
	output, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("kubectl command failed: %s", string(exitErr.Stderr))
		}
		return nil, fmt.Errorf("failed to execute kubectl: %w", err)
	}

	var pr TektonPipelineRun
	if err := json.Unmarshal(output, &pr); err != nil {
		return nil, fmt.Errorf("failed to parse kubectl output: %w", err)
	}

	apiClient := &TektonAPIClient{}
	status := apiClient.convertPipelineRunToStatus(&pr)

	return status, nil
}

// IsKubectlAvailable checks if kubectl is available
func IsKubectlAvailable() bool {
	cmd := exec.Command("kubectl", "version", "--client")
	err := cmd.Run()
	return err == nil
}
