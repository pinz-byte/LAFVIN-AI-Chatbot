# Symbios Terminal pre-flash review and flash record

The reviewed image was **explicitly approved and flashed on 2026-08-09**.

## What changed

- Added a separate `lafvin-aichatbot-symbios-terminal` build variant.
- Locked that variant's bootstrap destination to a reviewed HTTPS Symbios URL;
  it ignores factory `ota_url` values left in NVS.
- Added activation-code enrollment, a device-scoped NVS token, and short-lived
  WebSocket bearer credentials.
- Forced authenticated WSS and disabled fallback to Xiaozhi MQTT for the
  Symbios variant.
- Added a server-side gateway that validates the device JWT and injects any
  upstream provider credential from server environment only.

## What was deliberately preserved

No changes were made to:

- `main/boards/lafvin-aichatbot/lafvin-aichatbot.cc` or its pin map
  `config.h`;
- `main/audio/`, including local wake-word detection, codec, AEC, Opus, and
  resampling paths;
- `main/display/`, including ST7789/LVGL rendering and expressions.

The transport handoff remains the existing Xiaozhi WebSocket protocol so STT,
TTS, LLM emotion, MCP, and binary Opus frames continue through the original
application callbacks.

## Gates that must pass before flashing

1. Connect the board with a data cable and finish
   [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md), including the private
   original-image backup and physical smoke test on the explicitly approved
   stock LAFVIN baseline.
2. Deploy the gateway behind HTTPS/WSS and configure its server secrets.
   **PASS:** Cloud Run revision `symbios-voice-gateway-00005-tk4` is serving the
   authenticated Vertex Live bridge. Firestore persists enrollments, Secret
   Manager holds the JWT/admin secrets, and Vertex uses the Cloud Run service
   account rather than an API key.
3. Generate a local firmware config with the reviewed public endpoint:

   ```sh
   python3 tools/configure_symbios_firmware.py \
     --gateway-url \
       https://symbios-voice-gateway-hiz3vgfrfa-uc.a.run.app/xiaozhi/ota/
   ```

   **PASS:** the generated local config contains this endpoint and no
   credential.
4. Build the Symbios variant and review the compiler/partition output.
   **PASS:** Cloud Build `26efb7c3-2102-47ef-9c3d-7f2547c29fcc` used ESP-IDF
   5.5.2, compiled the local wake-word/audio/display paths, left 32% of the app
   partition free, and produced a merged image with SHA-256
   `a6087b9add751a13c52e88ecc9ef8d49c3bf51a1da8d894c0e7d8e7f030479d5`.
5. Run `python3 tools/preflash_audit.py`; it must report `PASS`.
   **DEFERRED AT APPROVAL:** the audit reported only the missing physical
   microphone/local-wake acknowledgement. The user then explicitly approved
   flashing; the stock vendor-cloud audio test remained deferred to avoid
   disclosing voice data to that service. These checks now move to the
   Symbios-backed post-flash validation.
6. Review the produced binary hash and flash command manually.
   **PASS:** the reviewed SHA-256 matched immediately before flashing. Esptool
   identified the ESP32-S3 with 8 MB PSRAM and 16 MB flash, erased the stock
   layout, wrote 16,384,752 bytes at `0x0` using DIO/80 MHz/16 MB settings,
   verified the written-data hash, and hard-reset normally.

## First post-flash boot

UART confirms project `xiaozhi` 2.2.4, ESP-IDF 5.5.2, SKU
`lafvin-aichatbot-symbios-terminal`, 8 MB PSRAM, LVGL display startup,
backlight at 75%, ES8311 speaker and ES7210 microphone initialization, and the
`Xiaozhi-D215` provisioning portal at `192.168.4.1`. No crash, panic, or digest
failure was observed. Physical microphone, local wake word, and a complete
Symbios voice exchange remain pending until Wi-Fi provisioning and activation.

The tracked `.invalid` endpoint remains a deliberate safety catch. Production
builds generate an ignored local config from an explicitly supplied HTTPS URL;
this prevents a normal source checkout from accidentally contacting a service.
