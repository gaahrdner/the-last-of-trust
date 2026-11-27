#!/usr/bin/env python3
"""
The Last of Trust - TPM 2.0 Remote Attestation Verifier.

Performs real cryptographic remote attestation against tlot-host:
  1. Enrolls the host's TPM 2.0 Attestation Key (AK) public key and captures a
     golden PCR + IMA baseline.
  2. Challenges the host with a fresh cryptographic random nonce to obtain a
     TPM 2.0 Quote signed by the host's TPM AK.
  3. Cryptographically verifies the quote signature, nonce, and PCR digest
     using `tpm2_checkquote`.
  4. Compares attested PCR values against the golden baseline and diffs the
     Linux IMA runtime measurement log to pinpoint any untrusted/modified files.
"""

import base64
import datetime
import json
import os
import secrets
import subprocess
import tempfile
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST_AGENT_URL = os.environ.get("HOST_AGENT_URL", "http://10.101.0.10:8080")
PORT = int(os.environ.get("VERIFIER_PORT", "8888"))
STATE_DIR = Path("/var/lib/verifier")
BASELINE_FILE = STATE_DIR / "baseline.json"
AK_PEM_FILE = STATE_DIR / "host_ak.pem"
DEFAULT_PCRS = "0,1,4,7,8,9,10"

PCR_DESCRIPTIONS = {
    0: "Firmware / Core Root of Trust (SRTM)",
    1: "Platform Configuration & Firmware Variables",
    4: "Boot Manager / Bootloader Code",
    7: "Secure Boot Policy & Certificates",
    8: "GRUB Bootloader Commands & Kernel",
    9: "GRUB Kernel Command Line & Initrd",
    10: "Linux IMA Runtime Integrity Measurements",
}


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_json(url, method="GET", payload=None, timeout=30):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Host agent HTTP {exc.code}: {body}")
    except Exception as exc:
        raise RuntimeError(f"Failed to contact host agent ({url}): {exc}")


def verify_quote_crypto(ak_pem_path, nonce_hex, message_b64, signature_b64, pcrs_bin_b64):
    """Run tpm2_checkquote to cryptographically verify the TPM 2.0 Quote."""
    with tempfile.TemporaryDirectory() as td:
        msg_path = os.path.join(td, "quote.msg")
        sig_path = os.path.join(td, "quote.sig")
        pcr_path = os.path.join(td, "quote.pcrs")
        Path(msg_path).write_bytes(base64.b64decode(message_b64))
        Path(sig_path).write_bytes(base64.b64decode(signature_b64))
        Path(pcr_path).write_bytes(base64.b64decode(pcrs_bin_b64))

        proc = subprocess.run(
            [
                "tpm2_checkquote",
                "-u", str(ak_pem_path),
                "-m", msg_path,
                "-s", sig_path,
                "-f", pcr_path,
                "-g", "sha256",
                "-q", nonce_hex,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return proc.returncode == 0, proc.stdout.strip(), proc.stderr.strip()


def enroll_host(pcr_list=DEFAULT_PCRS):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    health = http_json(f"{HOST_AGENT_URL}/health")
    ak = http_json(f"{HOST_AGENT_URL}/tpm/ak")
    AK_PEM_FILE.write_text(ak["public_pem"], encoding="utf-8")

    # Immediately challenge with a quote during enrollment to prove AK possession
    nonce = secrets.token_hex(16)
    quote = http_json(
        f"{HOST_AGENT_URL}/tpm/quote",
        method="POST",
        payload={"nonce": nonce, "pcrs": pcr_list},
    )
    ok, stdout, stderr = verify_quote_crypto(
        AK_PEM_FILE,
        nonce,
        quote["message_b64"],
        quote["signature_b64"],
        quote["pcrs_bin_b64"],
    )
    if not ok:
        raise RuntimeError(f"Enrollment quote verification failed: {stderr or stdout}")

    ima = http_json(f"{HOST_AGENT_URL}/ima/log")
    ima_baseline = {}
    for e in ima.get("entries", []):
        ima_baseline.setdefault(e["path"], [])
        if e["file_hash"] not in ima_baseline[e["path"]]:
            ima_baseline[e["path"]].append(e["file_hash"])

    baseline = {
        "enrolled_at": utc_now(),
        "host": health.get("hostname", "tlot-host"),
        "arch": health.get("arch", "unknown"),
        "kernel": health.get("kernel", "unknown"),
        "ima_enabled": health.get("ima_enabled", False),
        "ak_fingerprint_sha256": ak["fingerprint_sha256"],
        "pcr_selection": pcr_list,
        "golden_pcrs": {str(k): v for k, v in quote["pcrs"].items()},
        "ima_entry_count": ima.get("count", 0),
        "ima_baseline": ima_baseline,
        "last_attestation": None,
    }
    BASELINE_FILE.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    return baseline


BOOT_PCRS = {"0", "1", "4", "7", "8", "9"}
UNTRUSTED_EXEC_PREFIXES = ("/tmp/", "/var/tmp/", "/home/", "/root/", "/dev/shm/")


def attest_host():
    if not BASELINE_FILE.exists() or not AK_PEM_FILE.exists():
        raise ValueError("Host is not enrolled yet. Call POST /api/v1/enroll first.")

    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    pcr_list = baseline.get("pcr_selection", DEFAULT_PCRS)
    nonce = secrets.token_hex(16)

    quote = http_json(
        f"{HOST_AGENT_URL}/tpm/quote",
        method="POST",
        payload={"nonce": nonce, "pcrs": pcr_list},
    )
    sig_ok, stdout, stderr = verify_quote_crypto(
        AK_PEM_FILE,
        nonce,
        quote["message_b64"],
        quote["signature_b64"],
        quote["pcrs_bin_b64"],
    )

    golden = baseline["golden_pcrs"]
    actual = {str(k): v for k, v in quote["pcrs"].items()}
    pcr_mismatches = []
    boot_pcr_mismatches = []
    for pcr_str, expected_val in golden.items():
        actual_val = actual.get(pcr_str)
        if actual_val != expected_val:
            diff = {
                "pcr": int(pcr_str),
                "description": PCR_DESCRIPTIONS.get(int(pcr_str), "Platform Register"),
                "expected": expected_val,
                "actual": actual_val,
            }
            pcr_mismatches.append(diff)
            if pcr_str in BOOT_PCRS:
                boot_pcr_mismatches.append(diff)

    ima = http_json(f"{HOST_AGENT_URL}/ima/log")
    known_ima = baseline.get("ima_baseline", {})
    if isinstance(known_ima, list):
        known_ima = {p: h for p, h in known_ima}

    ima_violations = []
    new_ima_entries = []
    for e in ima.get("entries", []):
        path = e["path"]
        fhash = e["file_hash"]
        if path in known_ima:
            allowed_hashes = known_ima[path] if isinstance(known_ima[path], list) else [known_ima[path]]
            if fhash not in allowed_hashes and not path.startswith(("/etc/mtab", "/var/log/", "/run/")):
                ima_violations.append({
                    "reason": "modified_file_hash",
                    "path": path,
                    "expected_hashes": allowed_hashes,
                    "actual_hash": fhash,
                })
        else:
            new_ima_entries.append(e)
            if path.startswith(UNTRUSTED_EXEC_PREFIXES):
                ima_violations.append({
                    "reason": "untrusted_path_execution",
                    "path": path,
                    "actual_hash": fhash,
                })

    trusted = sig_ok and len(boot_pcr_mismatches) == 0 and len(ima_violations) == 0
    result = {
        "timestamp": utc_now(),
        "verdict": "TRUSTED" if trusted else "UNTRUSTED",
        "quote_signature_valid": sig_ok,
        "nonce": nonce,
        "ak_fingerprint_sha256": baseline["ak_fingerprint_sha256"],
        "boot_pcr_mismatches": boot_pcr_mismatches,
        "pcr_mismatches": pcr_mismatches,
        "ima_violations": ima_violations,
        "pcrs": actual,
        "ima_total_entries": ima.get("count", 0),
        "ima_new_entries_count": len(new_ima_entries),
        "ima_new_entries": new_ima_entries[-25:],
        "verifier_error": None if sig_ok else (stderr or stdout),
    }

    baseline["last_attestation"] = result
    BASELINE_FILE.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    return result


class VerifierHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[tlot-verifier] {self.address_string()} - {fmt % args}", flush=True)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {
                "status": "ok",
                "enrolled": BASELINE_FILE.exists(),
                "host_agent_url": HOST_AGENT_URL,
            })
        elif self.path == "/api/v1/status":
            if not BASELINE_FILE.exists():
                self._send_json(200, {"enrolled": False, "message": "Not enrolled yet"})
                return
            baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
            summary = {k: v for k, v in baseline.items() if k != "ima_baseline"}
            self._send_json(200, {"enrolled": True, **summary})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        try:
            if self.path == "/api/v1/enroll":
                baseline = enroll_host()
                summary = {k: v for k, v in baseline.items() if k != "ima_baseline"}
                self._send_json(200, {"status": "enrolled", **summary})
            elif self.path == "/api/v1/attest":
                result = attest_host()
                code = 200 if result["verdict"] == "TRUSTED" else 409
                self._send_json(code, result)
            else:
                self._send_json(404, {"error": "not found"})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:
            self._send_json(502, {"error": str(exc)})


if __name__ == "__main__":
    print(f"[tlot-verifier] Starting on 0.0.0.0:{PORT} (host={HOST_AGENT_URL})", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), VerifierHandler)
    server.serve_forever()
