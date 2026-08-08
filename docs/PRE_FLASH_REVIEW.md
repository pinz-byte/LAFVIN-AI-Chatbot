# Symbios Terminal pre-flash review

This branch is intentionally **not flash-ready** yet.

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
3. Generate a local firmware config with the real public endpoint:

   ```sh
   python3 tools/configure_symbios_firmware.py \
     --gateway-url https://your-gateway.example/xiaozhi/ota/
   ```

4. Build the Symbios variant and review the compiler/partition output.
5. Run `python3 tools/preflash_audit.py`; it must report `PASS`.
6. Review the produced binary hash and flash command manually.

The tracked `.invalid` endpoint is a deliberate safety catch. It prevents this
review branch from accidentally contacting an unreviewed service.
