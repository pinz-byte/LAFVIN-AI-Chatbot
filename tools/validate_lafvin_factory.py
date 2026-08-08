#!/usr/bin/env python3
"""Read-only identification and backup helper for the LAFVIN ESP32-S3.

This tool intentionally exposes no erase, write, or flash operation. Its
default mode identifies the chip, flash, and MAC. Factory flash backup is
opt-in and still uses esptool's read-only `read-flash` operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from serial.tools import list_ports


LIKELY_DESCRIPTIONS = ("cp210", "silicon labs", "usb serial", "esp32", "jtag")


def discover_ports() -> list[dict[str, object]]:
    ports = []
    for port in list_ports.comports():
        description = f"{port.description or ''} {port.manufacturer or ''}".lower()
        likely = any(marker in description for marker in LIKELY_DESCRIPTIONS)
        ports.append(
            {
                "device": port.device,
                "description": port.description,
                "manufacturer": port.manufacturer,
                "vid": port.vid,
                "pid": port.pid,
                "likely_lafvin": likely,
            }
        )
    return ports


def run_esptool(port: str, command: str, *arguments: str) -> str:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "esptool",
            "--chip",
            "esp32s3",
            "--port",
            port,
            command,
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        raise RuntimeError(f"esptool {command} failed:\n{output}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="serial port; auto-detected only when exactly one likely port exists")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="optional directory for a read-only full factory-flash backup",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("hardware-validation.json"),
        help="JSON report path (default: hardware-validation.json)",
    )
    args = parser.parse_args()

    ports = discover_ports()
    likely_ports = [port["device"] for port in ports if port["likely_lafvin"]]
    port = args.port
    if port is None and len(likely_ports) == 1:
        port = str(likely_ports[0])

    report: dict[str, object] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "ports": ports,
        "selected_port": port,
        "writes_performed": False,
        "status": "no-device",
    }
    if port is None:
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print("No unambiguous LAFVIN/CP210x serial device found.", file=sys.stderr)
        print(json.dumps(ports, indent=2), file=sys.stderr)
        return 2

    try:
        report["chip_id"] = run_esptool(port, "chip-id")
        report["flash_id"] = run_esptool(port, "flash-id")
        report["mac"] = run_esptool(port, "read-mac")
        report["status"] = "identified"

        if args.backup_dir is not None:
            args.backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup = args.backup_dir / f"lafvin-factory-{timestamp}.bin"
            report["backup"] = run_esptool(port, "read-flash", "0", "ALL", str(backup))
            report["backup_path"] = str(backup.resolve())
            report["backup_sha256"] = hashlib.sha256(backup.read_bytes()).hexdigest()
            report["status"] = "identified-and-backed-up"
    except RuntimeError as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(exc, file=sys.stderr)
        return 1

    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
