package client

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/openshift-online/gcp-hcp/experiments/pipeline-automation/tekton/gcpctl/pkg/api"
)

// TektonAPIClient handles communication with Tekton API for status checks
type TektonAPIClient struct {
	baseURL    string
	httpClient *http.Client
}

// NewTektonAPIClient creates a new Tekton API client
func NewTektonAPIClient(baseURL string) *TektonAPIClient {
	return &TektonAPIClient{
		baseURL: baseURL,
		httpClient: &http.Client{
			Timeout: defaultTimeout,
		},
	}
}

// TektonPipelineRun represents a Tekton PipelineRun from the API
type TektonPipelineRun struct {
	APIVersion string `json:"apiVersion"`
	Kind       string `json:"kind"`
	Metadata   struct {
		Name              string            `json:"name"`
		Namespace         string            `json:"namespace"`
		CreationTimestamp string            `json:"creationTimestamp"`
		Labels            map[string]string `json:"labels,omitempty"`
	} `json:"metadata"`
	Spec struct {
		PipelineRef struct {
			Name string `json:"name"`
		} `json:"pipelineRef"`
		Params []struct {
			Name  string `json:"name"`
			Value string `json:"value"`
		} `json:"params,omitempty"`
	} `json:"spec"`
	Status struct {
		Conditions []struct {
			Type    string `json:"type"`
			Status  string `json:"status"`
			Reason  string `json:"reason"`
			Message string `json:"message"`
		} `json:"conditions"`
		StartTime      string `json:"startTime,omitempty"`
		CompletionTime string `json:"completionTime,omitempty"`
		TaskRuns       map[string]struct {
			PipelineTaskName string `json:"pipelineTaskName"`
			Status           struct {
				Conditions []struct {
					Type   string `json:"type"`
					Status string `json:"status"`
					Reason string `json:"reason"`
				} `json:"conditions"`
				StartTime      string `json:"startTime,omitempty"`
				CompletionTime string `json:"completionTime,omitempty"`
			} `json:"status"`
		} `json:"taskRuns,omitempty"`
	} `json:"status"`
}

// TektonPipelineRunList represents a list of PipelineRuns
type TektonPipelineRunList struct {
	APIVersion string              `json:"apiVersion"`
	Kind       string              `json:"kind"`
	Items      []TektonPipelineRun `json:"items"`
}

// GetPipelineRunsByEventID queries Tekton API for pipeline runs matching an event ID
func (c *TektonAPIClient) GetPipelineRunsByEventID(ctx context.Context, namespace, eventID string) (*api.PipelineRunStatus, error) {
	if namespace == "" {
		namespace = "default"
	}

	// Query for pipeline runs with the event ID label
	// Tekton labels pipeline runs created by event listeners with triggers.tekton.dev/triggers-eventid
	url := fmt.Sprintf("%s/apis/tekton.dev/v1/namespaces/%s/pipelineruns?labelSelector=triggers.tekton.dev/triggers-eventid=%s",
		c.baseURL, namespace, eventID)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Accept", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to query Tekton API: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Tekton API returned status %d: %s", resp.StatusCode, string(body))
	}

	var pipelineList TektonPipelineRunList
	if err := json.Unmarshal(body, &pipelineList); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}

	if len(pipelineList.Items) == 0 {
		return nil, fmt.Errorf("no pipeline runs found for event ID: %s", eventID)
	}

	// Get the most recent pipeline run (should only be one, but just in case)
	pr := pipelineList.Items[0]

	// Convert to our status type
	status := c.convertPipelineRunToStatus(&pr)

	return status, nil
}

// GetPipelineRun queries for a specific pipeline run by name
func (c *TektonAPIClient) GetPipelineRun(ctx context.Context, namespace, name string) (*api.PipelineRunStatus, error) {
	if namespace == "" {
		namespace = "default"
	}

	url := fmt.Sprintf("%s/apis/tekton.dev/v1/namespaces/%s/pipelineruns/%s",
		c.baseURL, namespace, name)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Accept", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to query Tekton API: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Tekton API returned status %d: %s", resp.StatusCode, string(body))
	}

	var pr TektonPipelineRun
	if err := json.Unmarshal(body, &pr); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}

	status := c.convertPipelineRunToStatus(&pr)

	return status, nil
}

// convertPipelineRunToStatus converts Tekton API response to our status type
func (c *TektonAPIClient) convertPipelineRunToStatus(pr *TektonPipelineRun) *api.PipelineRunStatus {
	status := &api.PipelineRunStatus{
		Name:           pr.Metadata.Name,
		Namespace:      pr.Metadata.Namespace,
		Status:         "Unknown",
		StartTime:      pr.Status.StartTime,
		CompletionTime: pr.Status.CompletionTime,
	}

	// Determine overall status from conditions
	for _, cond := range pr.Status.Conditions {
		if cond.Type == "Succeeded" {
			switch cond.Status {
			case "True":
				status.Status = "Succeeded"
			case "False":
				if cond.Reason == "PipelineRunCancelled" {
					status.Status = "Cancelled"
				} else {
					status.Status = "Failed"
				}
				status.Message = cond.Message
			case "Unknown":
				if cond.Reason == "Running" {
					status.Status = "Running"
				} else if cond.Reason == "PipelineRunPending" || cond.Reason == "Pending" {
					status.Status = "Pending"
				} else {
					status.Status = "Unknown"
				}
			}
			break
		}
	}

	// Extract task statuses
	for _, taskRun := range pr.Status.TaskRuns {
		taskStatus := "Unknown"
		for _, cond := range taskRun.Status.Conditions {
			if cond.Type == "Succeeded" {
				switch cond.Status {
				case "True":
					taskStatus = "Succeeded"
				case "False":
					taskStatus = "Failed"
				case "Unknown":
					taskStatus = "Running"
				}
				break
			}
		}

		status.Tasks = append(status.Tasks, api.TaskRunStatus{
			Name:      taskRun.PipelineTaskName,
			Status:    taskStatus,
			StartTime: taskRun.Status.StartTime,
		})
	}

	// Add conditions
	for _, cond := range pr.Status.Conditions {
		status.Conditions = append(status.Conditions, api.PipelineRunCondition{
			Type:    cond.Type,
			Status:  cond.Status,
			Reason:  cond.Reason,
			Message: cond.Message,
		})
	}

	return status
}

// FormatDuration formats a duration in a human-readable way
func FormatDuration(d time.Duration) string {
	if d < time.Minute {
		return fmt.Sprintf("%ds", int(d.Seconds()))
	}
	if d < time.Hour {
		minutes := int(d.Minutes())
		seconds := int(d.Seconds()) % 60
		if seconds > 0 {
			return fmt.Sprintf("%dm%ds", minutes, seconds)
		}
		return fmt.Sprintf("%dm", minutes)
	}
	hours := int(d.Hours())
	minutes := int(d.Minutes()) % 60
	return fmt.Sprintf("%dh%dm", hours, minutes)
}

// CalculateDuration calculates duration between start and end times
func CalculateDuration(startTime, completionTime string) string {
	if startTime == "" {
		return "N/A"
	}

	start, err := time.Parse(time.RFC3339, startTime)
	if err != nil {
		return "N/A"
	}

	var end time.Time
	if completionTime != "" {
		end, err = time.Parse(time.RFC3339, completionTime)
		if err != nil {
			end = time.Now()
		}
	} else {
		end = time.Now()
	}

	duration := end.Sub(start)
	return FormatDuration(duration)
}

// GetStatusEmoji returns an emoji for the status
func GetStatusEmoji(status string) string {
	status = strings.ToLower(status)
	switch status {
	case "succeeded":
		return "✓"
	case "failed":
		return "✗"
	case "running":
		return "⏳"
	case "pending":
		return "⏸"
	case "cancelled":
		return "⊘"
	default:
		return "?"
	}
}
