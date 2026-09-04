# Adaptive Symbios Terminal deployment

Date: 2026-09-04 (America/Lima)
Status: deployed and live
Mode: authenticated, read-only display
Device write: none

## Result

The Symbios display now changes editorial purpose across the US market day
without changing firmware or creating a second data path:

| New York window | Terminal mode | Primary purpose |
|---|---|---|
| 06:00 through market close | `APEX LIVE` | Live context, signals, movers, extremes, news |
| 16:00–17:59 | `CLOSING DESK` | Close, portfolio, movers, carry signals |
| 18:00–20:59 | `PORTFOLIO AUTOPSY` | Portfolio result, close attribution, extremes |
| 21:00–22:59 | `SYMBIOS COMMAND` | Council, Slack briefing, news, carried decisions |
| 23:00–05:59 | `QUIET INTELLIGENCE` | Four-card maximum; highest-value facts only |
| Closed day, 08:00–17:59 | `WEEKEND REVIEW` | Last session, portfolio, catalysts, Council |

A fresh broker-confirmed `TRADE` or `RISK` event remains an absolute-priority
interrupt in every mode. Missing categories remain absent; the selector does
not fabricate filler or revive expired events.

## Data and trust boundary

The modes reuse the existing allow-listed APEX snapshot, authenticated device
request, and public BTC quote. New York wall time selects the editorial mode;
the market phase remains the producer-supplied APEX fact. Closed-session dates
still come from the latest verified quote timestamp.

No project repository, Notion page, broker account identifier, position
quantity, order path, API key, or secret was added to the device contract.
`SYMBIOS COMMAND` currently means the verified Council, Slack/HERMES, market
news, signals, and portfolio facts already present in the APEX feed. General
project-task ingestion remains outside this deployment.

## Source records

### APEX post-close foundation

- Repository: `pinz-byte/apex-ultra`
- Source branch: `fix/symbios-post-close-desk-20260904`
- Source commit: `647bbbed915dda9d8bb6ef81785d333684514086`
- M1 production commit: `2c1a61f` (`feat(symbios): add post-close desk modes`)
- Pre-deploy backup:
  `/Users/usuario/Documents/Claude/Projects/apex-ultra/deployment-backups/symbios-post-close-desk-20260904T1500Z`
- Production exporter SHA-256:
  `d8597b783ac72c073f5c49f98834a10421c0c17f50bcc9bf3593ac2b59f3a0cb`
- Production test SHA-256:
  `c884c1dbcf63aed14d780f36079505ec8819c1fed20c1bd7cab31ab514f924e6`
- Canonical APEX suite: 324 passed.

### Symbios gateway

- Repository: `pinz-byte/LAFVIN-AI-Chatbot`
- Branch: `fix/symbios-post-close-desk-20260904`
- Post-close source commit: `1b035e0`
- Adaptive source commit:
  `8154b22e47d1f6908b5d845dafd33bc180fb4146`
- Post-close Cloud Run revision: `symbios-voice-gateway-00051-yul`
- Post-close digest:
  `sha256:a10faf98f788f5f31124be5486cdcf1cfa61202731bf1a3a5e0876be2aba416f`
- Adaptive Cloud Run revision: `symbios-voice-gateway-00053-wap`
- Adaptive digest:
  `sha256:57f32f386beba7737c022a8f2aa0576bd1713f0cfe4a90fd243840ac215e0318`
- Traffic: 100% to the adaptive revision.
- Rollback target: `symbios-voice-gateway-00051-yul` with tag
  `post-close-desk`.

## Verification

- APEX Builder Gate: 0 failures; all non-applicable broker/execution checks
  recorded before implementation. `exec_server.py` and port 7701 were not
  touched.
- Focused adaptive tests: 21 passed.
- Complete gateway collection: 46 tests; 45 passed and one existing optional
  integration test skipped.
- Python compile check: passed.
- Mode simulation: 7–8 cards for active modes and exactly 4 for Quiet; largest
  observed encoded payload was 2,615 bytes against the 8,192-byte limit.
- Tagged revision health: HTTP 200 before promotion.
- Tagged unauthenticated terminal request: HTTP 400, as expected for missing
  device identity headers.
- Production health after promotion: HTTP 200.
- Enrolled device production request: HTTP 200 on revision `00053-wap` at
  `2026-09-04T17:06:49Z`. After the first new APEX PUT, the next enrolled
  device poll also returned HTTP 200 at `2026-09-04T17:09:50Z`, confirming
  producer-to-gateway-to-device continuity.
- Actual APEX snapshot simulation at `2026-09-04T17:03:54Z`: `intraday`,
  `apex_live`, `LIVE`, seven event cards, 3,665 encoded bytes. The live queue
  began with the active risk interruption and then showed APEX LIVE, signals,
  movers, NVDA news, HERMES, and Council.
- M1 launch agent `com.apex.ultra.loop`: run counter 63, last exit 0 at the
  verification cut. The first unassisted post-promotion cycle completed at
  `2026-09-04T17:09:03Z`; Cloud Run revision `00053-wap` accepted its
  authenticated PUT with HTTP 202.

## Rollback

Gateway rollback requires only moving Cloud Run traffic back to revision
`symbios-voice-gateway-00051-yul`. No device rollback is required because this
deployment wrote neither application nor assets partitions. The APEX producer
rollback files remain in the dated M1 backup above.
