# ES7210 RAM-only slot-audition review

## Decision and current state

**Approved and application-flashed; physical slot audition is pending.**

The candidate is a compile-time-gated diagnostic for the LAFVIN AI ChatBot
ESP32-S3. It is intended to isolate the unresolved microphone attenuation by
auditioning each raw ES7210 TDM slot locally. The build completed and its
artifacts passed offline integrity checks. At the original review boundary, no
serial port had been opened and the device still ran the previously approved
session-refresh application.

The user subsequently approved merged-image SHA-256
`81d4a7d2aee19a4563ff2fc6c8c73db88f057474d4841559821dd89daceb42ef`
and explicitly acknowledged the temporary button changes and protected-file
pre-flash audit exception. The approved application is now installed; the
four-slot physical listening test has not yet been performed.

## Diagnostic behavior

`CONFIG_LAFVIN_SLOT_AUDITION` is default-off and depends on the LAFVIN board.
When enabled, it deliberately replaces the normal UP/DOWN chat controls:

- UP/BOOT (GPIO0) advances through raw TDM slots 0, 1, 2, and 3;
- DOWN (GPIO19) starts one three-second capture for the selected slot;
- the provisional physical labels are slot 0/MIC1, slot 1/MIC3, slot 2/MIC2,
  and slot 3/MIC4, matching the ES7210 output order used by the codec driver;
- the first DOWN press can audition slot 0 without pressing UP first;
- each successful run plays the untouched capture locally, pauses 500 ms,
  then plays a bounded-normalized copy locally;
- the display reports only slot, mean absolute amplitude, peak, clipped-sample
  count, and applied gain.

The capture path is intentionally separate from normal voice transport:

1. Record the exact prior wake-word and voice-processing enable state.
2. Stop WakeNet/AFE voice processing and clear pending playback.
3. Reopen ES7210 input as one filtered raw TDM slot and apply the corresponding
   physical microphone gain control.
4. Discard 240 ms of warm-up audio.
5. Allocate exactly 144,000 bytes in PSRAM and capture 72,000 PCM16 samples
   (three seconds at 24 kHz).
6. Close the diagnostic input before speaker playback.
7. Play raw PCM, then normalize in place toward peak 12,000 with a maximum 16x
   gain and PCM16 saturation, and play the normalized copy.
8. Free the PSRAM buffer and restore the exact prior processing state.

There is no AFE, AEC, resampling, Opus encoding, filesystem/NVS write, OTA
write, gateway call, or other network call in the audition path. Raw PCM is not
logged. It exists only in transient RAM and the codec/DMA playback path and is
freed after the run. The existing authenticated Symbios gateway configuration
is retained in the image for normal startup, but the audition itself does not
send audio to it.

## Build provenance and artifacts

The review build used ESP-IDF 5.5.2 in regional Cloud Build job
`ba19a494-e944-478d-9e3e-55108d047d09`, which completed successfully on
2026-08-10. It enabled `CONFIG_LAFVIN_SLOT_AUDITION=y`, disabled the earlier
aggregate-level diagnostic, and injected the reviewed gateway URL through the
existing configuration tool. Provider API credentials remain server-side.

The application is 2,827,072 bytes. ESP-IDF reports 1,301,696 bytes (32%) free
in the smallest application partition. Esptool 5.1.0 identifies a valid
ESP32-S3 DIO/80 MHz/16 MB image, a valid image checksum, and valid appended
validation hash
`5546b6941017999b5a4bd4324e1b6d80554a78fc625044d0d875d193f8c1f793`.

Downloaded builder checksums match the local files:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `merged-binary.bin` | 16,384,750 | `81d4a7d2aee19a4563ff2fc6c8c73db88f057474d4841559821dd89daceb42ef` |
| extracted `xiaozhi.bin` | 2,827,072 | `ef0c7da14a3c9fc9e44633d3eb060cb4091b309fbe744cbf38f5836e7331941c` |
| release ZIP | 8,159,676 | `c6b94a62c74028e9ee0d1caba6e751088a5b94ac285a3a82f9f106aca3b6e193` |

Local review artifacts are under
`firmware-review/ba19a494-slot-audition/`; that directory is intentionally
gitignored. The immutable Cloud Storage prefix is
`gs://subastop-herald-symbios-firmware/symbios-terminal/ba19a494-e944-478d-9e3e-55108d047d09/`.

## Offline verification results

- The reviewed HTTPS gateway URL occurs exactly once; `.invalid` occurs zero
  times.
- The slot-selection, audition-request, and raw-playback markers each occur
  exactly once.
- Common Google, OpenAI, and GitHub key/token shapes and JWT shapes occur zero
  times.
- Four private-key *header labels* occur because the TLS parser contains the
  supported PEM format names. The same labels occur in the previously reviewed
  session-refresh image. No complete PEM private-key block occurs.
- The partition table and OTA-data regions are byte-for-byte identical to the
  reviewed session-refresh image.
- The bootloader has the same ESP32-S3 parameters and ESP-IDF 5.5.2 version.
  Its bytes differ only because the clean rebuild embeds a new compile time and
  therefore a new checksum/digest.
- Both images contain the same 24 asset entries. The font and all 21 emotion
  GIFs are byte-identical. The wake-model container and `index.json` differ in
  generated file ordering, but the contained `_MODEL_INFO_`, `wn9_data`, and
  `wn9_index` files are individually byte-identical.
- Python compilation, generated diagnostic configuration, normal Symbios
  configuration regression, mutually exclusive diagnostic flags, and
  `git diff --check` pass.

`tools/preflash_audit.py` correctly remains fail-closed. It reports that seven
protected audio/board files changed and that the factory display/wake/audio
smoke test has not been acknowledged. Those are intentional review blockers,
not waived checks.

## Reviewer checklist

- Confirm that a review-only build may repurpose both physical buttons and
  temporarily bypass normal chat behavior.
- Confirm the four-slot/physical-microphone labeling is acceptable as a
  provisional mapping to be validated by listening and aggregate metrics.
- Review the 16x normalization ceiling and target peak 12,000 for speaker
  safety and intelligibility.
- Review the codec close/reopen and exact processing-state restoration path.
- Accept or reject the intentional protected-file audit exception.
- Require a separate approval that names the exact merged-image SHA-256 before
  any later flash action.

## Application-only flash and boot result

Immediately before writing, the approved merged image and extracted
application were rehashed, and esptool revalidated the ESP32-S3 image checksum
and appended digest. The live device identified as the previously validated
ESP32-S3 revision 0.2 with 8 MB PSRAM and MAC ending `d2:14`. Its live partition
table was read at `0x8000` and matched the candidate byte-for-byte with SHA-256
`ce40cfe75056ef74bc052942f8a9ee3dce8e5e14ba17a6f63685a8fa0d11a23d`.

Only the 2,827,072-byte approved `xiaozhi.bin` was written at `0x20000`.
Esptool erased `0x20000` through `0x2d2fff`, wrote at 230400 baud, verified the
flashed-data hash, and hard-reset normally. NVS, Wi-Fi and activation state,
OTA metadata, PHY data, bootloader, partition table, and display/WakeNet assets
were not written.

The filtered post-flash UART boot confirms compile time
`Aug 10 2026 17:19:23`, ESP-IDF 5.5.2, 8 MB PSRAM, the Symbios SKU, display and
backlight initialization, ES8311/ES7210 initialization, retained Wi-Fi,
successful HTTPS bootstrap to the reviewed endpoint, `ota_0`,
`Activation done`, transition to idle, and WakeNet/AFE startup. No panic,
rollback, digest failure, or new activation prompt appeared.

The firmware is installed and awaits the four-slot UP/DOWN physical audition.
