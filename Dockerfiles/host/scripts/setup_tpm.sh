#!/usr/bin/env bash
set -euo pipefail

TPM_STATE_DIR="/var/lib/host/tpm"
TPM_SOCKET="/tmp/swtpm-sock"
TPM_LOG="/logs/swtpm.log"

mkdir -p "$TPM_STATE_DIR" /logs
rm -f "$TPM_SOCKET"

echo "[swtpm] Starting TPM 2.0 emulator (state: $TPM_STATE_DIR, socket: $TPM_SOCKET)"
exec swtpm socket \
    --tpmstate "dir=${TPM_STATE_DIR}" \
    --ctrl "type=unixio,path=${TPM_SOCKET}" \
    --log "file=${TPM_LOG},level=5" \
    --tpm2
