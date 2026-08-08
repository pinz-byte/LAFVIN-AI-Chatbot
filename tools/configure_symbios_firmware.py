#!/usr/bin/env python3
"""Generate a local Xiaozhi build variant with a reviewed Symbios URL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
BOARD_DIR = ROOT / "xiaozhi-esp32-main" / "main" / "boards" / "lafvin-aichatbot"
OUTPUT = BOARD_DIR / "config.symbios.local.json"


def validate_gateway_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise argparse.ArgumentTypeError("gateway URL must use HTTPS")
    if parsed.hostname is None or parsed.hostname.endswith(".invalid"):
        raise argparse.ArgumentTypeError("replace the .invalid review placeholder with a deployed gateway")
    if not parsed.path.endswith("/xiaozhi/ota/"):
        raise argparse.ArgumentTypeError("gateway URL path must end with /xiaozhi/ota/")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise argparse.ArgumentTypeError("gateway URL cannot contain credentials, query, or fragment")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-url", required=True, type=validate_gateway_url)
    args = parser.parse_args()

    config = {
        "target": "esp32s3",
        "builds": [
            {
                "name": "lafvin-aichatbot-symbios-terminal",
                "sdkconfig_append": [
                    "CONFIG_USE_DEVICE_AEC=y",
                    "CONFIG_LANGUAGE_EN_US=y",
                    "CONFIG_SYMBIOS_VOICE_GATEWAY=y",
                    f'CONFIG_SYMBIOS_GATEWAY_URL="{args.gateway_url}"',
                ],
            }
        ],
    }
    OUTPUT.write_text(json.dumps(config, indent=4) + "\n")
    print(OUTPUT)
    print(
        "Build only (do not flash): cd xiaozhi-esp32-main && "
        "python3 scripts/release.py lafvin-aichatbot "
        "-c config.symbios.local.json --name lafvin-aichatbot-symbios-terminal"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
