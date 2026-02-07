package config

import (
	"fmt"
	"os"

	"github.com/spf13/viper"
)

// Config holds the application configuration
type Config struct {
	TektonURL          string
	TektonDashboardURL string
	TektonAPIURL       string
	Verbose            bool
}

var globalConfig *Config

// Init initializes the configuration
func Init() error {
	viper.SetConfigName("config")
	viper.SetConfigType("yaml")
	viper.AddConfigPath("$HOME/.gcpctl")
	viper.AddConfigPath(".")

	// Set defaults
	viper.SetDefault("tekton_url", "http://localhost:8080")
	viper.SetDefault("tekton_dashboard_url", "")
	viper.SetDefault("tekton_api_url", "http://localhost:8080")
	viper.SetDefault("verbose", false)

	// Environment variables
	viper.SetEnvPrefix("GCPCTL")
	viper.AutomaticEnv()

	// Read config file if it exists
	if err := viper.ReadInConfig(); err != nil {
		if _, ok := err.(viper.ConfigFileNotFoundError); !ok {
			return fmt.Errorf("failed to read config file: %w", err)
		}
		// Config file not found; using defaults
	}

	globalConfig = &Config{
		TektonURL:          viper.GetString("tekton_url"),
		TektonDashboardURL: viper.GetString("tekton_dashboard_url"),
		TektonAPIURL:       viper.GetString("tekton_api_url"),
		Verbose:            viper.GetBool("verbose"),
	}

	return nil
}

// Get returns the global configuration
func Get() *Config {
	if globalConfig == nil {
		// Initialize with defaults if not yet initialized
		if err := Init(); err != nil {
			fmt.Fprintf(os.Stderr, "Warning: failed to initialize config: %v\n", err)
			globalConfig = &Config{
				TektonURL:          "http://localhost:8080",
				TektonDashboardURL: "",
				TektonAPIURL:       "http://localhost:8080",
				Verbose:            false,
			}
		}
	}
	return globalConfig
}

// Set updates the global configuration
func Set(cfg *Config) {
	globalConfig = cfg
}

// GetTektonURL returns the Tekton webhook URL
func GetTektonURL() string {
	return Get().TektonURL
}

// SetTektonURL sets the Tekton webhook URL
func SetTektonURL(url string) {
	Get().TektonURL = url
}

// IsVerbose returns whether verbose mode is enabled
func IsVerbose() bool {
	return Get().Verbose
}

// SetVerbose sets the verbose mode
func SetVerbose(verbose bool) {
	Get().Verbose = verbose
}

// GetTektonDashboardURL returns the Tekton dashboard URL
func GetTektonDashboardURL() string {
	return Get().TektonDashboardURL
}

// SetTektonDashboardURL sets the Tekton dashboard URL
func SetTektonDashboardURL(url string) {
	Get().TektonDashboardURL = url
}

// GetTektonAPIURL returns the Tekton API URL
func GetTektonAPIURL() string {
	return Get().TektonAPIURL
}

// SetTektonAPIURL sets the Tekton API URL
func SetTektonAPIURL(url string) {
	Get().TektonAPIURL = url
}
