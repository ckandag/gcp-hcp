package api

import (
	"testing"
)

func TestRegionRequest_Validate(t *testing.T) {
	tests := []struct {
		name    string
		req     RegionRequest
		wantErr bool
		errMsg  string
	}{
		{
			name: "valid request",
			req: RegionRequest{
				Environment: "production",
				Region:      "us-central1",
				Sector:      "main",
			},
			wantErr: false,
		},
		{
			name: "missing environment",
			req: RegionRequest{
				Region: "us-central1",
				Sector: "main",
			},
			wantErr: true,
			errMsg:  "environment is required",
		},
		{
			name: "missing region",
			req: RegionRequest{
				Environment: "production",
				Sector:      "main",
			},
			wantErr: true,
			errMsg:  "region is required",
		},
		{
			name: "missing sector",
			req: RegionRequest{
				Environment: "production",
				Region:      "us-central1",
			},
			wantErr: true,
			errMsg:  "sector is required",
		},
		{
			name:    "all fields empty",
			req:     RegionRequest{},
			wantErr: true,
			errMsg:  "environment is required",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.req.Validate()
			if (err != nil) != tt.wantErr {
				t.Errorf("RegionRequest.Validate() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if err != nil && tt.errMsg != "" {
				if err.Error() != tt.errMsg {
					t.Errorf("RegionRequest.Validate() error message = %v, want %v", err.Error(), tt.errMsg)
				}
			}
		})
	}
}

func TestValidationError_Error(t *testing.T) {
	err := &ValidationError{
		Field:   "test_field",
		Message: "test message",
	}

	if err.Error() != "test message" {
		t.Errorf("ValidationError.Error() = %v, want %v", err.Error(), "test message")
	}
}
