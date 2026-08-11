# SYMBIOS Terminal APEX ticker review

Date: 2026-08-10 (America/Lima)

Status: compile-only review candidate. The gateway has not been deployed, the
APEX exporter has not been enabled, and this firmware has not been flashed.

## Device recovery

The prior black screen followed an interrupted application-only write. The
exact previously approved hands-free application was rewritten at `0x20000`
and independently verified. Its boot log initializes the ST7789 LCD, Emote
assets, Wi-Fi, `wn9_hiesp` wake model, mono ES7210 input, and authenticated
Symbios gateway without panic or rollback. No assets, NVS, OTA metadata, PHY,
bootloader, or partition-table region was written during recovery.

Restored application SHA-256:
`abf5e60857fbc68e5f6e51b66e4c4a3cb73d606b47bed8e2ca8928ab9b105410`.

## Ticker candidate

The candidate preserves the accepted face/assets and rotates compact text
pages only while the application state is idle:

- direct Coinbase `BTC-USD` price and 24-hour change;
- APEX net liquidation value, cash percentage, position count, and direct risk
  count;
- up to six direct APEX position/watchlist prices, two per page;
- visible `LIVE`, `DELAYED`, `STALE`, or `OFFLINE` state.

Listening, speaking, connecting, activation, errors, and notifications take
display priority. Wake-word audio, automatic silence submission, and the DOWN
button fallback are unchanged. Fetching runs in a separate priority-1 task,
only begins while idle, is bounded to 4 KiB, and never reboots or disables voice
when market data is unavailable.

The device sends its existing enrolled `Device` credential to the Symbios
gateway. It contains no Coinbase, APEX, broker, Vertex, OpenAI, admin, or ingest
credential. The gateway accepts only a sanitized APEX summary and keeps only
the newest snapshot.

## Compile-only artifact

- ESP-IDF: 5.5.2 container
- target: ESP32-S3
- image mode/frequency/flash size: DIO / 80 MHz / 16 MB
- application size: 2,830,704 bytes
- application partition headroom: 1,298,064 bytes (31%)
- application file:
  `firmware-review/ticker-review-20260810/xiaozhi.bin`
- application SHA-256:
  `630a8ab34c2183df9b08f2f4001a9366f1bd29c6a4d63dd72cb1babfa4641216`
- ESP image checksum: valid
- ESP validation hash: valid
- compiled public feed endpoint:
  `https://symbios-voice-gateway-hiz3vgfrfa-uc.a.run.app/api/v1/terminal/feed`

Binary inspection finds the reviewed bootstrap/feed origins and no API key,
GitHub token, bearer token, APEX ingest variable, or common provider-key
signature. The application-only artifact is the review target; the generated
merged image is not approved for use because it also contains bootloader,
partition, OTA-data, and assets regions.

## Validation

- Gateway: 30 passed, 1 optional existing skip.
- APEX exporter: 6 passed.
- APEX builder gate after implementation: 0 FAIL, 5 N/A.
- Firmware: full `lafvin-aichatbot-symbios-terminal` compile and link passed in
  `espressif/idf:v5.5.2`.
- Full unrelated APEX suite: not executed because the current shell lacks the
  repository runtime dependencies (`psycopg2` is the first collection error).
  The new focused exporter tests do not require or bypass those dependencies.

The corrected pre-flash audit no longer mistakes ignored build output for a
committed secret. It intentionally remains blocked because protected display/
audio paths differ from the vendor baseline and a new physical display/wake/
audio smoke exception has not been acknowledged.

## Review boundary and sequence

Before a live ticker can appear:

1. review and deploy the gateway routes with a dedicated Secret Manager ingest
   token;
2. review and enable the APEX post-snapshot exporter on the M1 using the same
   dedicated token and HTTPS URL;
3. verify only allow-listed, timestamped data reaches the gateway;
4. obtain a separate explicit approval for the exact application SHA-256 and
   protected-file/smoke exception;
5. if approved, write only the application at `0x20000`; do not write assets.

No step in this review authorizes orders, Schwab writes, Council actions,
`exec_server.py`, a new APEX daemon, a gateway deployment, an APEX deployment,
or a device flash.
