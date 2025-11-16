package main

import (
	"context"
	"fmt"
	"os/exec"
)

// BuildHost builds the host container using docker-compose build
func (c *Container) BuildHost(ctx context.Context) (string, error) {
	fmt.Println("Building host container image with docker-compose...")

	cmd := exec.CommandContext(ctx, "docker-compose", "build", "host")
	output, err := cmd.CombinedOutput()

	if err != nil {
		return "", fmt.Errorf("failed to build host container: %w\nOutput: %s", err, string(output))
	}

	fmt.Printf("Build output:\n%s\n", string(output))
	return "Host container built successfully", nil
}

// BuildBMC builds the BMC container using docker-compose build
func (c *Container) BuildBMC(ctx context.Context) (string, error) {
	fmt.Println("Building BMC container image with docker-compose...")

	cmd := exec.CommandContext(ctx, "docker-compose", "build", "bmc")
	output, err := cmd.CombinedOutput()

	if err != nil {
		return "", fmt.Errorf("failed to build BMC container: %w\nOutput: %s", err, string(output))
	}

	fmt.Printf("Build output:\n%s\n", string(output))
	return "BMC container built successfully", nil
}

// BuildAll builds firmware and all container images
func (c *Container) BuildAll(ctx context.Context) (string, error) {
	// Build firmware first
	firmware := &Firmware{}
	result, err := firmware.Build(ctx)
	if err != nil {
		return "", fmt.Errorf("firmware build failed: %w", err)
	}
	fmt.Println(result)

	// Then build all containers with docker-compose
	fmt.Println("Building all containers...")
	cmd := exec.CommandContext(ctx, "docker-compose", "build")
	output, err := cmd.CombinedOutput()

	if err != nil {
		return "", fmt.Errorf("failed to build containers: %w\nOutput: %s", err, string(output))
	}

	fmt.Printf("Build output:\n%s\n", string(output))
	return "All builds completed successfully (firmware + containers)", nil
}
