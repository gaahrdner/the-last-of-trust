# macOS Quick Start Guide

This guide helps you get The Last of Trust running on macOS.

## Prerequisites

Before starting, ensure you have:

1. **Docker Desktop for Mac** (https://www.docker.com/products/docker-desktop)
   - Recommended: At least 8GB RAM allocated to Docker
   - Recommended: At least 4 CPUs allocated to Docker

2. **Dagger CLI** (v0.16.2+)
   ```bash
   curl -L https://dl.dagger.io/dagger/install.sh | sh
   ```

3. **Git** (usually pre-installed on macOS)

## macOS-Specific Notes

### No Hardware Acceleration
- macOS Docker runs in a Linux VM, so **KVM is not available**
- QEMU will use **TCG (software emulation)** instead
- This means slower performance but full functionality
- No need for `privileged: true` in docker-compose.yaml (already commented out)

### Resource Recommendations
Configure Docker Desktop resources (Preferences → Resources):
- **Memory**: 8GB minimum (12GB recommended)
- **CPUs**: 4 minimum (8 recommended)
- **Disk**: 20GB minimum free space

## Setup Steps

### 1. Run the Setup Script

```bash
./setup.sh
```

This will:
- Create all required directories
- Check for prerequisites
- Set up .gitignore
- Display next steps

### 2. Build the Firmware

```bash
cd /path/to/the-last-of-trust
dagger call firmware build
```

This downloads/builds a Coreboot ROM suitable for QEMU.

**Note**: The first run will be slow as Docker images are pulled. Subsequent runs use caching.

### 3. Build the Containers

```bash
# Build all containers at once
dagger call container build-all

# Or build individually
dagger call container build-host
dagger call container build-bmc
```

Alternatively, use docker-compose directly:
```bash
docker-compose build
```

### 4. Start the Environment

```bash
# Using Dagger
dagger call environment up

# Or using docker-compose
docker-compose up -d
```

### 5. Check Status

```bash
# Using Dagger
dagger call environment status

# Or using docker-compose
docker-compose ps
```

### 6. View Logs

```bash
# Using Dagger
dagger call environment logs

# Or using docker-compose
docker-compose logs -f

# View specific container logs
docker-compose logs -f host
docker-compose logs -f bmc
```

### 7. Access Containers

```bash
# Access host container shell
docker exec -it tlot-host /bin/bash

# Access BMC container shell
docker exec -it tlot-bmc /bin/bash
```

## Port Mappings

After starting, you can access services on:

### Host Container (tlot-host)
- **SSH**: localhost:2222
- **HTTP**: localhost:8080

### BMC Container (tlot-bmc)
- **SSH**: localhost:2223
- **HTTPS/Redfish**: localhost:8443
- **IPMI**: localhost:8623
- **VNC**: localhost:5900

## Troubleshooting

### Docker Desktop Issues

**Problem**: "Cannot connect to Docker daemon"
**Solution**: Ensure Docker Desktop is running (check menu bar icon)

**Problem**: "Docker is out of memory"
**Solution**: Increase memory in Docker Desktop → Preferences → Resources

### Build Issues

**Problem**: "failed to connect to dagger"
**Solution**:
```bash
# Restart Docker Desktop
# Then try again
dagger call firmware build
```

**Problem**: "Container build failed"
**Solution**:
```bash
# Clear Docker build cache
docker system prune -a
# Rebuild
docker-compose build --no-cache
```

### Runtime Issues

**Problem**: Host/BMC containers exit immediately
**Solution**:
```bash
# Check logs for errors
docker-compose logs host
docker-compose logs bmc

# Common issue: firmware ROM not found
# Make sure firmware was built:
ls -lh firmware/coreboot.rom
```

**Problem**: QEMU is very slow
**Solution**: This is expected on macOS without KVM. Consider:
- Reducing VM RAM (-m 2048 → -m 1024)
- Reducing CPUs (-smp 2 → -smp 1)
- Using a smaller Debian installation

## Installing Debian in the Host VM

The host container runs QEMU with an empty disk initially. To install Debian:

1. **Stop the environment**:
   ```bash
   dagger call environment down
   ```

2. **Edit docker-compose.yaml** - Find the host service and add the ISO mount:
   ```yaml
   volumes:
     - host-data:/var/lib/host
     - ./firmware:/firmware
     - ./logs/host:/logs
     - ./debian-11.9.0-amd64-netinst.iso:/build/debian-installer.iso:ro  # Add this
   ```

3. **Download Debian ISO** (if not already downloaded by the container):
   ```bash
   wget -O debian-11.9.0-amd64-netinst.iso \
     https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-11.9.0-amd64-netinst.iso
   ```

4. **Start the container**:
   ```bash
   docker-compose up -d host
   ```

5. **Attach to the console**:
   ```bash
   docker attach tlot-host
   ```

6. **Follow Debian installation prompts**

7. **After installation**, remove the ISO mount from docker-compose.yaml and restart

## Next Steps

After setup:
- Read [CLAUDE.md](CLAUDE.md) for architecture details
- Read [README.md](README.md) for project overview
- Explore security monitoring features
- Customize firmware configs in `configs/`

## Getting Help

- Check logs: `docker-compose logs`
- Check Docker Desktop dashboard
- Ensure all prerequisites are met
- Try rebuilding: `docker-compose build --no-cache`

## Stopping the Environment

```bash
# Using Dagger
dagger call environment down

# Or using docker-compose
docker-compose down

# To also remove volumes (WARNING: deletes VM data)
docker-compose down -v
```
