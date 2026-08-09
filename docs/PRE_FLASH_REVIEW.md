# Symbios Terminal pre-flash review and flash record

The first reviewed image was **explicitly approved and flashed on 2026-08-09**.
Live activation exposed a serial-number-less board compatibility defect. A
corrected replacement image has passed CI and is **awaiting review; it has not
been flashed**.

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

## Activation finding and corrected replacement

The device joined the provisioned 2.4 GHz network and displayed activation
code `638327`. The code was approved successfully, but Cloud Run request logs
then showed 28 `POST /xiaozhi/ota/activate` responses with HTTP 400 and no
device-token exchange. Source inspection confirmed the device has no factory
serial number in eFuse and the inherited activation helper therefore sent `{}`
instead of the gateway challenge.

Commit `73f7d03` fixes only the `CONFIG_SYMBIOS_VOICE_GATEWAY` path: it sends
the random enrollment challenge even when the optional factory serial/HMAC
material is absent. The stock activation implementation is unchanged, and the
gateway still rejects a missing or mismatched challenge.

GitHub Actions run `31325001210` passed the gateway tests and full ESP-IDF 5.5.2
builds for both `lafvin-aichatbot` and
`lafvin-aichatbot-symbios-terminal`. Its generic CI artifact was:

- archive: `firmware-review/73f7d03/v2.2.4_lafvin-aichatbot-symbios-terminal.zip`
  (SHA-256 `f73ff91407dfbecb2bda4287b133e9247747c3ce928d09580aa5a68adadbf504`);
- merged image: `firmware-review/73f7d03/image/merged-binary.bin`, 16,384,750
  bytes (SHA-256
  `60b1da1b70dd41721224cf5cdb41a3bf982a22e53b291c5ccb13293e7447c950`).

The user explicitly approved that hash, and it was written and verified. On
the next boot, UART showed that the generic CI artifact contained the tracked
`https://symbios-gateway.invalid/xiaozhi/ota/` safety endpoint. Wi-Fi and the
board were healthy, but DNS correctly rejected that non-existent host. The
displayed `32769` was the ESP network error code, not an activation code. Using
the generic artifact instead of the endpoint-injected build was a build-selection
error; no unintended cloud endpoint was contacted.

Cloud Build `adfa9f6b-35e9-4a59-bc32-a6432667dc60` then rebuilt the same source
with the reviewed production bootstrap URL injected. The builder-generated and
locally calculated checksums match, and binary inspection finds the Symbios SKU
and `https://symbios-voice-gateway-hiz3vgfrfa-uc.a.run.app/xiaozhi/ota/` while
finding no `.invalid` endpoint. The production replacement staged for review is:

- archive:
  `firmware-review/adfa9f6b-35e9-4a59-bc32-a6432667dc60/v2.2.4_lafvin-aichatbot-symbios-terminal.zip`
  (SHA-256 `b90f8fc9a711173954ccc66d2ae47ce99772a243d68d1214c6f0d21ece781915`);
- merged image:
  `firmware-review/adfa9f6b-35e9-4a59-bc32-a6432667dc60/merged-binary.bin`,
  16,384,750 bytes (SHA-256
  `9acfdb147838e8d48c5d79874455720582ade950fe6356d8f70326d1a9b97466`).

The board currently contains the generic safety image with SHA-256
`60b1da1b70dd41721224cf5cdb41a3bf982a22e53b291c5ccb13293e7447c950`.
The endpoint-injected production image has not been flashed and requires a new
explicit hash approval.

During activation handling, the gateway admin credential was rotated after a
local client diagnostic exposed its old value. Cloud Run revision
`symbios-voice-gateway-00006-8d9` serves 100% of traffic with secret version 2;
version 1 is disabled. Device and provider credentials were not exposed.

The tracked `.invalid` endpoint remains a deliberate safety catch. Production
builds generate an ignored local config from an explicitly supplied HTTPS URL;
this prevents a normal source checkout from accidentally contacting a service.
