# APEX–SYMBIOS Market Semantics and Source Recovery Brief

Date: 2026-08-31 (America/Lima)
Owner: LFP — Subascorp
Mode: read-only market display

## Purpose

Make the display distinguish a healthy authenticated feed from the freshness of
the market facts it contains. Closed-session cards must show the verified market
session date instead of the current refresh clock. Council and Slack events must
remain evidence-backed, bounded, and visible when their canonical producers have
fresh output.

## Current verified state

- The APEX five-minute loop is publishing successfully.
- The 2026-08-31 payload contains 12 rows and 10 source events.
- Council is fresh from `council_tiers_2026-08-31.json`.
- Slack mirroring is fresh in `terminal_events.json` and is written only after
  Slack accepts a message.
- The gateway currently labels the whole feed `LIVE` from snapshot recency even
  when the underlying quote rows are a prior close.
- Closed-session market cards currently print the refresh time, not the session
  date.

## Files in scope

### APEX producer on LFP-M1

- `symbios_terminal_export.py`
- `tests/test_symbios_terminal_export.py`
- `tools/terminal_events.py` only if source-state semantics require it
- `tests/test_terminal_events.py` only if `tools/terminal_events.py` changes

### Symbios gateway

- `gateway/symbios_gateway/apex_feed.py`
- `gateway/tests/test_terminal_feed.py`
- `gateway/tests/test_terminal_intention.py` only if selection changes

### Display protocol

- `xiaozhi-esp32-main/main/terminal_feed.cc`
- `tools/tests/test_display_only_firmware.py`

### Deployment evidence

- `docs/APEX_SYMBIOS_MARKET_SEMANTICS_DEPLOYMENT_2026-08-31.md`

No audio, wake word, voice session, order execution, OAuth, `exec_server.py`,
assets, bootloader, partition table, or merged firmware image is in scope.

## Contract

1. `status` continues to describe authenticated feed transport freshness.
2. A backward-compatible optional display label describes the market state:
   `LIVE`, `PREMARKET`, `LAST CLOSE`, `DELAYED`, `STALE`, or `OFFLINE`.
3. Existing firmware must continue accepting the gateway response while the new
   optional label is ignored.
4. New display firmware uses the optional label without changing audio or update
   behavior.
5. Closed-session market cards use the date of the newest verified direct quote,
   rendered in America/New_York, and retain that quote timestamp as provenance.
6. No price, signal, Council decision, or Slack notification is inferred.
7. Council is `FRESH` only inside its bounded freshness window; stale output is
   reported but not rendered as current.
8. Slack cards come only from Slack-accepted deliveries in the canonical event
   journal. Repeated operational notices may be deduplicated by the existing
   bounded editorial policy.
9. Fifteen device cards remain a hard capacity, not a content quota.
10. Secrets remain server-side. The device receives only public endpoints and its
    enrolled device credential.

## Pre-flight

- Run the ten-pattern APEX Builder Gate over every APEX file in scope.
- Confirm current Council and Slack producer files and launch agents.
- Build changes in isolated worktrees or branches; do not overwrite unrelated
  working-tree edits.
- Back up every production file before replacement.
- Run focused tests and the full APEX suite.
- Run gateway and display protocol tests.
- Deploy the gateway before any optional display application so the protocol is
  backward compatible.
- If an application image is required, back up and write only the application
  partition at `0x20000`; never write assets or a merged image.

## Acceptance

- Intraday data displays `LIVE` only when both transport and quote freshness are
  live.
- Closed/weekend cards display `LAST CLOSE` plus the real session date.
- Council and Slack status match their current canonical sources.
- The authenticated feed remains HTTP 200 and the APEX ingest remains HTTP 202.
- No OTA/bootstrap traffic, reboot loop, audio initialization, or device secret
  exposure is introduced.
- Production source, deployed hashes, rollback material, and Git commits are
  recorded in the deployment report.
