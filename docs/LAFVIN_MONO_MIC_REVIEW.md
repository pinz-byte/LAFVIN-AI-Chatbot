# LAFVIN mono-microphone correction review

## Decision and current state

**Exact-hash approved, application-flashed, and boot-verified. Physical voice
acceptance is pending.**

All four RAM-only ES7210 slot auditions recorded and played audio correctly.
That result establishes that the codec, I2S/TDM input, RAM capture, and local
speaker path work. It also breaks the earlier diagnostic loop: another cloud
gain or button-state change is not the next useful correction.

The stock LAFVIN definition declares an audio reference channel. Xiaozhi then
opens two input channels, describes them to the AFE as microphone plus
reference (`MR`), and enables device AEC. The slot audition proves that the
selected inputs carry microphone audio, but it does not establish a clean,
time-aligned speaker-reference signal. Treating a microphone slot as the AEC
reference is therefore the most plausible cause of the severe attenuation and
failed wake/turn processing.

The review candidate changes only the Symbios build contract:

- use ES7210 TDM slot 0 / MIC1 as one mono microphone channel;
- declare no hardware reference channel, so WakeNet and the voice AFE use `M`
  rather than `MR`;
- leave device AEC disabled and reject any build that combines it with the
  mono option;
- retain the local wake word, audio codec, display, authenticated Symbios
  gateway, and the diagnostic DOWN-button start/submit behavior;
- keep the option default-off, so the stock `lafvin-aichatbot` build retains
  the vendor input-reference and AEC settings.

The deployed gateway's existing `VERTEX_INPUT_GAIN=4.0` setting is unchanged.
Provider API credentials remain in the gateway's server-side secret bindings;
the firmware contains only the reviewed HTTPS gateway URL.

## Build provenance and artifacts

Regional Cloud Build job `3d959f4d-926a-4d2a-a687-3caf4ed2856b` completed
successfully on 2026-08-10 using ESP-IDF 5.5.2. The release configuration
explicitly contains `CONFIG_LAFVIN_MONO_MIC_INPUT=y` and
`CONFIG_LAFVIN_AUDIO_DIAGNOSTIC=y`, and contains no
`CONFIG_USE_DEVICE_AEC=y` or slot-audition option.

The application is 2,822,096 bytes and has 1,306,672 bytes (32%) free in the
smallest application partition. Esptool 4.8.1 identifies a valid ESP32-S3
image with six segments, valid checksum `a1`, and valid appended validation
hash `377aa16946f57d5e68aeb890229ee65033bf37afeaa9cf0523e7808535a94c3e`.

Downloaded builder checksums match the local files:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `merged-binary.bin` | 16,384,750 | `ce951a2678d8ecfe331b8587889097c0f0b2d32ce601fa1de2c476a8af04b954` |
| extracted `xiaozhi.bin` | 2,822,096 | `5192d8bb3b1a4f8bd1380f6611e56b79eee72ad8e9c3c68d13f26970693fbb8c` |
| release ZIP | 8,156,964 | `83d91329f4543fd64679bda38658cbf9796dd83f7a8a3c6a77147eb12932a252` |

Local review artifacts are under
`firmware-review/3d959f4d-mono-mic-review/`; that directory is intentionally
gitignored. The immutable Cloud Storage prefix is
`gs://subastop-herald-symbios-firmware/symbios-terminal/3d959f4d-926a-4d2a-a687-3caf4ed2856b/`.

## Offline verification results

- The downloaded merged image and release ZIP match the builder's checksum
  manifest.
- The reviewed gateway URL, mono-input marker, manual-listening marker, and
  manual-submit marker each occur exactly once in the application.
- `.invalid` and slot-audition markers occur zero times.
- No complete PEM private-key block occurs. Standalone private-key header names
  are TLS parser format labels, as in the previously reviewed images.
- The partition table, OTA metadata, and complete asset region are
  byte-for-byte identical to the working slot-audition image.
- Generated Symbios normal, manual-diagnostic, and slot-audition configurations
  use mono input and omit device AEC. Diagnostic flags remain mutually
  exclusive.
- Python compilation, JSON parsing, and `git diff --check` pass.

`tools/preflash_audit.py` remains fail-closed. It reports the intentional
protected audio/board changes and the absent factory display/wake/audio smoke
acknowledgement. The prior audit exception applied to the exact slot-audition
image; it is not reused for this candidate.

## Original review boundary

No serial port was opened and no device bytes were written while preparing or
validating this correction. The physical device still runs the approved
RAM-only slot-audition application with merged-image SHA-256
`81d4a7d2aee19a4563ff2fc6c8c73db88f057474d4841559821dd89daceb42ef`.

Before any flash, the reviewer must approve merged-image SHA-256
`ce951a2678d8ecfe331b8587889097c0f0b2d32ce601fa1de2c476a8af04b954`
and explicitly accept the protected-file audit exception for this exact image.
Only an application-only write at `0x20000` should then be considered, after
rehashing the artifact, validating the live partition table, and confirming
the target device identity.

## Application-only flash and boot result

The user explicitly approved merged-image SHA-256
`ce951a2678d8ecfe331b8587889097c0f0b2d32ce601fa1de2c476a8af04b954`
and acknowledged the protected-file audit exception. Immediately before the
write, both merged and application hashes matched the reviewed values.

The connected target identified as the previously validated ESP32-S3 revision
0.2 with 8 MB PSRAM and MAC ending `d2:14`. Its live 4,096-byte partition table
matched the candidate byte-for-byte with SHA-256
`ce40cfe75056ef74bc052942f8a9ee3dce8e5e14ba17a6f63685a8fa0d11a23d`.
Live OTA metadata reported sequence 1/state VALID with `ota_0` active at
`0x20000`.

Only the approved 2,822,096-byte `xiaozhi.bin`, SHA-256
`5192d8bb3b1a4f8bd1380f6611e56b79eee72ad8e9c3c68d13f26970693fbb8c`,
was written at `0x20000` using 230400 baud. Esptool erased `0x20000` through
`0x2d0fff`, wrote the application, verified the flashed-data hash, and
hard-reset normally. NVS, Wi-Fi and activation state, OTA metadata, PHY data,
bootloader, partition table, and assets were not written.

The post-flash UART boot confirms compile time `Aug 10 2026 18:05:48`, ESP-IDF
5.5.2, 8 MB PSRAM, the Symbios SKU, display/backlight, ES8311/ES7210 startup,
and the explicit mono marker. Retained Wi-Fi connected, the reviewed HTTPS
gateway bootstrap succeeded, `ota_0` remained active, and activation completed.
The AFE then reported version `1MIC_V251128`, exactly one microphone and zero
playback channels, and a WakeNet/VAD pipeline. No panic, rollback, digest
failure, or activation prompt appeared.

The remaining acceptance step is physical: first try the local wake word. If
needed, press DOWN once, speak a short sentence, then press DOWN once to submit
the manual turn. Do not use the slot-audition UP/DOWN sequence; that diagnostic
mode is absent from this image.
