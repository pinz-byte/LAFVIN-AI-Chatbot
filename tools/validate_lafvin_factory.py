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
FLASH_SIZE = 16 * 1024 * 1024


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


def run_esptool(port: str, baud: int, command: str, *arguments: str) -> str:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "esptool",
            "--chip",
            "esp32s3",
            "--port",
            port,
            "--baud",
            str(baud),
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


def backup_flash(
    port: str,
    baud: int,
    backup: Path,
    *,
    chunk_size: int,
    retries: int,
) -> None:
    parts_dir = backup.with_suffix(".parts")
    parts_dir.mkdir(parents=True, exist_ok=False)
    chunks: list[Path] = []
    try:
        for offset in range(0, FLASH_SIZE, chunk_size):
            size = min(chunk_size, FLASH_SIZE - offset)
            chunk = parts_dir / f"{offset:08x}.bin"
            chunks.append(chunk)
            for attempt in range(1, retries + 1):
                print(
                    f"Reading factory flash 0x{offset:08x}-0x{offset + size:08x} "
                    f"(attempt {attempt}/{retries})",
                    flush=True,
                )
                if chunk.exists():
                    chunk.unlink()
                try:
                    run_esptool(
                        port,
                        baud,
                        "read-flash",
                        hex(offset),
                        hex(size),
                        str(chunk),
                    )
                except RuntimeError:
                    if attempt == retries:
                        raise
                    continue
                if chunk.stat().st_size == size:
                    break
                if attempt == retries:
                    raise RuntimeError(
                        f"chunk at 0x{offset:x} has size {chunk.stat().st_size}, expected {size}"
                    )

        combined = parts_dir / "combined.bin"
        with combined.open("wb") as output:
            for chunk in chunks:
                output.write(chunk.read_bytes())
        if combined.stat().st_size != FLASH_SIZE:
            raise RuntimeError(
                f"combined backup has size {combined.stat().st_size}, expected {FLASH_SIZE}"
            )
        combined.replace(backup)
    finally:
        for chunk in [*chunks, parts_dir / "combined.bin"]:
            if chunk.exists():
                chunk.unlink()
        if parts_dir.exists():
            parts_dir.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="serial port; auto-detected only when exactly one likely port exists")
    parser.add_argument(
        "--baud",
        type=int,
        default=460800,
        choices=(115200, 230400, 460800, 921600),
        help="read baud after ROM sync (default: 460800)",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="optional directory for a read-only full factory-flash backup",
    )
    parser.add_argument(
        "--chunk-size",
        type=lambda value: int(value, 0),
        default=0x100000,
        help="backup read chunk size (default: 0x100000 / 1 MiB)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="read retries per backup chunk (default: 3)",
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
        report["chip_id"] = run_esptool(port, args.baud, "chip-id")
        report["flash_id"] = run_esptool(port, args.baud, "flash-id")
        report["mac"] = run_esptool(port, args.baud, "read-mac")
        report["status"] = "identified"

        if args.backup_dir is not None:
            if args.chunk_size <= 0 or args.chunk_size > FLASH_SIZE:
                raise RuntimeError("chunk size must be between 1 and 16 MiB")
            if args.retries < 1 or args.retries > 10:
                raise RuntimeError("retries must be between 1 and 10")
            args.backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup = args.backup_dir / f"lafvin-factory-{timestamp}.bin"
            backup_flash(
                port,
                args.baud,
                backup,
                chunk_size=args.chunk_size,
                retries=args.retries,
            )
            report["backup_method"] = "chunked-read-only"
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
