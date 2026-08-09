# Symbios Terminal

LAFVIN ESP32-S3 voice-terminal firmware and authenticated Symbios voice
gateway, now in post-flash provisioning and hardware validation.

- Firmware base: LAFVIN's Xiaozhi `src` branch (project version 2.2.4), with
  `78/xiaozhi-esp32` retained as the upstream reference remote.
- Hardware target: LAFVIN AIChatBot ESP32-S3, ES8311/ES7210 audio, 2-inch
  ST7789 display.
- Security boundary: the device holds only a device-scoped enrollment token;
  provider/API keys stay in the gateway environment.
- Hardware history: the connected board has been identified and its
  original 16 MB `RGB Demo` image has been backed up privately. After explicit
  approval, the unmodified LAFVIN Xiaozhi 2.2.4 baseline was flashed and passed
  esptool write verification; its boot log initializes the LAFVIN display and
  audio codecs and enters Wi-Fi provisioning. Physical LCD, captive-portal, and
  speaker tests pass; microphone and wake-word tests remain pending to avoid
  sending audio to the vendor cloud.
- Gateway state: Cloud Run revision `symbios-voice-gateway-00005-tk4` is live at
  `https://symbios-voice-gateway-hiz3vgfrfa-uc.a.run.app`. Production enrollment,
  device-token exchange, short-lived JWT authentication, WebSocket setup, and
  the service-account-authenticated Vertex Live handshake have passed. Gateway
  secrets are held in Secret Manager; no provider key is compiled into firmware.
- Device state: after the remaining physical test deferral was reported, the
  user explicitly approved the reviewed Symbios image on 2026-08-09. Esptool
  erased the stock layout, wrote and hash-verified the merged image, and reset
  normally. The first boot identifies SKU
  `lafvin-aichatbot-symbios-terminal`, initializes the local display and audio
  hardware, and enters the `Xiaozhi-D215` Wi-Fi provisioning portal. The merged
  image SHA-256 is
  `a6087b9add751a13c52e88ecc9ef8d49c3bf51a1da8d894c0e7d8e7f030479d5`.
  Wi-Fi enrollment, Symbios activation, microphone, and local wake-word tests
  remain to be completed against the Symbios gateway.

Start with [the hardware validation report](docs/HARDWARE_VALIDATION.md), then
use [the pre-flash review checklist](docs/PRE_FLASH_REVIEW.md).
