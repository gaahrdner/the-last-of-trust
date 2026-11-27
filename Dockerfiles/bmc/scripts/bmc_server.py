#!/usr/bin/env python3
"""
The Last of Trust - Out-of-Band BMC Controller (DMTF Redfish v1 API).

Provides a real HTTPS Redfish API (OpenBMC-compatible credentials & paths)
backed by live QEMU Machine Protocol (QMP) control over the isolated oob-net
network and real firmware inventory inspection from /firmware.
"""

import base64
import datetime
import json
import os
import socket
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

QMP_HOST = os.environ.get("HOST_QMP_ADDR", "10.100.0.10")
QMP_PORT = int(os.environ.get("HOST_QMP_PORT", "4444"))
BMC_USER = os.environ.get("BMC_USER", "root")
BMC_PASS = os.environ.get("BMC_PASS", "0penBmc")
HTTPS_PORT = int(os.environ.get("BMC_HTTPS_PORT", "443"))
CERT_DIR = Path("/var/lib/bmc/certs")
FIRMWARE_META = Path("/firmware/active-firmware.json")
AUDIT_LOG = Path("/logs/bmc_audit.jsonl")

audit_lock = threading.Lock()
audit_entries = []


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_audit(action, message, severity="OK"):
    entry = {
        "@odata.type": "#LogEntry.v1_11_0.LogEntry",
        "Id": str(len(audit_entries) + 1),
        "Name": action,
        "Created": utc_now(),
        "Severity": severity,
        "Message": message,
    }
    with audit_lock:
        audit_entries.append(entry)
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def ensure_tls_cert():
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    cert_file = CERT_DIR / "bmc.crt"
    key_file = CERT_DIR / "bmc.key"
    if not (cert_file.exists() and key_file.exists()):
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", str(key_file),
                "-out", str(cert_file),
                "-days", "365", "-nodes",
                "-subj", "/CN=tlot-bmc/O=TheLastOfTrust",
            ],
            check=True,
            capture_output=True,
        )
    return cert_file, key_file


def qmp_execute(command, arguments=None, timeout=5.0):
    """Send a single QMP command to the host QEMU instance over oob-net."""
    with socket.create_connection((QMP_HOST, QMP_PORT), timeout=timeout) as sock:
        f = sock.makefile("rwb", buffering=0)

        def read_json():
            line = f.readline()
            if not line:
                raise RuntimeError("QMP connection closed unexpectedly")
            return json.loads(line.decode("utf-8"))

        # 1. Read QMP greeting
        greeting = read_json()
        if "QMP" not in greeting:
            raise RuntimeError(f"Unexpected QMP greeting: {greeting}")

        # 2. Negotiate capabilities
        f.write(b'{"execute":"qmp_capabilities"}\n')
        cap_resp = read_json()
        if "error" in cap_resp:
            raise RuntimeError(f"QMP capabilities error: {cap_resp['error']}")

        # 3. Execute requested command
        payload = {"execute": command}
        if arguments:
            payload["arguments"] = arguments
        f.write((json.dumps(payload) + "\n").encode("utf-8"))

        # Skip async events until we get a return/error
        for _ in range(10):
            resp = read_json()
            if "return" in resp:
                return resp["return"]
            if "error" in resp:
                raise RuntimeError(f"QMP error: {resp['error']}")
        raise RuntimeError("No QMP response received")


def get_host_qmp_info():
    """Query live host state via QMP."""
    try:
        status = qmp_execute("query-status")
        mem = qmp_execute("query-memory-size-summary")
        cpus = qmp_execute("query-cpus-fast")
        running = bool(status.get("running", False))
        return {
            "reachable": True,
            "power_state": "On" if running else "Paused",
            "vm_status": status.get("status", "unknown"),
            "memory_mib": mem.get("base-memory", 0) // (1024 * 1024),
            "cpu_count": len(cpus),
        }
    except Exception as exc:
        return {
            "reachable": False,
            "power_state": "Off",
            "vm_status": f"unreachable: {exc}",
            "memory_mib": 0,
            "cpu_count": 0,
        }


def get_firmware_meta():
    if FIRMWARE_META.exists():
        try:
            return json.loads(FIRMWARE_META.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "id": "host-firmware",
        "name": "Unknown",
        "path": "unavailable",
        "architecture": "unknown",
        "size_bytes": 0,
        "sha256": "unknown",
        "tpm_version": "2.0",
        "measured_boot": False,
    }


class RedfishHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("OData-Version", "4.0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self):
        # ServiceRoot /redfish/v1 is unauthenticated per DMTF Redfish spec
        if self.path.rstrip("/") in ("/redfish", "/redfish/v1"):
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                user, passwd = decoded.split(":", 1)
                if user == BMC_USER and passwd == BMC_PASS:
                    return True
            except Exception:
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Redfish BMC"')
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Authentication required"}).encode())
        return False

    def log_message(self, fmt, *args):
        print(f"[tlot-bmc] {self.address_string()} - {fmt % args}", flush=True)

    def do_GET(self):
        if not self._check_auth():
            return
        path = self.path.rstrip("/")

        if path in ("/redfish", "/redfish/v1"):
            self._send_json(200, {
                "@odata.id": "/redfish/v1",
                "@odata.type": "#ServiceRoot.v1_13_0.ServiceRoot",
                "Id": "RootService",
                "Name": "The Last of Trust OpenBMC-Compatible Redfish Service",
                "RedfishVersion": "1.15.0",
                "Systems": {"@odata.id": "/redfish/v1/Systems"},
                "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
                "Managers": {"@odata.id": "/redfish/v1/Managers"},
                "UpdateService": {"@odata.id": "/redfish/v1/UpdateService"},
            })
        elif path == "/redfish/v1/Systems":
            self._send_json(200, {
                "@odata.id": "/redfish/v1/Systems",
                "@odata.type": "#ComputerSystemCollection.ComputerSystemCollection",
                "Name": "Computer System Collection",
                "Members@odata.count": 1,
                "Members": [{"@odata.id": "/redfish/v1/Systems/host"}],
            })
        elif path == "/redfish/v1/Systems/host":
            info = get_host_qmp_info()
            fw = get_firmware_meta()
            self._send_json(200, {
                "@odata.id": "/redfish/v1/Systems/host",
                "@odata.type": "#ComputerSystem.v1_19_0.ComputerSystem",
                "Id": "host",
                "Name": "tlot-host",
                "SystemType": "Virtual",
                "Manufacturer": "QEMU",
                "Model": f"Measured Boot Host ({fw.get('architecture', 'unknown')})",
                "PowerState": info["power_state"],
                "Status": {
                    "State": "Enabled" if info["reachable"] else "UnavailableOffline",
                    "Health": "OK" if info["reachable"] else "Warning",
                },
                "BiosVersion": fw.get("name", "Unknown"),
                "ProcessorSummary": {
                    "Count": info["cpu_count"],
                    "Status": {"State": "Enabled", "Health": "OK"},
                },
                "MemorySummary": {
                    "TotalSystemMemoryGiB": round(info["memory_mib"] / 1024.0, 2),
                    "Status": {"State": "Enabled", "Health": "OK"},
                },
                "TrustedModules": [{
                    "FirmwareVersion": "2.0 (swtpm)",
                    "InterfaceType": "TPM2_0",
                    "Status": {"State": "Enabled", "Health": "OK"},
                }],
                "Oem": {
                    "TheLastOfTrust": {
                        "QmpStatus": info["vm_status"],
                        "FirmwareSha256": fw.get("sha256"),
                    }
                },
                "Actions": {
                    "#ComputerSystem.Reset": {
                        "target": "/redfish/v1/Systems/host/Actions/ComputerSystem.Reset",
                        "ResetType@Redfish.AllowableValues": [
                            "On",
                            "ForceOff",
                            "GracefulShutdown",
                            "ForceRestart",
                        ],
                    }
                },
            })
        elif path == "/redfish/v1/Chassis":
            self._send_json(200, {
                "@odata.id": "/redfish/v1/Chassis",
                "@odata.type": "#ChassisCollection.ChassisCollection",
                "Members@odata.count": 1,
                "Members": [{"@odata.id": "/redfish/v1/Chassis/1"}],
            })
        elif path == "/redfish/v1/Chassis/1":
            info = get_host_qmp_info()
            self._send_json(200, {
                "@odata.id": "/redfish/v1/Chassis/1",
                "@odata.type": "#Chassis.v1_20_0.Chassis",
                "Id": "1",
                "Name": "TLOT Security Testbed Chassis",
                "ChassisType": "RackMount",
                "PowerState": info["power_state"],
                "Status": {"State": "Enabled", "Health": "OK"},
            })
        elif path == "/redfish/v1/Managers":
            self._send_json(200, {
                "@odata.id": "/redfish/v1/Managers",
                "@odata.type": "#ManagerCollection.ManagerCollection",
                "Members@odata.count": 1,
                "Members": [{"@odata.id": "/redfish/v1/Managers/bmc"}],
            })
        elif path == "/redfish/v1/Managers/bmc":
            self._send_json(200, {
                "@odata.id": "/redfish/v1/Managers/bmc",
                "@odata.type": "#Manager.v1_15_0.Manager",
                "Id": "bmc",
                "Name": "tlot-bmc",
                "ManagerType": "BMC",
                "FirmwareVersion": "tlot-bmc-1.0.0",
                "Status": {"State": "Enabled", "Health": "OK"},
                "DateTime": utc_now(),
                "LogServices": {"@odata.id": "/redfish/v1/Managers/bmc/LogServices"},
            })
        elif path == "/redfish/v1/Managers/bmc/LogServices":
            self._send_json(200, {
                "@odata.id": "/redfish/v1/Managers/bmc/LogServices",
                "Members@odata.count": 1,
                "Members": [{"@odata.id": "/redfish/v1/Managers/bmc/LogServices/Audit"}],
            })
        elif path == "/redfish/v1/Managers/bmc/LogServices/Audit":
            self._send_json(200, {
                "@odata.id": "/redfish/v1/Managers/bmc/LogServices/Audit",
                "Id": "Audit",
                "Name": "BMC Out-of-Band Audit Log",
                "Entries": {"@odata.id": "/redfish/v1/Managers/bmc/LogServices/Audit/Entries"},
            })
        elif path == "/redfish/v1/Managers/bmc/LogServices/Audit/Entries":
            self._send_json(200, {
                "@odata.id": "/redfish/v1/Managers/bmc/LogServices/Audit/Entries",
                "Name": "Audit Log Entries",
                "Members@odata.count": len(audit_entries),
                "Members": audit_entries[-100:],
            })
        elif path == "/redfish/v1/UpdateService":
            self._send_json(200, {
                "@odata.id": "/redfish/v1/UpdateService",
                "@odata.type": "#UpdateService.v1_11_0.UpdateService",
                "Id": "UpdateService",
                "Name": "Firmware Update Service",
                "ServiceEnabled": True,
                "FirmwareInventory": {
                    "@odata.id": "/redfish/v1/UpdateService/FirmwareInventory"
                },
            })
        elif path == "/redfish/v1/UpdateService/FirmwareInventory":
            self._send_json(200, {
                "@odata.id": "/redfish/v1/UpdateService/FirmwareInventory",
                "Members@odata.count": 1,
                "Members": [
                    {"@odata.id": "/redfish/v1/UpdateService/FirmwareInventory/host-firmware"}
                ],
            })
        elif path == "/redfish/v1/UpdateService/FirmwareInventory/host-firmware":
            fw = get_firmware_meta()
            self._send_json(200, {
                "@odata.id": "/redfish/v1/UpdateService/FirmwareInventory/host-firmware",
                "@odata.type": "#SoftwareInventory.v1_8_0.SoftwareInventory",
                "Id": fw.get("id", "host-firmware"),
                "Name": fw.get("name", "Host Firmware"),
                "Version": fw.get("sha256", "unknown")[:16],
                "Updateable": False,
                "Status": {"State": "Enabled", "Health": "OK"},
                "Oem": {"TheLastOfTrust": fw},
            })
        else:
            self._send_json(404, {"error": f"Unknown Redfish resource: {path}"})

    def do_POST(self):
        if not self._check_auth():
            return
        path = self.path.rstrip("/")
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON body"})
            return

        if path == "/redfish/v1/Systems/host/Actions/ComputerSystem.Reset":
            reset_type = body.get("ResetType", "")
            qmp_map = {
                "ForceRestart": ("system_reset", "Host hard reset via QMP system_reset"),
                "GracefulShutdown": ("system_powerdown", "Host ACPI powerdown via QMP"),
                "ForceOff": ("stop", "Host CPU halted via QMP stop"),
                "On": ("cont", "Host CPU resumed via QMP cont"),
            }
            if reset_type not in qmp_map:
                self._send_json(400, {
                    "error": f"Unsupported ResetType '{reset_type}'",
                    "allowable_values": list(qmp_map.keys()),
                })
                return
            cmd, desc = qmp_map[reset_type]
            try:
                qmp_execute(cmd)
                record_audit(f"ComputerSystem.Reset:{reset_type}", desc)
                self._send_json(200, {
                    "status": "success",
                    "ResetType": reset_type,
                    "qmp_command": cmd,
                    "message": desc,
                })
            except Exception as exc:
                record_audit(f"ComputerSystem.Reset:{reset_type}", str(exc), severity="Critical")
                self._send_json(502, {"error": f"QMP command failed: {exc}"})
        elif path == "/redfish/v1/Managers/bmc/LogServices/Audit/Entries":
            action = body.get("Name", "Security.Event")
            message = body.get("Message", "")
            severity = body.get("Severity", "Warning")
            record_audit(action, message, severity=severity)
            self._send_json(201, audit_entries[-1])
        else:
            self._send_json(404, {"error": f"Unknown Redfish action: {path}"})


if __name__ == "__main__":
    cert_file, key_file = ensure_tls_cert()
    record_audit("BMC.Startup", f"Redfish BMC listening on :{HTTPS_PORT} (QMP target {QMP_HOST}:{QMP_PORT})")
    server = ThreadingHTTPServer(("0.0.0.0", HTTPS_PORT), RedfishHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print(f"[tlot-bmc] Redfish HTTPS server listening on 0.0.0.0:{HTTPS_PORT}", flush=True)
    server.serve_forever()
