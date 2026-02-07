package main

import (
	"os"

	"github.com/openshift-online/gcp-hcp/experiments/pipeline-automation/tekton/gcpctl/cmd/gcpctl"
)

func main() {
	if err := gcpctl.Execute(); err != nil {
		os.Exit(1)
	}
}
