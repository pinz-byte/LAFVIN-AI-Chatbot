# Symbios Terminal

Review-stage LAFVIN ESP32-S3 voice-terminal firmware and authenticated Symbios
voice gateway.

- Firmware base: LAFVIN's Xiaozhi `src` branch (project version 2.2.4), with
  `78/xiaozhi-esp32` retained as the upstream reference remote.
- Hardware target: LAFVIN AIChatBot ESP32-S3, ES8311/ES7210 audio, 2-inch
  ST7789 display.
- Security boundary: the device holds only a device-scoped enrollment token;
  provider/API keys stay in the gateway environment.
- Current safety state: no custom firmware has been flashed. The connected
  board has been identified and its 16 MB factory image has been backed up
  privately. Its installed application identifies itself over UART as `RGB
  Demo`; it cycles the onboard LED without driving the LCD and reports an app
  SHA-256 mismatch at boot. The real gateway URL and a reviewed method for
  validating display/wake/audio are intentionally still unset, so the pre-flash
  gate remains blocked for review.

Start with [the hardware validation report](docs/HARDWARE_VALIDATION.md), then
use [the pre-flash review checklist](docs/PRE_FLASH_REVIEW.md).
