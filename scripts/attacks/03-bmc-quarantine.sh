#!/usr/bin/env bash
# Attack Scenario 03: Attestation Failure -> Automatic Out-of-Band BMC Quarantine & Recovery
set -euo pipefail

VERIFIER_URL="${VERIFIER_URL:-http://127.0.0.1:8888}"
BMC_URL="${BMC_URL:-https://127.0.0.1:8443}"
BMC_AUTH="${BMC_AUTH:-root:0penBmc}"
PAYLOAD="/tmp/quarantine_trigger_$(date +%s).sh"

echo "[1/4] Enrolling clean baseline..."
curl -sf -X POST "${VERIFIER_URL}/api/v1/enroll" >/dev/null

echo "[2/4] Triggering untrusted execution on host (${PAYLOAD})..."
docker exec tlot-host ssh -i /var/lib/host/ssh/id_ed25519 \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    lab@127.0.0.1 \
    "printf '#!/bin/sh\necho trigger-quarantine\n' > ${PAYLOAD} && chmod +x ${PAYLOAD} && ${PAYLOAD} >/dev/null"

echo "[3/4] Running attestation with quarantine=true (expecting BMC ForceOff)..."
curl -s -X POST -H 'Content-Type: application/json' -d '{"quarantine":true}' "${VERIFIER_URL}/api/v1/attest" \
    | jq '{verdict, quarantine: {quarantined: .quarantine.quarantined, reset: .quarantine.reset.ResetType, audit_id: .quarantine.audit.Id}}'

POWER_AFTER=$(curl -skf -u "$BMC_AUTH" "${BMC_URL}/redfish/v1/Systems/host" | jq -r '.PowerState')
echo "      BMC reports host PowerState=${POWER_AFTER}"
[ "$POWER_AFTER" = "Paused" ] || { echo "Expected PowerState=Paused after quarantine, got ${POWER_AFTER}" >&2; exit 1; }

echo "[4/4] Recovering host via BMC Redfish ComputerSystem.Reset (On)..."
curl -skf -u "$BMC_AUTH" -X POST -H 'Content-Type: application/json' \
    -d '{"ResetType":"On"}' "${BMC_URL}/redfish/v1/Systems/host/Actions/ComputerSystem.Reset" | jq '{status, ResetType}'

POWER_RECOVERED=$(curl -skf -u "$BMC_AUTH" "${BMC_URL}/redfish/v1/Systems/host" | jq -r '.PowerState')
[ "$POWER_RECOVERED" = "On" ] || { echo "Expected PowerState=On after recovery, got ${POWER_RECOVERED}" >&2; exit 1; }
echo "[OK] Attack 03 quarantined via out-of-band BMC Redfish and cleanly recovered (PowerState=${POWER_RECOVERED})"
