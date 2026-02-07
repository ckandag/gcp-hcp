package api

// RegionRequest represents the payload for Tekton webhook region operations
type RegionRequest struct {
	Environment string `json:"environment"`
	Region      string `json:"region"`
	Sector      string `json:"sector"`
}

// Validate checks if all required fields are present and valid
func (r *RegionRequest) Validate() error {
	if r.Environment == "" {
		return &ValidationError{Field: "environment", Message: "environment is required"}
	}
	if r.Region == "" {
		return &ValidationError{Field: "region", Message: "region is required"}
	}
	if r.Sector == "" {
		return &ValidationError{Field: "sector", Message: "sector is required"}
	}
	return nil
}

// ValidationError represents a validation error for a specific field
type ValidationError struct {
	Field   string
	Message string
}

func (e *ValidationError) Error() string {
	return e.Message
}

// TektonResponse represents the response from Tekton webhook
type TektonResponse struct {
	Status           string `json:"status,omitempty"`
	Message          string `json:"message,omitempty"`
	EventID          string `json:"eventID,omitempty"`
	EventListener    string `json:"eventListener,omitempty"`
	Namespace        string `json:"namespace,omitempty"`
	EventListenerUID string `json:"eventListenerUID,omitempty"`
}

// PipelineRunStatus represents the status of a Tekton PipelineRun
type PipelineRunStatus struct {
	Name           string                   `json:"name"`
	Namespace      string                   `json:"namespace,omitempty"`
	Status         string                   `json:"status"` // Unknown, Pending, Running, Succeeded, Failed, Cancelled
	StartTime      string                   `json:"startTime,omitempty"`
	CompletionTime string                   `json:"completionTime,omitempty"`
	Tasks          []TaskRunStatus          `json:"taskRuns,omitempty"`
	Conditions     []PipelineRunCondition   `json:"conditions,omitempty"`
	Message        string                   `json:"message,omitempty"`
}

// TaskRunStatus represents the status of a single task in a pipeline
type TaskRunStatus struct {
	Name      string `json:"name"`
	Status    string `json:"status"`
	StartTime string `json:"startTime,omitempty"`
}

// PipelineRunCondition represents a condition of the pipeline run
type PipelineRunCondition struct {
	Type    string `json:"type"`
	Status  string `json:"status"`
	Reason  string `json:"reason,omitempty"`
	Message string `json:"message,omitempty"`
}
