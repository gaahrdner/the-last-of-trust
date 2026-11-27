#!/usr/bin/env bash
# Attack Scenario 02: TPM 2.0 Quote Replay Attack (rejected by tpm2_checkquote nonce check)
set -euo pipefail

HOST_URL="${HOST_URL:-http://127.0.0.1:8081}"
VERIFIER_URL="${VERIFIER_URL:-http://127.0.0.1:8888}"
OLD_NONCE="deadbeef00112233445566778899aabb"
FRESH_NONCE="11223344556677889900aabbccddeeff"

echo "[1/3] Obtaining a genuine TPM 2.0 Quote signed for old nonce (${OLD_NONCE})..."
QUOTE=$(curl -sf -X POST -H 'Content-Type: application/json' \
    -d "{\"nonce\":\"${OLD_NONCE}\"}" "${HOST_URL}/tpm/quote")

echo "[2/3] Verifying quote with matching nonce (should succeed)..."
PAYLOAD_GOOD=$(echo "$QUOTE" | jq --arg n "$OLD_NONCE" '{expected_nonce: $n, message_b64, signature_b64, pcrs_bin_b64}')
curl -sf -X POST -H 'Content-Type: application/json' -d "$PAYLOAD_GOOD" "${VERIFIER_URL}/api/v1/verify-quote" | jq .

echo "[3/3] Replaying the exact same signed quote against a fresh challenge nonce (${FRESH_NONCE})..."
PAYLOAD_REPLAY=$(echo "$QUOTE" | jq --arg n "$FRESH_NONCE" '{expected_nonce: $n, message_b64, signature_b64, pcrs_bin_b64}')
HTTP_CODE=$(curl -s -o /tmp/tlot_attack02.json -w "%{http_code}" -X POST -H 'Content-Type: application/json' -d "$PAYLOAD_REPLAY" "${VERIFIER_URL}/api/v1/verify-quote")
jq . /tmp/tlot_attack02.json
rm -f /tmp/tlot_attack02.json

[ "$HTTP_CODE" = "401" ] || { echo "Expected HTTP 401 replay rejection, got ${HTTP_CODE}" >&2; exit 1; }
echo "[OK] Attack 02 quote replay cryptographically rejected by tpm2_checkquote (HTTP ${HTTP_CODE})"
