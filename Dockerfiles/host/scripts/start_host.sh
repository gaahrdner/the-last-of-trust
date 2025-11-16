#!/bin/bash
set -e

# Start the TPM emulator
/build/setup_tpm.sh &

# Wait for the TPM socket to be available
echo "Waiting for TPM socket..."
while [ ! -S /tmp/swtpm-sock ]; do
  sleep 1
done
echo "TPM socket is ready"

# Prepare the Debian disk image
/build/create_debian_image.sh

# Determine which firmware to use
BIOS_OPTION=""
if [ -f /firmware/coreboot.rom ]; then
    echo "Starting QEMU with coreboot/linuxboot firmware..."
    BIOS_OPTION="-bios /firmware/coreboot.rom"
else
    echo "WARNING: coreboot.rom not found, using default BIOS (SeaBIOS)"
    echo "To use coreboot firmware, run: dagger call firmware build"
    # QEMU will use default SeaBIOS
fi

# Default command - run QEMU
exec qemu-system-x86_64 \
  -machine q35 \
  -m 2048 \
  -smp 2 \
  $BIOS_OPTION \
  -nographic \
  -serial mon:stdio \
  -device e1000,netdev=net0,mac=52:54:00:12:34:56 \
  -netdev user,id=net0,hostfwd=tcp::22-:22 \
  -drive file=/var/lib/host/debian.qcow2,if=virtio,format=qcow2 \
  -chardev socket,id=chrtpm,path=/tmp/swtpm-sock \
  -tpmdev emulator,id=tpm0,chardev=chrtpm \
  -device tpm-tis,tpmdev=tpm0