from __future__ import annotations

from datetime import UTC, datetime

from aidy.market_recorder import _closed_candle, _session_code


def test_closed_candle_accepts_only_fully_closed_bar() -> None:
    captured = datetime(2026, 8, 16, 12, 5, tzinfo=UTC)
    payload = {
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "time": "2026-08-16T12:00:00Z",
        "open": 4350,
        "high": 4355,
        "low": 4348,
        "close": 4353,
    }
    assert _closed_candle(payload, expected_timeframe="5m", captured_at=captured) is not None


def test_current_unclosed_bar_is_rejected() -> None:
    captured = datetime(2026, 8, 16, 12, 4, 59, tzinfo=UTC)
    payload = {
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "time": "2026-08-16T12:00:00Z",
        "open": 4350,
        "high": 4355,
        "low": 4348,
        "close": 4353,
    }
    assert _closed_candle(payload, expected_timeframe="5m", captured_at=captured) is None


def test_naive_candle_timestamp_is_rejected() -> None:
    captured = datetime(2026, 8, 16, 12, 5, tzinfo=UTC)
    payload = {
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "time": "2026-08-16T12:00:00",
        "open": 4350,
        "high": 4355,
        "low": 4348,
        "close": 4353,
    }
    assert _closed_candle(payload, expected_timeframe="5m", captured_at=captured) is None


def test_session_label_is_dst_aware() -> None:
    assert _session_code(datetime(2026, 8, 17, 14, 0, tzinfo=UTC)) == "london_new_york_overlap"
