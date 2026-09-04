# APEX–SYMBIOS Post-Close Desk — execution brief

Status: approved for implementation  
Date: 2026-09-04 (America/Lima)  
Mode: read-only market intelligence display

## Problem

The terminal changes the market label after the closing bell, but its editorial
rotation still behaves like an intraday ticker. Movers, signals, technical
extremes, Council notes, Slack alerts, and portfolio facts continue without a
clear post-close hierarchy. This makes a healthy display look frozen and does
not help the user review the session or prepare for the next one.

## Objective

Make the existing verified feed select a visibly different briefing after the
market closes:

- `intraday`: live market context and current decision signals;
- `eod`: `CLOSING DESK`, led by the verified close and portfolio day result;
- weekday `closed`: `NIGHT WATCH`, led by last-close facts, carried signals,
  sourced news, Council/Slack, and next-session watch items;
- `weekend`: `WEEKEND BRIEF`, led by the last verified session, portfolio close,
  recent sourced context, Council/Slack, and BTC.

The transition must be automatic from the canonical APEX `market_phase`; it
must not depend on the device clock or a manual button.

## Truth and safety boundaries

- Portfolio values come only from the authenticated Schwab/APEX snapshot.
- Prices, movers, breadth, RSI observations, and signal states come only from
  existing deterministic APEX output.
- News, Council, and Slack cards retain their source and evidence timestamp.
- A carried signal is labelled as a close/next-session watch item; it is never
  presented as a new after-hours signal.
- Missing facts are omitted or explicitly marked unavailable. No market fact,
  portfolio value, trade, recommendation, or next-session outcome is inferred.
- The display remains read-only. Order execution, broker OAuth, and
  `exec_server.py`/port 7701 are outside scope.
- API keys, OAuth tokens, and device secrets remain server-side.

## Files in scope

### APEX producer

- `symbios_terminal_export.py`
- `tests/test_symbios_terminal_export.py`

### Symbios gateway

- `gateway/symbios_gateway/terminal_intention.py`
- `gateway/symbios_gateway/apex_feed.py`
- `gateway/tests/test_terminal_intention.py`
- `gateway/tests/test_terminal_feed.py`

### Evidence

- `docs/APEX_SYMBIOS_POST_CLOSE_DESK_DEPLOYMENT_2026-09-04.md`

Firmware, display assets, wake word, audio, bootloader, partition table, merged
images, OAuth handlers, order paths, and `exec_server.py` are not in scope.

## Editorial contract

1. `market_phase` is the sole phase switch; gateway transport freshness remains
   a separate status.
2. The lead market card uses phase-specific language: `CLOSING DESK`,
   `NIGHT WATCH`, or `WEEKEND BRIEF`, plus the real verified quote-session date.
3. A post-close portfolio card may show only direct `net_liq`, `cash_pct`, and
   `day_pl_total` facts and uses the verified session timestamp as provenance.
4. EOD and closed boards rename intraday groups to `CLOSE MOVERS`,
   `CARRY SIGNALS`, and `CLOSE EXTREMES`; weekend boards use last-session
   language.
5. Urgent fills/risk interruptions still preempt the editorial sequence.
6. News, Council, and Slack remain distinct sourced categories and are not
   displaced by repeated quote cards.
7. Fifteen device cards remain a hard capacity, not a content target.
8. Existing device JSON remains backward-compatible; no firmware flash is
   required.

## Verification

- Unit fixtures cover `eod`, weekday `closed`, weekend, and unchanged intraday.
- Friday evening remains `CLOSING DESK`/`NIGHT WATCH`, not weekend, until the
  canonical phase changes.
- Closed cards use the newest verified quote session date, not refresh time.
- Expired events are excluded; retained events keep bounded expiries.
- Gateway output remains within 15 cards and preserves unique categories.
- Full APEX and gateway test suites pass.
- A production snapshot shows the appropriate current phase and the device
  fetches it without panic, reboot, or repeated error audio.

## Deployment and rollback

Build both changes on isolated branches. Back up each production file before
replacement. Deploy the producer first, then a tested gateway revision, and
confirm the authenticated feed before promoting traffic. Rollback is the prior
producer backup plus the previous Cloud Run revision. No device write is part
of this change.
