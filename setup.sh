#!/bin/bash
set -e

echo "============================================"
echo "The Last of Trust - Setup Script"
echo "============================================"
echo ""

# Create required directories
echo "Creating required directories..."
mkdir -p firmware
mkdir -p logs/host
mkdir -p logs/bmc
mkdir -p logs/attestation
mkdir -p logs/offensive
mkdir -p logs/siem
mkdir -p configs/coreboot
mkdir -p configs/linux
mkdir -p configs/falco
mkdir -p configs/keylime
mkdir -p configs/osquery
mkdir -p configs/otel

echo "✓ Directories created"
echo ""

# Check for prerequisites
echo "Checking prerequisites..."
MISSING_DEPS=0

if ! command -v docker &> /dev/null; then
    echo "✗ Docker not found. Please install Docker Desktop for Mac"
    MISSING_DEPS=1
else
    echo "✓ Docker found"
fi

if ! command -v docker-compose &> /dev/null; then
    echo "✗ docker-compose not found. Please install docker-compose"
    MISSING_DEPS=1
else
    echo "✓ docker-compose found"
fi

if ! command -v dagger &> /dev/null; then
    echo "✗ Dagger CLI not found"
    echo "  Install with: curl -L https://dl.dagger.io/dagger/install.sh | sh"
    MISSING_DEPS=1
else
    DAGGER_VERSION=$(dagger version | head -1)
    echo "✓ Dagger found ($DAGGER_VERSION)"
fi

if ! command -v git &> /dev/null; then
    echo "✗ Git not found. Please install git"
    MISSING_DEPS=1
else
    echo "✓ Git found"
fi

echo ""

if [ $MISSING_DEPS -eq 1 ]; then
    echo "❌ Missing dependencies. Please install the required tools and run this script again."
    exit 1
fi

echo "✓ All prerequisites met!"
echo ""

# Create a basic .gitignore if it doesn't exist
if [ ! -f .gitignore ]; then
    echo "Creating .gitignore..."
    cat > .gitignore <<EOF
# Build artifacts
firmware/*.rom
firmware/*.bin

# Logs
logs/**/*.log
logs/**/*.txt

# VM images
*.qcow2
*.iso

# Dagger cache
.dagger/

# OS files
.DS_Store
*.swp
*.swo
*~
EOF
    echo "✓ .gitignore created"
    echo ""
fi

# Display next steps
echo "============================================"
echo "Setup Complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Build the firmware:"
echo "   dagger call firmware build"
echo ""
echo "2. Build the containers:"
echo "   dagger call container build-all"
echo ""
echo "3. Start the environment:"
echo "   dagger call environment up"
echo ""
echo "4. Check the status:"
echo "   dagger call environment status"
echo ""
echo "5. View logs:"
echo "   dagger call environment logs"
echo ""
echo "Or use Docker Compose directly:"
echo "   docker-compose build"
echo "   docker-compose up -d"
echo "   docker-compose ps"
echo "   docker-compose logs -f"
echo ""
echo "============================================"
echo ""
echo "For more information, see README.md or CLAUDE.md"
echo ""
