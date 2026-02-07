package client

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/openshift-online/gcp-hcp/experiments/pipeline-automation/tekton/gcpctl/pkg/api"
)

const (
	defaultTimeout = 30 * time.Second
	contentType    = "application/json"
)

// TektonClient handles communication with Tekton webhook
type TektonClient struct {
	baseURL    string
	httpClient *http.Client
}

// NewTektonClient creates a new Tekton webhook client
func NewTektonClient(baseURL string) *TektonClient {
	return &TektonClient{
		baseURL: baseURL,
		httpClient: &http.Client{
			Timeout: defaultTimeout,
		},
	}
}

// NewTektonClientWithTimeout creates a new Tekton webhook client with custom timeout
func NewTektonClientWithTimeout(baseURL string, timeout time.Duration) *TektonClient {
	return &TektonClient{
		baseURL: baseURL,
		httpClient: &http.Client{
			Timeout: timeout,
		},
	}
}

// AddRegion sends a region add request to the Tekton webhook
func (c *TektonClient) AddRegion(ctx context.Context, req *api.RegionRequest) (*api.TektonResponse, error) {
	// Validate request
	if err := req.Validate(); err != nil {
		return nil, fmt.Errorf("invalid request: %w", err)
	}

	// Marshal request body
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	// Create HTTP request
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL, bytes.NewBuffer(body))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	httpReq.Header.Set("Content-Type", contentType)
	httpReq.Header.Set("Accept", contentType)

	// Send request
	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// Read response body
	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	// Check status code
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("unexpected status code %d: %s", resp.StatusCode, string(respBody))
	}

	// Parse response
	var tektonResp api.TektonResponse
	if len(respBody) > 0 {
		if err := json.Unmarshal(respBody, &tektonResp); err != nil {
			// If response isn't JSON, treat it as a success with the body as message
			tektonResp = api.TektonResponse{
				Status:  "success",
				Message: string(respBody),
			}
		}
	} else {
		tektonResp = api.TektonResponse{
			Status:  "success",
			Message: "Region added successfully",
		}
	}

	return &tektonResp, nil
}

// SetTimeout updates the HTTP client timeout
func (c *TektonClient) SetTimeout(timeout time.Duration) {
	c.httpClient.Timeout = timeout
}
