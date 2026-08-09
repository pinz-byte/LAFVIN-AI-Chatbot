# Symbios Terminal pre-flash review and flash record

The first reviewed image and its endpoint-injected correction were **explicitly
approved and flashed on 2026-08-09**. Activation now succeeds and survives a
reboot. Local microphone/wake behavior remains unresolved. A narrowly scoped
diagnostic image passed CI, received explicit hash approval, and was flashed to
the active application slot without erasing device state.

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

## What was deliberately preserved in the production image

Before the separate diagnostic described below, no changes were made to:

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

The user explicitly approved the endpoint-injected image by its SHA-256. It was
erased, written at 230400 baud, verified by esptool, and rebooted normally.
Activation code `286697` was approved through the gateway. Firestore recorded
the device-token exchange, and a later UART reboot showed `Activation done`
followed by the idle state without another activation loop. The board currently
contains this production image with SHA-256
`9acfdb147838e8d48c5d79874455720582ade950fe6356d8f70326d1a9b97466`.

During activation handling, the gateway admin credential was rotated after a
local client diagnostic exposed its old value. Cloud Run revision
`symbios-voice-gateway-00006-8d9` serves 100% of traffic with secret version 2;
version 1 is disabled. Device and provider credentials were not exposed.

The tracked `.invalid` endpoint remains a deliberate safety catch. Production
builds generate an ignored local config from an explicitly supplied HTTPS URL;
this prevents a normal source checkout from accidentally contacting a service.

## Local microphone diagnostic flash and result

The idle face, display, speaker, Wi-Fi, authenticated activation, and token
persistence are healthy. UART confirms the local AFE starts with one microphone
plus one playback/reference channel and loads `wn9_nihaoxiaozhi_tts` (Mandarin
`你好小智`), not the older documented English `Hi ESP` model. Neither repeated
live speech nor controlled macOS Mandarin TTS produced a WakeNet event. The
small BOOT button also produced no listening-state change.

Commit `cec5828` adds a build-gated diagnostic that is disabled by default:

- once per second, it logs only per-channel mean absolute amplitude and peak;
  it never logs or persists raw audio;
- it maps the vendor-documented DOWN button on GPIO19 to the existing
  `ToggleChatState()` behavior;
- it does not change the endpoint, enrollment, display, speaker, codec pin map,
  provider credentials, or gateway authentication.

GitHub Actions run `31328494140` passed gateway tests and ESP-IDF 5.5.2 builds
for the stock LAFVIN variant, the normal Symbios variant, and the
endpoint-injected diagnostic variant. Builder, local, and archive checksums all
match. Binary inspection finds exactly one reviewed gateway URL, both diagnostic
markers, no `.invalid` URL, and no common OpenAI/Google API-key signatures.

- archive:
  `firmware-review/cec5828-diagnostic/releases/v2.2.4_lafvin-aichatbot-symbios-terminal.zip`
  (SHA-256 `d42a6f9c3c152cf98fdc23c1b097f16f74c5fee82b1ffa3d763261e4616322fd`);
- merged image:
  `firmware-review/cec5828-diagnostic/build/merged-binary.bin`, 16,384,750 bytes
  (SHA-256
  `961732b84bb67764a3bc9aa7b5c9287953718aba21f9f20519b042e9315e9a60`).

`tools/preflash_audit.py` remains fail-closed: it reports the two deliberate
protected-path changes (`audio_service.cc` and the LAFVIN board source) and the
still-missing factory wake/audio smoke acknowledgement. Therefore the
diagnostic image requires explicit hash approval as a documented exception.

The user explicitly approved merged-image SHA-256
`961732b84bb67764a3bc9aa7b5c9287953718aba21f9f20519b042e9315e9a60`.
Before writing, the live and reviewed partition tables were compared and found
byte-for-byte identical. OTA metadata reported sequence 1/state VALID, making
`ota_0` at `0x20000` the active slot. The current NVS/OTA/PHY region was saved
to a private ignored backup with mode `0600` and SHA-256
`1e8a4c3ba63becb40509772b6f56b764b27bb8b637cc29aa9ce207824da76a75`.

Only the 2,821,808-byte `xiaozhi.bin` extracted from the approved merged image
was written at `0x20000`; its SHA-256 is
`10c5af65bac100d34ffdde758959c45a94ebafb3dc7b67e20eaf63c60855d5af`.
No full erase, NVS write, partition-table write, bootloader write, or asset write
was performed. Esptool verified the data hash and hard-reset normally. UART
then confirmed the diagnostic compile timestamp, `ota_0`, preserved Wi-Fi,
`Activation done`, idle state, and the expected Symbios endpoint.

The physical DOWN button produced the diagnostic marker, opened authenticated
WSS sessions, and changed the state from idle through connecting to listening.
Further presses stopped and restarted listening. This validates the GPIO19
mapping, device token, gateway discovery, WebSocket authentication, and manual
listening path.

The input result is local and abnormal: channel 0 has idle peaks generally in
the 20–80 range and reacts to nearby speech only into roughly the 300–600 range;
channel 1 remains zero while playback is idle. No WakeNet event occurred. The
mean-absolute log field rendered incorrectly as `lu`, so only the correctly
rendered peak values were used. The microphone/I2S path is not completely dead,
but the selected ES7210 channel is severely attenuated or the TDM slot/gain
mapping is wrong. The wake failure occurs before the Symbios gateway.

## Manual turn submission correction staged for review

Live testing exposed two independent end-of-turn defects. In the diagnostic
firmware, a second DOWN press called `ToggleChatState()`, whose listening-state
branch closes the WebSocket audio channel and returns to standby. It therefore
never submitted the captured turn. At the gateway, a Xiaozhi `listen.stop`
message stopped local forwarding but did not send Vertex Live an explicit
audio-stream-end event, so buffered audio could remain unprocessed when
automatic voice activity detection did not end the turn itself.

Commit `cf1f86c` makes the diagnostic DOWN callback state-aware: idle starts
manual listening, listening calls `StopListening()` to submit the turn without
closing the authenticated session, and speaking retains the existing abort
behavior. It also corrects the diagnostic mean-level integer formatting. The
gateway now converts the matching `listen.stop` event into
`realtime_input.audio_stream_end` for Vertex Live. Provider credentials remain
server-side; no device credential or API key was added to the firmware.

Gateway tests passed locally (`11 passed, 1 skipped`) and in GitHub Actions.
Cloud Run revision `symbios-voice-gateway-00007-tg8` is healthy and serves 100%
of traffic using the unchanged service account, secrets, and public URL.

GitHub Actions run `31329470115` passed all four jobs: gateway tests, stock
LAFVIN ESP-IDF build, normal Symbios ESP-IDF build, and the endpoint-injected
diagnostic review build. Builder, local, and archive merged-image checksums
match. Binary inspection finds the reviewed gateway URL exactly once, no
`.invalid` URL, the manual-start/manual-submit/abort and corrected input-level
markers, and no common API-key/token signatures.

- archive:
  `firmware-review/cf1f86c-manual-submit/releases/v2.2.4_lafvin-aichatbot-symbios-terminal.zip`
  (SHA-256 `a20858dcd239c52749cbde673c8b1640e303dd1d126226bffb4ef289a33d451c`);
- merged image:
  `firmware-review/cf1f86c-manual-submit/build/merged-binary.bin`, 16,384,750
  bytes (SHA-256
  `29e7bf6bffd717d068285e589610ed788431537bad6a0162c9aa59d3454a9c50`).

`tools/preflash_audit.py` remains fail-closed for the same documented reasons:
the diagnostic deliberately changes `audio_service.cc` and the LAFVIN board
source, and the factory wake/audio smoke acknowledgement is absent.

The user explicitly approved merged-image SHA-256
`29e7bf6bffd717d068285e589610ed788431537bad6a0162c9aa59d3454a9c50`.
Immediately before writing, the hash was rechecked, the live and reviewed
partition tables matched byte-for-byte, and OTA metadata again reported
sequence 1/state VALID with `ota_0` active at `0x20000`. The existing private
NVS/OTA/PHY backup remained present with mode `0600` and its documented
SHA-256.

Only the 2,822,032-byte application image was extracted from the approved
merged binary and written at `0x20000`. Its SHA-256 is
`7ae4d13ab7879fb81ca76ee44c5bfe9ea6d1ac637c714914fcb7054f9247adeb`;
esptool reported valid image checksum and validation hash, then verified the
written-data hash and hard-reset normally. No full erase or write to NVS,
OTA metadata, PHY data, bootloader, partition table, or assets was performed.

Post-flash UART confirms compile time `Aug 9 2026 18:38:40`, ESP-IDF 5.5.2,
the Symbios SKU, `ota_0`, retained Wi-Fi, the reviewed HTTPS endpoint,
`Activation done`, the idle face, local WakeNet/AFE startup, and correctly
formatted numeric input-level diagnostics. A physical DOWN/speak/DOWN exchange
remains the final live acceptance test; opening a new serial-monitor window
resets this board, so that test is deferred to uninterrupted user operation.
