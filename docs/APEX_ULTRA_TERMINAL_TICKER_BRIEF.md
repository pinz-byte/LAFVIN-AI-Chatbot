# APEX Ultra → SYMBIOS Terminal ticker brief

Status: review-candidate implementation authorized by the user's APEX Ultra
ticker request. No APEX deployment, gateway deployment, or device flash is
authorized by this brief.

## Objective

Turn the 320×240 SYMBIOS Terminal into a read-only, visibly timestamped market
and portfolio ticker while preserving wake-word, mono-microphone, audio,
speaker, voice gateway, and manual-button fallback behavior.

The screen must distinguish direct market observations from APEX-generated
state. It must never execute orders, invoke Council, infer a live position,
expose a broker credential, or represent a stale snapshot as current.

## Truth sources

- **Stocks and portfolio:** the canonical `apex-ultra/snapshot.json` produced by
  the M1 loop from its existing Schwab read path. The exporter reads the file
  only after validating its schema and `generated_at`; it does not query or
  mutate the broker.
- **Bitcoin:** Coinbase Exchange public `BTC-USD` ticker and stats endpoints,
  fetched by the Symbios gateway. The ESP32 never contacts Coinbase directly.
- **Device identity:** the already enrolled Symbios device credential. No new
  market, APEX, broker, or cloud secret is stored in firmware or NVS.

## Phase 1 display

The current LAFVIN build uses the Emote renderer. Phase 1 therefore preserves
the accepted assets and face animation and adds a compact rotating text ribbon
only while idle:

1. `BTC $price change% source-age`
2. up to three APEX stock rows selected from direct snapshot position/watchlist
   values, never estimates;
3. `APEX net-liq cash% positions risk source-age`;
4. an explicit `LIVE`, `DELAYED`, `STALE`, or `OFFLINE` badge.

Listening, speaking, alerts, and activation always take visual priority over
the ticker. DOWN remains the manual voice fallback. Phase 2 native cards or
charts require a separate display/assets candidate and physical review.

## Data contract

The gateway-to-device payload is capped at 4 KiB and versioned. It permits only:

- `schema_version`;
- `generated_at` and `received_at` RFC 3339 timestamps;
- `status` in `LIVE|DELAYED|STALE|OFFLINE`;
- BTC `symbol`, `price`, `change_24h_pct`, `source_at`;
- APEX `net_liq`, `cash_pct`, `position_count`, `risk_count`, `source_at`;
- no more than six rows containing `symbol`, `price`, optional `change_pct`,
  `kind`, and `source_at`.

Unknown fields are ignored; unknown enum values, non-finite numbers, negative
prices, oversized strings, invalid timestamps, and payloads over the cap are
rejected. Portfolio data older than 10 minutes is `STALE`; absence is
`OFFLINE`. Market-session closure is distinct from stale data.

## Authentication and transport

1. The existing five-minute APEX loop calls a small, non-blocking post-snapshot
   exporter. The exporter sanitizes the in-memory snapshot and pushes the
   bounded payload to the Symbios gateway over HTTPS with a dedicated ingest
   bearer loaded from the existing M1 secret file at process start. Export is
   disabled unless both endpoint and bearer are configured.
2. The gateway validates, stores only the latest sanitized snapshot, and never
   accepts orders, broker tokens, arbitrary files, or remote render markup.
3. The enrolled ESP32 requests the compact ticker payload using its existing
   device authentication. Provider and ingest credentials stay server-side.
4. Logs contain symbols, timestamps, status, and validation failures, but not
   bearer tokens, account identifiers, quantities, or full position records.

## Audit scope

### `pinz-byte/apex-ultra`

- `APEX_XX_SYMBIOS_TERMINAL_EXPORT_BRIEF_2026-08-10.md` (new, copy of the
  ratified execution scope)
- `symbios_terminal_export.py` (new)
- `tests/test_symbios_terminal_export.py` (new)
- `loop.py` (one guarded call immediately after a successful snapshot
  write; export errors are warning-only and cannot block the canonical loop)

No edits to `dashboard.py`, `schwab_oauth.py`, Council code, `exec_server.py`,
signal plans, orders, or broker clients are in scope. No additional agent,
daemon, or LaunchAgent is introduced: APEX remains one loop and one dashboard.

### Symbios gateway

- `gateway/symbios_gateway/apex_feed.py` (new)
- `gateway/symbios_gateway/market.py` (new)
- `gateway/symbios_gateway/app.py`
- `gateway/symbios_gateway/config.py`
- `gateway/tests/test_terminal_feed.py` (new)
- `gateway/.env.example`
- `gateway/README.md`

### ESP32 firmware

- `xiaozhi-esp32-main/main/terminal_feed.h` (new)
- `xiaozhi-esp32-main/main/terminal_feed.cc` (new)
- `xiaozhi-esp32-main/main/application.cc`
- `xiaozhi-esp32-main/main/display/display.h`
- `xiaozhi-esp32-main/main/display/emote_display.h`
- `xiaozhi-esp32-main/main/display/emote_display.cc`
- `xiaozhi-esp32-main/main/Kconfig.projbuild`
- `xiaozhi-esp32-main/main/CMakeLists.txt`
- `xiaozhi-esp32-main/main/boards/lafvin-aichatbot/config.json`
- `xiaozhi-esp32-main/main/boards/lafvin-aichatbot/config.symbios.local.json`
- `tools/configure_symbios_firmware.py`
- `tools/preflash_audit.py` (exclude ignored build artifacts from the source
  secret scan; do not weaken protected-path or physical-smoke gates)

## Acceptance gates

- APEX builder gate: all ten failure-pattern checks PASS or are explicitly N/A
  for the exact files above; active brief preflight also passes.
- Exporter tests prove schema allow-listing, redaction, freshness calculation,
  network timeout, retry bounds, and fail-closed behavior.
- The APEX export hook is off by default, has a hard timeout, performs no
  retries inside the five-minute loop, and cannot change the loop exit code.
- Gateway tests prove dedicated ingest authentication, size limits, replay/
  timestamp handling, Firestore isolation, Coinbase timeout/failure behavior,
  and device authorization without credential disclosure.
- Stock/position output is copied only from the direct canonical snapshot; an
  unknown value is `PENDING`, never calculated or inferred.
- Firmware parser fuzz/unit tests cover bounds and malformed payloads. Stock and
  APEX refresh failures leave voice functions available and show `STALE` or
  `OFFLINE` rather than rebooting.
- Stock LAFVIN and Symbios ESP-IDF 5.5.2 builds pass. Binary inspection finds
  the reviewed gateway origin and no credential signatures.
- A RAM-only or review firmware build demonstrates ticker/voice visual
  priority on the physical 320×240 screen.
- Any new firmware or assets write requires a separately presented exact hash
  and explicit flash approval.
