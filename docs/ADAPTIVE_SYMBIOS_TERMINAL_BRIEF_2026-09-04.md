# Adaptive Symbios Terminal brief

Date: 2026-09-04 (America/Lima)
Status: approved for server-side implementation
Device boundary: no firmware or assets write

## Objective

Turn the existing authenticated APEX feed into a time-aware editorial terminal
without inventing facts or adding another credential path. The display must
change purpose as the US market day advances:

1. `APEX LIVE` from 06:00 ET through the market session;
2. `CLOSING DESK` from 16:00 through 17:59 ET;
3. `PORTFOLIO AUTOPSY` from 18:00 through 20:59 ET;
4. `SYMBIOS COMMAND` from 21:00 through 22:59 ET;
5. `QUIET INTELLIGENCE` from 23:00 through 05:59 ET;
6. `WEEKEND REVIEW` from 08:00 through 17:59 ET on a closed
   weekend/holiday, with `QUIET INTELLIGENCE` outside that window.

New York time is the scheduling clock. The date attached to a closed-session
mode continues to come from the latest verified quote timestamp, not the
gateway refresh time.

## Evidence and editorial rules

- Continue using only the existing allow-listed APEX snapshot, authenticated
  device request, and public BTC quote.
- Preserve absolute first priority for a fresh broker-confirmed `TRADE` or
  `RISK` interruption.
- `APEX LIVE`: market, signals, movers, technical extremes, news, Council,
  briefing.
- `CLOSING DESK`: market close, portfolio close, movers, carry signals, news,
  Council, briefing, extremes.
- `PORTFOLIO AUTOPSY`: portfolio, close context, movers, extremes, signals,
  news, Council, briefing.
- `SYMBIOS COMMAND`: close context, Council, Slack briefing, news, carry
  signals, portfolio, movers, extremes.
- `WEEKEND REVIEW`: last-session context, portfolio, news, Council, briefing,
  signals, movers, extremes.
- `QUIET INTELLIGENCE`: at most four high-value cards after any interrupt:
  close context, portfolio, latest sourced news, then Council/briefing.
- Missing categories remain absent. No filler, inference, duplicate cards, or
  stale-event resurrection.

## Files to modify

- `gateway/symbios_gateway/terminal_intention.py`
- `gateway/symbios_gateway/apex_feed.py`
- `gateway/tests/test_terminal_intention.py`
- `gateway/tests/test_terminal_feed.py`
- deployment documentation under `docs/`

The APEX producer, `exec_server.py`, device firmware, assets, enrollment,
voice, storage, Secret Manager bindings, broker access, and order execution are
out of scope.

## Pre-flight

- APEX Builder Gate has zero unresolved failures for the scoped files.
- The current post-close gateway suite passes.
- Existing Cloud Run configuration and service account are inherited.
- Deploy first as a tagged zero-traffic revision; promote only after health,
  authentication-boundary, and contract tests pass.

## Acceptance

- Boundary tests cover every time transition, weekend/holiday behavior, and an
  invalid market phase.
- Each mode produces the documented category order from the same verified
  facts.
- Quiet mode respects the four-card cap while never suppressing a fresh
  `TRADE/RISK` interrupt.
- Payload remains within the installed device's 8 KiB / 15-card bounds.
- Full gateway tests pass.
- Production health remains HTTP 200 and unauthenticated feed access remains
  rejected.
