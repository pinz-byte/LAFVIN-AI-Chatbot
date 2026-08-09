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
  audio codecs and enters Wi-Fi provisioning. Physical LCD, captive-portal, and
  speaker tests pass; microphone and wake-word tests remain pending to avoid
  sending audio to the vendor cloud. No Symbios firmware has been flashed.
- Gateway state: Cloud Run revision `symbios-voice-gateway-00005-tk4` is live at
  `https://symbios-voice-gateway-hiz3vgfrfa-uc.a.run.app`. Production enrollment,
  device-token exchange, short-lived JWT authentication, WebSocket setup, and
  the service-account-authenticated Vertex Live handshake have passed. Gateway
  secrets are held in Secret Manager; no provider key is compiled into firmware.
- Review build: ESP-IDF 5.5.2 compiled the production-endpoint variant without
  flashing it. The merged image SHA-256 is
  `a6087b9add751a13c52e88ecc9ef8d49c3bf51a1da8d894c0e7d8e7f030479d5`.
  The pre-flash gate remains blocked only on the unverified physical microphone
  and local wake-word smoke test.

Start with [the hardware validation report](docs/HARDWARE_VALIDATION.md), then
use [the pre-flash review checklist](docs/PRE_FLASH_REVIEW.md).
