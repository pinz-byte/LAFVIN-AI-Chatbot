from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx


class MarketDataError(RuntimeError):
    pass


def _positive_number(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarketDataError(f"invalid Coinbase {name}") from exc
    if not math.isfinite(number) or number <= 0:
        raise MarketDataError(f"invalid Coinbase {name}")
    return number


def _source_time(value: object) -> str:
    if not isinstance(value, str):
        raise MarketDataError("invalid Coinbase time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MarketDataError("invalid Coinbase time") from exc
    if parsed.tzinfo is None:
        raise MarketDataError("invalid Coinbase time")
    return parsed.astimezone(timezone.utc).isoformat()


class CoinbaseMarketClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Coinbase base URL must use HTTPS")
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def get_btc(self) -> dict[str, object]:
        timeout = httpx.Timeout(self._timeout_seconds)
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=timeout,
                headers={"User-Agent": "symbios-voice-gateway/terminal-feed"},
                transport=self._transport,
            ) as client:
                ticker_response, stats_response = await asyncio.gather(
                    client.get("/products/BTC-USD/ticker"),
                    client.get("/products/BTC-USD/stats"),
                )
            ticker_response.raise_for_status()
            stats_response.raise_for_status()
            ticker = ticker_response.json()
            stats = stats_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MarketDataError("Coinbase request failed") from exc
        price = _positive_number(ticker.get("price"), "price")
        opening = _positive_number(stats.get("open"), "open")
        return {
            "symbol": "BTC-USD",
            "price": price,
            "change_24h_pct": (price - opening) / opening * 100.0,
            "source_at": _source_time(ticker.get("time")),
        }
