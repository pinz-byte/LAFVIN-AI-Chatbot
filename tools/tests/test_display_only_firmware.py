from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIGURE = ROOT / "tools" / "configure_symbios_firmware.py"
FIRMWARE = ROOT / "xiaozhi-esp32-main" / "main"
GATEWAY = "https://symbios-voice-gateway-hiz3vgfrfa-uc.a.run.app/xiaozhi/ota/"


def _generate(tmp_path: Path) -> tuple[dict, list[str]]:
    output = tmp_path / "display.json"
    subprocess.run(
        [
            sys.executable,
            str(CONFIGURE),
            "--gateway-url",
            GATEWAY,
            "--display-only",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    config = json.loads(output.read_text())
    append = config["builds"][0]["sdkconfig_append"]
    return config, append


def test_display_only_configuration_is_explicit_and_consistent(tmp_path: Path) -> None:
    config, append = _generate(tmp_path)

    assert config["target"] == "esp32s3"
    assert config["builds"][0]["name"] == "lafvin-aichatbot-symbios-display-v1"
    assert len(append) == len(set(append))

    required = {
        "CONFIG_SYMBIOS_DISPLAY_ONLY=y",
        "CONFIG_SYMBIOS_VOICE_GATEWAY=y",
        "CONFIG_SYMBIOS_TERMINAL_TICKER=y",
        'CONFIG_SYMBIOS_TIMEZONE="PET5"',
        "CONFIG_LAFVIN_MONO_MIC_INPUT=n",
        "CONFIG_LAFVIN_AUDIO_DIAGNOSTIC=n",
        "CONFIG_LAFVIN_SLOT_AUDITION=n",
        "CONFIG_SYMBIOS_AUTO_SUBMIT_ON_SILENCE=n",
        "CONFIG_SYMBIOS_PREWARM_AUDIO_CHANNEL=n",
        "CONFIG_USE_DEVICE_AEC=n",
        "CONFIG_USE_SERVER_AEC=n",
        "CONFIG_USE_AUDIO_PROCESSOR=n",
        "CONFIG_WAKE_WORD_DISABLED=y",
        "CONFIG_USE_AFE_WAKE_WORD=n",
        "CONFIG_USE_CUSTOM_WAKE_WORD=n",
        "CONFIG_SEND_WAKE_WORD_DATA=n",
        "CONFIG_SR_WN_WN9_HIESP=n",
        "CONFIG_SR_MN_EN_NONE=y",
        "CONFIG_FLASH_NONE_ASSETS=y",
    }
    assert required <= set(append)


def test_generated_configuration_contains_public_urls_not_credentials(tmp_path: Path) -> None:
    _, append = _generate(tmp_path)
    rendered = "\n".join(append)

    assert GATEWAY in rendered
    assert "https://symbios-voice-gateway-hiz3vgfrfa-uc.a.run.app/api/v1/terminal/feed" in rendered
    assert "sk-" not in rendered
    assert "api_key" not in rendered.lower()
    assert "secret" not in rendered.lower()


def test_gateway_url_with_embedded_credentials_is_rejected(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(CONFIGURE),
            "--gateway-url",
            "https://user:password@example.com/xiaozhi/ota/",
            "--display-only",
            "--output",
            str(tmp_path / "rejected.json"),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert not (tmp_path / "rejected.json").exists()


def test_display_only_source_never_initializes_voice_or_speaker() -> None:
    application = (FIRMWARE / "application.cc").read_text()
    board = (
        FIRMWARE / "boards" / "lafvin-aichatbot" / "lafvin-aichatbot.cc"
    ).read_text()

    assert "#if !CONFIG_SYMBIOS_DISPLAY_ONLY\n    auto codec = board.GetAudioCodec();" in application
    assert "Display-only mode: voice protocol disabled" in application
    assert "Automatic and remote firmware upgrades are disabled" in application
    assert "Display-only mode: codec I2C bus disabled" in board
    assert "gpio_set_level(pa_en_pin_, 0);" in board
    assert "Audio codec requested by display-only firmware" in board
    assert "return nullptr;" in board


def test_display_only_bootstrap_discards_voice_and_update_destinations() -> None:
    ota = (FIRMWARE / "ota.cc").read_text()

    assert "Ignoring WebSocket configuration in display-only mode" in ota
    assert "Ignoring firmware update metadata in display-only mode" in ota
    assert "has_websocket_config_ = false;" in ota
    assert "has_new_version_ = false;" in ota


def test_terminal_feed_is_bounded_fail_soft_and_overlap_safe() -> None:
    feed = (FIRMWARE / "terminal_feed.cc").read_text()
    display = (FIRMWARE / "display" / "lcd_display.cc").read_text()

    assert "constexpr size_t kMaxPayloadBytes = 8192;" in feed
    assert "constexpr size_t kMaxCards = 15;" in feed
    assert "constexpr int kMaxRetrySeconds = 15 * 60;" in feed
    assert "TerminalCard OfflineCard()" in feed
    assert "LoadCachedCard(cached)" in feed
    assert "CONFIG_SYMBIOS_TICKER_REFRESH_SECONDS, retry_seconds * 2" in feed
    assert "lv_label_set_long_mode(ticker_title_label_, LV_LABEL_LONG_DOT);" in display
    assert "lv_label_set_long_mode(ticker_primary_label_, LV_LABEL_LONG_DOT);" in display
    assert "ticker title and primary bands must not overlap" in display
    assert "ticker primary and readout bands must not overlap" in display
