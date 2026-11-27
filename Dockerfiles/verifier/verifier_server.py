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
import hashlib
import json
import os
import secrets
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST_AGENT_URL = os.environ.get("HOST_AGENT_URL", "http://10.101.0.10:8080")
HOST_AGENT_TOKEN = os.environ.get("TLOT_AGENT_TOKEN", "")
BMC_URL = os.environ.get("BMC_URL", "https://10.101.0.20:443")
BMC_USER = os.environ.get("BMC_USER", "root")
BMC_PASS = os.environ.get("BMC_PASS", "0penBmc")
PORT = int(os.environ.get("VERIFIER_PORT", "8888"))
STATE_DIR = Path("/var/lib/verifier")
BASELINE_FILE = STATE_DIR / "baseline.json"
AK_PEM_FILE = STATE_DIR / "host_ak.pem"
DASHBOARD_FILE = Path("/opt/verifier/dashboard.html")
DEFAULT_PCRS = "0,1,4,7,8,9,10"

runtime_config = {
    "auto_quarantine": os.environ.get("AUTO_QUARANTINE", "false").lower() == "true",
    "attest_interval_seconds": int(os.environ.get("ATTEST_INTERVAL_SECONDS", "0")),
}
history_lock = threading.Lock()
attest_history = []

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
    headers = {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if HOST_AGENT_TOKEN:
        headers["Authorization"] = f"Bearer {HOST_AGENT_TOKEN}"
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


def replay_ima_pcr10(binary_b64):
    """
    Cryptographically replay Linux IMA binary_runtime_measurements into SHA-256 PCR 10.
    Proves the IMA measurement log matches the TPM-signed PCR 10 digest without omission.
    """
    data = base64.b64decode(binary_b64)
    pcr10 = b"\x00" * 32
    offset = 0
    total_len = len(data)
    entry_count = 0

    while offset + 28 <= total_len:
        pcr, = struct.unpack_from("<I", data, offset)
        offset += 4
        sha1_tmpl = data[offset:offset + 20]
        offset += 20
        name_len, = struct.unpack_from("<I", data, offset)
        offset += 4
        offset += name_len
        if offset + 4 > total_len:
            break
        data_len, = struct.unpack_from("<I", data, offset)
        offset += 4
        tmpl_data = data[offset:offset + data_len]
        offset += data_len

        if pcr == 10:
            if sha1_tmpl == b"\x00" * 20:
                entry_digest = b"\xff" * 32
            else:
                entry_digest = hashlib.sha256(tmpl_data).digest()
            pcr10 = hashlib.sha256(pcr10 + entry_digest).digest()
            entry_count += 1

    return pcr10.hex(), entry_count


def decode_uefi_eventlog():
    """Fetch and decode the host UEFI TPM 2.0 binary event log via tpm2_eventlog."""
    ev = http_json(f"{HOST_AGENT_URL}/tpm/eventlog")
    raw = base64.b64decode(ev["eventlog_b64"])
    with tempfile.TemporaryDirectory() as td:
        ev_path = os.path.join(td, "eventlog.bin")
        Path(ev_path).write_bytes(raw)
        proc = subprocess.run(
            ["tpm2_eventlog", ev_path],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode != 0:
            return {
                "available": True,
                "decoded": False,
                "size_bytes": ev["size_bytes"],
                "sha256": ev["sha256"],
                "error": proc.stderr.strip(),
            }
        # Count events per PCR from YAML output
        pcr_event_counts = {}
        total_events = 0
        for line in proc.stdout.splitlines():
            s = line.strip()
            if s.startswith("PCRIndex:"):
                idx = s.split(":", 1)[1].strip()
                pcr_event_counts[idx] = pcr_event_counts.get(idx, 0) + 1
                total_events += 1
        return {
            "available": True,
            "decoded": True,
            "size_bytes": ev["size_bytes"],
            "sha256": ev["sha256"],
            "total_events": total_events,
            "events_per_pcr": pcr_event_counts,
        }


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


def bmc_request(path, method="POST", payload=None, timeout=10):
    """Send an authenticated Redfish request to tlot-bmc over mgmt-net."""
    url = f"{BMC_URL.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    auth_b64 = base64.b64encode(f"{BMC_USER}:{BMC_PASS}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def quarantine_host_via_bmc(reason):
    """Quarantine an untrusted host via BMC Redfish ForceOff + Audit Log."""
    actions = {}
    try:
        actions["audit"] = bmc_request(
            "/redfish/v1/Managers/bmc/LogServices/Audit/Entries",
            method="POST",
            payload={
                "Name": "Attestation.Failure",
                "Severity": "Critical",
                "Message": reason,
            },
        )
    except Exception as exc:
        actions["audit_error"] = str(exc)

    try:
        actions["reset"] = bmc_request(
            "/redfish/v1/Systems/host/Actions/ComputerSystem.Reset",
            method="POST",
            payload={"ResetType": "ForceOff"},
        )
        actions["quarantined"] = True
    except Exception as exc:
        actions["quarantined"] = False
        actions["reset_error"] = str(exc)
    return actions


def attest_host(quarantine_on_fail=None):
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

    # Cryptographically replay binary IMA log against quoted PCR 10
    ima_replay_valid = False
    ima_replayed_pcr10 = None
    ima_replayed_entries = 0
    try:
        ima_bin = http_json(f"{HOST_AGENT_URL}/ima/binary")
        ima_replayed_pcr10, ima_replayed_entries = replay_ima_pcr10(ima_bin["binary_b64"])
        ima_replay_valid = (ima_replayed_pcr10 == actual.get("10"))
    except Exception:
        ima_replay_valid = False

    # Decode UEFI TPM 2.0 binary event log
    try:
        eventlog_summary = decode_uefi_eventlog()
    except Exception as exc:
        eventlog_summary = {"available": False, "decoded": False, "error": str(exc)}

    trusted = (
        sig_ok
        and ima_replay_valid
        and len(boot_pcr_mismatches) == 0
        and len(ima_violations) == 0
    )
    should_quarantine = (
        runtime_config["auto_quarantine"]
        if quarantine_on_fail is None
        else bool(quarantine_on_fail)
    )
    quarantine_result = None
    if not trusted and should_quarantine:
        reason = (
            f"Attestation UNTRUSTED: boot_pcr_mismatches={len(boot_pcr_mismatches)}, "
            f"ima_violations={len(ima_violations)}, ima_replay_valid={ima_replay_valid}"
        )
        quarantine_result = quarantine_host_via_bmc(reason)

    result = {
        "timestamp": utc_now(),
        "verdict": "TRUSTED" if trusted else "UNTRUSTED",
        "quote_signature_valid": sig_ok,
        "ima_pcr10_replay_valid": ima_replay_valid,
        "ima_replayed_pcr10": ima_replayed_pcr10,
        "ima_replayed_entries": ima_replayed_entries,
        "eventlog": eventlog_summary,
        "quarantine": quarantine_result,
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

    with history_lock:
        attest_history.append({
            "timestamp": result["timestamp"],
            "verdict": result["verdict"],
            "nonce": result["nonce"],
            "ima_pcr10_replay_valid": result["ima_pcr10_replay_valid"],
            "ima_violations_count": len(ima_violations),
            "quarantined": bool(quarantine_result and quarantine_result.get("quarantined")),
        })
        if len(attest_history) > 100:
            del attest_history[:-100]

    baseline["last_attestation"] = result
    BASELINE_FILE.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    return result


def background_monitor_loop():
    """Optional continuous attestation loop controlled by attest_interval_seconds."""
    while True:
        interval = runtime_config.get("attest_interval_seconds", 0)
        if interval <= 0:
            time.sleep(5)
            continue
        time.sleep(interval)
        if not BASELINE_FILE.exists():
            continue
        try:
            res = attest_host()
            print(
                f"[tlot-verifier] [monitor] verdict={res['verdict']} "
                f"ima_replay={res['ima_pcr10_replay_valid']} "
                f"violations={len(res['ima_violations'])}",
                flush=True,
            )
        except Exception as exc:
            print(f"[tlot-verifier] [monitor] error: {exc}", flush=True)


def build_dashboard_state():
    """Aggregate live Host, BMC, and Verifier state for the real-time UI."""
    # 1. Host telemetry (gracefully handles paused/quarantined host)
    host_info = {"reachable": False}
    try:
        health = http_json(f"{HOST_AGENT_URL}/health", timeout=3)
        pcrs = http_json(f"{HOST_AGENT_URL}/tpm/pcrs", timeout=5)
        ima = http_json(f"{HOST_AGENT_URL}/ima/log", timeout=5)
        host_info = {
            "reachable": True,
            "health": health,
            "pcrs": pcrs.get("pcrs", {}),
            "ima_count": ima.get("count", 0),
            "ima_recent": ima.get("entries", [])[-12:],
        }
    except Exception as exc:
        host_info = {"reachable": False, "error": str(exc)}

    # 2. BMC telemetry via Redfish
    bmc_info = {"reachable": False}
    try:
        sys_data = bmc_request("/redfish/v1/Systems/host", method="GET", timeout=3)
        fw_data = bmc_request(
            "/redfish/v1/UpdateService/FirmwareInventory/host-firmware",
            method="GET",
            timeout=3,
        )
        audit_data = bmc_request(
            "/redfish/v1/Managers/bmc/LogServices/Audit/Entries",
            method="GET",
            timeout=3,
        )
        bmc_info = {
            "reachable": True,
            "power_state": sys_data.get("PowerState", "Unknown"),
            "qmp_status": sys_data.get("Oem", {}).get("TheLastOfTrust", {}).get("QmpStatus", "unknown"),
            "bios_version": sys_data.get("BiosVersion", "Unknown"),
            "cpu_count": sys_data.get("ProcessorSummary", {}).get("Count", 0),
            "memory_gib": sys_data.get("MemorySummary", {}).get("TotalSystemMemoryGiB", 0),
            "firmware": fw_data.get("Oem", {}).get("TheLastOfTrust", {}),
            "audit_entries": audit_data.get("Members", [])[-20:],
        }
    except Exception as exc:
        bmc_info = {"reachable": False, "error": str(exc)}

    # 3. Verifier state
    baseline_summary = None
    if BASELINE_FILE.exists():
        b = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
        baseline_summary = {k: v for k, v in b.items() if k != "ima_baseline"}

    with history_lock:
        hist = list(attest_history[-25:])

    return {
        "timestamp": utc_now(),
        "host": host_info,
        "bmc": bmc_info,
        "verifier": {
            "enrolled": baseline_summary is not None,
            "baseline": baseline_summary,
            "config": dict(runtime_config),
            "history": hist,
            "pcr_descriptions": PCR_DESCRIPTIONS,
        },
    }


def run_replay_attack_demo():
    """Demonstrate TPM 2.0 quote replay rejection with a mismatched nonce."""
    if not AK_PEM_FILE.exists():
        raise ValueError("Enroll the host first before running the quote replay demo.")
    old_nonce = secrets.token_hex(16)
    fresh_nonce = secrets.token_hex(16)
    quote = http_json(
        f"{HOST_AGENT_URL}/tpm/quote",
        method="POST",
        payload={"nonce": old_nonce, "pcrs": DEFAULT_PCRS},
    )
    ok_old, _, _ = verify_quote_crypto(
        AK_PEM_FILE, old_nonce, quote["message_b64"], quote["signature_b64"], quote["pcrs_bin_b64"]
    )
    ok_replay, stdout, stderr = verify_quote_crypto(
        AK_PEM_FILE, fresh_nonce, quote["message_b64"], quote["signature_b64"], quote["pcrs_bin_b64"]
    )
    return {
        "timestamp": utc_now(),
        "old_nonce": old_nonce,
        "fresh_challenge_nonce": fresh_nonce,
        "original_quote_valid": ok_old,
        "replayed_quote_accepted": ok_replay,
        "rejection_reason": stderr or stdout or "Nonce mismatch in TPMS_ATTEST extraData",
    }


class VerifierHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, html_bytes):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html_bytes)))
        self.end_headers()
        self.wfile.write(html_bytes)

    def log_message(self, fmt, *args):
        print(f"[tlot-verifier] {self.address_string()} - {fmt % args}", flush=True)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            if DASHBOARD_FILE.exists():
                self._send_html(200, DASHBOARD_FILE.read_bytes())
            else:
                self._send_json(404, {"error": "dashboard.html not found"})
        elif self.path == "/api/v1/dashboard":
            self._send_json(200, build_dashboard_state())
        elif self.path == "/health":
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
        elif self.path == "/api/v1/eventlog":
            try:
                self._send_json(200, decode_uefi_eventlog())
            except Exception as exc:
                self._send_json(502, {"error": str(exc)})
        elif self.path == "/api/v1/history":
            with history_lock:
                self._send_json(200, {"count": len(attest_history), "entries": list(attest_history)})
        elif self.path == "/api/v1/config":
            self._send_json(200, runtime_config)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")

            if self.path == "/api/v1/enroll":
                baseline = enroll_host()
                summary = {k: v for k, v in baseline.items() if k != "ima_baseline"}
                self._send_json(200, {"status": "enrolled", **summary})
            elif self.path == "/api/v1/attest":
                q_flag = body.get("quarantine") if isinstance(body, dict) else None
                result = attest_host(quarantine_on_fail=q_flag)
                code = 200 if result["verdict"] == "TRUSTED" else 409
                self._send_json(code, result)
            elif self.path == "/api/v1/config":
                if "auto_quarantine" in body:
                    runtime_config["auto_quarantine"] = bool(body["auto_quarantine"])
                if "attest_interval_seconds" in body:
                    runtime_config["attest_interval_seconds"] = max(0, int(body["attest_interval_seconds"]))
                self._send_json(200, runtime_config)
            elif self.path == "/api/v1/verify-quote":
                if not AK_PEM_FILE.exists():
                    raise ValueError("Host is not enrolled yet.")
                ok, stdout, stderr = verify_quote_crypto(
                    AK_PEM_FILE,
                    body["expected_nonce"],
                    body["message_b64"],
                    body["signature_b64"],
                    body["pcrs_bin_b64"],
                )
                code = 200 if ok else 401
                self._send_json(code, {
                    "valid": ok,
                    "expected_nonce": body["expected_nonce"],
                    "error": None if ok else (stderr or stdout),
                })
            elif self.path == "/api/v1/demo/replay":
                self._send_json(200, run_replay_attack_demo())
            elif self.path == "/api/v1/bmc/reset":
                reset_type = body.get("ResetType", "")
                res = bmc_request(
                    "/redfish/v1/Systems/host/Actions/ComputerSystem.Reset",
                    method="POST",
                    payload={"ResetType": reset_type},
                )
                self._send_json(200, res)
            else:
                self._send_json(404, {"error": "not found"})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:
            self._send_json(502, {"error": str(exc)})


if __name__ == "__main__":
    print(f"[tlot-verifier] Starting on 0.0.0.0:{PORT} (host={HOST_AGENT_URL}, bmc={BMC_URL})", flush=True)
    threading.Thread(target=background_monitor_loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), VerifierHandler)
    server.serve_forever()
