from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from symbios_gateway.app import create_app
from symbios_gateway.config import GatewaySettings
from symbios_gateway.security import TokenError, verify_session_token
from symbios_gateway.storage import GatewayStore


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
        database_path=tmp_path / "gateway.sqlite3",
        allow_insecure_urls=True,
    )


def test_enrollment_bootstrap_and_short_lived_session(settings: GatewaySettings) -> None:
    store = GatewayStore(settings.database_path)
    with TestClient(create_app(settings, store)) as client:
        bootstrap = client.post("/xiaozhi/ota/", headers=DEVICE_HEADERS, json={"version": 2})
        assert bootstrap.status_code == 200
        activation = bootstrap.json()["activation"]
        assert len(activation["code"]) == 6
        assert "websocket" not in bootstrap.json()

        pending = client.post("/xiaozhi/ota/activate", headers=DEVICE_HEADERS, json={})
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

        activated = client.post("/xiaozhi/ota/activate", headers=DEVICE_HEADERS, json={})
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
            database_path=tmp_path / "gateway.sqlite3",
        )
