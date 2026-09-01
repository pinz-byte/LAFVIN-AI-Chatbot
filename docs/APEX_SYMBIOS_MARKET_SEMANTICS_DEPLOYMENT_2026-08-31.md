# APEX–SYMBIOS Market Semantics Deployment

Date: 2026-08-31 (America/Lima)
Status: deployed and physically verified
Mode: read-only market display

## Result

The terminal now separates transport health from the age and session meaning of
market data. `status` remains the authenticated feed-health field. The optional,
backward-compatible `display_status` is derived from market phase and the oldest
visible quote and can be `LIVE`, `PREMARKET`, `LAST CLOSE`, `DELAYED`, `STALE`,
or `OFFLINE`.

Closed-session cards use the date and timestamp of the latest verified direct
quote, rather than the gateway refresh clock. The current payload therefore
renders `LAST CLOSE` and `MARKET CLOSE · AUG 31` while preserving the underlying
quote timestamp.

Council and Slack were verified against their canonical producers. Council is
fresh from its dated tier output. Slack terminal events remain limited to
messages that received an HTTP 200 from Slack; no event was reconstructed or
invented for this deployment.

## Source and deployment records

### APEX producer

- Repository: `pinz-byte/apex-ultra`
- Branch: `fix/symbios-last-close-20260828`
- Isolated source commit: `7282401f48608e149246873bd8fbeb1317751e1f`
- Production runtime commit: `96d53aa69dfe620986c6ef23c855ffdcb57a598d`
- Production backup:
  `/Users/usuario/Documents/Claude/Projects/apex-ultra/deployment-backups/symbios-market-semantics-20260831T233817Z`
- Focused exporter tests: 14 passed
- Full clean APEX suite: 326 passed
- Scheduled production cycle: exit 0, 51 direct quotes, 2 signals, 1 retained
  technical observation, gateway ingest HTTP 202

### Symbios gateway

- Repository: `pinz-byte/LAFVIN-AI-Chatbot`
- Branch: `fix/symbios-market-semantics-20260831`
- Gateway semantics commit: `8d742a340d27ebcaacbdd2ec9747e50750988522`
- Cloud Run revision: `symbios-voice-gateway-00049-hom`
- Container digest:
  `sha256:7912a952de1cd8dd458a800cf8692c51553f87983929031f8e76f7cd0755c922`
- Traffic: 100%
- Rollback tags retained: `display-contract-v2` and `display-only`
- Gateway suite: 44 passed, 1 skipped
- Production verification: terminal feed HTTP 200 and APEX ingest HTTP 202

### Display application

- Feed protocol commit: `ffc4c3069ef746f522246ee568e6ca24158142df`
- Display-only boot correction: `bb90d407a3a7eaf85416e33ef880de47afa4a690`
- GitHub Actions run: `33454562944`
- Application image: `xiaozhi.bin`, 2,039,568 bytes
- SHA-256: `8e99a9bfbe80c8b6ce510d84faeb8044eab38923690204f51d3674ffac3d49a5`
- Image validation hash:
  `68632d4689af670bab6410a7f3f3c543a69d5f7c4ae54ccae49e7521d9a8b6a5`
- Post-write readback: byte-identical, same SHA-256
- Physical boot: two corrected boots observed; Wi-Fi connected, 14 cards
  refreshed, zero audio-codec requests, panics, or reboots
- Post-boot production feed: HTTP 200 on revision 49

The first review image from run `33453102925` exposed a null audio-codec access
in the status-bar timer after Wi-Fi scanning. The device was immediately restored
from the fresh application backup. The corrected source prevents all mute and
low-battery sound access in display-only mode and adds a static regression test.

## Device write boundary and rollback

Fresh backup and manifest:

`firmware-backups/symbios-market-semantics-preflash-20260831T190502-0500`

Only the application image was written at `0x20000`. Assets, bootloader,
partition table, OTA metadata, NVS, PHY data, and the second OTA slot were not
written. No merged image was flashed. The previous stable application SHA-256 is
`d32e258eb52fd566e252d6a66e2d70dd1d000fb6a4cf815c39342c94ca48fe8c`.

## Operational notes

- The APEX repository root contains older deployment backups with duplicate test
  module names. The canonical `tests/` suite and a clean worktree were used for
  validation.
- GitHub Actions reports a non-blocking Node 20 action-runtime deprecation notice.
- APEX currently emits an evidence-backed warning that the Schwab refresh token
  is nearing expiry. That credential remains server-side and was not modified by
  this deployment.
