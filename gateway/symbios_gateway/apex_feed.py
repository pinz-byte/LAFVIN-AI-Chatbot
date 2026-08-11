from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Mapping


MAX_FEED_BYTES = 4096
MAX_ROWS = 6
MAX_SOURCE_AGE_SECONDS = 24 * 60 * 60
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9.\-]{1,12}$")


class ApexFeedError(ValueError):
    pass


def _parse_timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ApexFeedError(f"invalid {name}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApexFeedError(f"invalid {name}") from exc
    if parsed.tzinfo is None:
        raise ApexFeedError(f"invalid {name}")
    return parsed.astimezone(timezone.utc)


def _number(
    value: object,
    name: str,
    *,
    nullable: bool = False,
    minimum: float | None = None,
) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApexFeedError(f"invalid {name}")
    number = float(value)
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise ApexFeedError(f"invalid {name}")
    return number


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10000:
        raise ApexFeedError(f"invalid {name}")
    return value


def parse_apex_snapshot(
    body: bytes,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, object], int]:
    if len(body) > MAX_FEED_BYTES:
        raise ApexFeedError("payload too large")
    try:
        source = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApexFeedError("invalid JSON") from exc
    if not isinstance(source, Mapping) or source.get("schema_version") != 1:
        raise ApexFeedError("unsupported schema version")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    generated = _parse_timestamp(source.get("generated_at"), "generated_at")
    age = (current - generated).total_seconds()
    if age < -60:
        raise ApexFeedError("generated_at is in the future")
    if age > MAX_SOURCE_AGE_SECONDS:
        raise ApexFeedError("generated_at is too old")

    raw_apex = source.get("apex")
    raw_rows = source.get("rows")
    if not isinstance(raw_apex, Mapping) or not isinstance(raw_rows, list):
        raise ApexFeedError("missing apex or rows")
    if len(raw_rows) > MAX_ROWS:
        raise ApexFeedError("too many rows")
    apex_source = _parse_timestamp(raw_apex.get("source_at"), "apex.source_at")

    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, Mapping):
            raise ApexFeedError(f"invalid rows[{index}]")
        symbol = raw_row.get("symbol")
        kind = raw_row.get("kind")
        if not isinstance(symbol, str) or SYMBOL_PATTERN.fullmatch(symbol) is None:
            raise ApexFeedError(f"invalid rows[{index}].symbol")
        if symbol in seen:
            raise ApexFeedError(f"duplicate rows[{index}].symbol")
        if kind not in {"position", "watchlist"}:
            raise ApexFeedError(f"invalid rows[{index}].kind")
        row_source = _parse_timestamp(raw_row.get("source_at"), f"rows[{index}].source_at")
        row: dict[str, object] = {
            "symbol": symbol,
            "price": _number(raw_row.get("price"), f"rows[{index}].price", minimum=0.00000001),
            "kind": kind,
            "source_at": row_source.isoformat(),
        }
        if "change_pct" in raw_row:
            row["change_pct"] = _number(
                raw_row.get("change_pct"), f"rows[{index}].change_pct", nullable=True
            )
        rows.append(row)
        seen.add(symbol)

    normalized: dict[str, object] = {
        "schema_version": 1,
        "generated_at": generated.isoformat(),
        "apex": {
            "net_liq": _number(raw_apex.get("net_liq"), "apex.net_liq", nullable=True, minimum=0.0),
            "cash_pct": _number(raw_apex.get("cash_pct"), "apex.cash_pct", nullable=True),
            "position_count": _count(raw_apex.get("position_count"), "apex.position_count"),
            "risk_count": _count(raw_apex.get("risk_count"), "apex.risk_count"),
            "source_at": apex_source.isoformat(),
        },
        "rows": rows,
    }
    return normalized, int(generated.timestamp())


def _freshness(source_at: datetime, now: datetime) -> str:
    age = max(0.0, (now - source_at).total_seconds())
    if age <= 6 * 60:
        return "LIVE"
    if age <= 10 * 60:
        return "DELAYED"
    return "STALE"


def build_terminal_feed(
    stored_json: str | None,
    *,
    btc: dict[str, object] | None,
    now: datetime | None = None,
) -> dict[str, object]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if stored_json is None:
        return {
            "schema_version": 1,
            "generated_at": current.isoformat(),
            "received_at": current.isoformat(),
            "status": "OFFLINE",
            "btc": btc,
            "apex": None,
            "rows": [],
        }
    try:
        stored = json.loads(stored_json)
        generated = _parse_timestamp(stored["generated_at"], "generated_at")
        received_at = _parse_timestamp(stored["received_at"], "received_at")
    except (ApexFeedError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ApexFeedError("stored feed is invalid") from exc
    return {
        "schema_version": 1,
        "generated_at": generated.isoformat(),
        "received_at": received_at.isoformat(),
        "status": _freshness(generated, current),
        "btc": btc,
        "apex": stored.get("apex"),
        "rows": stored.get("rows", []),
    }
