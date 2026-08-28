from __future__ import annotations

from datetime import datetime, timedelta, timezone

from symbios_gateway.terminal_intention import (
    intention_category,
    select_terminal_intentions,
)


NOW = datetime(2026, 8, 12, 18, 30, tzinfo=timezone.utc)


def event(identity: str, kind: str, title: str, **extra: object) -> dict[str, object]:
    return {
        "id": identity,
        "kind": kind,
        "priority": int(extra.pop("priority", 70)),
        "title": title,
        "body": str(extra.pop("body", "Verified observation.")),
        "source": str(extra.pop("source", "APEX")),
        "source_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "freshness": "FRESH",
        **extra,
    }


def test_categories_are_human_intentions_not_transport_states() -> None:
    assert intention_category(event("m", "BRIEF", "MARKET OPEN", source="APEX MARKET")) == "market"
    assert intention_category(event("n", "BRIEF", "NEWS · NVDA", source="SEEKING ALPHA")) == "news"
    assert intention_category(event(
        "b", "INFO", "BUY SIGNAL", metric_label="SIGNAL", metric_value="BUY"
    )) == "buy"
    assert intention_category(event(
        "bn", "INFO", "BUY SIGNALS", source="APEX SIGNAL",
        metric_label="STATUS", metric_value="NONE ACTIVE",
    )) == "buy"
    assert intention_category(event(
        "sn", "INFO", "SELL SIGNALS", source="APEX SIGNAL",
        metric_label="STATUS", metric_value="NONE ACTIVE",
    )) == "sell"
    assert intention_category(event("r", "OVERBOUGHT", "RSI")) == "overbought"


def test_builder_combines_paired_states_into_glanceable_decision_cards() -> None:
    events = [
        event("market", "BRIEF", "MARKET OPEN", source="APEX MARKET"),
        event("up", "MOVER_UP", "TOP GAINER", symbol="NBIS"),
        event("down", "MOVER_DOWN", "TOP LOSER", symbol="META"),
        event("buy", "INFO", "BUY SIGNAL", symbol="HOOD", metric_label="SIGNAL", metric_value="BUY"),
        event("sell", "INFO", "SELL SIGNAL", symbol="NVDA", metric_label="SIGNAL", metric_value="SELL"),
        event("under", "OVERSOLD", "RSI", symbol="TSLA"),
        event("over", "OVERBOUGHT", "RSI", symbol="PLTR"),
        event("news", "BRIEF", "NEWS · CRWV", source="SEEKING ALPHA"),
        event("council", "COUNCIL", "GO · ADD", symbol="HOOD"),
        event("brief", "BRIEF", "MIDDAY BRIEF", source="APEX SLACK"),
    ]

    selected = select_terminal_intentions(events, current=NOW)

    assert len(selected) == 7
    assert [intention_category(item) for item in selected] == [
        "market", "signal_board", "market_movers", "technical_extremes",
        "news", "council", "briefing",
    ]
    assert next(item for item in selected if item["title"] == "SIGNAL BOARD")["body"] == (
        "BUY HOOD | SELL NVDA"
    )
    assert next(item for item in selected if item["title"] == "MARKET MOVERS")["body"] == (
        "UP NBIS | DOWN META"
    )


def test_paper_filings_collapse_to_one_council_and_expired_facts_disappear() -> None:
    events = [
        event(
            f"paper-{index}",
            "TRADE",
            f"APEX MASTERS — Voice {index} filed: KTOS",
            source="APEX SLACK",
            priority=100,
        )
        for index in range(5)
    ]
    expired = event("expired", "BRIEF", "OLD NEWS", source="SEEKING ALPHA")
    expired["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    events.append(expired)

    selected = select_terminal_intentions(events, current=NOW)

    assert len(selected) == 1
    assert selected[0]["kind"] == "COUNCIL"
    assert intention_category(selected[0]) == "council"


def test_missing_signal_or_rsi_is_not_fabricated() -> None:
    selected = select_terminal_intentions([
        event("market", "BRIEF", "MARKET CLOSED", source="APEX MARKET"),
        event("news", "BRIEF", "NEWS · TSLA", source="SEEKING ALPHA"),
    ], current=NOW)

    assert [intention_category(item) for item in selected] == ["market", "news"]
    assert not any(intention_category(item) in {"signal_board", "technical_extremes"} for item in selected)
