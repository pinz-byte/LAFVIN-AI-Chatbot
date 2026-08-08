# Symbios voice gateway

This service is the authenticated boundary between a Symbios Terminal and a
Xiaozhi-protocol-compatible voice backend. The ESP32 never receives the
upstream provider credential.

## Authentication flow

1. An unenrolled device posts its hardware manifest to `/xiaozhi/ota/` and
   receives a six-digit activation code.
2. An operator approves that code through the admin endpoint. The admin token
   is held by the server/operator, not by the device.
3. The device polls `/xiaozhi/ota/activate` and receives a random,
   device-scoped token. The gateway stores only its SHA-256 hash; the ESP32
   stores the token in NVS.
4. Authenticated bootstrap exchanges that device token for a five-minute
   WebSocket JWT bound to both `Device-Id` and `Client-Id`.
5. The gateway verifies the JWT and proxies Xiaozhi text and Opus binary frames
   to the configured backend, adding the server-side upstream credential.

TLS is mandatory in production. The gateway intentionally has no permissive
or anonymous voice mode.

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

The upstream endpoint must implement the Xiaozhi WebSocket protocol, including
the hello, listen, STT, LLM, TTS, MCP, and Opus-frame behavior expected by the
firmware. `SYMBIOS_UPSTREAM_AUTHORIZATION` is optional and is never returned by
any gateway response.

## Test

```sh
pytest
```
