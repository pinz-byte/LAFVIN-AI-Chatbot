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

## Expired voice-session correction staged for review

The uninterrupted physical test showed that DOWN changed the display to
connecting and then immediately returned it to standby. Cloud Run recorded two
HTTP 403 WebSocket attempts at `2026-08-09T19:11:44Z` and
`2026-08-09T19:11:51Z`, before any audio reached Vertex Live. The firmware had
cached the five-minute WebSocket JWT issued during boot and reused it after the
device had been idle beyond its expiry. This was independent of the microphone
gain and manual-submit corrections.

Commit `ea73ca9` changes only the `CONFIG_SYMBIOS_VOICE_GATEWAY` path. Before
each new audio channel, the device now calls the authenticated HTTPS bootstrap
with its durable device-scoped NVS credential, requires a valid WSS response,
and then connects with the newly issued short-lived JWT. Refresh failure is
fail-closed and leaves the device disconnected. Stock Xiaozhi/LAFVIN transport
behavior is unchanged. No provider credential or API key is present in the
firmware; upstream authentication remains on the gateway service account.

Cloud Run revision `symbios-voice-gateway-00009-6b8` includes privacy-safe
authentication-rejection reasons and aggregate input/output audio metrics. It
does not log bearer tokens, raw audio, or transcript content. Local gateway
tests passed (`12 passed, 1 skipped`).

GitHub Actions run `31331108031` built commit
`ea73ca9ee555ae3fcb437a6aa39f43ccf1d84ad4` and passed all four jobs: gateway
tests, the stock LAFVIN build, the normal Symbios build, and the
endpoint-injected diagnostic review build. Builder, downloaded, and archive
merged-image checksums match. Binary inspection finds the reviewed gateway URL
exactly once, no `.invalid` endpoint, the manual-start/manual-submit/abort and
input-level markers, the new credential-refresh marker, and no common
API-key/token signatures.

- archive:
  `firmware-review/ea73ca9-session-refresh/releases/v2.2.4_lafvin-aichatbot-symbios-terminal.zip`,
  8,157,069 bytes (SHA-256
  `3b76b3a7d0bec8870b9b9ee618a7621d59ab2a80ec5817bd65352d9c531e827e`);
- merged image:
  `firmware-review/ea73ca9-session-refresh/build/merged-binary.bin`,
  16,384,750 bytes (SHA-256
  `bc0c96f262b2f4ce48e8045f596d9934a2e194b9a391116a55139e9ef484b630`);
- application image:
  `firmware-review/ea73ca9-session-refresh/build/xiaozhi.bin`, 2,822,528
  bytes (SHA-256
  `884c03924e84f913f58d3b936615269fc07db8e8064efb80b2d8911332ba7e32`).

Esptool validates the ESP32-S3 application checksum and appended digest. The
image targets DIO, 80 MHz, 16 MB flash, was built with ESP-IDF 5.5.2, and reports
compile time `Aug 9 2026 19:16:42`. Its partition table, OTA-data region, and
assets are byte-for-byte identical to the currently approved manual-submit
image. If separately approved, only the application image at `0x20000` is
eligible to be written, preserving NVS, Wi-Fi, activation, OTA metadata,
bootloader, partition table, and assets.

`tools/preflash_audit.py` remains fail-closed for the same documented
diagnostic exceptions: `audio_service.cc` and the LAFVIN board source differ
from the vendor baseline, and the factory wake/audio smoke acknowledgement is
absent. At this review stage, no flash had been performed for the candidate;
the board still ran the explicitly approved manual-submit image with SHA-256
`29e7bf6bffd717d068285e589610ed788431537bad6a0162c9aa59d3454a9c50`.

## Session-refresh application flash and boot result

The user explicitly approved merged-image SHA-256
`bc0c96f262b2f4ce48e8045f596d9934a2e194b9a391116a55139e9ef484b630`.
Immediately before writing, the downloaded merged image, the merged image
inside the release archive, and the extracted application image were rehashed.
All matched the reviewed values.

The live ESP32-S3 reported revision v0.2, 8 MB PSRAM, and the expected device
identity. Its partition table matched the reviewed partition table
byte-for-byte. The initial OTA CRC helper incorrectly checked 28 bytes; source
verification against ESP-IDF 5.5.2 showed that
`bootloader_common_ota_select_crc()` covers only the four-byte `ota_seq`, with
`UINT32_MAX` as the initial CRC. The corrected calculation matched stored CRC
`0x4743989a`, and OTA metadata reported sequence 1/state VALID with `ota_0`
active at `0x20000`.

Only the 2,822,528-byte approved `xiaozhi.bin` was written at `0x20000`. Its
SHA-256 is
`884c03924e84f913f58d3b936615269fc07db8e8064efb80b2d8911332ba7e32`.
Esptool erased only `0x20000` through `0x2d1fff`, wrote the image at 230400
baud, verified the flash data hash, and hard-reset normally. NVS, Wi-Fi,
activation, OTA metadata, PHY data, bootloader, partition table, and assets
were not written.

Post-flash UART confirms the reviewed compile time `Aug 9 2026 19:16:42`,
ESP-IDF 5.5.2, the Symbios SKU, `ota_0`, 8 MB PSRAM, display/backlight, ES8311
speaker and ES7210 microphone initialization, retained Wi-Fi, successful HTTPS
bootstrap, `Activation done`, the idle state, and WakeNet/AFE startup. No crash,
panic, digest failure, or new activation prompt occurred. A physical
DOWN/speak/DOWN exchange remains the final live acceptance test for the new
per-session credential refresh and end-to-end response.

## Manual activity-boundary gateway correction

The physical post-flash test confirmed that the per-session credential refresh
works. Cloud Run revision `symbios-voice-gateway-00009-6b8` accepted the fresh
WebSocket and recorded `listen.start`, 127 Opus frames decoded to 243,840 PCM
bytes, and `listen.stop`. Aggregate input levels were mean absolute amplitude
340 and peak 4,457. The second DOWN press therefore reached the gateway; the
device's immediate standby display is its expected local post-submit state.
Vertex returned no transcription, response audio, or turn-complete event.

The gateway had left Vertex automatic activity detection enabled and converted
the physical stop into `audio_stream_end`. A direct Vertex probe using
synthesized speech scaled to comparable levels (mean 360, peak 4,197) completed
successfully when automatic activity detection was disabled and the turn was
bounded by explicit `activity_start` and `activity_end` events. The deployed
gateway-only correction applies those deterministic push-to-talk boundaries.
It does not change or reflash firmware, retain raw audio, expose credentials,
or alter the reviewed gateway URL.

Commit `d0433c8` passed the project-environment gateway suite (`13 passed, 1
skipped`) and Python compilation. Cloud Run revision
`symbios-voice-gateway-00010-6vs` was then deployed and is serving 100% of
traffic. Both the reviewed device URL and Cloud Run's project-number URL return
healthy. The service account, nine environment entries, two Secret Manager
bindings, device firmware, and reviewed public endpoint are unchanged. A new
physical DOWN/speak/DOWN exchange is required for final live acceptance.

## Attenuated-input gateway correction

The next physical exchange reached the same deployed gateway end to end. The
device opened its authenticated WebSocket, sent `listen.start`, delivered 119
Opus frames (228,480 decoded PCM bytes), and sent `listen.stop` after 7.14
seconds. The raw decoded turn measured mean absolute amplitude 158 and peak
2,761. Vertex returned no transcription, response audio, or turn-complete
event. The WebSocket remained open after submission, proving that the device
returned to its local standby UI rather than shutting down.

Two subsequent UART-capture attempts opened the CP210x serial port and each
caused a fresh ESP32-S3 `POWERON` boot plus a new OTA bootstrap request. The
serial adapter resets this board when the port is opened even when DTR/RTS are
pre-cleared, so those operator-induced boots are not evidence of a spontaneous
post-turn crash. Further acceptance checks use gateway telemetry and avoid
opening the serial port.

Current upstream support for the matching Lichuang/SZPI ES7210 design confirms
that TDM slot 0 is physical MIC1 and slot 1 is the physical MIC3 playback
reference. It uses 28 dB for MIC1 and mutes MIC3; the LAFVIN firmware already
uses the same slots with 30 dB on MIC1. A firmware channel-map change is
therefore not justified by the evidence.

The staged gateway-only correction applies a bounded 4x gain to decoded PCM16
immediately before it is sent to Vertex. Raw aggregate metrics remain measured
before gain, and the scaler clips safely at PCM16 limits. It does not persist
audio, change authentication, expose a credential, modify the endpoint, or
alter/flash the device firmware. The gain is constrained to the range 1x-16x
and can be configured through the non-secret `VERTEX_INPUT_GAIN` environment
setting. Local gateway tests pass (`15 passed, 1 skipped`) and Python
compilation succeeds.

Commit `88c2fc2` was built successfully by regional Cloud Build job
`14d12225-916c-4550-93cd-95c5d2bbaf24`. The pushed image digest is
`sha256:1d65d6abc1b285185e1fbde56468f19a63c9c35a513c63abb0d7222b02a3351c`.
Cloud Run revision `symbios-voice-gateway-00014-sug` first served zero percent
of production traffic behind a temporary preflight tag; its health route
returned HTTP 200, its service account and both Secret Manager bindings
matched production, and `VERTEX_INPUT_GAIN=4.0` was the only new environment
entry. The temporary tag was then removed and the revision was promoted to 100
percent traffic. The public health route returns HTTP 200. The device firmware
was not changed or flashed. A physical DOWN/speak/DOWN turn remains the final
live acceptance check.

## RAM-only ES7210 slot-audition candidate

The 4x gateway input gain did not establish which ES7210 input slot contains
the strongest acoustic microphone signal. A default-off LAFVIN-only diagnostic
has therefore been prepared to isolate that hardware question before making
another cloud or wake-word change. UP selects a raw TDM slot; DOWN records three
seconds into PSRAM and plays the raw and bounded-normalized PCM through the
local speaker. The path bypasses AFE, AEC, resampling, Opus, and all network
transport, does not persist PCM, and restores the exact prior wake/voice state.

Regional Cloud Build job `ba19a494-e944-478d-9e3e-55108d047d09` completed the
ESP-IDF 5.5.2 build successfully. The 2,827,072-byte application has 32% of its
partition free and passes esptool checksum and appended-digest validation. The
downloaded builder checksums match:

- merged image SHA-256:
  `81d4a7d2aee19a4563ff2fc6c8c73db88f057474d4841559821dd89daceb42ef`;
- application SHA-256:
  `ef0c7da14a3c9fc9e44633d3eb060cb4091b309fbe744cbf38f5836e7331941c`;
- release ZIP SHA-256:
  `c6b94a62c74028e9ee0d1caba6e751088a5b94ac285a3a82f9f106aca3b6e193`.

Offline inspection finds the reviewed endpoint exactly once, no `.invalid`
endpoint, no complete PEM private-key block, and no common API-key/token or JWT
shape. Partition and OTA metadata match the prior reviewed image exactly. All
display/font/emotion assets are byte-identical; the regenerated WakeNet
container has a different file order, but every contained model file is
byte-identical.

The pre-flash audit remains intentionally **BLOCKED** because seven protected
audio/board sources changed and the factory display/wake/audio acknowledgement
is absent. Full implementation, privacy boundary, artifact provenance, binary
comparison, risks, and reviewer checklist are in
`docs/ES7210_SLOT_AUDITION_REVIEW.md`.

This candidate has not been flashed. No serial port was opened and the device
still runs the previously approved session-refresh image. A separate approval
naming the exact candidate hash is required before any later flash action.

## ES7210 slot-audition application flash and boot result

The user explicitly approved merged-image SHA-256
`81d4a7d2aee19a4563ff2fc6c8c73db88f057474d4841559821dd89daceb42ef`
and acknowledged the temporary button behavior and protected-file pre-flash
audit exception. Immediately before writing, the approved merged and
application hashes were rechecked and the ESP32-S3 image checksum and appended
digest were valid.

The live ESP32-S3 revision 0.2 reported 8 MB PSRAM and the previously validated
identity. Its partition table matched the candidate byte-for-byte. Only the
2,827,072-byte approved application, SHA-256
`ef0c7da14a3c9fc9e44633d3eb060cb4091b309fbe744cbf38f5836e7331941c`,
was written at `0x20000`. Esptool erased `0x20000` through `0x2d2fff`, wrote at
230400 baud, verified the flashed-data hash, and hard-reset normally. NVS,
Wi-Fi and activation state, OTA metadata, PHY data, bootloader, partition
table, and assets were not written.

Post-flash UART confirms compile time `Aug 10 2026 17:19:23`, ESP-IDF 5.5.2,
8 MB PSRAM, the Symbios SKU, display/backlight, ES8311 speaker and ES7210 input
initialization, retained Wi-Fi, successful authenticated gateway bootstrap,
`ota_0`, `Activation done`, the idle state, and WakeNet/AFE startup. No panic,
rollback, digest failure, or activation prompt occurred. At that point, the
four-slot physical UP/DOWN audition remained the final diagnostic acceptance
test.

## ES7210 physical result and mono-microphone correction candidate

The user completed all four physical slot auditions on 2026-08-10 and reported
that every test recorded and played back audio perfectly. This accepts the raw
ES7210/I2S capture and local playback path and rules out a dead microphone
transport. It does not establish any captured slot as a clean, time-aligned
speaker reference.

Source tracing found that the vendor LAFVIN input-reference flag caused normal
Symbios firmware to open two input channels, present them to the AFE as `MR`,
and enable device AEC. The most plausible remaining fault is therefore an
invalid AEC/reference contract that attenuates the real speech channel.

A default-off, LAFVIN-only correction has been prepared. The Symbios variant
uses ES7210 slot 0 / MIC1 as mono `M` input, declares no reference channel,
omits device AEC, and has a compile-time guard against enabling both modes.
The stock LAFVIN variant is unchanged. WakeNet, display, codec output,
authenticated gateway routing, and manual DOWN-button start/submit remain
enabled. Provider credentials remain server-side.

Cloud Build job `3d959f4d-926a-4d2a-a687-3caf4ed2856b` passed. The application
is 2,822,096 bytes with 32% partition free; esptool validates its checksum and
appended digest. Downloaded artifact hashes match the builder manifest:

- merged image SHA-256:
  `ce951a2678d8ecfe331b8587889097c0f0b2d32ce601fa1de2c476a8af04b954`;
- application SHA-256:
  `5192d8bb3b1a4f8bd1380f6611e56b79eee72ad8e9c3c68d13f26970693fbb8c`;
- release ZIP SHA-256:
  `83d91329f4543fd64679bda38658cbf9796dd83f7a8a3c6a77147eb12932a252`.

Partition table, OTA metadata, and assets match the working slot-audition
image byte-for-byte. Binary inspection finds the reviewed endpoint, mono-input
marker, and manual start/submit markers exactly once; it finds no placeholder
endpoint, slot-audition marker, or complete private-key block.

The pre-flash audit remained **BLOCKED** on protected audio/board changes and
the absent factory smoke acknowledgement. At the review boundary this
candidate had not been flashed and the device had not been accessed. Full
details are in `docs/LAFVIN_MONO_MIC_REVIEW.md`.

The user subsequently approved merged-image SHA-256
`ce951a2678d8ecfe331b8587889097c0f0b2d32ce601fa1de2c476a8af04b954`
and explicitly acknowledged the protected-file audit exception. The live
ESP32-S3 identity and partition table matched the reviewed target, and OTA
metadata reported sequence 1/state VALID with `ota_0` active at `0x20000`.

Only the 2,822,096-byte approved application, SHA-256
`5192d8bb3b1a4f8bd1380f6611e56b79eee72ad8e9c3c68d13f26970693fbb8c`,
was written at `0x20000`. Esptool verified the flashed-data hash and reset
normally; no NVS, OTA metadata, PHY, bootloader, partition-table, or asset
region was written. UART confirms the mono marker, retained Wi-Fi, successful
gateway bootstrap, activation, `ota_0`, AFE `1MIC_V251128` with one microphone
and zero playback channels, and WakeNet startup. No panic or rollback occurred.
Physical wake/manual-turn acceptance remains pending.

## RAM-only gateway loopback physical result

The user explicitly approved one temporary RAM-only gateway audio-loopback
turn and acknowledged that the submitted voice audio would be held only in
volatile memory and cleared immediately after playback. Gateway commit
`a9cc892` passed the local suite (`17 passed, 1 skipped`) and Gateway CI. Cloud
Run revision `symbios-voice-gateway-00016-vol` was deployed behind a zero-
traffic tag, returned HTTP 200, and matched the production service account,
Secret Manager bindings, datastore, and gain configuration. Only the provider
setting differed. It was then temporarily promoted for the physical test.

The authenticated device turn delivered 180 Opus frames, decoded to 345,600
PCM bytes with mean absolute amplitude 220 and peak 4,200. Playback completed,
the volatile buffer was cleared, and the user reported hearing their words
clearly. This accepts the complete microphone/AFE, device Opus encoder,
authenticated transport, gateway decoder, gain/resampling, gateway Opus
encoder, device decoder, and speaker path. No raw audio or transcript was
logged or persisted. Production traffic was then restored to Vertex revision
`symbios-voice-gateway-00014-sug`, whose public health route returned HTTP 200.
No firmware was changed or flashed.

## Vertex binary-frame parser correction candidate

The accepted loopback isolates the remaining failure to the Vertex response
side of the gateway. A metadata-only synthetic probe using the same Vertex
model and service identity showed that Vertex sends the setup response and all
subsequent server events as binary WebSocket frames. The gateway already
accepted the binary setup through `json.loads`, but its response loop then
discarded every non-string frame before JSON decoding. This exactly accounts
for the healthy input metrics followed by no transcription, turn-complete
event, or response audio.

The candidate correction decodes both text and UTF-8 binary JSON frames and
rejects malformed or non-object payloads. A regression test covers both frame
types and invalid input. The isolated Python 3.13 suite passes (`18 passed, 1
skipped`), Python compilation succeeds, and `git diff --check` is clean. This
is a gateway-only change: it does not alter device firmware, authentication,
Secret Manager bindings, raw-audio handling, or the public endpoint.

The user explicitly approved deployment of commit
`e60b8a02483c946e9323bebacc89d171a10cb724` after its Gateway CI job passed.
Cloud Run revision `symbios-voice-gateway-00019-led` was built from that exact
checkout and first deployed at zero percent traffic behind a temporary tag.
The tagged health route returned HTTP 200, and the revision matched the
reviewed service account, both Secret Manager references, Firestore backend,
Vertex model, 4x input gain, and `vertex_live` provider. The verified revision
was then promoted to 100 percent traffic. Both the candidate and RAM-loopback
tags were removed; the public health route returns HTTP 200 and there are no
revision error logs. No firmware was changed or flashed. One physical
DOWN/speak/DOWN turn remains the final end-to-end acceptance test.
