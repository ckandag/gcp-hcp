package client

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/openshift-online/gcp-hcp/experiments/pipeline-automation/tekton/gcpctl/pkg/api"
)

func TestNewTektonClient(t *testing.T) {
	client := NewTektonClient("http://localhost:8080")
	if client == nil {
		t.Fatal("NewTektonClient returned nil")
	}
	if client.baseURL != "http://localhost:8080" {
		t.Errorf("baseURL = %v, want %v", client.baseURL, "http://localhost:8080")
	}
	if client.httpClient.Timeout != defaultTimeout {
		t.Errorf("timeout = %v, want %v", client.httpClient.Timeout, defaultTimeout)
	}
}

func TestNewTektonClientWithTimeout(t *testing.T) {
	customTimeout := 60 * time.Second
	client := NewTektonClientWithTimeout("http://localhost:8080", customTimeout)
	if client == nil {
		t.Fatal("NewTektonClientWithTimeout returned nil")
	}
	if client.httpClient.Timeout != customTimeout {
		t.Errorf("timeout = %v, want %v", client.httpClient.Timeout, customTimeout)
	}
}

func TestTektonClient_AddRegion_Success(t *testing.T) {
	// Create a test server that returns a success response
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Verify request method
		if r.Method != http.MethodPost {
			t.Errorf("Method = %v, want %v", r.Method, http.MethodPost)
		}

		// Verify content type
		if ct := r.Header.Get("Content-Type"); ct != "application/json" {
			t.Errorf("Content-Type = %v, want %v", ct, "application/json")
		}

		// Decode and verify request body
		var req api.RegionRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatalf("Failed to decode request: %v", err)
		}

		if req.Environment != "production" {
			t.Errorf("Environment = %v, want %v", req.Environment, "production")
		}
		if req.Region != "us-central1" {
			t.Errorf("Region = %v, want %v", req.Region, "us-central1")
		}
		if req.Sector != "main" {
			t.Errorf("Sector = %v, want %v", req.Sector, "main")
		}

		// Send success response
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(api.TektonResponse{
			Status:  "success",
			Message: "Region added successfully",
		})
	}))
	defer server.Close()

	// Create client and make request
	client := NewTektonClient(server.URL)
	ctx := context.Background()

	req := &api.RegionRequest{
		Environment: "production",
		Region:      "us-central1",
		Sector:      "main",
	}

	resp, err := client.AddRegion(ctx, req)
	if err != nil {
		t.Fatalf("AddRegion() error = %v", err)
	}

	if resp.Status != "success" {
		t.Errorf("Status = %v, want %v", resp.Status, "success")
	}
	if resp.Message != "Region added successfully" {
		t.Errorf("Message = %v, want %v", resp.Message, "Region added successfully")
	}
}

func TestTektonClient_AddRegion_ValidationError(t *testing.T) {
	client := NewTektonClient("http://localhost:8080")
	ctx := context.Background()

	// Request with missing required field
	req := &api.RegionRequest{
		Environment: "production",
		Region:      "us-central1",
		// Sector is missing
	}

	_, err := client.AddRegion(ctx, req)
	if err == nil {
		t.Fatal("AddRegion() should return error for invalid request")
	}
}

func TestTektonClient_AddRegion_HTTPError(t *testing.T) {
	// Create a test server that returns an error
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		w.Write([]byte("Bad request"))
	}))
	defer server.Close()

	client := NewTektonClient(server.URL)
	ctx := context.Background()

	req := &api.RegionRequest{
		Environment: "production",
		Region:      "us-central1",
		Sector:      "main",
	}

	_, err := client.AddRegion(ctx, req)
	if err == nil {
		t.Fatal("AddRegion() should return error for HTTP error response")
	}
}

func TestTektonClient_AddRegion_Timeout(t *testing.T) {
	// Create a test server that delays response
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(2 * time.Second)
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	client := NewTektonClientWithTimeout(server.URL, 100*time.Millisecond)
	ctx := context.Background()

	req := &api.RegionRequest{
		Environment: "production",
		Region:      "us-central1",
		Sector:      "main",
	}

	_, err := client.AddRegion(ctx, req)
	if err == nil {
		t.Fatal("AddRegion() should return error for timeout")
	}
}

func TestTektonClient_SetTimeout(t *testing.T) {
	client := NewTektonClient("http://localhost:8080")
	newTimeout := 60 * time.Second

	client.SetTimeout(newTimeout)

	if client.httpClient.Timeout != newTimeout {
		t.Errorf("timeout = %v, want %v", client.httpClient.Timeout, newTimeout)
	}
}
