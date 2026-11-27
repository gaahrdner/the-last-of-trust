# Measured Boot Architecture

## Overview

Measured boot creates a cryptographic chain of trust from firmware through the operating system, with each component measuring the next before executing it. All measurements are stored in TPM Platform Configuration Registers (PCRs).

## What is Measured Boot?

**Traditional Boot**: Each component loads and executes the next blindly.

**Measured Boot**: Each component:
1. Measures (hashes) the next component
2. Extends the measurement into a TPM PCR
3. Then executes it

This creates an immutable audit trail of what was loaded during boot.

## TPM PCR Usage

The TPM has 24 PCRs (Platform Configuration Registers). We'll use:

| PCR | Component | What It Measures |
|-----|-----------|------------------|
| 0 | BIOS/Coreboot | Core root of trust measurement |
| 1 | BIOS/Coreboot | Platform configuration (optional) |
| 2 | Option ROMs | Loaded option ROMs |
| 3 | Option ROMs | Option ROM configuration |
| 4 | MBR/GPT | Boot sector code |
| 5 | MBR/GPT | Boot configuration |
| 6 | State transitions | Platform state transitions |
| 7 | Platform vendor | Vendor-specific measurements |
| 8 | **Bootloader** | GRUB/systemd-boot code |
| 9 | **Bootloader** | Kernel command line |
| 10 | **IMA** | Runtime file measurements |
| 11-15 | Reserved | Future use |
| 16-23 | Debug | Not reset on reboot |

## Our Boot Chain

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Firmware (Coreboot)                                      │
│    - Initializes TPM                                        │
│    - Measures itself → PCR 0                                │
│    - Measures LinuxBoot kernel → PCR 4                      │
│    - Executes LinuxBoot                                     │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. LinuxBoot Kernel                                         │
│    - Initializes TPM drivers                                │
│    - Measures bootloader → PCR 8                            │
│    - Executes bootloader (GRUB/systemd-boot)                │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. Bootloader (GRUB)                                        │
│    - Measures kernel → PCR 8                                │
│    - Measures initrd → PCR 8                                │
│    - Measures kernel command line → PCR 9                   │
│    - Executes Debian kernel                                 │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. Debian Kernel                                            │
│    - Initializes IMA subsystem                              │
│    - IMA measures every file executed → PCR 10              │
│    - Starts init system                                     │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. Runtime (IMA)                                            │
│    - Continuously measures files as they're accessed        │
│    - All measurements → PCR 10                              │
│    - Log available in /sys/kernel/security/ima/             │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Steps

### Step 1: Coreboot Configuration

**Goal**: Build Coreboot that measures itself and LinuxBoot.

**Key Config Options**:
```
CONFIG_COREBOOT_BOOTBLOCK_TPM_INIT=y
CONFIG_TPM=y
CONFIG_TPM2=y
CONFIG_TPM_MEASURED_BOOT=y
CONFIG_VBOOT=y  # Optional: verified boot
```

**What Happens**:
- Coreboot bootblock initializes TPM
- Coreboot measures its own components into PCR 0
- Coreboot measures LinuxBoot payload into PCR 4
- Control passes to LinuxBoot

### Step 2: LinuxBoot Kernel

**Goal**: Kernel with TPM drivers and IMA support.

**Key Config Options**:
```
CONFIG_TCG_TPM=y
CONFIG_TCG_TIS=y
CONFIG_TCG_CRB=y
CONFIG_IMA=y
CONFIG_IMA_MEASURE_PCR_IDX=10
CONFIG_IMA_DEFAULT_HASH_SHA256=y
CONFIG_AUDIT=y
```

**What Happens**:
- Kernel detects TPM via ACPI/device tree
- TPM drivers loaded
- IMA subsystem initialized
- Ready to measure files

### Step 3: Bootloader (GRUB)

**Goal**: GRUB that extends PCRs before loading kernel.

**Configuration**:
```bash
# In grub.cfg
insmod tpm
# GRUB automatically measures kernel, initrd, cmdline
```

**What Happens**:
- GRUB measures kernel image → PCR 8
- GRUB measures initrd → PCR 8
- GRUB measures command line → PCR 9
- Kernel boots

### Step 4: IMA (Integrity Measurement Architecture)

**Goal**: Measure all file access at runtime.

**Kernel Boot Parameter**:
```
ima_policy=tcb ima_hash=sha256
```

**What Happens**:
- Every executable measured before execution
- Every library measured before loading
- All measurements logged to /sys/kernel/security/ima/ascii_runtime_measurements
- PCR 10 extended with each measurement

## Verification

### Reading PCR Values

```bash
# Read all PCRs
tpm2_pcrread

# Read specific PCRs
tpm2_pcrread sha256:0,4,8,9,10
```

### Expected PCR Values

After a clean boot:
- **PCR 0**: Coreboot measurements (deterministic if firmware unchanged)
- **PCR 4**: LinuxBoot kernel hash (deterministic)
- **PCR 8**: Bootloader + kernel + initrd (deterministic)
- **PCR 9**: Kernel command line (deterministic)
- **PCR 10**: All files loaded (changes with each boot)

### Viewing IMA Log

```bash
# See what was measured
cat /sys/kernel/security/ima/ascii_runtime_measurements

# Count measurements
wc -l /sys/kernel/security/ima/ascii_runtime_measurements

# Find specific file measurement
grep "/usr/bin/bash" /sys/kernel/security/ima/ascii_runtime_measurements
```

## Attack Detection

### Scenario 1: Modified Kernel

**Attack**: Replace kernel with backdoored version

**Detection**:
- PCR 8 will have different value
- Attestation will fail (different PCR quote)
- Can't fake it because TPM is tamper-resistant

### Scenario 2: Modified Application

**Attack**: Replace /usr/bin/ssh with trojaned version

**Detection**:
- IMA will measure it before execution
- Hash won't match expected value
- Logged in IMA runtime measurements
- PCR 10 will be different

### Scenario 3: Bootkit

**Attack**: Modify bootloader

**Detection**:
- Coreboot measures bootloader
- PCR 4 or 8 will differ
- Attestation fails
- Boot can be blocked by policy

## Remote Attestation Flow

```
┌──────────┐                           ┌──────────┐
│  Device  │                           │ Verifier │
│ (Target) │                           │ (Server) │
└────┬─────┘                           └────┬─────┘
     │                                      │
     │ 1. Request: Send me a quote          │
     │◄─────────────────────────────────────┤
     │                                      │
     │ 2. TPM generates quote (signed PCRs) │
     │  - PCR values: 0,4,8,9,10            │
     │  - Signature from TPM private key    │
     │  - Nonce (prevents replay)           │
     │                                      │
     │ 3. Quote + Event Log                 │
     ├─────────────────────────────────────►│
     │                                      │
     │                                      │ 4. Verify:
     │                                      │    - Signature valid?
     │                                      │    - PCRs match expected?
     │                                      │    - Event log consistent?
     │                                      │
     │ 5. Attestation Result: Pass/Fail     │
     │◄─────────────────────────────────────┤
     │                                      │
```

## Files and Locations

### On Host (Container)

```
/var/lib/host/tpm/              # TPM state directory
├── tpm2-00.permall             # Persistent TPM data
└── tpm-state.dat               # TPM volatile state
```

### In Debian VM

```
/sys/kernel/security/ima/
├── ascii_runtime_measurements  # Human-readable IMA log
├── binary_runtime_measurements # Binary IMA log
└── policy                      # Current IMA policy

/sys/kernel/security/tpm0/
└── binary_bios_measurements    # BIOS/firmware event log
```

## Configuration Files

### Coreboot Config

Location: `configs/coreboot/measured_boot.config`

Key settings:
- Enable TPM 2.0
- Enable measured boot
- Set measurement PCRs
- Configure event log

### Linux Kernel Config

Location: `configs/linux/measured_boot.config`

Key settings:
- TPM drivers
- IMA enabled
- PCR 10 for IMA
- SHA-256 hashing

### IMA Policy

Location: `configs/ima/policy.conf`

Example policy:
```
# Measure all executables
measure func=BINFMT_CHECK

# Measure all libraries
measure func=FILE_MMAP mask=MAY_EXEC

# Measure kernel modules
measure func=MODULE_CHECK

# Measure firmware
measure func=FIRMWARE_CHECK
```

## Troubleshooting

### TPM Not Detected

```bash
# Check if TPM device exists
ls -la /dev/tpm*

# Check kernel detected it
dmesg | grep -i tpm

# Check TPM module loaded
lsmod | grep tpm
```

### No Measurements in PCR 10

```bash
# Check IMA is enabled
cat /proc/cmdline | grep ima

# Check IMA policy
cat /sys/kernel/security/ima/policy

# Check IMA log exists
ls -la /sys/kernel/security/ima/
```

### PCR Values All Zeros

- TPM not initialized properly
- Firmware not measuring
- Boot happened too fast (race condition)

## Performance Considerations

### IMA Overhead

- Each file access triggers hash calculation
- ~1-5% CPU overhead for typical workload
- Can be mitigated with:
  - Selective policy (don't measure everything)
  - Caching measurements
  - Appraisal mode (measure only, don't enforce)

### Boot Time Impact

- Measuring adds ~2-5 seconds to boot
- Most time in:
  - Firmware measuring payload (~1s)
  - IMA measuring initial files (~1-3s)

## Security Properties

### What Measured Boot Provides

✅ **Detection of modifications**: Any change to boot chain is measurable
✅ **Audit trail**: Complete log of what was loaded
✅ **Remote attestation**: Prove boot state to remote party
✅ **Tamper evidence**: Can't hide modifications from PCRs

### What It Does NOT Provide

❌ **Prevention**: Doesn't stop malicious code from running
❌ **Real-time blocking**: Detection happens after the fact
❌ **Confidentiality**: Measurements are readable by anyone
❌ **Complete coverage**: Only measures files, not memory or runtime

### Combined with Other Technologies

- **Verified Boot**: Prevents execution of unsigned code
- **Secure Boot**: UEFI signature verification
- **Full Disk Encryption**: TPM-sealed keys
- **Remote Attestation**: Keylime for continuous verification

## Next Steps

1. Build Coreboot with TPM support
2. Configure Linux kernel with IMA
3. Set up GRUB to measure kernel
4. Test measurement chain
5. Implement remote attestation (Keylime)

---

**References**:
- [TCG PC Client Platform Firmware Profile](https://trustedcomputinggroup.org/resource/pc-client-specific-platform-firmware-profile-specification/)
- [Linux IMA Documentation](https://www.kernel.org/doc/html/latest/security/IMA-templates.html)
- [Keylime Remote Attestation](https://keylime.dev/)
- [Coreboot Measured Boot](https://doc.coreboot.org/security/vboot/index.html)
