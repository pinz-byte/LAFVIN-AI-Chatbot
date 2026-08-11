# Symbios voice gateway

This service is the authenticated boundary between a Symbios Terminal and
Vertex AI Gemini Live. It decodes the device's 16 kHz Xiaozhi Opus stream to
PCM for the server-to-server Live WebSocket, then converts 24 kHz response PCM
back to the device's 60 ms Opus frames. The ESP32 receives no provider key.

## Authentication flow

1. An unenrolled device posts its hardware manifest to `/xiaozhi/ota/` and
   receives a six-digit activation code.
2. An operator approves that code through the admin endpoint. The admin token
   is held by the server/operator, not by the device.
3. The device returns the random enrollment challenge while polling
   `/xiaozhi/ota/activate` and receives a random, device-scoped token. The
   challenge prevents a client with only a known device ID from racing an
   approved activation. The gateway stores only the token's SHA-256 hash; the
   ESP32 stores the token in NVS.
4. Authenticated bootstrap exchanges that device token for a five-minute
   WebSocket JWT bound to both `Device-Id` and `Client-Id`.
5. The gateway verifies the JWT, opens a service-account-authenticated Vertex Live
   session, and bridges Xiaozhi hello/listen/STT/TTS/audio events.

## Authenticated Symbios context

The optional project-awareness bridge exposes exactly two read-only Vertex
functions: an operational brief and a focused Memory Bridge search. Configure
both variables together:

```sh
SYMBIOS_CONTEXT_BASE_URL=https://symbios-query-server.example.com
SYMBIOS_CONTEXT_TOKEN=<Secret Manager reference at deploy time>
```

`SYMBIOS_CONTEXT_TOKEN` is a gateway-only bearer. It must be injected from a
server-side secret store and must never be placed in an ESP32 build setting,
bootstrap response, log, or device NVS. The gateway deliberately does not
expose the query server's session-ingest endpoint or any other write action.
When the variables are absent, no context tools are declared to Vertex.

The configured service must implement the canonical Symbios Memory Bridge
`POST /brief` and `POST /query` contracts. This integration extends that
retrieval boundary; it does not read repositories, Notion, Pinecone, APEX, or
broker accounts through parallel paths.

TLS is mandatory in production. The gateway intentionally has no permissive
or anonymous voice mode.

## Read-only APEX terminal feed

`PUT /api/v1/apex/snapshot` accepts a maximum 4 KiB allow-listed portfolio
summary using a dedicated server-side `SYMBIOS_APEX_INGEST_TOKEN`. The gateway
keeps only the newest sanitized snapshot in an isolated SQLite table or
Firestore collection. Replayed or older snapshots are rejected.

`GET /api/v1/terminal/feed` requires the enrolled device's existing `Device`
credential. It adds a server-fetched public Coinbase `BTC-USD` quote and labels
the APEX data `LIVE`, `DELAYED`, `STALE`, or `OFFLINE` from its direct source
timestamp. Account identifiers, quantities, cost basis, thesis text, broker
credentials, and the ingest token are never accepted by the terminal contract.
Coinbase failure leaves the APEX feed available with `btc: null`.

The APEX exporter and gateway ingest are disabled until the dedicated token and
HTTPS URL are configured on their respective servers. These settings are not
returned by bootstrap and must not be compiled into firmware.

## Production deployment

The reviewed deployment is Cloud Run revision
`symbios-voice-gateway-00005-tk4` at
`https://symbios-voice-gateway-hiz3vgfrfa-uc.a.run.app`. Its `/health` route,
enrollment flow, rejection of invalid admin credentials and mismatched device
challenges, activation, device-token authentication, short-lived WebSocket JWT,
and Vertex Live setup handshake have been exercised against production.
Synthetic validation records were deleted afterward.

Production uses Firestore for activation/device records so Cloud Run restarts
and horizontal scaling do not lose enrollment. `SYMBIOS_JWT_SECRET` and
`SYMBIOS_ADMIN_TOKEN` are injected from Secret Manager and are never returned
by any gateway response. Vertex uses the Cloud Run service account and does not
require an API key.

## Run locally

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
# Export reviewed values from .env with your preferred secret manager.
uvicorn symbios_gateway.app:create_app --factory --host 127.0.0.1 --port 8080
```

Approve a code shown on the LAFVIN display:

```sh
curl -X POST \
  -H "Authorization: Bearer $SYMBIOS_ADMIN_TOKEN" \
  "https://voice.example.com/admin/enroll/123456"
```

For compatibility testing, `SYMBIOS_VOICE_PROVIDER=proxy` still supports a
reviewed Xiaozhi-compatible upstream configured with
`SYMBIOS_UPSTREAM_WS_URL`; production is configured for `vertex_live`. An
`openai_realtime` provider remains available but requires a funded server-side
`OPENAI_API_KEY`.

`SYMBIOS_VOICE_PROVIDER=ram_loopback` is an explicit-consent diagnostic only.
It never opens a provider connection. It keeps at most 20 seconds of one
gateway-decoded turn in volatile process memory, applies the same reviewed
input gain, returns that waveform to the authenticated device in real time,
and zeroes the buffer after playback, abort, or disconnect. It logs aggregate
levels and byte counts only—never PCM or a transcript—and must be switched
back to `vertex_live` after the physical listening test.

## Test

```sh
pytest
```
