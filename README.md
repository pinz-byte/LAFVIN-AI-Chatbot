# Symbios Terminal

Review-stage LAFVIN ESP32-S3 voice-terminal firmware and authenticated Symbios
voice gateway.

- Firmware base: LAFVIN's Xiaozhi `src` branch (project version 2.2.4), with
  `78/xiaozhi-esp32` retained as the upstream reference remote.
- Hardware target: LAFVIN AIChatBot ESP32-S3, ES8311/ES7210 audio, 2-inch
  ST7789 display.
- Security boundary: the device holds only a device-scoped enrollment token;
  provider/API keys stay in the gateway environment.
- Current safety state: the connected board has been identified and its
  original 16 MB `RGB Demo` image has been backed up privately. After explicit
  approval, the unmodified LAFVIN Xiaozhi 2.2.4 baseline was flashed and passed
  esptool write verification; its boot log initializes the LAFVIN display and
  audio codecs and enters Wi-Fi provisioning. No Symbios firmware has been
  flashed. The real gateway URL and physical display/wake/audio confirmation
  remain unset, so the Symbios pre-flash gate is still blocked for review.

Start with [the hardware validation report](docs/HARDWARE_VALIDATION.md), then
use [the pre-flash review checklist](docs/PRE_FLASH_REVIEW.md).
