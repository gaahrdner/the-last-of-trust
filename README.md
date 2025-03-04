# The Last of Trust

A firmware security testbed for Open Compute components with measured boot verification, runtime monitoring, and AI-driven offensive security testing.

## Overview

The Last of Trust is a containerized firmware security lab that creates a realistic environment for testing, monitoring, and attacking Open Compute firmware components. Named after the concept of "surviving in a hostile environment" while maintaining trust anchors, this project simulates a complete firmware ecosystem with:

- Host firmware (Coreboot/LinuxBoot) running in QEMU
- BMC firmware (OpenBMC) in a separate QEMU instance
- TPM-based measured boot and remote attestation
- Out-of-band management network between BMC and host
- Automated firmware security scanning with Chipsec
- Runtime security monitoring via Falco and osquery
- AI-powered offensive security testing
- Centralized security monitoring and event correlation (SIEM)

## Architecture

```mermaid
flowchart TB
    subgraph Docker Host
        subgraph "out-of-band network (172.20.0.0/24)"
            Host["Host Container\n(QEMU x86_64)\nCoreboot+LinuxBoot"]
            BMC["BMC Container\n(QEMU ARM)\nOpenBMC"]
            SIEM["SIEM Container\nElasticsearch/Kibana\nLog Aggregation"]
            Attestation["Attestation Service\nTPM Quote Verification\nBaseline Management"]
            AIOffensive["AI Security Container\nAutomated Testing\nVulnerability Scanning"]
            
            subgraph Host
                TPM["Virtual TPM (swtpm)"]
                HostOS["Linux OS\nChipsec\nFalco\nosquery"]
            end
        end
        
        subgraph "volumes"
            FirmwareVol["Firmware Volume\n- coreboot.rom\n- host.img\n- openbmc.mtd"]
            LogVol["Logs Volume\n- Host logs\n- BMC logs\n- Attestation logs\n- Security scan results"]
        end
    end
    
    Admin(["Administrator\nWeb Interface"])
    
    %% Connections
    Host <--> BMC
    Host --> SIEM
    BMC --> SIEM
    Attestation <--> Host
    Attestation --> SIEM
    AIOffensive --> Host
    AIOffensive --> BMC
    AIOffensive --> SIEM
    
    Host -.-> FirmwareVol
    BMC -.-> FirmwareVol
    SIEM -.-> LogVol
    Host -.-> LogVol
    BMC -.-> LogVol
    Attestation -.-> LogVol
    AIOffensive -.-> LogVol
    
    Admin --> SIEM
    Admin --> Attestation
    
    %% Styles
    classDef container fill:#e6f7ff,stroke:#1890ff,stroke-width:2px;
    classDef volume fill:#f6ffed,stroke:#52c41a,stroke-width:2px;
    classDef component fill:#f9f0ff,stroke:#722ed1,stroke-width:1px;
    classDef external fill:#fff7e6,stroke:#fa8c16,stroke-width:2px;
    
    class Host,BMC,SIEM,Attestation,AIOffensive container;
    class FirmwareVol,LogVol volume;
    class TPM,HostOS component;
    class Admin external;

The project uses Docker containers to virtualize each component:

- **Host Container**: QEMU running Coreboot with LinuxBoot payload and Linux OS
- **BMC Container**: QEMU running ARM OpenBMC for out-of-band management
- **TPM Component**: Virtual TPM (swtpm) for measured boot and attestation
- **Attestation Service**: Verifies host TPM measurements against a trusted baseline
- **SIEM Container**: ELK stack for log aggregation and security monitoring
- **Offensive Container**: AI-powered security testing tools to probe for vulnerabilities

All components are interconnected via Docker networks, with special attention to an isolated out-of-band management network between the BMC and host.

## Features

- **Measured Boot**: TPM-backed boot attestation ensures firmware integrity
- **Out-of-Band Management**: Dedicated network for BMC-to-host management
- **Continuous Security Scanning**: Periodic Chipsec scans check firmware security
- **Runtime Security Monitoring**: Falco and osquery detect anomalous behavior
- **Remote Attestation**: Verification service validates TPM quotes against a baseline
- **Automated Red Team**: AI-powered offensive security tooling constantly probes for weaknesses
- **Centralized Monitoring**: All security events and logs flow to a central SIEM
- **Web Dashboard**: View system security status, attestation results, and detected threats

## Prerequisites

- Docker and Docker Compose
- 8GB+ RAM recommended
- 20GB+ free disk space
- Linux host (for best KVM performance)

## Quick Start

```bash
# Clone the repository
git clone https://github.com/your-org/the-last-of-trust.git
cd the-last-of-trust

# Start the lab environment
docker-compose up -d

# View the security dashboard
firefox http://localhost:5601
```

## Component Details

### Host Firmware Container

Runs QEMU with Coreboot/LinuxBoot as the firmware. The boot process is measured by the TPM, and the OS runs security monitoring tools including Chipsec for firmware security analysis.

### BMC Container

Runs OpenBMC in QEMU to simulate a management controller. Provides IPMI and Redfish interfaces for out-of-band management of the host.

### TPM Component

Virtual TPM implementation used to record and validate boot measurements, supporting both measured boot and remote attestation.

### Attestation Service

Maintains a baseline of trusted PCR measurements and verifies the host's TPM quotes. Provides a web interface for managing trust baselines.

### SIEM Container

Elasticsearch/Logstash/Kibana stack that collects and analyzes logs from all components. Provides dashboards for security monitoring and alerting.

### Offensive Security Container

AI-powered penetration testing tools that continuously probe the environment for vulnerabilities.

## Networks

The environment uses multiple Docker networks:
- `oob-net` (172.20.0.0/24): Out-of-band management network between BMC and host
- `mgmt-net`: Optional network for external management access

## Directory Structure

```
├── firmware/
│   ├── coreboot.rom                    # Host BIOS image
│   ├── host.img                        # Host OS disk image
│   └── obmc-phosphor-image-romulus.mtd # BMC firmware image
├── configs/                            # Configuration files
├── logs/                               # Persistent logs directory
├── docker-compose.yml                  # Main compose file
└── Dockerfiles/                        # Container build files
```

## Usage Scenarios

### Firmware Security Research

Study firmware security concepts in a realistic but controlled environment. Experiment with measured boot, attestation, and firmware hardening techniques.

### Security Monitoring Testing

Test security monitoring tools and rules against simulated firmware attacks. Validate detection capabilities for firmware-level threats.

### Red Team/Blue Team Exercises

Use the AI offensive container to simulate attacks while monitoring the SIEM for detection. Practice responding to firmware security incidents.

### Educational Platform

Learn about firmware security, TPM attestation, and out-of-band management in a hands-on environment.

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgements

- [Coreboot](https://www.coreboot.org/)
- [LinuxBoot](https://www.linuxboot.org/)
- [OpenBMC](https://github.com/openbmc/openbmc)
- [Keylime](https://keylime.dev/)
- [Falco](https://falco.org/)
- [Osquery](https://osquery.io/)
- [Chipsec](https://github.com/chipsec/chipsec)
