#!/bin/bash
set -e

# Variables
DEBIAN_VERSION=${DEBIAN_VERSION:-bullseye}
DISK_SIZE=${DISK_SIZE:-8G}
IMAGE_PATH="/var/lib/host/debian.qcow2"
LOGS_DIR="/logs"

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOGS_DIR/debian_setup.log"
}

# Ensure logs directory exists
mkdir -p $LOGS_DIR

log "Starting Debian image preparation"

# Create the disk image if it doesn't exist
if [ ! -f "$IMAGE_PATH" ]; then
    log "Creating new Debian disk image..."
    qemu-img create -f qcow2 "$IMAGE_PATH" "$DISK_SIZE"
    
    # Download Debian netboot installer
    if [ ! -f "/build/debian-installer.iso" ]; then
        log "Downloading Debian installer..."
        # Try to get the current version dynamically
        wget -O /build/debian-installer.iso "https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-12.8.0-amd64-netinst.iso" || {
            log "Download failed, trying current link..."
            wget -O /build/debian-installer.iso "https://cdimage.debian.org/debian-cd/12.8.0/amd64/iso-cd/debian-12.8.0-amd64-netinst.iso" || {
                log "Download failed, skipping ISO download."
                log "You can manually download the ISO and mount it later."
            }
        }
    fi
    
    # Instructions for manual installation
    log "====================================================="
    log "Debian image created. To install Debian:"
    log "1. Add '-cdrom /build/debian-installer.iso' to the QEMU command line"
    log "2. Follow the installation prompts"
    log "3. Once installation is complete, remove the '-cdrom' option"
    log "====================================================="
    
    # Install security tools
    log "Note: After installing Debian, you will need to install:"
    log "- osquery for endpoint monitoring"
    log "- Falco for runtime security"
    log "- Chipsec for firmware security analysis"
    log "====================================================="
else
    log "Debian disk image already exists at $IMAGE_PATH"
fi

# Security configuration reminders
log "Security Configuration Recommendations:"
log "1. Enable Secure Boot in the OS if available"
log "2. Configure IMA (Integrity Measurement Architecture)"
log "3. Set up TPM2 tools for attestation"
log "4. Configure remote logging"

# Exit normally, as the main QEMU command will be provided by docker-compose
exit 0