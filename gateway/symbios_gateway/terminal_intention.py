from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Mapping


MAX_INTENTIONS = 10


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _signal_is(event: Mapping[str, object], sides: set[str]) -> bool:
    return (
        str(event.get("metric_label", "")).upper() == "SIGNAL"
        and str(event.get("metric_value", "")).upper() in sides
    )


def intention_category(event: Mapping[str, object]) -> str:
    """Return the human decision question answered by one verified event."""
    kind = str(event.get("kind", "")).upper()
    source = str(event.get("source", "")).upper()
    title = str(event.get("title", "")).upper()
    if title in {"SIGNAL BOARD", "CARRY SIGNALS", "WEEKEND SIGNALS"}:
        return "signal_board"
    if title in {"MARKET MOVERS", "CLOSE MOVERS", "LAST CLOSE MOVERS", "LAST SESSION MOVERS"}:
        return "market_movers"
    if title in {"TECHNICAL EXTREMES", "CLOSE EXTREMES", "LAST SESSION EXTREMES"}:
        return "technical_extremes"
    if source == "SCHWAB PORTFOLIO":
        return "portfolio_close"
    if kind in {"TRADE", "RISK"}:
        return "interrupt"
    if kind == "BRIEF" and source == "APEX MARKET":
        return "market"
    if kind == "MOVER_UP":
        return "mover_up"
    if kind == "MOVER_DOWN":
        return "mover_down"
    if _signal_is(event, {"BUY", "ADD"}):
        return "buy"
    if _signal_is(event, {"SELL", "RISK"}):
        return "sell"
    if source == "APEX SIGNAL" and title.startswith("BUY SIGNAL"):
        return "buy"
    if source == "APEX SIGNAL" and title.startswith("SELL SIGNAL"):
        return "sell"
    if kind == "OVERSOLD":
        return "oversold"
    if kind == "OVERBOUGHT":
        return "overbought"
    if source in {"SEEKING ALPHA", "ARK INVEST"} or title.startswith("NEWS ·"):
        return "news"
    if kind == "COUNCIL" or "APEX MASTERS" in title:
        return "council"
    if kind == "BRIEF" or "BRIEF" in title or "HERMES" in title:
        return "briefing"
    return "other"


def _semantic_event(raw: Mapping[str, object]) -> dict[str, object]:
    event = dict(raw)
    if event.get("kind") == "TRADE" and not (
        event.get("source") == "LIVE BOOK"
        and isinstance(event.get("symbol"), str)
        and isinstance(event.get("value"), (int, float))
        and not isinstance(event.get("value"), bool)
    ):
        text = f"{event.get('title', '')} {event.get('body', '')}"
        if "APEX MASTERS" in text or event.get("source") == "APEX MASTERS":
            event["kind"] = "COUNCIL"
            event["priority"] = min(int(event.get("priority", 0)), 80)
        else:
            event["kind"] = "INFO"
            event["priority"] = min(int(event.get("priority", 0)), 30)
    return event


def _board_event(
    *,
    prefix: str,
    title: str,
    body: str,
    metric_label: str,
    metric_value: str,
    source: str,
    events: list[dict[str, object]],
) -> dict[str, object]:
    source_at = max(str(event["source_at"]) for event in events)
    expires_at = min(str(event["expires_at"]) for event in events)
    fingerprint = ":".join(str(event["id"]) for event in events)
    return {
        "id": f"{prefix}:{hashlib.sha256(fingerprint.encode()).hexdigest()[:20]}",
        "kind": "BRIEF",
        "priority": max(int(event.get("priority", 0)) for event in events),
        "title": title,
        "body": body,
        "metric_label": metric_label,
        "metric_value": metric_value,
        "source": source,
        "source_at": source_at,
        "expires_at": expires_at,
        "freshness": "FRESH",
    }


def _signal_phrase(event: dict[str, object] | None, side: str) -> str | None:
    if event is None:
        return None
    if str(event.get("metric_label", "")).upper() == "STATUS":
        return f"{side} NONE"
    action = str(event.get("metric_value", side)).upper()
    symbol = str(event.get("symbol", "ACTIVE")).upper()
    return f"{action} {symbol}"


def _change_phrase(event: dict[str, object] | None, direction: str) -> str | None:
    if event is None:
        return None
    symbol = str(event.get("symbol", "MARKET")).upper()
    change = event.get("change_pct")
    suffix = f" {float(change):+.1f}%" if isinstance(change, (int, float)) else ""
    return f"{direction} {symbol}{suffix}"


def _rsi_phrase(event: dict[str, object] | None, label: str) -> str | None:
    if event is None:
        return None
    symbol = str(event.get("symbol", "MARKET")).upper()
    rsi = str(event.get("metric_value", "N/A")).upper()
    return f"{label} {symbol} RSI {rsi}"


def select_terminal_intentions(
    value: object,
    *,
    current: datetime,
    market_phase: str = "unknown",
    limit: int = MAX_INTENTIONS,
) -> list[dict[str, object]]:
    """Build a compact editorial queue from verified event facts.

    The 320x240 screen combines paired states instead of spending separate
    pages on BUY/SELL, up/down movers, or oversold/overbought. Fifteen is a
    hard capacity, never a quota; this selector normally returns fewer cards.
    """
    if not isinstance(value, list) or limit <= 0:
        return []
    now = current.astimezone(timezone.utc)
    candidates: list[dict[str, object]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        source_at = _timestamp(raw.get("source_at"))
        expires_at = _timestamp(raw.get("expires_at"))
        if source_at is None or expires_at is None or expires_at <= now:
            continue
        event = _semantic_event(raw)
        event["_intent"] = intention_category(event)
        candidates.append(event)
    candidates.sort(
        key=lambda item: (int(item.get("priority", 0)), str(item.get("source_at", ""))),
        reverse=True,
    )

    def best(category: str) -> dict[str, object] | None:
        return next((event for event in candidates if event.get("_intent") == category), None)

    selected: list[dict[str, object]] = []

    def append(event: dict[str, object] | None) -> None:
        if event is None or len(selected) >= min(limit, MAX_INTENTIONS):
            return
        selected.append({key: item for key, item in event.items() if key != "_intent"})

    phase = market_phase if market_phase in {
        "premarket", "intraday", "eod", "closed", "weekend", "unknown"
    } else "unknown"
    labels = {
        "eod": ("CARRY SIGNALS", "CLOSE MOVERS", "CLOSE EXTREMES"),
        "closed": ("CARRY SIGNALS", "LAST CLOSE MOVERS", "CLOSE EXTREMES"),
        "weekend": ("WEEKEND SIGNALS", "LAST SESSION MOVERS", "LAST SESSION EXTREMES"),
    }.get(phase, ("SIGNAL BOARD", "MARKET MOVERS", "TECHNICAL EXTREMES"))
    signal_title, mover_title, technical_title = labels

    interrupt = next(
        (
            event for event in candidates
            if event.get("_intent") == "interrupt"
            and (_timestamp(event.get("source_at")) or datetime.min.replace(tzinfo=timezone.utc))
            >= now - timedelta(hours=6)
        ),
        None,
    )
    append(interrupt)

    buy, sell = best("buy"), best("sell")
    signal_parts = [part for part in (_signal_phrase(buy, "BUY"), _signal_phrase(sell, "SELL")) if part]
    signal_events = [event for event in (buy, sell) if event is not None]
    signal_board = None
    if signal_events:
        active = sum(
            str(event.get("metric_label", "")).upper() == "SIGNAL" for event in signal_events
        )
        signal_board = _board_event(
            prefix="signal-board",
            title=signal_title,
            body=" | ".join(signal_parts),
            metric_label="ACTIVE",
            metric_value=str(active),
            source="APEX SIGNAL",
            events=signal_events,
        )

    mover_up, mover_down = best("mover_up"), best("mover_down")
    mover_parts = [
        part for part in (_change_phrase(mover_up, "UP"), _change_phrase(mover_down, "DOWN"))
        if part
    ]
    mover_events = [event for event in (mover_up, mover_down) if event is not None]
    mover_board = None
    if mover_events:
        mover_board = _board_event(
            prefix="market-movers",
            title=mover_title,
            body=" | ".join(mover_parts),
            metric_label="DIRECTION",
            metric_value="UP / DOWN" if len(mover_events) == 2 else "ONE SIDE",
            source="APEX MARKET",
            events=mover_events,
        )

    oversold, overbought = best("oversold"), best("overbought")
    technical_parts = [
        part for part in (_rsi_phrase(oversold, "OS"), _rsi_phrase(overbought, "OB")) if part
    ]
    technical_events = [event for event in (oversold, overbought) if event is not None]
    technical_board = None
    if technical_events:
        technical_board = _board_event(
            prefix="technical",
            title=technical_title,
            body=" | ".join(technical_parts),
            metric_label="RSI",
            metric_value=str(len(technical_events)),
            source="APEX TECHNICAL",
            events=technical_events,
        )

    cards = {
        "market": best("market"),
        "portfolio": best("portfolio_close"),
        "signals": signal_board,
        "movers": mover_board,
        "technical": technical_board,
        "news": best("news"),
        "council": best("council"),
        "briefing": best("briefing"),
        "other": best("other"),
    }
    if phase == "eod":
        order = (
            "market", "portfolio", "movers", "signals", "news",
            "council", "briefing", "technical", "other",
        )
    elif phase in {"closed", "weekend"}:
        order = (
            "market", "portfolio", "news", "council", "briefing",
            "signals", "movers", "technical", "other",
        )
    else:
        order = (
            "market", "signals", "movers", "technical", "news",
            "council", "briefing", "other",
        )
    for name in order:
        append(cards[name])
    return selected
