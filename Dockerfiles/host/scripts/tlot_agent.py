#!/usr/bin/env python3
"""
The Last of Trust - Host TPM 2.0 & IMA Attestation Agent.

Runs inside the QEMU guest VM and exposes a JSON HTTP API for:
  - Reading real TPM 2.0 PCRs via tpm2_pcrread
  - Provisioning/exposing a persistent TPM 2.0 Attestation Key (AK)
  - Generating fresh cryptographic TPM 2.0 Quotes via tpm2_quote
  - Reading the real UEFI/BIOS TPM 2.0 event log
  - Reading the real Linux IMA runtime measurement log
"""

import base64
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AK_HANDLE = "0x81010002"
EK_HANDLE = "0x81010001"
STATE_DIR = Path("/var/lib/tlot-agent")
AK_PUB_PEM = STATE_DIR / "ak.pem"
AK_PUB_TSS = STATE_DIR / "ak.pub"
EVENTLOG_PATH = Path("/sys/kernel/security/tpm0/binary_bios_measurements")
IMA_LOG_PATH = Path("/sys/kernel/security/ima/ascii_runtime_measurements")
PORT = int(os.environ.get("TLOT_AGENT_PORT", "8080"))


def run_cmd(cmd, timeout=30):
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command {' '.join(cmd)} failed (rc={proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


def ensure_ak():
    """Ensure a persistent TPM 2.0 Endorsement Key and Attestation Key exist."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if AK_PUB_PEM.exists() and AK_PUB_TSS.exists():
        # Verify handle still exists in TPM
        out = run_cmd(["tpm2_getcap", "handles-persistent"])
        if AK_HANDLE.lower() in out.lower():
            return

    with tempfile.TemporaryDirectory() as td:
        ek_ctx = os.path.join(td, "ek.ctx")
        ak_ctx = os.path.join(td, "ak.ctx")
        ak_name = os.path.join(td, "ak.name")

        # Evict stale handles if present
        out = run_cmd(["tpm2_getcap", "handles-persistent"])
        for h in (AK_HANDLE, EK_HANDLE):
            if h.lower() in out.lower():
                subprocess.run(
                    ["tpm2_evictcontrol", "-C", "o", "-c", h],
                    capture_output=True,
                )

        run_cmd(["tpm2_createek", "-c", ek_ctx, "-G", "rsa", "-u", os.path.join(td, "ek.pub")])
        run_cmd(["tpm2_evictcontrol", "-C", "o", "-c", ek_ctx, EK_HANDLE])

        run_cmd([
            "tpm2_createak",
            "-C", EK_HANDLE,
            "-c", ak_ctx,
            "-G", "rsa",
            "-g", "sha256",
            "-s", "rsassa",
            "-u", str(AK_PUB_TSS),
            "-n", ak_name,
        ])
        run_cmd(["tpm2_evictcontrol", "-C", "o", "-c", ak_ctx, AK_HANDLE])
        run_cmd(["tpm2_readpublic", "-c", AK_HANDLE, "-f", "pem", "-o", str(AK_PUB_PEM)])


def read_pcrs(pcr_list="0,1,2,3,4,5,6,7,8,9,10"):
    out = run_cmd(["tpm2_pcrread", f"sha256:{pcr_list}"])
    pcrs = {}
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s*:\s*0x([0-9a-fA-F]+)", line)
        if m:
            pcrs[int(m.group(1))] = m.group(2).lower()
    return pcrs


def generate_quote(nonce_hex, pcr_list="0,1,4,7,8,9,10"):
    ensure_ak()
    if not re.fullmatch(r"[0-9a-fA-F]{8,128}", nonce_hex or ""):
        raise ValueError("nonce must be 8-128 hex characters")

    tmp_root = "/dev/shm" if os.path.isdir("/dev/shm") else None
    with tempfile.TemporaryDirectory(dir=tmp_root) as td:
        msg_path = os.path.join(td, "quote.msg")
        sig_path = os.path.join(td, "quote.sig")
        pcr_path = os.path.join(td, "quote.pcrs")

        run_cmd([
            "tpm2_quote",
            "-c", AK_HANDLE,
            "-l", f"sha256:{pcr_list}",
            "-q", nonce_hex,
            "-m", msg_path,
            "-s", sig_path,
            "-o", pcr_path,
            "-g", "sha256",
        ])

        return {
            "nonce": nonce_hex,
            "pcr_selection": f"sha256:{pcr_list}",
            "message_b64": base64.b64encode(Path(msg_path).read_bytes()).decode(),
            "signature_b64": base64.b64encode(Path(sig_path).read_bytes()).decode(),
            "pcrs_bin_b64": base64.b64encode(Path(pcr_path).read_bytes()).decode(),
            "pcrs": read_pcrs(pcr_list),
        }


def read_ima_log(limit=None):
    if not IMA_LOG_PATH.exists():
        return {"available": False, "count": 0, "entries": []}
    entries = []
    with IMA_LOG_PATH.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.strip().split(None, 4)
            if len(parts) < 5:
                continue
            entries.append({
                "pcr": int(parts[0]),
                "template_hash": parts[1],
                "template": parts[2],
                "file_hash": parts[3],
                "path": parts[4],
            })
    total = len(entries)
    if limit is not None and limit > 0:
        entries = entries[-limit:]
    return {"available": True, "count": total, "entries": entries}


class AgentHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[tlot-agent] {self.address_string()} - {fmt % args}", flush=True)

    def do_GET(self):
        try:
            if self.path == "/health":
                tpm_ok = Path("/dev/tpmrm0").exists()
                ima_ok = IMA_LOG_PATH.exists()
                cmdline = Path("/proc/cmdline").read_text().strip()
                self._send_json(200, {
                    "status": "ok" if tpm_ok else "degraded",
                    "hostname": socket.gethostname(),
                    "arch": platform.machine(),
                    "kernel": platform.release(),
                    "tpm_device": tpm_ok,
                    "ima_enabled": ima_ok,
                    "eventlog_available": EVENTLOG_PATH.exists(),
                    "cmdline": cmdline,
                })
            elif self.path.startswith("/tpm/pcrs"):
                self._send_json(200, {"algorithm": "sha256", "pcrs": read_pcrs()})
            elif self.path == "/tpm/ak":
                ensure_ak()
                pem = AK_PUB_PEM.read_text()
                tss_b64 = base64.b64encode(AK_PUB_TSS.read_bytes()).decode()
                fp = hashlib.sha256(pem.encode()).hexdigest()
                self._send_json(200, {
                    "handle": AK_HANDLE,
                    "fingerprint_sha256": fp,
                    "public_pem": pem,
                    "public_tss_b64": tss_b64,
                })
            elif self.path == "/tpm/eventlog":
                if not EVENTLOG_PATH.exists():
                    self._send_json(404, {"error": "TPM event log not available"})
                    return
                raw = EVENTLOG_PATH.read_bytes()
                self._send_json(200, {
                    "size_bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "eventlog_b64": base64.b64encode(raw).decode(),
                })
            elif self.path.startswith("/ima/log"):
                self._send_json(200, read_ima_log())
            else:
                self._send_json(404, {"error": "not found"})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")

            if self.path == "/tpm/quote":
                nonce = data.get("nonce", "")
                pcrs = data.get("pcrs", "0,1,4,7,8,9,10")
                quote = generate_quote(nonce, pcrs)
                self._send_json(200, quote)
            else:
                self._send_json(404, {"error": "not found"})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})


if __name__ == "__main__":
    print(f"[tlot-agent] Starting on 0.0.0.0:{PORT}", flush=True)
    if Path("/dev/tpmrm0").exists():
        try:
            ensure_ak()
            print("[tlot-agent] TPM 2.0 Attestation Key ready", flush=True)
        except Exception as e:
            print(f"[tlot-agent] Warning: AK init deferred: {e}", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), AgentHandler)
    server.serve_forever()
