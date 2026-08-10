import asyncio
import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from symbios_gateway.app import create_app
from symbios_gateway.config import GatewaySettings
from symbios_gateway.loopback import _zero_and_clear, run_ram_loopback_bridge
from symbios_gateway.security import TokenError, verify_session_token
from symbios_gateway.storage import GatewayStore
from symbios_gateway.vertex import (
    VertexBridgeState,
    _handle_vertex_listen_event,
    _record_vertex_input_pcm,
    _vertex_input_mean_abs,
    _vertex_setup,
)


DEVICE_HEADERS = {
    "Device-Id": "aa:bb:cc:dd:ee:ff",
    "Client-Id": "123e4567-e89b-12d3-a456-426614174000",
}


@pytest.fixture
def settings(tmp_path: Path) -> GatewaySettings:
    return GatewaySettings(
        public_base_url="http://gateway.test",
        jwt_secret="j" * 32,
        admin_token="a" * 32,
        upstream_ws_url="ws://upstream.test/xiaozhi/v1/",
        voice_provider="proxy",
        database_path=tmp_path / "gateway.sqlite3",
        allow_insecure_urls=True,
    )


def test_enrollment_bootstrap_and_short_lived_session(settings: GatewaySettings) -> None:
    store = GatewayStore(settings.database_path)
    with TestClient(create_app(settings, store)) as client:
        assert client.get("/health").json() == {"status": "ok"}

        bootstrap = client.post("/xiaozhi/ota/", headers=DEVICE_HEADERS, json={"version": 2})
        assert bootstrap.status_code == 200
        activation = bootstrap.json()["activation"]
        assert len(activation["code"]) == 6
        assert "websocket" not in bootstrap.json()

        pending = client.post(
            "/xiaozhi/ota/activate",
            headers=DEVICE_HEADERS,
            json={"challenge": activation["challenge"]},
        )
        assert pending.status_code == 202

        rejected = client.post(
            f"/admin/enroll/{activation['code']}",
            headers={"Authorization": "Bearer wrong"},
        )
        assert rejected.status_code == 401

        approved = client.post(
            f"/admin/enroll/{activation['code']}",
            headers={"Authorization": f"Bearer {settings.admin_token}"},
        )
        assert approved.status_code == 200
        assert approved.json()["device_id"] == DEVICE_HEADERS["Device-Id"]

        wrong_challenge = client.post(
            "/xiaozhi/ota/activate",
            headers=DEVICE_HEADERS,
            json={"challenge": "wrong-challenge-value"},
        )
        assert wrong_challenge.status_code == 202

        activated = client.post(
            "/xiaozhi/ota/activate",
            headers=DEVICE_HEADERS,
            json={"challenge": activation["challenge"]},
        )
        assert activated.status_code == 200
        device_token = activated.json()["symbios"]["device_token"]
        assert len(device_token) >= 32

        authenticated_headers = {
            **DEVICE_HEADERS,
            "Authorization": f"Device {device_token}",
        }
        session = client.post("/xiaozhi/ota/", headers=authenticated_headers, json={"version": 2})
        assert session.status_code == 200
        websocket = session.json()["websocket"]
        assert websocket["url"] == "ws://gateway.test/xiaozhi/v1/"
        claims = verify_session_token(settings.jwt_secret, websocket["token"])
        assert claims["sub"] == DEVICE_HEADERS["Device-Id"]
        assert claims["client_id"] == DEVICE_HEADERS["Client-Id"]


def test_invalid_device_token_never_receives_websocket_credentials(settings: GatewaySettings) -> None:
    store = GatewayStore(settings.database_path)
    with TestClient(create_app(settings, store)) as client:
        response = client.post(
            "/xiaozhi/ota/",
            headers={**DEVICE_HEADERS, "Authorization": "Device not-valid"},
            json={},
        )
        assert response.status_code == 200
        assert "activation" in response.json()
        assert "websocket" not in response.json()


def test_session_tokens_expire() -> None:
    from symbios_gateway.security import issue_session_token

    secret = "s" * 32
    token = issue_session_token(
        secret,
        device_id="device-1",
        client_id="client-1",
        ttl_seconds=30,
        now=100,
    )
    assert verify_session_token(secret, token, now=129)["sub"] == "device-1"
    with pytest.raises(TokenError, match="expired"):
        verify_session_token(secret, token, now=130)


def test_websocket_requires_a_device_bound_bearer(settings: GatewaySettings) -> None:
    from symbios_gateway.security import issue_session_token

    store = GatewayStore(settings.database_path)
    with TestClient(create_app(settings, store)) as client:
        with pytest.raises(WebSocketDisconnect) as missing:
            with client.websocket_connect("/xiaozhi/v1/"):
                pass
        assert missing.value.code == 4401

        token = issue_session_token(
            settings.jwt_secret,
            device_id=DEVICE_HEADERS["Device-Id"],
            client_id=DEVICE_HEADERS["Client-Id"],
            ttl_seconds=30,
        )
        with pytest.raises(WebSocketDisconnect) as mismatched:
            with client.websocket_connect(
                "/xiaozhi/v1/",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Device-Id": "00:00:00:00:00:00",
                    "Client-Id": DEVICE_HEADERS["Client-Id"],
                },
            ):
                pass
        assert mismatched.value.code == 4403


def test_production_config_requires_tls(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        GatewaySettings(
            public_base_url="http://gateway.test",
            jwt_secret="j" * 32,
            admin_token="a" * 32,
            upstream_ws_url="wss://upstream.test/xiaozhi/v1/",
            voice_provider="proxy",
            database_path=tmp_path / "gateway.sqlite3",
        )


def test_ram_loopback_config_needs_no_provider_credential(tmp_path: Path) -> None:
    settings = GatewaySettings(
        public_base_url="https://gateway.test",
        jwt_secret="j" * 32,
        admin_token="a" * 32,
        voice_provider="ram_loopback",
        database_path=tmp_path / "gateway.sqlite3",
    )

    assert settings.voice_provider == "ram_loopback"


def test_ram_loopback_replays_and_clears_volatile_pcm(
    settings: GatewaySettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeCodec:
        instances: list["FakeCodec"] = []

        def __init__(self) -> None:
            self.clear_count = 0
            self.output = bytearray()
            self.__class__.instances.append(self)

        def clear_output(self) -> None:
            self.clear_count += 1
            self.output.clear()

        def decode_input_16k(self, _: bytes) -> bytes:
            return struct.pack("<" + "h" * 320, *([400] * 320))

        def feed_output(self, pcm16: bytes) -> list[bytes]:
            self.output.extend(pcm16)
            if len(self.output) < 2880:
                return []
            self.output.clear()
            return [b"loopback-opus"]

        def flush_output(self) -> list[bytes]:
            if not self.output:
                return []
            self.output.clear()
            return [b"loopback-tail"]

    class FakeWebSocket:
        def __init__(self) -> None:
            self.received = iter(
                [
                    {
                        "type": "websocket.receive",
                        "text": json.dumps({"type": "listen", "state": "start"}),
                    },
                    {"type": "websocket.receive", "bytes": b"device-opus"},
                    {
                        "type": "websocket.receive",
                        "text": json.dumps({"type": "listen", "state": "stop"}),
                    },
                    {"type": "websocket.disconnect"},
                ]
            )
            self.json_messages: list[dict[str, object]] = []
            self.binary_messages: list[bytes] = []

        async def receive(self) -> dict[str, object]:
            return next(self.received)

        async def send_json(self, message: dict[str, object]) -> None:
            self.json_messages.append(message)

        async def send_bytes(self, message: bytes) -> None:
            self.binary_messages.append(message)

    import symbios_gateway.loopback as loopback

    monkeypatch.setattr(loopback, "XiaozhiAudioCodec", FakeCodec)
    websocket = FakeWebSocket()
    loopback_settings = replace(settings, voice_provider="ram_loopback")
    asyncio.run(
        run_ram_loopback_bridge(
            websocket,  # type: ignore[arg-type]
            loopback_settings,
            protocol_version=1,
        )
    )

    states = [message.get("state") for message in websocket.json_messages]
    assert states == [None, "start", None, "stop"]
    assert websocket.binary_messages == [b"loopback-tail"]
    assert FakeCodec.instances[0].output == bytearray()
    assert FakeCodec.instances[0].clear_count >= 2

    secret = bytearray(b"transient-pcm")
    _zero_and_clear(secret)
    assert secret == bytearray()


def test_vertex_setup_uses_explicit_activity_boundaries(settings: GatewaySettings) -> None:
    setup = json.loads(
        _vertex_setup(replace(settings, gcp_project="test-project"))
    )["setup"]

    assert setup["realtime_input_config"] == {
        "automatic_activity_detection": {"disabled": True}
    }


def test_vertex_manual_turn_sends_explicit_activity_boundaries() -> None:
    class Upstream:
        def __init__(self) -> None:
            self.messages: list[str] = []

        async def send(self, message: str) -> None:
            self.messages.append(message)

    class Codec:
        def __init__(self) -> None:
            self.clear_count = 0

        def clear_output(self) -> None:
            self.clear_count += 1

    upstream = Upstream()
    codec = Codec()
    state = VertexBridgeState()

    asyncio.run(
        _handle_vertex_listen_event(
            {"type": "listen", "state": "start"}, upstream, state, codec
        )
    )
    assert state.listening is True
    assert codec.clear_count == 1
    assert json.loads(upstream.messages[-1]) == {
        "realtime_input": {"activity_start": {}}
    }

    asyncio.run(
        _handle_vertex_listen_event(
            {"type": "listen", "state": "stop"}, upstream, state, codec
        )
    )
    assert state.listening is False
    assert json.loads(upstream.messages[-1]) == {
        "realtime_input": {"activity_end": {}}
    }


def test_vertex_audio_metrics_record_pcm_without_retaining_audio() -> None:
    state = VertexBridgeState()

    _record_vertex_input_pcm(state, b"\x00\x00\x64\x00\x9c\xff\xff\x7f")

    assert state.input_frames == 1
    assert state.input_pcm_bytes == 8
    assert state.input_samples == 4
    assert state.input_peak == 32767
    assert _vertex_input_mean_abs(state) == 8241
