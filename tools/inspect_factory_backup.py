#!/usr/bin/env python3
"""Extract non-secret partition and app metadata from an ESP32 flash backup."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


PARTITION_TABLE_OFFSET = 0x8000
PARTITION_ENTRY_SIZE = 32
PARTITION_MAGIC = 0x50AA
APP_IMAGE_MAGIC = 0xE9
APP_DESCRIPTION_MAGIC = 0xABCD5432


def c_string(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def inspect_app(image: bytes, offset: int, size: int) -> dict[str, object] | None:
    if offset + 32 > len(image) or image[offset] != APP_IMAGE_MAGIC:
        return None
    description_offset = offset + 24 + 8
    description = image[description_offset : description_offset + 256]
    if len(description) < 176 or struct.unpack_from("<I", description)[0] != APP_DESCRIPTION_MAGIC:
        return None
    partition = image[offset : min(offset + size, len(image))]
    return {
        "version": c_string(description[16:48]),
        "project_name": c_string(description[48:80]),
        "compile_time": c_string(description[80:96]),
        "compile_date": c_string(description[96:112]),
        "idf_version": c_string(description[112:144]),
        "elf_sha256": description[144:176].hex(),
        "partition_sha256": hashlib.sha256(partition).hexdigest(),
    }


def inspect_backup(path: Path) -> dict[str, object]:
    image = path.read_bytes()
    partitions: list[dict[str, object]] = []
    for index in range(96):
        start = PARTITION_TABLE_OFFSET + index * PARTITION_ENTRY_SIZE
        entry = image[start : start + PARTITION_ENTRY_SIZE]
        if len(entry) < PARTITION_ENTRY_SIZE:
            break
        magic = struct.unpack_from("<H", entry)[0]
        if magic != PARTITION_MAGIC:
            break
        _, partition_type, subtype, offset, size, label, flags = struct.unpack("<HBBLL16sL", entry)
        partition: dict[str, object] = {
            "label": c_string(label),
            "type": partition_type,
            "subtype": subtype,
            "offset": f"0x{offset:x}",
            "size": size,
            "flags": flags,
        }
        if partition_type == 0:
            app = inspect_app(image, offset, size)
            if app is not None:
                partition["app"] = app
        partitions.append(partition)
    return {
        "backup_size": len(image),
        "backup_sha256": hashlib.sha256(image).hexdigest(),
        "partitions": partitions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_backup(args.backup), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
