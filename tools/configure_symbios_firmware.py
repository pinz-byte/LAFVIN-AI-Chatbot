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


def terminal_feed_url(gateway_url: str) -> str:
    parsed = urlparse(gateway_url)
    return f"{parsed.scheme}://{parsed.netloc}/api/v1/terminal/feed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-url", required=True, type=validate_gateway_url)
    diagnostic_mode = parser.add_mutually_exclusive_group()
    diagnostic_mode.add_argument(
        "--lafvin-audio-diagnostic",
        action="store_true",
        help="enable local input-level logs; Symbios builds retain the GPIO19 fallback",
    )
    diagnostic_mode.add_argument(
        "--lafvin-slot-audition",
        action="store_true",
        help="enable RAM-only ES7210 slot capture and local raw/normalized playback",
    )
    args = parser.parse_args()

    sdkconfig_append = [
        "CONFIG_LAFVIN_MONO_MIC_INPUT=y",
        "CONFIG_LANGUAGE_EN_US=y",
        "CONFIG_SR_WN_WN9_NIHAOXIAOZHI_TTS=n",
        "CONFIG_SR_WN_WN9_HIESP=y",
        "CONFIG_SYMBIOS_VOICE_GATEWAY=y",
        "CONFIG_SYMBIOS_AUTO_SUBMIT_ON_SILENCE=y",
        "CONFIG_SYMBIOS_TERMINAL_TICKER=y",
        f'CONFIG_SYMBIOS_TERMINAL_FEED_URL="{terminal_feed_url(args.gateway_url)}"',
        f'CONFIG_SYMBIOS_GATEWAY_URL="{args.gateway_url}"',
    ]
    if args.lafvin_audio_diagnostic:
        sdkconfig_append.append("CONFIG_LAFVIN_AUDIO_DIAGNOSTIC=y")
    if args.lafvin_slot_audition:
        sdkconfig_append.append("CONFIG_LAFVIN_SLOT_AUDITION=y")

    config = {
        "target": "esp32s3",
        "builds": [
            {
                "name": "lafvin-aichatbot-symbios-terminal",
                "sdkconfig_append": sdkconfig_append,
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
