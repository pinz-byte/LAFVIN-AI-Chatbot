# LAFVIN English wake-model assets review

## Decision and current state

**Prepared and build-verified. Not flashed.**

The physical device now completes authenticated manual voice turns: DOWN starts
listening, the second DOWN submits the turn, Vertex transcribes it, and the
device plays the spoken response. The remaining failure is local wake-word
detection. The installed assets contain only the Mandarin
`wn9_nihaoxiaozhi_tts` model, while the user expects an English wake phrase.
Repeated physical `Ni hao Xiao Zhi` attempts after the mono-microphone
correction produced no state change.

The candidate changes model selection only for the Symbios build:

- disable `CONFIG_SR_WN_WN9_NIHAOXIAOZHI_TTS`;
- enable the built-in `CONFIG_SR_WN_WN9_HIESP` model;
- retain mono MIC1 input, the authenticated Symbios gateway, English UI,
  display assets, audio codec, and the proven manual DOWN-button fallback;
- retain aggregate-only input-level diagnostics in the reviewed build;
- leave the stock `lafvin-aichatbot` build unchanged.

The wake phrase for this candidate is **“Hi ESP.”** It does not add a custom
“CLC” model or change WakeNet thresholds, AFE gain, audio source, provider
credentials, or gateway behavior.

## Why the proposed write is assets-only

The running application loads `srmodels.bin` generically from the partition
labeled `assets`; no application C++ path selects a specific `CONFIG_SR_WN_*`
model. The model-selection symbols are consumed by the asset build script.
Therefore reflashing the application is unnecessary and would replace a voice
path that has already passed physical acceptance.

The partition table defines:

| Partition | Offset | Size |
| --- | ---: | ---: |
| `ota_0` application | `0x20000` | `0x3f0000` |
| `ota_1` application | `0x410000` | `0x3f0000` |
| `assets` | `0x800000` | `0x800000` |

The proposed write is only the 7,996,242-byte `generated_assets.bin` at
`0x800000`. It leaves 392,366 bytes free in the assets partition. NVS, Wi-Fi,
activation state, OTA metadata, PHY data, bootloader, partition table, and both
application slots are excluded.

## Build provenance and exact hashes

Source commit:
`857a73df27acb02ef20a2ee6e422035342611e68`.

GitHub Actions run `31436825809` passed:

- gateway tests;
- stock LAFVIN compile-only build;
- normal Symbios compile-only build;
- endpoint-injected Symbios review build with
  `CONFIG_LAFVIN_AUDIO_DIAGNOSTIC=y` and slot audition disabled.

Regional Cloud Build `6f07e1f6-ec84-46a5-955f-27d632827c6a` also completed
successfully under ESP-IDF 5.5.2. Its immutable artifacts are stored at:

`gs://subastop-herald-symbios-firmware/symbios-terminal/6f07e1f6-ec84-46a5-955f-27d632827c6a/`

Downloaded hashes match the builder manifest:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| merged image | 16,384,850 | `b7a25d9295af0e79c3ba27dbfd87e169059ce18660503f3974e2173c17ee9089` |
| release ZIP | 8,112,920 | `dd9cbaae593c150b5d5f03b7c70991c2d0b7cf7631bfbd2fe86eca3762cd9302` |
| extracted application | 2,822,096 | `1670c56947f3527423d9929ebeb4db2c557a4e5bcbd497d4550ddb355ba7d8c9` |
| proposed assets write | 7,996,242 | `dc15f362a44ca66c5b709b339efed04e44130c2bbf76c5a2dd57338d460be8b1` |

The release ZIP's merged image is byte-identical to the downloaded merged
image. Esptool 4.8.1 identifies a valid six-segment ESP32-S3 application with
checksum `b3` and valid appended validation hash
`7d19ba571001216ae91a0232763ae261c57f552a2b5d8ff13ed6a2c35e6022ab`.
The rebuilt application is recorded for provenance only and is not part of the
proposed write.

## Assets comparison and privacy audit

Both the installed-model build and candidate contain the same 24 asset names.
Twenty-three files are byte-identical, including the font and all 21 display
emotion GIFs plus `index.json`. Only `srmodels.bin` changes:

| Asset | Current | Candidate |
| --- | --- | --- |
| model name | `wn9_nihaoxiaozhi_tts` | `wn9_hiesp` |
| `srmodels.bin` bytes | 291,042 | 291,142 |
| `srmodels.bin` SHA-256 | `243978f55ce4ede7b86cb30747e3bdd88fd0d7c3e7f4af75741e81a98b7093f1` | `32c77462144475964e3b03b48c14e9b9636eb5684407d14dec5cc6a5b967c244` |

The candidate assets table contains 24 files, stored length 7,996,230, and a
valid internal additive checksum `0x4c76`. The candidate model container
contains `wn9_hiesp`; the old Mandarin model name is absent.

Offline scanning of the proposed assets write finds no Symbios gateway URL,
OpenAI-style key, Google API-key shape, JWT shape, or formatted PEM private
key. Provider credentials remain server-side.

The partition table and OTA-initial regions are byte-identical to the current
working mono image. Rebuilt bootloader and application bytes differ because
they were produced in a new build, but neither region is included in the
assets-only proposal.

## Audit boundary, risks, and reviewer checklist

`tools/preflash_audit.py` remains intentionally **BLOCKED** by the cumulative
protected audio/board changes and the missing factory display/wake/audio smoke
acknowledgement. This candidate itself changes only the unprotected LAFVIN
build configuration and local config generator, but writing the shared assets
partition still requires an explicit exception because it contains both the
wake model and display resources.

Before any later write:

1. Rehash the exact assets file and merged image.
2. Identify the live ESP32-S3 and verify its partition table.
3. Read and hash the current live assets partition for recovery.
4. Confirm `ota_0` remains the active, valid application.
5. Write only `generated_assets.bin` at `0x800000` and verify the flash hash.
6. Confirm boot, display assets, `wn9_hiesp` loading, manual DOWN fallback, and
   the hands-free “Hi ESP” wake phrase.

The principal risk is power loss or corruption while updating the shared
assets partition, which could temporarily remove display or speech-model
assets. The retained live-assets backup and prior Mandarin asset image provide
a recovery path. A model change may also produce false accepts or false
rejects; physical phrase and idle-room testing remain mandatory.

No serial port was opened, and no bytes were written to the device while
preparing this review. Flashing requires a separate approval naming both the
merged-image SHA-256 and the proposed assets SHA-256, plus acknowledgement of
the assets/protected-file audit exception.

## Approved assets-only flash result

The user explicitly approved merged-image SHA-256
`b7a25d9295af0e79c3ba27dbfd87e169059ce18660503f3974e2173c17ee9089`
and assets SHA-256
`dc15f362a44ca66c5b709b339efed04e44130c2bbf76c5a2dd57338d460be8b1`,
and acknowledged the shared-assets/protected-file audit exception. Immediately
before the write, both approved files were rehashed, the live ESP32-S3 and 16 MB
flash were identified, the live partition table matched the reviewed table
byte-for-byte, and OTA metadata reported sequence 1/state VALID with `ota_0`
active.

The complete pre-write assets partition was read into the permissions-restricted
recovery file
`firmware-review/6f07e1f6-english-wake-review/live-preflash-backup-20260810/live-assets-mandarin.bin`.
It is 8,388,608 bytes with SHA-256
`4d6d194a8482f8fc49b5b5c5857a44fe5a5b08059b0ecde361860e7fe8601138`.
The accompanying live partition-table SHA-256 is
`ce40cfe75056ef74bc052942f8a9ee3dce8e5e14ba17a6f63685a8fa0d11a23d`.

Esptool 5.1.0 wrote only `generated_assets.bin` at `0x800000`; its erase range
was `0x800000` through `0xfa0fff`, entirely within the assets partition. The
tool padded the 7,996,242-byte source with two erased-value bytes for word
alignment, reported its write-time data hash valid, and a separate
`verify-flash` pass reported a matching digest. It did not write the
application slots, bootloader, partition table, OTA metadata, NVS, or PHY
regions.

Post-reset UART confirms retained Wi-Fi, successful Symbios gateway bootstrap,
activation, `ota_0`, idle state, display initialization, mono MIC1 input, and
successful assets loading. WakeNet explicitly reports model `wn9_hiesp`, the
`Hi,ESP` WakeNet9 configuration, a one-microphone AFE pipeline, and live input
levels. Physical hands-free “Hi ESP” recognition and the retained manual DOWN
fallback remain the final user acceptance tests.
