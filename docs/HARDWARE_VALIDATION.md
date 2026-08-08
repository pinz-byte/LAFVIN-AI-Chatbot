# LAFVIN hardware and factory-firmware validation

Status on 2026-08-08: **blocked at physical enumeration; no write was
attempted**.

The Mac USB device tree and `/dev/cu.*` inventory showed no CP210x, ESP32 USB
JTAG/serial, `usbserial`, or `usbmodem` device. Only built-in Bluetooth/debug
ports were present. This means the board was disconnected, unpowered, attached
through a charge-only cable, or attached through an unenumerated hub. The
factory firmware cannot yet be claimed as physically validated.

## Expected hardware identity

The vendor documentation and LAFVIN source agree on the following target:

- ESP32-S3 dual-core controller, 16 MB flash, 8 MB PSRAM, 2.4 GHz Wi-Fi.
- LAFVIN audio codec module using ES8311 output and ES7210 input.
- I2S: MCLK GPIO38, WS GPIO13, BCLK GPIO14, codec-to-MCU GPIO12,
  MCU-to-codec GPIO45, PA enable GPIO48.
- Codec I2C: SDA GPIO1 and SCL GPIO2.
- 2-inch 320x240 ST7789 SPI display: DC GPIO39, CS GPIO47, clock GPIO41,
  MOSI GPIO40, backlight GPIO42.
- BOOT/wake button on GPIO0.

These are static source/document checks, not a substitute for a powered-board
test.

## Read-only identification

Use a known USB data cable, connect the ESP32-S3 USB/UART port directly, then:

```sh
python3 -m venv .venv-hardware
.venv-hardware/bin/pip install -r tools/hardware-requirements.txt
.venv-hardware/bin/python tools/validate_lafvin_factory.py
```

The tool exposes only identification and `read-flash`. It has no erase or write
command. Before any custom flash, preserve the full 16 MB factory image:

```sh
.venv-hardware/bin/python tools/validate_lafvin_factory.py \
  --backup-dir factory-backups
```

Keep the generated SHA-256 and backup private: an unencrypted flash dump may
contain Wi-Fi credentials and factory service tokens.

## Factory smoke test required before custom firmware

With the untouched factory image:

1. Confirm the display initializes with correct orientation, colors, and
   backlight.
2. Confirm 2.4 GHz Wi-Fi provisioning and normal factory-cloud connection.
3. Confirm GPIO0 wakes/starts a conversation.
4. Confirm local wake words (documented by LAFVIN as “Hi, ESP” or “Sophia”).
5. Speak at normal distance and verify microphone capture/transcription.
6. Verify clean speaker playback and interruption/AEC behavior.
7. Verify status, transcript, and expression updates on the display.
8. Run the read-only identification/backup command and retain its report.

Any failure here is a hardware/factory baseline problem and should be resolved
before evaluating Symbios firmware.
