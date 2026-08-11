from __future__ import annotations

import json
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from symbios_gateway.apex_feed import build_terminal_feed, parse_apex_snapshot
from symbios_gateway.app import create_app
from symbios_gateway.config import GatewaySettings
from symbios_gateway.market import MarketDataError
from symbios_gateway.market import CoinbaseMarketClient
from symbios_gateway.storage import GatewayStore


DEVICE_HEADERS = {
    "Device-Id": "aa:bb:cc:dd:ee:ff",
    "Client-Id": "123e4567-e89b-12d3-a456-426614174000",
}


class Market:
    async def get_btc(self) -> dict[str, object]:
        return {
            "symbol": "BTC-USD",
            "price": 120000.0,
            "change_24h_pct": 2.5,
            "source_at": "2026-08-10T20:00:00+00:00",
        }


class OfflineMarket:
    async def get_btc(self) -> dict[str, object]:
        raise MarketDataError("provider detail must not escape")


def settings(tmp_path: Path) -> GatewaySettings:
    return GatewaySettings(
        public_base_url="http://gateway.test",
        jwt_secret="j" * 32,
        admin_token="a" * 32,
        apex_ingest_token="i" * 32,
        upstream_ws_url="ws://upstream.test/xiaozhi/v1/",
        voice_provider="proxy",
        database_path=tmp_path / "gateway.sqlite3",
        allow_insecure_urls=True,
    )


def payload(at: datetime) -> dict[str, object]:
    source = at.astimezone(timezone.utc).isoformat()
    return {
        "schema_version": 1,
        "generated_at": source,
        "apex": {
            "net_liq": 150000.0,
            "cash_pct": 18.5,
            "position_count": 3,
            "risk_count": 1,
            "source_at": source,
            "account_id": "ignored",
        },
        "rows": [
            {
                "symbol": "AAPL",
                "price": 210.25,
                "kind": "position",
                "source_at": source,
                "quantity": 500,
            }
        ],
        "orders": ["ignored"],
    }


def enroll(client: TestClient, app_settings: GatewaySettings) -> str:
    activation = client.post("/xiaozhi/ota/", headers=DEVICE_HEADERS, json={}).json()[
        "activation"
    ]
    approved = client.post(
        f"/admin/enroll/{activation['code']}",
        headers={"Authorization": f"Bearer {app_settings.admin_token}"},
    )
    assert approved.status_code == 200
    activated = client.post(
        "/xiaozhi/ota/activate",
        headers=DEVICE_HEADERS,
        json={"challenge": activation["challenge"]},
    )
    return activated.json()["symbios"]["device_token"]


def test_parser_ignores_unknown_fields_and_rejects_oversize() -> None:
    now = datetime.now(timezone.utc)
    normalized, _ = parse_apex_snapshot(json.dumps(payload(now)).encode(), now=now)
    text = json.dumps(normalized)
    assert "account_id" not in text
    assert "quantity" not in text
    assert "orders" not in text

    try:
        parse_apex_snapshot(b"{" + b"x" * 4096 + b"}", now=now)
    except ValueError as exc:
        assert "too large" in str(exc)
    else:
        raise AssertionError("oversized payload was accepted")


def test_ingest_auth_replay_and_device_auth(tmp_path: Path) -> None:
    app_settings = settings(tmp_path)
    store = GatewayStore(app_settings.database_path)
    with TestClient(create_app(app_settings, store, Market())) as client:
        body = payload(datetime.now(timezone.utc))
        rejected = client.put("/api/v1/apex/snapshot", json=body)
        assert rejected.status_code == 401

        accepted = client.put(
            "/api/v1/apex/snapshot",
            headers={"Authorization": f"Bearer {app_settings.apex_ingest_token}"},
            json=body,
        )
        assert accepted.status_code == 202
        replay = client.put(
            "/api/v1/apex/snapshot",
            headers={"Authorization": f"Bearer {app_settings.apex_ingest_token}"},
            json=body,
        )
        assert replay.status_code == 409

        assert client.get("/api/v1/terminal/feed", headers=DEVICE_HEADERS).status_code == 401
        token = enroll(client, app_settings)
        feed_response = client.get(
            "/api/v1/terminal/feed",
            headers={**DEVICE_HEADERS, "Authorization": f"Device {token}"},
        )
        assert feed_response.status_code == 200
        assert feed_response.headers["cache-control"] == "no-store"
        feed = feed_response.json()
        assert feed["status"] == "LIVE"
        assert feed["btc"]["symbol"] == "BTC-USD"
        assert feed["rows"] == [
            {
                "symbol": "AAPL",
                "price": 210.25,
                "kind": "position",
                "source_at": body["generated_at"],
            }
        ]
        response_text = feed_response.text
        assert app_settings.apex_ingest_token not in response_text
        assert "account_id" not in response_text
        assert "quantity" not in response_text


def test_stale_decay_and_coinbase_failure_are_explicit(tmp_path: Path) -> None:
    app_settings = settings(tmp_path)
    store = GatewayStore(app_settings.database_path)
    source_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    normalized, epoch = parse_apex_snapshot(
        json.dumps(payload(source_at)).encode(), now=datetime.now(timezone.utc)
    )
    normalized["received_at"] = datetime.now(timezone.utc).isoformat()
    assert store.save_terminal_snapshot(
        json.dumps(normalized), source_at=epoch, received_at=int(datetime.now().timestamp())
    )
    with TestClient(create_app(app_settings, store, OfflineMarket())) as client:
        token = enroll(client, app_settings)
        feed = client.get(
            "/api/v1/terminal/feed",
            headers={**DEVICE_HEADERS, "Authorization": f"Device {token}"},
        ).json()
        assert feed["status"] == "STALE"
        assert feed["btc"] is None


def test_offline_payload_has_no_fabricated_apex_values() -> None:
    at = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
    feed = build_terminal_feed(None, btc=None, now=at)
    assert feed["status"] == "OFFLINE"
    assert feed["apex"] is None
    assert feed["rows"] == []


def test_apex_ingest_settings_are_all_or_nothing_and_redacted(tmp_path: Path) -> None:
    app_settings = settings(tmp_path)
    assert "i" * 32 not in repr(app_settings)
    try:
        replace(app_settings, apex_ingest_token="short")
    except ValueError as exc:
        assert "32 characters" in str(exc)
    else:
        raise AssertionError("short ingest token was accepted")


def test_coinbase_client_uses_direct_ticker_and_stats() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ticker"):
            return httpx.Response(
                200,
                json={"price": "120000.00", "time": "2026-08-10T20:00:00Z"},
            )
        return httpx.Response(200, json={"open": "100000.00"})

    client = CoinbaseMarketClient(
        "https://coinbase.test",
        4.0,
        transport=httpx.MockTransport(handler),
    )
    btc = asyncio.run(client.get_btc())
    assert btc == {
        "symbol": "BTC-USD",
        "price": 120000.0,
        "change_24h_pct": 20.0,
        "source_at": "2026-08-10T20:00:00+00:00",
    }


def test_coinbase_timeout_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider internals", request=request)

    client = CoinbaseMarketClient(
        "https://coinbase.test",
        1.0,
        transport=httpx.MockTransport(handler),
    )
    try:
        asyncio.run(client.get_btc())
    except MarketDataError as exc:
        assert str(exc) == "Coinbase request failed"
    else:
        raise AssertionError("Coinbase timeout did not fail closed")
