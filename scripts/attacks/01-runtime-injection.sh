#!/usr/bin/env bash
# Attack Scenario 01: Untrusted Runtime Execution (detected by Linux IMA + PCR 10)
set -euo pipefail

VERIFIER_URL="${VERIFIER_URL:-http://127.0.0.1:8888}"
PAYLOAD="/tmp/attack_payload_$(date +%s).sh"

echo "[1/3] Enrolling clean baseline..."
curl -sf -X POST "${VERIFIER_URL}/api/v1/enroll" | jq '{status, ak_fingerprint_sha256, ima_entry_count}'

echo "[2/3] Injecting and executing untrusted payload (${PAYLOAD}) on tlot-host..."
docker exec tlot-host ssh -i /var/lib/host/ssh/id_ed25519 \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    lab@127.0.0.1 \
    "printf '#!/bin/sh\necho simulated-malware\n' > ${PAYLOAD} && chmod +x ${PAYLOAD} && ${PAYLOAD} >/dev/null"

echo "[3/3] Challenging host with remote attestation..."
HTTP_CODE=$(curl -s -o /tmp/tlot_attack01.json -w "%{http_code}" -X POST "${VERIFIER_URL}/api/v1/attest")
jq '{verdict, ima_pcr10_replay_valid, pcr_mismatches: [.pcr_mismatches[].pcr], ima_violations}' /tmp/tlot_attack01.json
rm -f /tmp/tlot_attack01.json

[ "$HTTP_CODE" = "409" ] || { echo "Expected HTTP 409 UNTRUSTED, got ${HTTP_CODE}" >&2; exit 1; }
echo "[OK] Attack 01 caught by TPM 2.0 + IMA (HTTP ${HTTP_CODE})"
