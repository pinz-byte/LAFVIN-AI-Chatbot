# Symbios Terminal pre-flash review

This branch is intentionally **not approved for flashing** yet.

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
   **BLOCKED:** its only current failure is the missing acknowledgement for the
   physical microphone and local wake-word smoke test.
6. Review the produced binary hash and flash command manually.
   **WAITING FOR REVIEW:** the binary exists locally under `firmware-review/`,
   but no custom flash command has been run.

The tracked `.invalid` endpoint remains a deliberate safety catch. Production
builds generate an ignored local config from an explicitly supplied HTTPS URL;
this prevents a normal source checkout from accidentally contacting a service.
