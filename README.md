# The Last of Trust - Firmware Security Testbed

A firmware security testbed for Open Compute components with measured boot verification, runtime monitoring, and AI-driven offensive security testing.

## Overview

The Last of Trust is a containerized firmware security lab that creates a realistic environment for testing, monitoring, and attacking Open Compute firmware components. Named after the concept of "surviving in a hostile environment" while maintaining trust anchors, this project simulates a complete firmware ecosystem.

## Current Implementation Status

This repository currently focuses on setting up the core components:

- Host container: Runs QEMU with Coreboot/LinuxBoot firmware and boots Debian
- BMC container: Runs OpenBMC in QEMU, providing out-of-band management

The other components described in the overall architecture (SIEM, Attestation Service, AI-powered offensive security testing) will be implemented in future phases.

## Directory Structure

```
.
├── build                    # Dagger build system code
│   ├── ci.go                # CI pipeline functions
│   ├── containers.go        # Container build functions
│   ├── environment.go       # Environment management functions
│   └── firmware.go          # Firmware build functions
├── configs                  # Configuration files
│   ├── coreboot             # Coreboot configurations
│   ├── falco                # Falco security monitoring configs
│   ├── keylime              # Remote attestation configs
│   ├── linux                # Linux kernel configurations
│   ├── osquery              # Osquery endpoint monitoring configs
│   └── otel                 # OpenTelemetry observability configs
├── dagger.json              # Dagger project definition
├── docker-compose.yaml      # Docker compose environment definition
├── Dockerfiles              # Container build files
│   ├── bmc                  # BMC container
│   ├── host                 # Host container
│   └── offensive            # Offensive security container
├── firmware                 # Built firmware images
├── LICENSE
├── logs                     # Log files
│   ├── attestation
│   ├── bmc
│   ├── host
│   ├── offensive
│   └── siem
└── README.md
```

## Setup Instructions

### Prerequisites

- Docker and Docker Compose
- Git
- Dagger CLI (v0.16.2 or later)
- At least 8GB of free RAM
- At least 20GB of free disk space

### Setting Up Dagger

1. **Install Dagger CLI**:

   ```bash
   # Install Dagger CLI
   curl -L https://dl.dagger.io/dagger/install.sh | sh
   
   # Verify installation
   dagger version
   ```

2. **Create required directories** (first time only):

   ```bash
   mkdir -p configs/coreboot configs/linux
   mkdir -p firmware logs/host logs/bmc
   ```

### Using the Dagger Build System

1. **Build firmware**:

   ```bash
   dagger call firmware build
   ```

   This will:
   - Build coreboot with LinuxBoot as a payload
   - Configure TPM and measured boot support
   - Create the firmware image in the `./firmware` directory
   - The first run will also generate default configurations in the `configs` directory

2. **Build container images**:

   ```bash
   # Build host container
   dagger call container buildHost
   
   # Build BMC container
   dagger call container buildBMC
   
   # Build both containers and firmware
   dagger call container buildAll
   ```

3. **Start the environment**:

   ```bash
   dagger call environment up
   ```

4. **Monitor the logs**:

   ```bash
   dagger call environment logs
   ```

5. **Check container status**:

   ```bash
   dagger call environment status
   ```

6. **Access container shells**:

   ```bash
   # Host shell
   docker exec -it tlot-host /bin/bash
   
   # BMC shell
   docker exec -it tlot-bmc /bin/bash
   ```

7. **Stop the environment**:

   ```bash
   dagger call environment down
   ```

8. **CI Pipeline**:

   ```bash
   # Run CI pipeline (builds firmware only)
   dagger call ci run
   ```

## Installing Debian

When you first run the host container, you'll need to install Debian:

1. Stop the host container:
```bash
dagger call environment down
```

2. Modify the docker-compose.yml file to add the installation ISO:
```yaml
command: >
  qemu-system-x86_64
  -machine q35
  -m 2048
  -smp 2
  -bios /firmware/coreboot.rom
  -nographic
  -serial mon:stdio
  -device e1000,netdev=net0
  -netdev user,id=net0,hostfwd=tcp::22-:22
  -drive file=/var/lib/host/debian.qcow2,if=virtio,format=qcow2
  -cdrom /build/debian-installer.iso
  -chardev socket,id=chrtpm,path=/tmp/swtpm-sock
  -tpmdev emulator,id=tpm0,chardev=chrtpm
  -device tpm-tis,tpmdev=tpm0
```

3. Start the host container:
```bash
dagger call environment up
```

4. Follow the Debian installation process through the console:
```bash
docker attach tlot-host
```

5. After installation, stop the container and remove the `-cdrom` option from docker-compose.yaml

## TPM and Measured Boot

The host container includes a software TPM (swtpm) that enables:

1. Measured boot process with coreboot
2. TPM PCR measurements for runtime attestation
3. Secure key storage and sealed secrets

## Customizing the Firmware

The firmware configurations are stored in the `configs` directory:

```
configs/
├── coreboot/
│   ├── config.qemu-q35        # Base coreboot config
│   └── linuxboot.config       # Additional configs for linuxboot integration
└── linux/
    └── linuxboot.config       # Additional configs for linuxboot features
```

To customize the firmware:

1. Edit the configuration files in the `configs` directory
2. Rebuild the firmware with `dagger call firmware build`
3. Restart the host container with `dagger call environment down && dagger call environment up`

For example, to enable additional security features in the Linux kernel, edit `configs/linux/linuxboot.config` and add:

```
CONFIG_SECURITY_SELINUX=y
CONFIG_SECURITY_SMACK=y
CONFIG_INTEGRITY_SIGNATURE=y
```

The first time you run the build, default configurations will be created if they don't exist. You can then customize these generated configs for future builds.

## Security Features

The current implementation provides:

- TPM-based measured boot
- Out-of-band management via BMC
- Security monitoring with osquery, Falco, and Chipsec

Future phases will add:

- Remote attestation service using Keylime
- SIEM integration with Elasticsearch/Kibana
- AI-powered offensive security testing
- Comprehensive security monitoring dashboard

## Troubleshooting

- If the host container fails to start, check that the firmware ROM exists in the firmware directory
- If networking between the BMC and host doesn't work, ensure the TAP interface is properly configured
- For OpenBMC issues, check the logs with `docker-compose logs bmc`
- For TPM issues, examine `/logs/host/tpm.log`

## Contributing

Contributions are welcome! See the repo's CONTRIBUTING.md for details.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgements

- [Coreboot](https://www.coreboot.org/)
- [LinuxBoot](https://www.linuxboot.org/)
- [OpenBMC](https://github.com/openbmc/openbmc)
- [Keylime](https://keylime.dev/)
- [Falco](https://falco.org/)
- [Osquery](https://osquery.io/)
- [Chipsec](https://github.com/chipsec/chipsec)