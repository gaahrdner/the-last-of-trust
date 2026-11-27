# The Last of Trust

A containerized **TPM 2.0 Measured Boot, Linux IMA, Remote Attestation, and Redfish BMC** security testbed.

## Architecture

The testbed runs three real, networked services in Docker Compose across two isolated networks:

```
                   ┌──────────────────────────────────────┐
                   │   mgmt-net (10.101.0.0/24)           │
                   │                                      │
                   │  ┌────────────────────────────────┐  │
                   │  │ tlot-verifier (10.101.0.30)    │  │
                   │  │ - TPM 2.0 AK enrollment        │  │
                   │  │ - Fresh-nonce tpm2_checkquote  │  │
                   │  │ - PCR & IMA tamper detection   │  │
                   │  └───────────────┬────────────────┘  │
                   │                  │ HTTP :8080        │
                   │                  ▼                   │
┌──────────────────┴──────────────────┴───────────────────┴──┐
│ tlot-host (10.100.0.10 / 10.101.0.10)                      │
│ - QEMU (native arm64 virt or x86_64 q35)                   │
│ - EDK II UEFI firmware (AAVMF/OVMF) w/ TPM 2.0 Measured    │
│   Boot (or custom x86_64 Coreboot ROM in ./firmware/)      │
│ - swtpm TPM 2.0 emulator                                   │
│ - Ubuntu 24.04 guest with Linux IMA (ima_policy=tcb)       │
│ - tlot-agent (TPM 2.0 PCRs, AK, Quotes, Event Log, IMA)    │
└──────────────────┬─────────────────────────────────────────┘
                   │ QMP :4444 over oob-net (10.100.0.0/24)
                   ▼
┌────────────────────────────────────────────────────────────┐
│ tlot-bmc (10.100.0.20 / 10.101.0.20)                       │
│ - DMTF Redfish v1 HTTPS API (:8443 -> :443)                │
│ - Live QEMU QMP power state & ComputerSystem.Reset         │
│ - Real SHA-256 FirmwareInventory & Audit LogService        │
└────────────────────────────────────────────────────────────┘
```

### Measured Boot Chain

| PCR | Measured By | Contents |
|-----|-------------|----------|
| 0 | EDK II UEFI (AAVMF / OVMF) | Firmware volumes / Core Root of Trust |
| 1 | EDK II UEFI | Platform configuration & firmware variables |
| 4 | EDK II UEFI | Boot manager / EFI bootloader code |
| 7 | EDK II UEFI | Secure Boot policy & certificates |
| 8–9 | GRUB2 | Kernel, initrd, and kernel command line |
| 10 | Linux Kernel IMA | Every executed binary & TCB file (`ima_policy=tcb`, SHA-256) |

## Quick Start

### Prerequisites

- Docker & Docker Compose v2+
- `curl` and `jq` (for Makefile / verification helpers)
- Works natively on both **Apple Silicon (arm64)** and **x86_64 Linux/macOS**

### Run the Testbed

```bash
# 1. Build all containers (host, bmc, verifier)
make build

# 2. Start the stack
make up

# 3. Run the end-to-end verification suite
#    (waits for first-boot cloud-init + IMA reboot, verifies TPM 2.0 PCRs,
#     Redfish BMC, cryptographic TPM 2.0 quote attestation, and tamper detection)
make test
```

> **Note:** On the very first boot, `tlot-host` downloads the official Ubuntu 24.04 cloud image (~600 MB), installs `tpm2-tools` via `cloud-init`, enables `ima_policy=tcb ima_hash=sha256` in GRUB, and automatically reboots once to activate IMA. Subsequent starts boot directly from the persistent volume.

## Common Operations

| Command | Description |
|---------|-------------|
| `make pcrs` | Read live TPM 2.0 SHA-256 PCRs (0–10) from the host |
| `make ima` | Inspect the Linux IMA runtime measurement log |
| `make eventlog` | Decode the UEFI/GRUB TPM 2.0 binary event log via `tpm2_eventlog` |
| `make enroll` | Enroll the host's TPM 2.0 AK and golden PCR/IMA baseline |
| `make attest` | Challenge the host with a fresh nonce, verify `tpm2_checkquote` & replay IMA PCR 10 |
| `make history` | View recent attestation history from the verifier |
| `make bmc-status` | Query live host state via Redfish (`https://localhost:8443/redfish/v1/Systems/host`) |
| `make bmc-firmware` | Inspect active host firmware SHA-256 via Redfish `FirmwareInventory` |
| `make bmc-reset` | Hard-reset the host VM out-of-band via Redfish `ComputerSystem.Reset` |
| `make attack-injection` | Run Attack 01: untrusted runtime script injection (caught by IMA + PCR 10) |
| `make attack-replay` | Run Attack 02: TPM 2.0 quote replay with stale nonce (rejected with HTTP 401) |
| `make attack-quarantine` | Run Attack 03: tamper -> verifier BMC `ForceOff` quarantine -> Redfish `On` recovery |
| `make ssh` | SSH into the guest (`lab` / `lab` on port `2222`) |
| `make clean` | Stop containers and wipe persistent VM, TPM, and verifier volumes |

## Configuration Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECURE_BOOT` | `false` | Set `true` to boot with EDK II Secure Boot firmware (`*.secboot.fd` + `*.ms.fd`) |
| `TLOT_AGENT_TOKEN` | _(empty)_ | Optional shared Bearer token securing `tlot-agent` <-> `tlot-verifier` requests |
| `AUTO_QUARANTINE` | `false` | Set `true` to automatically halt `tlot-host` via BMC Redfish on attestation failure |
| `ATTEST_INTERVAL_SECONDS` | `0` | Background continuous attestation interval in seconds (`0` disables polling) |
| `HOST_AGENT_PORT` | `8081` | Host port mapped to `tlot-agent` (`8080` inside container) |

## Exposed Ports

| Service | Host Port | Description |
|---------|-----------|-------------|
| `tlot-host` | `2222` | SSH to Debian guest (`lab` / `lab`) |
| `tlot-host` | `8081` | Host attestation agent HTTP API (`/health`, `/tpm/pcrs`, `/tpm/ak`, `/tpm/quote`, `/tpm/eventlog`, `/ima/log`) |
| `tlot-bmc` | `8443` | Redfish HTTPS API (Basic Auth `root:0penBmc`) |
| `tlot-verifier` | `8888` | Remote attestation verifier HTTP API (`/health`, `/api/v1/status`, `/api/v1/enroll`, `/api/v1/attest`) |

## Custom Coreboot Firmware (Optional, x86_64)

On `x86_64`, if you place a compiled `coreboot.rom` in `./firmware/coreboot.rom`, `tlot-host` will automatically boot it instead of OVMF. A reference defconfig (`configs/coreboot/qemu-q35-tpm.defconfig`) and build script (`scripts/build-coreboot.sh`) are included.

## License

MIT — see [LICENSE](LICENSE).
