# Symbios Terminal

Review-stage LAFVIN ESP32-S3 voice-terminal firmware and authenticated Symbios
voice gateway.

- Firmware base: LAFVIN's Xiaozhi `src` branch (project version 2.2.4), with
  `78/xiaozhi-esp32` retained as the upstream reference remote.
- Hardware target: LAFVIN AIChatBot ESP32-S3, ES8311/ES7210 audio, 2-inch
  ST7789 display.
- Security boundary: the device holds only a device-scoped enrollment token;
  provider/API keys stay in the gateway environment.
- Current safety state: no custom firmware has been flashed, the real gateway
  URL is unset, and physical factory validation remains pending until the board
  enumerates over USB.

Start with [the hardware validation report](docs/HARDWARE_VALIDATION.md), then
use [the pre-flash review checklist](docs/PRE_FLASH_REVIEW.md).
