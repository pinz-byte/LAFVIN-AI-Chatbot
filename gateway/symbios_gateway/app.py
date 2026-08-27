from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from websockets.asyncio.client import connect as connect_websocket
from websockets.exceptions import ConnectionClosed

from .config import GatewaySettings
from .apex_feed import ApexFeedError, build_terminal_feed, parse_apex_snapshot
from .loopback import RamLoopbackBridgeError, run_ram_loopback_bridge
from .market import CoinbaseMarketClient, MarketDataError
from .realtime import RealtimeBridgeError, run_openai_realtime_bridge
from .security import TokenError, issue_session_token, verify_session_token
from .storage import FirestoreGatewayStore, GatewayStore, Store
from .vertex import VertexLiveBridgeError, run_vertex_live_bridge


logger = logging.getLogger("uvicorn.error")


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9:._-]{3,128}$")


def _identifier(value: str | None, name: str) -> str:
    if value is None or IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"missing or invalid {name}")
    return value


def _device_credential(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, credential = authorization.partition(" ")
    if not separator or scheme.lower() != "device" or not credential:
        return None
    return credential


def _bearer_credential(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, credential = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not credential:
        return None
    return credential


def _create_store(settings: GatewaySettings) -> Store:
    if settings.store_backend == "firestore":
        assert settings.gcp_project is not None
        return FirestoreGatewayStore(settings.gcp_project)
    return GatewayStore(settings.database_path)


def create_app(
    settings: GatewaySettings | None = None,
    store: Store | None = None,
    market_client: CoinbaseMarketClient | None = None,
) -> FastAPI:
    settings = settings or GatewaySettings.from_env()
    store = store or _create_store(settings)
    market_client = market_client or CoinbaseMarketClient(
        settings.coinbase_base_url, settings.market_timeout_seconds
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        store.close()

    app = FastAPI(title="Symbios Voice Gateway", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store

    @app.get("/")
    @app.get("/health")
    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.put("/api/v1/apex/snapshot", status_code=status.HTTP_202_ACCEPTED)
    async def ingest_apex_snapshot(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        if not settings.apex_ingest_enabled:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "APEX ingest is disabled")
        credential = _bearer_credential(authorization)
        assert settings.apex_ingest_token is not None
        if credential is None or not hmac.compare_digest(
            credential, settings.apex_ingest_token
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid ingest credential")
        body = await request.body()
        if len(body) > 4096:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "feed too large")
        received = datetime.now(timezone.utc)
        try:
            snapshot, source_at = parse_apex_snapshot(body, now=received)
        except ApexFeedError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        snapshot["received_at"] = received.isoformat()
        encoded = json.dumps(snapshot, allow_nan=False, separators=(",", ":"))
        if not store.save_terminal_snapshot(
            encoded,
            source_at=source_at,
            received_at=int(received.timestamp()),
        ):
            raise HTTPException(status.HTTP_409_CONFLICT, "snapshot is not newer")
        return {"accepted": True, "generated_at": snapshot["generated_at"]}

    @app.get("/api/v1/terminal/feed")
    async def terminal_feed(
        response: Response,
        authorization: str | None = Header(default=None),
        device_id_header: str | None = Header(default=None, alias="Device-Id"),
        client_id_header: str | None = Header(default=None, alias="Client-Id"),
    ) -> dict[str, object]:
        device_id = _identifier(device_id_header, "Device-Id")
        client_id = _identifier(client_id_header, "Client-Id")
        credential = _device_credential(authorization)
        if credential is None or not store.authenticate(device_id, client_id, credential):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid device credential")
        btc = None
        try:
            btc = await market_client.get_btc()
        except (MarketDataError, OSError):
            logger.warning("BTC terminal quote unavailable")
        response.headers["Cache-Control"] = "no-store"
        return build_terminal_feed(store.load_terminal_snapshot(), btc=btc)

    @app.post("/xiaozhi/ota/")
    async def bootstrap(
        request: Request,
        authorization: str | None = Header(default=None),
        device_id_header: str | None = Header(default=None, alias="Device-Id"),
        client_id_header: str | None = Header(default=None, alias="Client-Id"),
    ) -> dict[str, object]:
        # Consume and size-limit the hardware manifest even though routing uses
        # authenticated headers. This prevents an unread oversized request body.
        body = await request.body()
        if len(body) > 64 * 1024:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "manifest too large")

        device_id = _identifier(device_id_header, "Device-Id")
        client_id = _identifier(client_id_header, "Client-Id")
        credential = _device_credential(authorization)
        if credential and store.authenticate(device_id, client_id, credential):
            response: dict[str, object] = {
                "server_time": {"timestamp": int(time.time() * 1000), "timezone_offset": 0},
            }
            if settings.display_only:
                return response
            token = issue_session_token(
                settings.jwt_secret,
                device_id=device_id,
                client_id=client_id,
                ttl_seconds=settings.session_ttl_seconds,
            )
            response["websocket"] = {
                "url": settings.websocket_url,
                "token": token,
                "version": 1,
            }
            return response

        enrollment = store.get_or_create_enrollment(
            device_id,
            client_id,
            ttl_seconds=settings.activation_ttl_seconds,
        )
        return {
            "server_time": {"timestamp": int(time.time() * 1000), "timezone_offset": 0},
            "activation": {
                "code": enrollment.code,
                "challenge": enrollment.challenge,
                "message": "Approve this code in the Symbios gateway before voice access is enabled.",
                "timeout_ms": settings.activation_ttl_seconds * 1000,
            },
        }

    @app.post("/xiaozhi/ota/activate")
    async def activate(
        request: Request,
        device_id_header: str | None = Header(default=None, alias="Device-Id"),
        client_id_header: str | None = Header(default=None, alias="Client-Id"),
    ) -> dict[str, dict[str, str]]:
        device_id = _identifier(device_id_header, "Device-Id")
        client_id = _identifier(client_id_header, "Client-Id")
        body = await request.body()
        if len(body) > 4 * 1024:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "activation payload too large")
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid activation payload")
        challenge = payload.get("challenge") if isinstance(payload, dict) else None
        if not isinstance(challenge, str) or not 16 <= len(challenge) <= 256:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid activation challenge")
        token = store.activate(device_id, client_id, challenge)
        if token is None:
            raise HTTPException(status.HTTP_202_ACCEPTED, "activation pending")
        return {"symbios": {"device_token": token}}

    @app.post("/admin/enroll/{code}")
    async def approve_enrollment(
        code: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        credential = _bearer_credential(authorization)
        if credential is None or not hmac.compare_digest(credential, settings.admin_token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid admin credential")
        if not re.fullmatch(r"\d{6}", code):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid enrollment code")
        enrollment = store.approve(code)
        if enrollment is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "enrollment code not found or expired")
        return {
            "approved": True,
            "device_id": enrollment.device_id,
            "client_id": enrollment.client_id,
            "expires_at": enrollment.expires_at,
        }

    @app.websocket("/xiaozhi/v1/")
    async def voice_gateway(websocket: WebSocket) -> None:
        if settings.display_only:
            await websocket.close(code=4404, reason="display-only terminal")
            return
        authorization = websocket.headers.get("authorization")
        token = _bearer_credential(authorization)
        if token is None:
            await websocket.close(code=4401, reason="missing bearer token")
            return
        try:
            claims = verify_session_token(settings.jwt_secret, token)
        except TokenError as exc:
            logger.info("Rejected voice session bearer: %s", exc)
            await websocket.close(code=4401, reason="invalid bearer token")
            return

        device_id = websocket.headers.get("device-id")
        client_id = websocket.headers.get("client-id")
        if claims["sub"] != device_id or claims["client_id"] != client_id:
            await websocket.close(code=4403, reason="device identity mismatch")
            return

        try:
            if settings.voice_provider in {
                "openai_realtime",
                "vertex_live",
                "ram_loopback",
            }:
                await websocket.accept()
                try:
                    raw_hello = await asyncio.wait_for(websocket.receive_text(), timeout=8)
                    hello = json.loads(raw_hello)
                    protocol_version = int(hello.get("version", 1))
                    if hello.get("type") != "hello" or protocol_version not in {1, 2, 3}:
                        raise ValueError("invalid Xiaozhi hello")
                except (asyncio.TimeoutError, json.JSONDecodeError, TypeError, ValueError):
                    await websocket.close(code=4400, reason="invalid Xiaozhi hello")
                    return
                if settings.voice_provider == "ram_loopback":
                    await run_ram_loopback_bridge(
                        websocket,
                        settings,
                        protocol_version=protocol_version,
                    )
                elif settings.voice_provider == "vertex_live":
                    await run_vertex_live_bridge(
                        websocket,
                        settings,
                        protocol_version=protocol_version,
                    )
                else:
                    await run_openai_realtime_bridge(
                        websocket,
                        settings,
                        device_id=device_id,
                        client_id=client_id,
                        protocol_version=protocol_version,
                    )
                return

            upstream_headers = {
                "Device-Id": device_id,
                "Client-Id": client_id,
                "Protocol-Version": websocket.headers.get("protocol-version", "1"),
            }
            if settings.upstream_authorization:
                upstream_headers["Authorization"] = settings.upstream_authorization
            assert settings.upstream_ws_url is not None
            async with connect_websocket(
                settings.upstream_ws_url,
                additional_headers=upstream_headers,
                max_size=2 * 1024 * 1024,
                ping_interval=20,
                ping_timeout=20,
            ) as upstream:
                await websocket.accept()

                async def device_to_upstream() -> None:
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        if message.get("text") is not None:
                            await upstream.send(message["text"])
                        elif message.get("bytes") is not None:
                            await upstream.send(message["bytes"])

                async def upstream_to_device() -> None:
                    async for message in upstream:
                        if isinstance(message, str):
                            await websocket.send_text(message)
                        else:
                            await websocket.send_bytes(message)

                tasks = {
                    asyncio.create_task(device_to_upstream()),
                    asyncio.create_task(upstream_to_device()),
                }
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    task.result()
        except (
            OSError,
            ConnectionClosed,
            WebSocketDisconnect,
            RealtimeBridgeError,
            VertexLiveBridgeError,
            RamLoopbackBridgeError,
        ):
            if websocket.client_state.name == "CONNECTED":
                await websocket.close(code=1011, reason="voice backend unavailable")

    return app
