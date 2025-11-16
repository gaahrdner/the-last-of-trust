# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

The Last of Trust is a firmware security testbed for Open Compute components. It creates a containerized environment for testing, monitoring, and performing security research on firmware components, specifically:

- **Host container**: Runs QEMU with Coreboot/LinuxBoot firmware and boots Debian
- **BMC container**: Runs OpenBMC in QEMU for out-of-band management
- **Security features**: TPM-based measured boot, runtime monitoring with osquery/Falco/Chipsec

## Build System Architecture

This project uses **Dagger** (v0.16.2) as the build system, written in Go. The build system is modular:

- `build/main.go` - Entry point defining Dagger module types (Firmware, Container, Environment, CI)
- `build/firmware.go` - Firmware build logic (currently placeholder, will build Coreboot+LinuxBoot)
- `build/container.go` - Container image builds for host and BMC
- `build/environment.go` - Docker Compose environment management
- `build/ci.go` - CI pipeline implementation

### Key Architectural Pattern

The Dagger module exports multiple top-level types (Firmware, Container, Environment, CI), each with methods that become Dagger functions. This allows calling build tasks via:
```bash
dagger call <type> <method>
```

## Essential Commands

### Building and Environment Management

```bash
# Build firmware (Coreboot + LinuxBoot)
dagger call firmware build

# Build containers
dagger call container buildHost    # Host container only
dagger call container buildBMC     # BMC container only
dagger call container buildAll     # All containers + firmware

# Environment lifecycle
dagger call environment up         # Start containers
dagger call environment down       # Stop containers
dagger call environment logs       # View logs
dagger call environment status     # Check container status

# CI pipeline
dagger call ci run                 # Build firmware only
```

### Direct Docker Access

```bash
# Start environment
docker-compose up -d

# Stop environment
docker-compose down

# Access container shells
docker exec -it tlot-host /bin/bash
docker exec -it tlot-bmc /bin/bash

# View logs
docker-compose logs
docker-compose logs host
docker-compose logs bmc
```

## Directory Structure

```
build/              # Dagger build system (Go)
configs/            # Configuration files for firmware components
  coreboot/         # Coreboot configs
  linux/            # Linux kernel configs for LinuxBoot
  falco/            # Falco security monitoring
  keylime/          # Remote attestation
  osquery/          # Endpoint monitoring
  otel/             # OpenTelemetry
Dockerfiles/        # Container build files
  host/             # Host container + scripts (QEMU, TPM, Debian setup)
  bmc/              # BMC container + scripts (OpenBMC, Redfish)
  offensive/        # Future: offensive security container
firmware/           # Build output: firmware images
logs/               # Runtime logs from containers
docker-compose.yaml # Container orchestration
```

## Network Architecture

Two Docker networks are defined in `docker-compose.yaml`:

- **oob-net** (172.20.0.0/24): Out-of-band management network for BMC-to-host communication
  - Host: 172.20.0.10
  - BMC: 172.20.0.20
- **mgmt-net** (192.168.10.0/24): General management network
  - Host: 192.168.10.10
  - BMC: 192.168.10.20

## Port Mappings

### Host Container (tlot-host)
- 2222 → 22 (SSH to Debian)
- 8080 → 80 (HTTP)

### BMC Container (tlot-bmc)
- 2223 → 22 (SSH to BMC)
- 443 → 443 (HTTPS/web interface)
- 623 → 623 (IPMI)
- 5900 → 5900 (VNC for virtual console)

## QEMU Configuration

The host container runs QEMU with specific firmware security features:

- **Machine type**: q35 (modern Intel chipset)
- **Firmware**: Coreboot ROM from `/firmware/coreboot.rom`
- **TPM**: Software TPM (swtpm) via Unix socket at `/tmp/swtpm-sock`
  - Device: tpm-tis (TPM Interface Specification)
  - Enables measured boot and PCR measurements
- **Storage**: Debian installation on virtio qcow2 image at `/var/lib/host/debian.qcow2`
- **Networking**: e1000 NIC with user-mode networking

## Development Workflow

### Modifying Firmware Configuration

1. Edit configs in `configs/coreboot/` or `configs/linux/`
2. Rebuild: `dagger call firmware build`
3. Restart environment: `dagger call environment down && dagger call environment up`

### Modifying Container Behavior

1. Edit Dockerfiles or scripts in `Dockerfiles/host/scripts/` or `Dockerfiles/bmc/scripts/`
2. Rebuild containers: `dagger call container buildAll`
3. Restart: `dagger call environment down && dagger call environment up`

### Modifying Dagger Build Logic

The build system is in Go:
1. Edit `build/*.go` files
2. Run `go mod tidy` in the `build/` directory if dependencies changed
3. Test with `dagger call <type> <method>`

## Important Implementation Details

### First-Time Setup Requirements

The first time running, you must create required directories:
```bash
mkdir -p configs/coreboot configs/linux
mkdir -p firmware logs/host logs/bmc
```

The firmware build will generate default configurations if they don't exist.

### Debian Installation Process

On first run, the host container needs Debian installed:
1. Stop environment: `dagger call environment down`
2. Edit `docker-compose.yaml` to add `-cdrom /build/debian-installer.iso` to QEMU command
3. Start: `dagger call environment up`
4. Attach to console: `docker attach tlot-host`
5. Complete Debian installation
6. Remove `-cdrom` option from docker-compose.yaml and restart

### Prerequisites

- Docker and Docker Compose
- Dagger CLI v0.16.2+
- 8GB+ RAM
- 20GB+ disk space

## Testing Strategy

Currently, the CI pipeline (`dagger call ci run`) only builds firmware and verifies the ROM exists. Future testing will include:
- Firmware boot verification
- TPM measurement validation
- Security monitoring integration tests
- BMC communication tests
