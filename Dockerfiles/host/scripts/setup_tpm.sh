#!/bin/bash
set -e

TPM_STATE_DIR="/var/lib/host/tpm"
TPM_SOCKET="/tmp/swtpm-sock"

# Create TPM state directory if it doesn't exist
mkdir -p $TPM_STATE_DIR

# Start the software TPM emulator
echo "Starting software TPM emulator..."
swtpm socket \
  --tpmstate dir=$TPM_STATE_DIR \
  --ctrl type=unixio,path=$TPM_SOCKET \
  --log level=20 \
  --tpm2

# We shouldn't get here unless there's an error
echo "TPM emulator exited unexpectedly"
exit 1