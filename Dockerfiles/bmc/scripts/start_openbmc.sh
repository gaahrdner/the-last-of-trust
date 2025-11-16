#!/bin/bash
set -e

OPENBMC_DIR="/var/lib/openbmc"
QEMU_MACHINE=${QEMU_MACHINE:-q35}
QEMU_ARCH=${QEMU_ARCH:-x86_64}
MACHINE=${MACHINE:-qemu-x86}
LOGS_DIR="/logs"
FIRMWARE_DIR="/firmware"

# Ensure logs directory exists
mkdir -p $LOGS_DIR

# Check if OpenBMC is already built
if [ ! -f "$OPENBMC_DIR/openbmc-image.qcow2" ]; then
    echo "OpenBMC image not found. Using pre-built QEMU OpenBMC image..."
    
    # Clone OpenBMC (for reference materials, we won't build from scratch in container)
    if [ ! -d "$OPENBMC_DIR/openbmc" ]; then
        git clone https://github.com/openbmc/openbmc "$OPENBMC_DIR/openbmc" --depth=1
    fi
    
    # Download a pre-built QEMU OpenBMC image
    # Check if the firmware contains an OpenBMC image first
    if [ -f "$FIRMWARE_DIR/obmc-phosphor-image-qemu-x86.qcow2" ]; then
        echo "Using OpenBMC image from firmware directory"
        cp "$FIRMWARE_DIR/obmc-phosphor-image-qemu-x86.qcow2" "$OPENBMC_DIR/openbmc-image.qcow2"
    else
        echo "Downloading pre-built OpenBMC image..."
        # Note: URL is for example only - you would need to provide a real image location
        wget -O "$OPENBMC_DIR/openbmc-image.qcow2.xz" "https://github.com/openbmc/openbmc/releases/download/x.y.z/obmc-phosphor-image-qemu-x86.qcow2.xz" || {
            echo "Pre-built image download failed. Creating a dummy image for demonstration."
            qemu-img create -f qcow2 "$OPENBMC_DIR/openbmc-image.qcow2" 1G
        }
        
        # Uncompress if needed
        if [ -f "$OPENBMC_DIR/openbmc-image.qcow2.xz" ]; then
            xz -d "$OPENBMC_DIR/openbmc-image.qcow2.xz"
        fi
    fi
fi

# Initialize Redfish and other services
/build/start_redfish.sh &

# Log BMC boot information
echo "Starting BMC with QEMU at $(date)" | tee -a $LOGS_DIR/bmc_boot.log

# Start QEMU with OpenBMC image
# Using user-mode networking for better macOS/Docker compatibility
echo "Starting QEMU with OpenBMC image..."
exec qemu-system-x86_64 \
  -machine $QEMU_MACHINE \
  -m 512 \
  -drive file=$OPENBMC_DIR/openbmc-image.qcow2,format=qcow2,if=virtio \
  -nographic \
  -serial mon:stdio \
  -device e1000,netdev=net0,mac=52:54:00:12:34:57 \
  -netdev user,id=net0,hostfwd=tcp::443-:443,hostfwd=tcp::623-:623 | tee -a $LOGS_DIR/bmc_console.log