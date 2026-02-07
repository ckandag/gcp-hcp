package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"time"

	compute "cloud.google.com/go/compute/apiv1"
	"cloud.google.com/go/compute/apiv1/computepb"
	"google.golang.org/api/option"
)

// Config holds the application configuration
type Config struct {
	ProjectID string
	TokenFile string
	Audience  string
}

func main() {
	log.Println("Starting GCP WIF Example Application...")

	// Load configuration from environment
	cfg := &Config{
		ProjectID: getEnv("GCP_PROJECT_ID", ""),
		TokenFile: getEnv("TOKEN_FILE", "/var/run/secrets/openshift/serviceaccount/token"),
		Audience:  getEnv("TOKEN_AUDIENCE", "openshift"),
	}

	if cfg.ProjectID == "" {
		log.Fatal("GCP_PROJECT_ID environment variable is required")
	}

	log.Printf("Configuration: ProjectID=%s, TokenFile=%s, Audience=%s",
		cfg.ProjectID, cfg.TokenFile, cfg.Audience)

	ctx := context.Background()

	// Run the main loop
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	// Run once immediately
	if err := listComputeInstances(ctx, cfg); err != nil {
		log.Printf("Error listing instances: %v", err)
	}

	// Then run periodically
	for range ticker.C {
		if err := listComputeInstances(ctx, cfg); err != nil {
			log.Printf("Error listing instances: %v", err)
		}
	}
}

// listComputeInstances demonstrates using GCP API with WIF token
func listComputeInstances(ctx context.Context, cfg *Config) error {
	log.Println("=== Starting GCP API Call ===")

	// Read the token from file (provided by token-minter sidecar)
	token, err := readToken(cfg.TokenFile)
	if err != nil {
		return fmt.Errorf("failed to read token: %w", err)
	}

	log.Printf("Token read successfully (length: %d bytes)", len(token))

	// Log token metadata without exposing the full token
	if err := logTokenMetadata(token); err != nil {
		log.Printf("Warning: Could not parse token metadata: %v", err)
	}

	// Create credentials using the token file
	// This uses GCP's credential file which should point to the token file
	credentialsFile := os.Getenv("GOOGLE_APPLICATION_CREDENTIALS")
	if credentialsFile == "" {
		return fmt.Errorf("GOOGLE_APPLICATION_CREDENTIALS not set")
	}

	// Create compute client
	client, err := compute.NewInstancesRESTClient(ctx, option.WithCredentialsFile(credentialsFile))
	if err != nil {
		return fmt.Errorf("failed to create compute client: %w", err)
	}
	defer client.Close()

	log.Println("Successfully created GCP client")

	// List compute instances across all zones
	zones := []string{"us-central1-a", "us-central1-b", "us-central1-c"}
	totalInstances := 0

	for _, zone := range zones {
		req := &computepb.ListInstancesRequest{
			Project: cfg.ProjectID,
			Zone:    zone,
		}

		log.Printf("Listing instances in zone: %s", zone)

		it := client.List(ctx, req)
		zoneCount := 0

		for {
			instance, err := it.Next()
			if err != nil {
				// End of list or error
				if err.Error() == "no more items in iterator" {
					break
				}
				log.Printf("Error iterating instances in %s: %v", zone, err)
				break
			}

			zoneCount++
			totalInstances++

			log.Printf("  - Instance: %s (Status: %s, MachineType: %s)",
				instance.GetName(),
				instance.GetStatus(),
				instance.GetMachineType())
		}

		if zoneCount == 0 {
			log.Printf("  No instances found in zone: %s", zone)
		}
	}

	log.Printf("=== API Call Complete: Found %d total instances ===\n", totalInstances)
	return nil
}

// readToken reads the service account token from the file
func readToken(tokenFile string) (string, error) {
	data, err := os.ReadFile(tokenFile)
	if err != nil {
		return "", fmt.Errorf("failed to read token file %s: %w", tokenFile, err)
	}
	return string(data), nil
}

// logTokenMetadata logs metadata about the JWT token without exposing sensitive data
func logTokenMetadata(token string) error {
	// Simple JWT parsing to extract header and payload (not verifying signature)
	parts := splitToken(token)
	if len(parts) != 3 {
		return fmt.Errorf("invalid JWT format")
	}

	// Decode payload (index 1)
	payload, err := decodeBase64(parts[1])
	if err != nil {
		return fmt.Errorf("failed to decode payload: %w", err)
	}

	var claims map[string]interface{}
	if err := json.Unmarshal(payload, &claims); err != nil {
		return fmt.Errorf("failed to unmarshal claims: %w", err)
	}

	// Log safe metadata
	log.Printf("Token metadata - aud: %v, iss: %v, sub: %v",
		claims["aud"],
		claims["iss"],
		claims["sub"])

	if exp, ok := claims["exp"].(float64); ok {
		expTime := time.Unix(int64(exp), 0)
		log.Printf("Token expires at: %s (in %v)",
			expTime.Format(time.RFC3339),
			time.Until(expTime).Round(time.Second))
	}

	return nil
}

// Helper functions
func splitToken(token string) []string {
	result := []string{}
	start := 0
	for i := 0; i < len(token); i++ {
		if token[i] == '.' {
			result = append(result, token[start:i])
			start = i + 1
		}
	}
	result = append(result, token[start:])
	return result
}

func decodeBase64(s string) ([]byte, error) {
	// Add padding if needed
	for len(s)%4 != 0 {
		s += "="
	}

	// Simple base64 decoding (using standard library would be better in production)
	const base64Table = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

	result := make([]byte, 0, len(s)*3/4)
	buf := uint32(0)
	bits := 0

	for _, c := range s {
		if c == '=' {
			break
		}

		val := -1
		for i, b := range base64Table {
			if byte(c) == byte(b) {
				val = i
				break
			}
		}

		if val == -1 {
			continue
		}

		buf = buf<<6 | uint32(val)
		bits += 6

		if bits >= 8 {
			bits -= 8
			result = append(result, byte(buf>>bits))
			buf &= (1 << bits) - 1
		}
	}

	return result, nil
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}
