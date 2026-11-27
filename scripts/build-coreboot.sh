#!/bin/bash
set -e

# Coreboot build script with TPM support
# This builds Coreboot for QEMU Q35 with measured boot enabled

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="${PROJECT_ROOT}/firmware/build"
OUTPUT_DIR="${PROJECT_ROOT}/firmware"
CONFIG_DIR="${PROJECT_ROOT}/configs/coreboot"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Check dependencies
check_dependencies() {
    log "Checking build dependencies..."

    local deps=("git" "make" "gcc" "g++" "bison" "flex" "m4" "gnat")
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null; then
            error "Required dependency '$dep' not found. Please install it."
        fi
    done

    log "All dependencies found"
}

# Clone Coreboot if needed
clone_coreboot() {
    log "Checking Coreboot repository..."

    if [ ! -d "${BUILD_DIR}/coreboot" ]; then
        log "Cloning Coreboot repository..."
        mkdir -p "${BUILD_DIR}"
        git clone --depth=1 https://review.coreboot.org/coreboot "${BUILD_DIR}/coreboot"
        cd "${BUILD_DIR}/coreboot"
        git submodule update --init --checkout
    else
        log "Coreboot repository exists, updating..."
        cd "${BUILD_DIR}/coreboot"
        git pull
        git submodule update --init --checkout
    fi
}

# Build toolchain
build_toolchain() {
    log "Building Coreboot toolchain..."
    cd "${BUILD_DIR}/coreboot"

    if [ ! -d "util/crossgcc/xgcc" ]; then
        log "Building cross-compiler toolchain (this takes a while...)"
        make crossgcc-i386 CPUS=$(nproc)
    else
        log "Toolchain already built, skipping..."
    fi
}

# Configure Coreboot
configure_coreboot() {
    log "Configuring Coreboot for QEMU Q35 with TPM..."
    cd "${BUILD_DIR}/coreboot"

    # Start with default QEMU Q35 config
    make defconfig KBUILD_DEFCONFIG=configs/config.emulation_qemu_x86_q35

    # Apply our TPM-specific configuration
    if [ -f "${CONFIG_DIR}/qemu-q35-tpm.defconfig" ]; then
        log "Applying TPM configuration..."
        cp "${CONFIG_DIR}/qemu-q35-tpm.defconfig" .config
        make olddefconfig
    else
        warn "Custom TPM config not found, using default QEMU config"
    fi

    # Enable TPM options via menuconfig options
    ./util/scripts/config --enable CONFIG_TPM
    ./util/scripts/config --enable CONFIG_TPM2
    ./util/scripts/config --enable CONFIG_MAINBOARD_HAS_TPM2
    ./util/scripts/config --enable CONFIG_TPM_MEASURED_BOOT
    ./util/scripts/config --enable CONFIG_VBOOT_MEASURED_BOOT
    ./util/scripts/config --enable CONFIG_DEBUG_TPM

    # Update config with dependencies
    make olddefconfig

    log "Configuration complete"
}

# Build LinuxBoot payload (simplified kernel)
build_linuxboot_payload() {
    log "Building LinuxBoot payload..."

    local KERNEL_DIR="${BUILD_DIR}/linuxboot"

    if [ ! -d "$KERNEL_DIR" ]; then
        log "Downloading Linux kernel for LinuxBoot..."
        mkdir -p "$KERNEL_DIR"
        cd "$KERNEL_DIR"

        # Download a small kernel (we'll use latest stable)
        wget -c https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.1.tar.xz
        tar xf linux-6.1.tar.xz
        cd linux-6.1

        # Minimal config for LinuxBoot
        make defconfig

        # Enable TPM drivers
        ./scripts/config --enable CONFIG_TCG_TPM
        ./scripts/config --enable CONFIG_TCG_TIS
        ./scripts/config --enable CONFIG_TCG_CRB
        ./scripts/config --enable CONFIG_IMA
        ./scripts/config --enable CONFIG_IMA_MEASURE_PCR_IDX
        ./scripts/config --set-val CONFIG_IMA_MEASURE_PCR_IDX 10
        ./scripts/config --enable CONFIG_IMA_DEFAULT_HASH_SHA256

        make olddefconfig

        log "Building kernel (this may take a while...)"
        make -j$(nproc) bzImage

        # Copy kernel to coreboot payload location
        cp arch/x86/boot/bzImage "${BUILD_DIR}/coreboot/payload.elf"
    else
        log "LinuxBoot payload already exists, skipping build..."
        if [ -f "$KERNEL_DIR/linux-6.1/arch/x86/boot/bzImage" ]; then
            cp "$KERNEL_DIR/linux-6.1/arch/x86/boot/bzImage" "${BUILD_DIR}/coreboot/payload.elf"
        fi
    fi
}

# Build Coreboot
build_coreboot() {
    log "Building Coreboot..."
    cd "${BUILD_DIR}/coreboot"

    # Build with maximum verbosity for debugging
    make -j$(nproc) V=1

    if [ -f "build/coreboot.rom" ]; then
        log "Coreboot built successfully!"
        log "ROM size: $(stat -f%z "build/coreboot.rom" 2>/dev/null || stat --printf="%s" "build/coreboot.rom") bytes"

        # Copy to output directory
        mkdir -p "${OUTPUT_DIR}"
        cp build/coreboot.rom "${OUTPUT_DIR}/coreboot.rom"

        log "Coreboot ROM copied to ${OUTPUT_DIR}/coreboot.rom"
    else
        error "Coreboot build failed!"
    fi
}

# Verify ROM
verify_rom() {
    log "Verifying ROM..."

    if [ ! -f "${OUTPUT_DIR}/coreboot.rom" ]; then
        error "ROM file not found!"
    fi

    local rom_size=$(stat -f%z "${OUTPUT_DIR}/coreboot.rom" 2>/dev/null || stat --printf="%s" "${OUTPUT_DIR}/coreboot.rom")
    log "ROM size: $rom_size bytes"

    # Check if cbfstool exists
    if [ -f "${BUILD_DIR}/coreboot/util/cbfstool/cbfstool" ]; then
        log "Contents of ROM:"
        "${BUILD_DIR}/coreboot/util/cbfstool/cbfstool" "${OUTPUT_DIR}/coreboot.rom" print
    fi

    log "✓ ROM verification complete"
}

# Main build process
main() {
    log "=== Coreboot Build Script ==="
    log "Building Coreboot with TPM Measured Boot support"

    check_dependencies
    clone_coreboot
    build_toolchain
    configure_coreboot
    build_linuxboot_payload
    build_coreboot
    verify_rom

    log "=== Build Complete ==="
    log "Coreboot ROM with TPM support is ready:"
    log "  ${OUTPUT_DIR}/coreboot.rom"
    log ""
    log "To use this ROM:"
    log "  1. Restart the environment: docker compose restart host"
    log "  2. The new ROM will be automatically loaded"
    log "  3. Check boot logs: docker logs -f tlot-host"
}

# Run main
main "$@"
