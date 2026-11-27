#!/usr/bin/env bash
set -euo pipefail

HOST_URL="${HOST_URL:-http://127.0.0.1:8081}"
BMC_URL="${BMC_URL:-https://127.0.0.1:8443}"
VERIFIER_URL="${VERIFIER_URL:-http://127.0.0.1:8888}"
BMC_AUTH="root:0penBmc"

pass() { echo "  [PASS] $*"; }
fail() { echo "  [FAIL] $*" >&2; exit 1; }

echo "=== 1. Waiting for host attestation agent (VM boot + IMA init) ==="
for i in $(seq 1 180); do
    if HEALTH=$(curl -sf "${HOST_URL}/health" 2>/dev/null); then
        IMA_OK=$(echo "$HEALTH" | jq -r '.ima_enabled')
        TPM_OK=$(echo "$HEALTH" | jq -r '.tpm_device')
        if [ "$TPM_OK" = "true" ] && [ "$IMA_OK" = "true" ]; then
            pass "Host online: $(echo "$HEALTH" | jq -c '{hostname, arch, kernel, tpm_device, ima_enabled}')"
            break
        fi
    fi
    if [ "$i" -eq 180 ]; then
        fail "Timed out waiting for host agent with TPM2 + IMA"
    fi
    sleep 3
done

echo "=== 2. Verifying real TPM 2.0 PCR measurements ==="
PCRS=$(curl -sf "${HOST_URL}/tpm/pcrs")
PCR0=$(echo "$PCRS" | jq -r '.pcrs["0"]')
PCR10=$(echo "$PCRS" | jq -r '.pcrs["10"]')
ZERO="0000000000000000000000000000000000000000000000000000000000000000"
[ -n "$PCR0" ] && [ "$PCR0" != "$ZERO" ] && [ "$PCR0" != "null" ] || fail "PCR 0 is zero or missing"
[ -n "$PCR10" ] && [ "$PCR10" != "$ZERO" ] && [ "$PCR10" != "null" ] || fail "PCR 10 (IMA) is zero or missing"
pass "PCR 0 (Firmware): ${PCR0:0:24}..."
pass "PCR 10 (IMA):     ${PCR10:0:24}..."

IMA_COUNT=$(curl -sf "${HOST_URL}/ima/log" | jq -r '.count')
[ "$IMA_COUNT" -gt 0 ] || fail "IMA measurement log is empty"
pass "IMA runtime log has ${IMA_COUNT} measured files"

echo "=== 3. Verifying BMC Redfish API & live QMP host status ==="
SYS=$(curl -skf -u "$BMC_AUTH" "${BMC_URL}/redfish/v1/Systems/host")
POWER=$(echo "$SYS" | jq -r '.PowerState')
[ "$POWER" = "On" ] || fail "Expected BMC PowerState=On, got ${POWER}"
pass "BMC Redfish System PowerState=${POWER}, BiosVersion=$(echo "$SYS" | jq -r '.BiosVersion')"

FW=$(curl -skf -u "$BMC_AUTH" "${BMC_URL}/redfish/v1/UpdateService/FirmwareInventory/host-firmware")
FW_VER=$(echo "$FW" | jq -r '.Version')
[ -n "$FW_VER" ] && [ "$FW_VER" != "unknown" ] || fail "BMC firmware inventory missing SHA-256"
pass "BMC FirmwareInventory host-firmware version=${FW_VER}"

echo "=== 4. Enrolling host & running cryptographic TPM 2.0 attestation ==="
ENROLL=$(curl -sf -X POST "${VERIFIER_URL}/api/v1/enroll")
AK_FP=$(echo "$ENROLL" | jq -r '.ak_fingerprint_sha256')
pass "Enrolled TPM 2.0 AK fingerprint=${AK_FP:0:24}..."

ATTEST=$(curl -sf -X POST "${VERIFIER_URL}/api/v1/attest")
VERDICT=$(echo "$ATTEST" | jq -r '.verdict')
SIG_OK=$(echo "$ATTEST" | jq -r '.quote_signature_valid')
[ "$VERDICT" = "TRUSTED" ] && [ "$SIG_OK" = "true" ] || fail "Expected TRUSTED attestation, got: $ATTEST"
pass "Cryptographic TPM 2.0 quote verified: verdict=${VERDICT}, nonce=$(echo "$ATTEST" | jq -r '.nonce')"

echo "=== 5. Tamper detection test (executing untrusted binary on host) ==="
docker exec tlot-host ssh -i /var/lib/host/ssh/id_ed25519 \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    lab@127.0.0.1 \
    'echo "#!/bin/sh" > /tmp/untrusted_payload.sh && echo "echo pwned" >> /tmp/untrusted_payload.sh && chmod +x /tmp/untrusted_payload.sh && /tmp/untrusted_payload.sh >/dev/null'

HTTP_CODE=$(curl -s -o /tmp/tlot_tamper.json -w "%{http_code}" -X POST "${VERIFIER_URL}/api/v1/attest")
TAMPER_VERDICT=$(jq -r '.verdict' /tmp/tlot_tamper.json)
MISMATCH_PCRS=$(jq -c '[.pcr_mismatches[].pcr]' /tmp/tlot_tamper.json)
DETECTED_FILE=$(jq -r '.ima_new_entries[] | select(.path | contains("untrusted_payload.sh")) | .path' /tmp/tlot_tamper.json | head -n1)
rm -f /tmp/tlot_tamper.json

[ "$HTTP_CODE" = "409" ] && [ "$TAMPER_VERDICT" = "UNTRUSTED" ] || fail "Expected UNTRUSTED (409) after tamper, got HTTP ${HTTP_CODE} (${TAMPER_VERDICT})"
[ -n "$DETECTED_FILE" ] || fail "Expected IMA diff to flag untrusted_payload.sh"
pass "Tamper detected! verdict=${TAMPER_VERDICT}, drifted PCRs=${MISMATCH_PCRS}, flagged=${DETECTED_FILE}"

echo ""
echo "ALL END-TO-END CHECKS PASSED!"
