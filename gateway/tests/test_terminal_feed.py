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
        parse_apex_snapshot(b"{" + b"x" * 8192 + b"}", now=now)
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
        assert feed["display_status"] == "LIVE"
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
        assert feed["display_status"] == "STALE"
        assert feed["btc"] is None


def test_offline_payload_has_no_fabricated_apex_values() -> None:
    at = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
    feed = build_terminal_feed(None, btc=None, now=at)
    assert feed["status"] == "OFFLINE"
    assert feed["display_status"] == "OFFLINE"
    assert feed["terminal_mode"] == "quiet_intelligence"
    assert feed["apex"] is None
    assert feed["rows"] == []
    assert feed["events"] == []


def test_market_phase_is_allow_listed_for_close_and_weekend_rendering() -> None:
    now = datetime(2026, 8, 15, 16, 0, tzinfo=timezone.utc)
    source = payload(now)
    source["schema_version"] = 2
    source["apex"]["market_phase"] = "weekend"

    normalized, _ = parse_apex_snapshot(json.dumps(source).encode(), now=now)

    assert normalized["apex"]["market_phase"] == "weekend"

    normalized["received_at"] = now.isoformat()
    feed = build_terminal_feed(json.dumps(normalized), btc=None, now=now)
    assert feed["status"] == "LIVE"
    assert feed["display_status"] == "LAST CLOSE"
    assert feed["terminal_mode"] == "weekend_review"


def test_feed_passes_closed_phase_into_post_close_editorial_profile() -> None:
    now = datetime(2026, 8, 18, 2, 0, tzinfo=timezone.utc)
    expires = (now + timedelta(hours=8)).isoformat()

    def close_event(identity: str, kind: str, title: str, **extra: object) -> dict[str, object]:
        return {
            "id": identity,
            "kind": kind,
            "priority": int(extra.pop("priority", 70)),
            "title": title,
            "body": str(extra.pop("body", "Verified close fact.")),
            "source": str(extra.pop("source", "APEX")),
            "source_at": now.isoformat(),
            "expires_at": expires,
            "freshness": "FRESH",
            **extra,
        }

    stored = {
        "schema_version": 2,
        "generated_at": now.isoformat(),
        "received_at": now.isoformat(),
        "apex": {"source_at": now.isoformat(), "market_phase": "closed"},
        "rows": [],
        "events": [
            close_event("market", "BRIEF", "NIGHT WATCH · AUG 17", source="APEX MARKET"),
            close_event("portfolio", "INFO", "PORTFOLIO AT CLOSE", source="SCHWAB PORTFOLIO"),
            close_event("up", "MOVER_UP", "TOP GAINER", symbol="AAPL", change_pct=2.1),
            close_event("down", "MOVER_DOWN", "TOP LOSER", symbol="TSLA", change_pct=-1.4),
            close_event("buy", "INFO", "BUY SIGNAL", symbol="NVDA", metric_label="SIGNAL", metric_value="BUY"),
        ],
        "sources": {
            "council": {"status": "MISSING", "source_at": None},
            "slack": {"status": "MISSING", "source_at": None},
        },
    }

    feed = build_terminal_feed(json.dumps(stored), btc=None, now=now)

    assert [event["title"] for event in feed["events"]] == [
        "QUIET INTELLIGENCE · AUG 17",
        "PORTFOLIO AT CLOSE",
        "CARRY SIGNALS",
        "LAST CLOSE MOVERS",
    ]
    assert feed["terminal_mode"] == "quiet_intelligence"


def test_display_status_uses_quote_freshness_not_only_snapshot_freshness() -> None:
    now = datetime(2026, 8, 31, 15, 30, tzinfo=timezone.utc)
    source = payload(now)
    source["schema_version"] = 2
    source["apex"]["market_phase"] = "intraday"
    source["rows"][0]["source_at"] = (now - timedelta(minutes=11)).isoformat()
    normalized, _ = parse_apex_snapshot(json.dumps(source).encode(), now=now)
    normalized["received_at"] = now.isoformat()

    feed = build_terminal_feed(json.dumps(normalized), btc=None, now=now)

    assert feed["status"] == "LIVE"
    assert feed["display_status"] == "STALE"


def test_schema_two_events_are_prioritized_bounded_and_expiry_gated() -> None:
    now = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
    source = payload(now)
    source["schema_version"] = 2
    source["sources"] = {
        "council": {"status": "FRESH", "source_at": now.isoformat()},
        "slack": {"status": "FRESH", "source_at": now.isoformat()},
    }
    source["events"] = [
        {
            "id": "brief:1",
            "kind": "BRIEF",
            "priority": 45,
            "title": "Midday briefing",
            "body": "Rates and breadth update.",
            "source": "APEX SLACK",
            "source_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "freshness": "FRESH",
        },
        {
            "id": "fill:1",
            "kind": "TRADE",
            "priority": 100,
            "title": "BUY 10",
            "body": "Broker-confirmed live fill.",
            "symbol": "AAPL",
            "value": 210.25,
            "metric_label": "QTY",
            "metric_value": "10",
            "source": "LIVE BOOK",
            "source_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "freshness": "FRESH",
        },
        {
            "id": "expired:1",
            "kind": "INFO",
            "priority": 30,
            "title": "Expired",
            "body": "Must not reach device.",
            "source": "APEX",
            "source_at": (now - timedelta(hours=2)).isoformat(),
            "expires_at": (now - timedelta(hours=1)).isoformat(),
            "freshness": "FRESH",
        },
    ]

    normalized, _ = parse_apex_snapshot(json.dumps(source).encode(), now=now)

    assert normalized["schema_version"] == 2
    assert [event["id"] for event in normalized["events"]] == ["fill:1", "brief:1"]
    assert normalized["events"][0]["source"] == "LIVE BOOK"
    assert normalized["sources"]["council"]["status"] == "FRESH"


def test_schema_two_rejects_unbounded_or_unknown_event() -> None:
    now = datetime.now(timezone.utc)
    source = payload(now)
    source["schema_version"] = 2
    source["events"] = [{
        "id": "bad:1",
        "kind": "BUY_NOW",
        "priority": 101,
        "title": "Bad",
        "body": "Unknown event",
        "source": "APEX",
        "source_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
    }]
    try:
        parse_apex_snapshot(json.dumps(source).encode(), now=now)
    except ValueError as exc:
        assert "events[0]" in str(exc)
    else:
        raise AssertionError("unknown event was accepted")


def test_device_rotation_is_category_diverse_and_paper_fills_are_not_live_trades() -> None:
    now = datetime(2026, 8, 12, 16, 0, tzinfo=timezone.utc)

    def event(identity: str, kind: str, title: str, **extra: object) -> dict[str, object]:
        return {
            "id": identity,
            "kind": kind,
            "priority": int(extra.pop("priority", 70)),
            "title": title,
            "body": str(extra.pop("body", "Observed event.")),
            "source": str(extra.pop("source", "APEX")),
            "source_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=10)).isoformat(),
            "freshness": "FRESH",
            **extra,
        }

    events = [
        event(
            f"paper:{index}",
            "TRADE",
            f"APEX MASTERS — Voice {index} filed: KTOS",
            priority=100,
            source="APEX SLACK",
        )
        for index in range(3)
    ] + [
        event("market:1", "BRIEF", "MARKET OPEN · 12:00 ET", source="APEX MARKET"),
        event("up:1", "MOVER_UP", "TOP GAINER", symbol="NBIS", value=230.0, change_pct=23.5),
        event("down:1", "MOVER_DOWN", "TOP LOSER", symbol="PLTR", value=170.0, change_pct=-4.0),
        event("buy:1", "INFO", "BUY SIGNAL", symbol="NBIS", value=230.0, metric_label="SIGNAL", metric_value="BUY"),
        event("sell:1", "INFO", "SELL SIGNAL", symbol="NVDA", value=225.0, metric_label="SIGNAL", metric_value="SELL"),
    ]
    stored = {
        "schema_version": 2,
        "generated_at": now.isoformat(),
        "received_at": now.isoformat(),
        "apex": {"source_at": now.isoformat(), "market_phase": "intraday"},
        "rows": [],
        "events": events,
        "sources": {
            "council": {"status": "FRESH", "source_at": now.isoformat()},
            "slack": {"status": "FRESH", "source_at": now.isoformat()},
        },
    }

    feed = build_terminal_feed(json.dumps(stored), btc=None, now=now)

    assert [item["title"] for item in feed["events"]] == [
        "APEX LIVE · 12:00 ET", "SIGNAL BOARD", "MARKET MOVERS",
        "APEX MASTERS — Voice 0 filed: KTOS",
    ]
    assert sum(item["kind"] == "COUNCIL" for item in feed["events"]) == 1
    assert not any(item["kind"] == "TRADE" for item in feed["events"])
    signal_board = next(item for item in feed["events"] if item["title"] == "SIGNAL BOARD")
    assert signal_board["body"] == "BUY NBIS | SELL NVDA"


def test_stale_feed_suppresses_actionable_events() -> None:
    now = datetime(2026, 8, 12, 16, 0, tzinfo=timezone.utc)
    generated = now - timedelta(minutes=11)
    stored = {
        "schema_version": 2,
        "generated_at": generated.isoformat(),
        "received_at": generated.isoformat(),
        "apex": None,
        "rows": [],
        "events": [{
            "id": "buy:stale",
            "kind": "INFO",
            "priority": 78,
            "title": "BUY SIGNAL",
            "body": "Must not appear as current.",
            "source": "APEX SIGNAL",
            "source_at": generated.isoformat(),
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "freshness": "FRESH",
            "symbol": "AAPL",
            "value": 210.0,
            "metric_label": "SIGNAL",
            "metric_value": "BUY",
        }],
        "sources": {
            "council": {"status": "STALE", "source_at": generated.isoformat()},
            "slack": {"status": "STALE", "source_at": generated.isoformat()},
        },
    }

    feed = build_terminal_feed(json.dumps(stored), btc=None, now=now)

    assert feed["status"] == "STALE"
    assert feed["events"] == []


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
