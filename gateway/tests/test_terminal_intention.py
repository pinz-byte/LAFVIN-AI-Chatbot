from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from symbios_gateway.terminal_intention import (
    adaptive_terminal_mode,
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
    assert intention_category(event(
        "p", "INFO", "PORTFOLIO CLOSE", source="SCHWAB PORTFOLIO"
    )) == "portfolio_close"


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

    selected = select_terminal_intentions(events, current=NOW, market_phase="intraday")

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


def test_post_close_profiles_change_priority_and_language_by_phase() -> None:
    common = [
        event("portfolio", "INFO", "PORTFOLIO CLOSE", source="SCHWAB PORTFOLIO"),
        event("up", "MOVER_UP", "TOP GAINER", symbol="NBIS", change_pct=4.2),
        event("down", "MOVER_DOWN", "TOP LOSER", symbol="META", change_pct=-3.1),
        event("buy", "INFO", "BUY SIGNAL", symbol="HOOD", metric_label="SIGNAL", metric_value="BUY"),
        event("sell", "INFO", "SELL SIGNAL", symbol="NVDA", metric_label="SIGNAL", metric_value="SELL"),
        event("under", "OVERSOLD", "RSI", symbol="TSLA", metric_value="28.0"),
        event("over", "OVERBOUGHT", "RSI", symbol="PLTR", metric_value="74.0"),
        event("news", "BRIEF", "NEWS · CRWV", source="SEEKING ALPHA"),
        event("council", "COUNCIL", "GO · ADD", symbol="HOOD"),
        event("brief", "BRIEF", "CLOSE NOTE", source="APEX SLACK"),
    ]

    eod = select_terminal_intentions([
        event("market-eod", "BRIEF", "CLOSING DESK · AUG 28", source="APEX MARKET"),
        *common,
    ], current=NOW, market_phase="eod")
    assert [item["title"] for item in eod] == [
        "CLOSING DESK · AUG 28",
        "PORTFOLIO CLOSE",
        "CLOSE MOVERS",
        "CARRY SIGNALS",
        "NEWS · CRWV",
        "GO · ADD",
        "CLOSE NOTE",
        "CLOSE EXTREMES",
    ]

    closed = select_terminal_intentions([
        event("market-closed", "BRIEF", "NIGHT WATCH · AUG 28", source="APEX MARKET"),
        *common,
    ], current=NOW, market_phase="closed")
    assert [item["title"] for item in closed] == [
        "WEEKEND REVIEW · AUG 28",
        "PORTFOLIO CLOSE",
        "NEWS · CRWV",
        "GO · ADD",
        "CLOSE NOTE",
        "CARRY SIGNALS",
        "LAST CLOSE MOVERS",
        "CLOSE EXTREMES",
    ]

    weekend = select_terminal_intentions([
        event("market-weekend", "BRIEF", "WEEKEND BRIEF · AUG 28", source="APEX MARKET"),
        *common,
    ], current=NOW, market_phase="weekend")
    assert [item["title"] for item in weekend] == [
        "WEEKEND REVIEW · AUG 28",
        "PORTFOLIO CLOSE",
        "NEWS · CRWV",
        "GO · ADD",
        "CLOSE NOTE",
        "WEEKEND SIGNALS",
        "LAST SESSION MOVERS",
        "LAST SESSION EXTREMES",
    ]


def test_adaptive_mode_boundaries_use_new_york_clock() -> None:
    et = ZoneInfo("America/New_York")

    def at(hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 9, 4, hour, minute, tzinfo=et)

    assert adaptive_terminal_mode(current=at(5, 59), market_phase="premarket") == "quiet_intelligence"
    assert adaptive_terminal_mode(current=at(6), market_phase="premarket") == "apex_live"
    assert adaptive_terminal_mode(current=at(12), market_phase="intraday") == "apex_live"
    assert adaptive_terminal_mode(current=at(17, 59), market_phase="eod") == "closing_desk"
    assert adaptive_terminal_mode(current=at(18), market_phase="eod") == "portfolio_autopsy"
    assert adaptive_terminal_mode(current=at(20, 59), market_phase="eod") == "portfolio_autopsy"
    assert adaptive_terminal_mode(current=at(21), market_phase="eod") == "symbios_command"
    assert adaptive_terminal_mode(current=at(22, 59), market_phase="eod") == "symbios_command"
    assert adaptive_terminal_mode(current=at(23), market_phase="eod") == "quiet_intelligence"
    assert adaptive_terminal_mode(current=at(7, 59), market_phase="weekend") == "quiet_intelligence"
    assert adaptive_terminal_mode(current=at(8), market_phase="weekend") == "weekend_review"
    assert adaptive_terminal_mode(current=at(17, 59), market_phase="closed") == "weekend_review"
    assert adaptive_terminal_mode(current=at(18), market_phase="closed") == "quiet_intelligence"
    assert adaptive_terminal_mode(current=at(12), market_phase="bad-value") == "quiet_intelligence"


def test_adaptive_modes_reorder_the_same_verified_facts() -> None:
    et = ZoneInfo("America/New_York")

    def select_at(hour: int, *, interrupt: bool = False) -> list[dict[str, object]]:
        at = datetime(2026, 9, 4, hour, 30, tzinfo=et).astimezone(timezone.utc)
        expires = (at + timedelta(hours=8)).isoformat()
        facts = [
            event("market-mode", "BRIEF", "NIGHT WATCH · SEP 04", source="APEX MARKET"),
            event("portfolio-mode", "INFO", "PORTFOLIO AT CLOSE", source="SCHWAB PORTFOLIO"),
            event("up-mode", "MOVER_UP", "TOP GAINER", symbol="NVDA", change_pct=4.2),
            event("down-mode", "MOVER_DOWN", "TOP LOSER", symbol="TSLA", change_pct=-3.1),
            event("buy-mode", "INFO", "BUY SIGNAL", symbol="HOOD", metric_label="SIGNAL", metric_value="BUY"),
            event("sell-mode", "INFO", "SELL SIGNAL", symbol="META", metric_label="SIGNAL", metric_value="SELL"),
            event("under-mode", "OVERSOLD", "RSI", symbol="AAPL", metric_value="28.0"),
            event("over-mode", "OVERBOUGHT", "RSI", symbol="PLTR", metric_value="74.0"),
            event("news-mode", "BRIEF", "NEWS · CRWV", source="SEEKING ALPHA"),
            event("council-mode", "COUNCIL", "GO · ADD", symbol="HOOD"),
            event("brief-mode", "BRIEF", "CLOSE NOTE", source="APEX SLACK"),
        ]
        if interrupt:
            facts.append(event(
                "fill-mode", "TRADE", "BUY 10", source="LIVE BOOK",
                symbol="AAPL", value=210.0, priority=100,
            ))
        for fact in facts:
            fact["source_at"] = at.isoformat()
            fact["expires_at"] = expires
        return select_terminal_intentions(facts, current=at, market_phase="eod")

    autopsy = select_at(19)
    assert [item["title"] for item in autopsy[:5]] == [
        "PORTFOLIO AT CLOSE",
        "PORTFOLIO AUTOPSY · SEP 04",
        "CLOSE MOVERS",
        "CLOSE EXTREMES",
        "CARRY SIGNALS",
    ]

    command = select_at(21)
    assert [item["title"] for item in command[:5]] == [
        "SYMBIOS COMMAND · SEP 04",
        "GO · ADD",
        "CLOSE NOTE",
        "NEWS · CRWV",
        "CARRY SIGNALS",
    ]

    quiet = select_at(23, interrupt=True)
    assert len(quiet) == 4
    assert quiet[0]["kind"] == "TRADE"
    assert [item["title"] for item in quiet[1:]] == [
        "QUIET INTELLIGENCE · SEP 04",
        "PORTFOLIO AT CLOSE",
        "NEWS · CRWV",
    ]


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
