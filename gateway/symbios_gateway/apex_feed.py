from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Mapping

from .terminal_intention import MAX_INTENTIONS, select_terminal_intentions


MAX_FEED_BYTES = 8192
MAX_ROWS = 12
MAX_EVENTS = MAX_INTENTIONS
MAX_DEVICE_CARDS = 15
MAX_VISIBLE_ROWS = 4
MAX_SOURCE_AGE_SECONDS = 24 * 60 * 60
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9.\-]{1,12}$")
EVENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9:._\-]{1,40}$")
EVENT_KINDS = {
    "TRADE", "RISK", "COUNCIL", "OVERSOLD", "OVERBOUGHT",
    "MOVER_UP", "MOVER_DOWN", "BRIEF", "INFO",
}
SOURCE_STATUSES = {"FRESH", "STALE", "MISSING", "PENDING"}
MARKET_PHASES = {"premarket", "intraday", "eod", "closed", "weekend", "unknown"}


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


def _priority(value: object, name: str) -> int:
    priority = _count(value, name)
    if priority > 100:
        raise ApexFeedError(f"invalid {name}")
    return priority


def _text(value: object, name: str, *, maximum: int, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > maximum:
        raise ApexFeedError(f"invalid {name}")
    if not empty and not value.strip():
        raise ApexFeedError(f"invalid {name}")
    return value


def _parse_sources(value: object) -> dict[str, object]:
    if value is None:
        return {
            "council": {"status": "MISSING", "source_at": None},
            "slack": {"status": "MISSING", "source_at": None},
        }
    if not isinstance(value, Mapping):
        raise ApexFeedError("invalid sources")
    output: dict[str, object] = {}
    for name in ("council", "slack"):
        source = value.get(name)
        if not isinstance(source, Mapping) or source.get("status") not in SOURCE_STATUSES:
            raise ApexFeedError(f"invalid sources.{name}")
        source_at = source.get("source_at")
        output[name] = {
            "status": source["status"],
            "source_at": (
                _parse_timestamp(source_at, f"sources.{name}.source_at").isoformat()
                if source_at is not None else None
            ),
        }
    return output


def _parse_events(
    value: object,
    *,
    current: datetime,
) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_EVENTS:
        raise ApexFeedError("invalid events")
    output: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise ApexFeedError(f"invalid events[{index}]")
        identity = raw.get("id")
        kind = raw.get("kind")
        if not isinstance(identity, str) or EVENT_ID_PATTERN.fullmatch(identity) is None:
            raise ApexFeedError(f"invalid events[{index}].id")
        if identity in seen or kind not in EVENT_KINDS:
            raise ApexFeedError(f"invalid events[{index}]")
        source_at = _parse_timestamp(raw.get("source_at"), f"events[{index}].source_at")
        expires_at = _parse_timestamp(raw.get("expires_at"), f"events[{index}].expires_at")
        if source_at > current + timedelta(seconds=60) or expires_at <= source_at:
            raise ApexFeedError(f"invalid events[{index}].expires_at")
        if expires_at <= current:
            continue
        event: dict[str, object] = {
            "id": identity,
            "kind": kind,
            "priority": _priority(raw.get("priority"), f"events[{index}].priority"),
            "title": _text(raw.get("title"), f"events[{index}].title", maximum=48),
            "body": _text(
                raw.get("body", ""), f"events[{index}].body", maximum=180, empty=True
            ),
            "source": _text(raw.get("source"), f"events[{index}].source", maximum=24),
            "source_at": source_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "freshness": "FRESH",
        }
        symbol = raw.get("symbol")
        if symbol is not None:
            if not isinstance(symbol, str) or SYMBOL_PATTERN.fullmatch(symbol) is None:
                raise ApexFeedError(f"invalid events[{index}].symbol")
            event["symbol"] = symbol
        for field in ("value", "change_pct"):
            if field in raw:
                event[field] = _number(raw.get(field), f"events[{index}].{field}", nullable=True)
        metric_label = raw.get("metric_label")
        metric_value = raw.get("metric_value")
        if (metric_label is None) != (metric_value is None):
            raise ApexFeedError(f"invalid events[{index}].metric")
        if metric_label is not None:
            event["metric_label"] = _text(
                metric_label, f"events[{index}].metric_label", maximum=16
            )
            event["metric_value"] = _text(
                metric_value, f"events[{index}].metric_value", maximum=24
            )
        output.append(event)
        seen.add(identity)
    output.sort(key=lambda item: (int(item["priority"]), str(item["source_at"])), reverse=True)
    return output


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
    if not isinstance(source, Mapping) or source.get("schema_version") not in {1, 2}:
        raise ApexFeedError("unsupported schema version")
    schema_version = int(source["schema_version"])

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
        "schema_version": schema_version,
        "generated_at": generated.isoformat(),
        "apex": {
            "net_liq": _number(raw_apex.get("net_liq"), "apex.net_liq", nullable=True, minimum=0.0),
            "cash_pct": _number(raw_apex.get("cash_pct"), "apex.cash_pct", nullable=True),
            "day_pl_total": _number(
                raw_apex.get("day_pl_total"), "apex.day_pl_total", nullable=True
            ) if "day_pl_total" in raw_apex else None,
            "market_phase": (
                raw_apex.get("market_phase", "unknown")
                if raw_apex.get("market_phase", "unknown") in MARKET_PHASES
                else "unknown"
            ),
            "position_count": _count(raw_apex.get("position_count"), "apex.position_count"),
            "risk_count": _count(raw_apex.get("risk_count"), "apex.risk_count"),
            "source_at": apex_source.isoformat(),
        },
        "rows": rows,
        "events": _parse_events(source.get("events"), current=current),
        "sources": _parse_sources(source.get("sources")),
    }
    return normalized, int(generated.timestamp())


def _freshness(source_at: datetime, now: datetime) -> str:
    age = max(0.0, (now - source_at).total_seconds())
    if age <= 6 * 60:
        return "LIVE"
    if age <= 10 * 60:
        return "DELAYED"
    return "STALE"


def _display_status(
    transport_status: str,
    apex: object,
    rows: object,
    *,
    now: datetime,
) -> str:
    """Separate feed health from the market state shown on the device."""
    if transport_status != "LIVE":
        return transport_status
    if not isinstance(apex, Mapping):
        return "LIVE"
    phase = apex.get("market_phase")
    if phase in {"eod", "closed", "weekend"}:
        return "LAST CLOSE"

    row_times: list[datetime] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            try:
                row_times.append(_parse_timestamp(row.get("source_at"), "rows.source_at"))
            except ApexFeedError:
                continue
    market_freshness = (
        _freshness(min(row_times), now) if row_times else transport_status
    )
    if market_freshness != "LIVE":
        return market_freshness
    if phase == "premarket":
        return "PREMARKET"
    return "LIVE"


def build_terminal_feed(
    stored_json: str | None,
    *,
    btc: dict[str, object] | None,
    now: datetime | None = None,
) -> dict[str, object]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if stored_json is None:
        return {
            "schema_version": 2,
            "generated_at": current.isoformat(),
            "received_at": current.isoformat(),
            "status": "OFFLINE",
            "display_status": "OFFLINE",
            "btc": btc,
            "apex": None,
            "rows": [],
            "events": [],
            "sources": {
                "council": {"status": "MISSING", "source_at": None},
                "slack": {"status": "MISSING", "source_at": None},
            },
        }
    try:
        stored = json.loads(stored_json)
        generated = _parse_timestamp(stored["generated_at"], "generated_at")
        received_at = _parse_timestamp(stored["received_at"], "received_at")
    except (ApexFeedError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ApexFeedError("stored feed is invalid") from exc
    status = _freshness(generated, current)
    apex = stored.get("apex")
    rows = stored.get("rows", [])
    feed = {
        "schema_version": stored.get("schema_version", 1),
        "generated_at": generated.isoformat(),
        "received_at": received_at.isoformat(),
        "status": status,
        "display_status": _display_status(status, apex, rows, now=current),
        "btc": btc,
        "apex": apex,
        "rows": rows,
        "events": (
            select_terminal_intentions(stored.get("events", []), current=current)
            if status != "STALE" else []
        ),
        "sources": stored.get("sources", _parse_sources(None)),
    }
    # The device has fifteen physical slide slots. Events answer decision
    # questions; portfolio and BTC each reserve one slot; the remainder carries
    # distinct held/watch prices instead of silently truncating useful events.
    reserved = (1 if feed["apex"] is not None else 0) + (1 if feed["btc"] is not None else 0)
    row_budget = min(MAX_VISIBLE_ROWS, max(0, MAX_DEVICE_CARDS - len(feed["events"]) - reserved))
    feed["rows"] = feed["rows"][:row_budget]
    encoded = json.dumps(feed, separators=(",", ":"), allow_nan=False).encode("utf-8")
    while len(encoded) > MAX_FEED_BYTES and feed["rows"]:
        feed["rows"].pop()
        encoded = json.dumps(feed, separators=(",", ":"), allow_nan=False).encode("utf-8")
    while len(encoded) > MAX_FEED_BYTES and feed["events"]:
        feed["events"].pop()
        encoded = json.dumps(feed, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_FEED_BYTES:
        raise ApexFeedError("terminal feed exceeds device bound")
    return feed
