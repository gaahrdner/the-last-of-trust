# Measured Boot & Remote Attestation Architecture

## Overview

**The Last of Trust** implements a real, end-to-end cryptographic measured boot and remote attestation chain inside Docker Compose:

```
┌──────────────────────────────────────────────────────────────────────┐
│ 1. Firmware: EDK II UEFI (AAVMF on arm64 / OVMF on x86_64)           │
│    (or optional custom Coreboot ROM on x86_64)                       │
│    - Initializes swtpm TPM 2.0 via TIS interface                     │
│    - Measures firmware volumes & config → PCR 0, 1                   │
│    - Measures EFI bootloader & Secure Boot policy → PCR 4, 7         │
│    - Populates ACPI TPM2 table & binary UEFI event log               │
└──────────────────────────────────┬───────────────────────────────────┘
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 2. Bootloader: GRUB2 (EFI)                                           │
│    - Measures Linux kernel, initrd, and boot commands → PCR 8, 9     │
│    - Passes `ima_policy=tcb ima_hash=sha256` to kernel               │
└──────────────────────────────────┬───────────────────────────────────┘
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 3. OS Kernel: Ubuntu 24.04 (built-in CONFIG_TCG_TIS=y, CONFIG_IMA=y) │
│    - Binds /dev/tpmrm0 early before rootfs mount                     │
│    - Exposes /sys/kernel/security/tpm0/binary_bios_measurements      │
│    - IMA continuously measures executed/TCB files → PCR 10 (SHA-256) │
└──────────────────────────────────┬───────────────────────────────────┘
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 4. Host Attestation Agent (`tlot-agent.py`, port 8080)               │
│    - Provisions persistent TPM 2.0 EK (0x81010001) & AK (0x81010002) │
│    - Signs fresh-nonce quotes via `tpm2_quote` (staged in /dev/shm)  │
│    - Serves PCRs, AK PEM, binary UEFI event log, ASCII & binary IMA  │
│    - Optional Bearer token auth (`TLOT_AGENT_TOKEN`)                 │
└──────────────────────────────────┬───────────────────────────────────┘
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 5. Remote Verifier & Live UI (`tlot-verifier`, port 8888)            │
│    - Serves real-time Trust Chain dashboard at http://localhost:8888 │
│    - Enrolls AK public key + golden boot PCRs & IMA allowlist        │
│    - Challenges host with 128-bit random nonce (`tpm2_checkquote`)   │
│    - Replays binary IMA log to cryptographically verify PCR 10       │
│    - Decodes UEFI TPM 2.0 event log via `tpm2_eventlog`              │
│    - On `UNTRUSTED`: optionally quarantines host via BMC Redfish     │
└──────────────────────────────────┬───────────────────────────────────┘
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 6. Out-of-Band BMC (`tlot-bmc`, HTTPS port 8443 -> 443)              │
│    - DMTF Redfish v1 API (`root:0penBmc`)                            │
│    - Live host control via QEMU QMP over isolated `oob-net`          │
│    - `ComputerSystem.Reset` (`ForceOff`, `On`, `ForceRestart`, etc.) │
│    - Real SHA-256 `FirmwareInventory` & Redfish `Audit` LogService   │
└──────────────────────────────────────────────────────────────────────┘
```

## TPM 2.0 PCR Map

| PCR | Measured By | Verification Policy |
|-----|-------------|---------------------|
| 0 | EDK II UEFI / Coreboot | Exact match against golden baseline |
| 1 | EDK II UEFI | Exact match against golden baseline |
| 4 | EDK II UEFI | Exact match against golden baseline |
| 7 | EDK II UEFI (Secure Boot) | Exact match against golden baseline (`SECURE_BOOT=true` enables signed MS/Ubuntu chain) |
| 8 | GRUB2 | Exact match against golden baseline |
| 9 | GRUB2 | Exact match against golden baseline |
| 10 | Linux IMA (`ima-ng`, SHA-256) | Cryptographic binary log replay (`SHA256(PCR10 \|\| SHA256(template_data))`) + file hash & untrusted-path policy |

## Cryptographic Verification Guarantees

1. **Freshness (Anti-Replay)**: Every attestation generates a fresh 128-bit cryptographic nonce passed to `tpm2_quote` and verified by `tpm2_checkquote`. Replaying a previously valid signed quote fails with HTTP `401` (demonstrated by `scripts/attacks/02-quote-replay.sh`).
2. **IMA Log Integrity**: The verifier replays `/sys/kernel/security/ima/binary_runtime_measurements` entry by entry into a SHA-256 PCR 10 accumulator and requires a bit-for-bit match against the TPM-signed PCR 10 digest. A compromised host cannot hide executed binaries by omitting lines from the log.
3. **Out-of-Band Containment**: Because `tlot-bmc` controls `tlot-host` via QEMU QMP over the isolated `oob-net` (`10.100.0.0/24`), the verifier can halt (`ForceOff`) a compromised host even if the guest OS is fully compromised (demonstrated by `scripts/attacks/03-bmc-quarantine.sh`).

## Network Isolation

- **`oob-net` (`10.100.0.0/24`)**: Out-of-band management network between `tlot-bmc` (`10.100.0.20`) and `tlot-host` QMP (`10.100.0.10:4444`).
- **`mgmt-net` (`10.101.0.0/24`)**: Management network connecting `tlot-verifier` (`10.101.0.30`), `tlot-host` attestation agent (`10.101.0.10:8080`), and `tlot-bmc` Redfish API (`10.101.0.20:443`).
