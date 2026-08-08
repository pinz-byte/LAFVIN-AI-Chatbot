from __future__ import annotations

import asyncio
import hmac
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from websockets.asyncio.client import connect as connect_websocket
from websockets.exceptions import ConnectionClosed

from .config import GatewaySettings
from .security import TokenError, issue_session_token, verify_session_token
from .storage import GatewayStore


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


def create_app(settings: GatewaySettings | None = None, store: GatewayStore | None = None) -> FastAPI:
    settings = settings or GatewaySettings.from_env()
    store = store or GatewayStore(settings.database_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        store.close()

    app = FastAPI(title="Symbios Voice Gateway", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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
            token = issue_session_token(
                settings.jwt_secret,
                device_id=device_id,
                client_id=client_id,
                ttl_seconds=settings.session_ttl_seconds,
            )
            return {
                "server_time": {"timestamp": int(time.time() * 1000), "timezone_offset": 0},
                "websocket": {
                    "url": settings.websocket_url,
                    "token": token,
                    "version": 1,
                },
            }

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
        device_id_header: str | None = Header(default=None, alias="Device-Id"),
        client_id_header: str | None = Header(default=None, alias="Client-Id"),
    ) -> dict[str, dict[str, str]]:
        device_id = _identifier(device_id_header, "Device-Id")
        client_id = _identifier(client_id_header, "Client-Id")
        token = store.activate(device_id, client_id)
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
    async def voice_proxy(websocket: WebSocket) -> None:
        authorization = websocket.headers.get("authorization")
        token = _bearer_credential(authorization)
        if token is None:
            await websocket.close(code=4401, reason="missing bearer token")
            return
        try:
            claims = verify_session_token(settings.jwt_secret, token)
        except TokenError:
            await websocket.close(code=4401, reason="invalid bearer token")
            return

        device_id = websocket.headers.get("device-id")
        client_id = websocket.headers.get("client-id")
        if claims["sub"] != device_id or claims["client_id"] != client_id:
            await websocket.close(code=4403, reason="device identity mismatch")
            return

        upstream_headers = {
            "Device-Id": device_id,
            "Client-Id": client_id,
            "Protocol-Version": websocket.headers.get("protocol-version", "1"),
        }
        if settings.upstream_authorization:
            upstream_headers["Authorization"] = settings.upstream_authorization

        try:
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
        except (OSError, ConnectionClosed, WebSocketDisconnect):
            if websocket.client_state.name == "CONNECTED":
                await websocket.close(code=1011, reason="voice backend unavailable")

    return app
