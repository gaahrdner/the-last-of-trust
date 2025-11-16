package main

import (
	"context"
	"fmt"
	"os"
	"os/exec"
)

// Up starts the Docker Compose environment
func (e *Environment) Up(ctx context.Context) (string, error) {
	fmt.Println("Starting environment with docker-compose...")

	cmd := exec.CommandContext(ctx, "docker-compose", "up", "-d")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("failed to start environment: %w", err)
	}

	return "Environment started successfully", nil
}

// Down stops the Docker Compose environment
func (e *Environment) Down(ctx context.Context) (string, error) {
	fmt.Println("Stopping environment...")

	cmd := exec.CommandContext(ctx, "docker-compose", "down")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("failed to stop environment: %w", err)
	}

	return "Environment stopped successfully", nil
}

// Logs displays the logs from the Docker Compose environment
func (e *Environment) Logs(ctx context.Context) (string, error) {
	fmt.Println("Displaying logs...")

	cmd := exec.CommandContext(ctx, "docker-compose", "logs")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("failed to display logs: %w", err)
	}

	return "Logs displayed", nil
}

// Status shows the status of all containers
func (e *Environment) Status(ctx context.Context) (string, error) {
	fmt.Println("Checking environment status...")

	cmd := exec.CommandContext(ctx, "docker-compose", "ps")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("failed to check status: %w", err)
	}

	return "Status displayed", nil
}
