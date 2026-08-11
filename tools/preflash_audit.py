#!/usr/bin/env python3
"""Fail-closed review gate for Symbios Terminal firmware."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "xiaozhi-esp32-main"
PROTECTED_PREFIXES = (
    "xiaozhi-esp32-main/main/audio/",
    "xiaozhi-esp32-main/main/display/",
)
PROTECTED_FILES = {
    "xiaozhi-esp32-main/main/boards/lafvin-aichatbot/lafvin-aichatbot.cc",
    "xiaozhi-esp32-main/main/boards/lafvin-aichatbot/config.h",
}
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"(?i)(api[_-]?key|secret[_-]?key)\s*[:=]\s*['\"][^'\"]{12,}['\"]"),
)


def git_changed_files() -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", "vendor/src"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


def git_audited_files() -> list[Path]:
    """Return tracked and non-ignored untracked source paths.

    Generated build output is intentionally excluded: calling it a possible
    *committed* secret is both noisy and inaccurate. Untracked review source is
    retained so the gate still catches a secret before its first commit.
    """
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode() for item in completed.stdout.split(b"\0") if item]


def main() -> int:
    failures: list[str] = []
    changed = git_changed_files()
    protected_changes = [
        path
        for path in changed
        if path in PROTECTED_FILES or path.startswith(PROTECTED_PREFIXES)
    ]
    if protected_changes:
        failures.append("protected local hardware/audio/display paths changed: " + ", ".join(protected_changes))

    local_config = FIRMWARE / "main" / "boards" / "lafvin-aichatbot" / "config.symbios.local.json"
    if not local_config.exists():
        failures.append("reviewed local gateway config has not been generated")
    elif ".invalid" in local_config.read_text():
        failures.append("local gateway config still contains a .invalid placeholder")

    validation = ROOT / "hardware-validation.json"
    if not validation.exists():
        failures.append("hardware-validation.json is missing")
    else:
        try:
            report = json.loads(validation.read_text())
        except (OSError, json.JSONDecodeError):
            failures.append("hardware-validation.json is unreadable or invalid")
        else:
            if report.get("status") != "identified-and-backed-up":
                failures.append("factory firmware has not been identified and backed up")
            else:
                backup = Path(str(report.get("backup_path", "")))
                if not backup.is_file():
                    failures.append("factory backup referenced by hardware-validation.json is missing")
                elif backup.stat().st_size != 16 * 1024 * 1024:
                    failures.append("factory backup is not exactly 16 MiB")
                elif hashlib.sha256(backup.read_bytes()).hexdigest() != report.get("backup_sha256"):
                    failures.append("factory backup SHA-256 does not match hardware-validation.json")

    if not (ROOT / "factory-smoke-test.ok").exists():
        failures.append("factory display/wake/audio smoke test has not been acknowledged")

    for path in git_audited_files():
        if (
            not path.is_file()
            or ".git" in path.parts
            or any(part.startswith(".venv") for part in path.parts)
        ):
            continue
        if path.suffix.lower() in {".bin", ".zip", ".png", ".jpg", ".jpeg", ".gif"}:
            continue
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                failures.append(f"possible source secret in {path.relative_to(ROOT)}")
                break

    if failures:
        print("PRE-FLASH AUDIT: BLOCKED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("PRE-FLASH AUDIT: PASS")
    print("Protected wake-word/audio/display paths are unchanged and all physical gates are satisfied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
