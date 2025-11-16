package main

import (
	"context"
	"fmt"
	"os"
)

// Run executes the CI pipeline
func (c *CI) Run(ctx context.Context) (string, error) {
	fmt.Println("=== Running CI Pipeline ===")

	// Create directories for outputs
	fmt.Println("Creating required directories...")
	if err := os.MkdirAll("firmware", 0755); err != nil {
		return "", fmt.Errorf("failed to create firmware directory: %w", err)
	}

	if err := os.MkdirAll("logs/host", 0755); err != nil {
		return "", fmt.Errorf("failed to create logs directory: %w", err)
	}

	if err := os.MkdirAll("logs/bmc", 0755); err != nil {
		return "", fmt.Errorf("failed to create logs directory: %w", err)
	}

	if err := os.MkdirAll("configs/coreboot", 0755); err != nil {
		return "", fmt.Errorf("failed to create configs directory: %w", err)
	}

	if err := os.MkdirAll("configs/linux", 0755); err != nil {
		return "", fmt.Errorf("failed to create configs directory: %w", err)
	}

	// Build firmware
	fmt.Println("\n--- Building Firmware ---")
	firmware := &Firmware{}
	result, err := firmware.Build(ctx)
	if err != nil {
		return "", fmt.Errorf("firmware build failed: %w", err)
	}
	fmt.Println(result)

	// Verify firmware exists
	if _, err := os.Stat("firmware/coreboot.rom"); os.IsNotExist(err) {
		return "", fmt.Errorf("firmware build didn't produce a ROM file")
	}

	fmt.Println("\n=== CI Pipeline Completed Successfully ===")
	return "CI pipeline completed successfully (firmware built and verified)", nil
}
