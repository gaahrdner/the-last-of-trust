#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="/var/lib/host"
FIRMWARE_DIR="/firmware"
LOGS_DIR="/logs"
TPM_SOCKET="/tmp/swtpm-sock"
HOST_ARCH="$(uname -m)"
VM_MEM="${VM_MEM:-1536}"
VM_CPUS="${VM_CPUS:-2}"
DISK_SIZE="${DISK_SIZE:-10G}"

mkdir -p "$STATE_DIR/ssh" "$LOGS_DIR" "$FIRMWARE_DIR"

log() {
    echo "[host $(date '+%H:%M:%S')] $*" | tee -a "$LOGS_DIR/host_boot.log"
}

# 1. Start software TPM 2.0 emulator
/opt/tlot/setup_tpm.sh &
TPM_PID=$!

log "Waiting for swtpm socket at ${TPM_SOCKET}..."
for _ in $(seq 1 30); do
    if [ -S "$TPM_SOCKET" ]; then
        break
    fi
    sleep 0.5
done
if [ ! -S "$TPM_SOCKET" ]; then
    log "ERROR: swtpm socket failed to appear"
    exit 1
fi
log "TPM 2.0 emulator ready (pid=${TPM_PID})"

# 2. Select architecture-appropriate QEMU, UEFI firmware, and Debian cloud image
if [ "$HOST_ARCH" = "aarch64" ] || [ "$HOST_ARCH" = "arm64" ]; then
    DEB_ARCH="arm64"
    QEMU_BIN="qemu-system-aarch64"
    FW_CODE="/usr/share/AAVMF/AAVMF_CODE.fd"
    FW_VARS_SRC="/usr/share/AAVMF/AAVMF_VARS.fd"
    FW_NAME="AAVMF (EDK II UEFI ARM64 with TPM 2.0)"
else
    DEB_ARCH="amd64"
    QEMU_BIN="qemu-system-x86_64"
    FW_CODE="/usr/share/OVMF/OVMF_CODE_4M.fd"
    FW_VARS_SRC="/usr/share/OVMF/OVMF_VARS_4M.fd"
    FW_NAME="OVMF (EDK II UEFI x86_64 with TPM 2.0)"
fi

FW_VARS="${STATE_DIR}/efi_vars.fd"
if [ ! -f "$FW_VARS" ]; then
    cp "$FW_VARS_SRC" "$FW_VARS"
fi

# Allow custom Coreboot ROM override on x86_64 if user built one
USE_CUSTOM_ROM="false"
if [ "$DEB_ARCH" = "amd64" ] && [ -f "${FIRMWARE_DIR}/coreboot.rom" ]; then
    USE_CUSTOM_ROM="true"
    FW_CODE="${FIRMWARE_DIR}/coreboot.rom"
    FW_NAME="Coreboot (Custom QEMU Q35 ROM)"
fi

# Publish active firmware metadata for BMC Redfish FirmwareInventory
FW_SHA256="$(sha256sum "$FW_CODE" | awk '{print $1}')"
FW_SIZE="$(stat -c%s "$FW_CODE")"
cat > "${FIRMWARE_DIR}/active-firmware.json" <<EOF
{
  "id": "host-firmware",
  "name": "${FW_NAME}",
  "path": "${FW_CODE}",
  "architecture": "${HOST_ARCH}",
  "size_bytes": ${FW_SIZE},
  "sha256": "${FW_SHA256}",
  "tpm_version": "2.0",
  "measured_boot": true,
  "updated_at": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
}
EOF
log "Active firmware: ${FW_NAME} (sha256=${FW_SHA256:0:16}...)"

# 3. Prepare Ubuntu 24.04 cloud image (built-in TPM 2.0 TIS + IMA) + cloud-init seed ISO
BASE_IMAGE="${STATE_DIR}/ubuntu-24.04-cloudimg-${DEB_ARCH}.qcow2"
VM_DISK="${STATE_DIR}/host.qcow2"
SEED_ISO="${STATE_DIR}/seed.iso"
SSH_KEY="${STATE_DIR}/ssh/id_ed25519"

if [ ! -f "$SSH_KEY" ]; then
    ssh-keygen -t ed25519 -N "" -f "$SSH_KEY" -C "tlot-lab" >/dev/null
fi
SSH_PUBKEY="$(cat "${SSH_KEY}.pub")"

if [ ! -f "$BASE_IMAGE" ]; then
    IMG_URL="https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-${DEB_ARCH}.img"
    log "Downloading official Ubuntu 24.04 cloud image (${DEB_ARCH})..."
    curl -fL --retry 3 -o "${BASE_IMAGE}.tmp" "$IMG_URL"
    mv "${BASE_IMAGE}.tmp" "$BASE_IMAGE"
    log "Downloaded $(du -h "$BASE_IMAGE" | awk '{print $1}')"
fi

if [ ! -f "$VM_DISK" ]; then
    log "Creating VM disk overlay (${DISK_SIZE})..."
    qemu-img create -f qcow2 -F qcow2 -b "$BASE_IMAGE" "$VM_DISK" "$DISK_SIZE" >/dev/null
fi

if [ ! -f "$SEED_ISO" ]; then
    log "Generating cloud-init seed ISO (TPM2 + IMA + tlot-agent)..."
    AGENT_B64="$(base64 -w 0 /opt/tlot/tlot_agent.py)"

    cat > "${STATE_DIR}/meta-data" <<EOF
instance-id: tlot-host-01
local-hostname: tlot-host
EOF

    cat > "${STATE_DIR}/user-data" <<EOF
#cloud-config
hostname: tlot-host
manage_etc_hosts: true
ssh_pwauth: true
disable_root: false

users:
  - name: lab
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    plain_text_passwd: lab
    ssh_authorized_keys:
      - ${SSH_PUBKEY}

package_update: true
packages:
  - tpm2-tools
  - python3
  - jq
  - curl

write_files:
  - path: /usr/local/bin/tlot-agent.py
    permissions: "0755"
    encoding: b64
    content: ${AGENT_B64}
  - path: /etc/systemd/system/tlot-agent.service
    permissions: "0644"
    content: |
      [Unit]
      Description=The Last of Trust TPM 2.0 & IMA Attestation Agent
      After=network-online.target
      Wants=network-online.target

      [Service]
      Type=simple
      ExecStart=/usr/bin/python3 /usr/local/bin/tlot-agent.py
      Restart=always
      RestartSec=3

      [Install]
      WantedBy=multi-user.target
  - path: /etc/default/grub.d/99-tlot-ima.cfg
    permissions: "0644"
    content: |
      GRUB_CMDLINE_LINUX_DEFAULT="\${GRUB_CMDLINE_LINUX_DEFAULT} ima_policy=tcb ima_hash=sha256"

runcmd:
  - update-grub
  - systemctl daemon-reload
  - systemctl enable tlot-agent.service

power_state:
  mode: reboot
  message: "Rebooting to activate Linux IMA measured boot policy"
  timeout: 30
  condition: true
EOF

    cloud-localds "$SEED_ISO" "${STATE_DIR}/user-data" "${STATE_DIR}/meta-data"
fi

# 4. Build QEMU arguments
QEMU_ARGS=(
    -m "$VM_MEM"
    -smp "$VM_CPUS"
    -nographic
    -serial "mon:stdio"
    -qmp "tcp:0.0.0.0:4444,server,nowait"
    -drive "file=${VM_DISK},if=virtio,format=qcow2"
    -drive "file=${SEED_ISO},if=virtio,format=raw,readonly=on"
    -netdev "user,id=net0,hostfwd=tcp:0.0.0.0:22-:22,hostfwd=tcp:0.0.0.0:8080-:8080"
    -device "virtio-net-pci,netdev=net0,mac=52:54:00:12:34:56"
    -chardev "socket,id=chrtpm,path=${TPM_SOCKET}"
    -tpmdev "emulator,id=tpm0,chardev=chrtpm"
)

if [ "$DEB_ARCH" = "arm64" ]; then
    ACCEL="tcg"
    if [ -e /dev/kvm ]; then
        ACCEL="kvm"
    fi
    QEMU_ARGS+=(
        -machine "virt,accel=${ACCEL}"
        -cpu "$( [ "$ACCEL" = "kvm" ] && echo host || echo cortex-a72 )"
        -drive "if=pflash,format=raw,readonly=on,file=${FW_CODE}"
        -drive "if=pflash,format=raw,file=${FW_VARS}"
        -device "tpm-tis-device,tpmdev=tpm0"
    )
else
    ACCEL="tcg"
    if [ -e /dev/kvm ]; then
        ACCEL="kvm"
    fi
    QEMU_ARGS+=(
        -machine "q35,accel=${ACCEL}"
        -cpu "$( [ "$ACCEL" = "kvm" ] && echo host || echo max )"
        -device "tpm-tis,tpmdev=tpm0"
    )
    if [ "$USE_CUSTOM_ROM" = "true" ]; then
        QEMU_ARGS+=(-bios "$FW_CODE")
    else
        QEMU_ARGS+=(
            -drive "if=pflash,format=raw,readonly=on,file=${FW_CODE}"
            -drive "if=pflash,format=raw,file=${FW_VARS}"
        )
    fi
fi

log "Launching ${QEMU_BIN} (arch=${DEB_ARCH}, accel=${ACCEL}, mem=${VM_MEM}MB, cpus=${VM_CPUS})"
exec "$QEMU_BIN" "${QEMU_ARGS[@]}"
